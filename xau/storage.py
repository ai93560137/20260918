"""GCS 層：讀寫都加 generation 檢查（同 main.py 一樣嘅做法），本服務只寫 PREFIX 前綴。"""
import json
import random
import time

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

import config

TEXT = "application/json; charset=utf-8"
_client = None


class StorageError(Exception):
    pass


def _bucket():
    global _client
    if _client is None:
        _client = storage.Client()
    return _client.bucket(config.BUCKET)


def _guard(name):
    if not name.startswith(config.PREFIX):
        raise StorageError(f"refusing to write outside {config.PREFIX}: {name}")


def read_text(name):
    try:
        blob = _bucket().get_blob(name)
        return None if blob is None else blob.download_as_bytes().decode("utf-8")
    except NotFound:
        return None
    except Exception as exc:
        raise StorageError(f"read {name}: {exc}") from exc


def read_json(name, default):
    text = read_text(name)
    if text is None or not text.strip():
        return default
    try:
        return json.loads(text)
    except ValueError as exc:
        raise StorageError(f"corrupt JSON in {name}: {exc}") from exc


def write_text(name, text):
    _guard(name)
    try:
        _bucket().blob(name).upload_from_string(text, content_type=TEXT)
    except Exception as exc:
        raise StorageError(f"write {name}: {exc}") from exc


def write_json(name, data):
    write_text(name, json.dumps(data, ensure_ascii=False))


def update(name, mutate, *, default_factory=dict, attempts=10):
    """原子 read-modify-write。mutate(data) -> (new_data, result)；new_data=None 唔寫。mutate 可能跑多次，唔可以有副作用。"""
    _guard(name)
    for attempt in range(attempts):
        try:
            blob = _bucket().get_blob(name)
            if blob is None:
                generation, data = 0, default_factory()
            else:
                generation = blob.generation
                raw = blob.download_as_bytes(if_generation_match=generation).decode("utf-8")
                try:
                    data = json.loads(raw) if raw.strip() else default_factory()
                except ValueError:
                    print(f"⚠️ [GCS] {name} 內容損毀，重設為預設值", flush=True)
                    data = default_factory()
        except (PreconditionFailed, NotFound):
            time.sleep(random.uniform(0.05, 0.2) * (1.5 ** attempt))
            continue
        except Exception as exc:
            raise StorageError(f"read {name}: {exc}") from exc
        new_data, result = mutate(data)
        if new_data is None:
            return result
        try:
            _bucket().blob(name).upload_from_string(json.dumps(new_data, ensure_ascii=False),
                                                    if_generation_match=generation, content_type=TEXT)
            return result
        except PreconditionFailed:
            time.sleep(random.uniform(0.05, 0.2) * (1.5 ** attempt))
        except Exception as exc:
            raise StorageError(f"write {name}: {exc}") from exc
    raise StorageError(f"update {name}: gave up after {attempts} retries")


def append_jsonl(name, row, keep_last=None):
    """GCS 冇 append：讀→加一行→寫。每日一個檔，每分鐘最多一次，夠用。"""
    def mutate(rows):
        rows = rows if isinstance(rows, list) else []
        rows.append(row)
        return (rows[-keep_last:] if keep_last else rows), None
    update(name, mutate, default_factory=list)
