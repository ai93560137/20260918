"""研究數據快取（使用者 11-08 批：合併數據存入 GCS）。每個完整年份一個 npz，放 GCS xau/sig/cache/。
只讀 helper 由 rev15_history.load／h1_lab.h1 調用：有快取就用，冇就照舊逐日讀。寫入只由 build_data_cache.py 做（唔會覆寫已有物件，除非 --force）。
命名：m1_duka_<年>.npz、m1_mt5_<年>.npz、h1_gold_<年>.npz、h1_silver_<年>.npz；內容 t（UTC 秒，int64）、o、h、l、c（float64）。"""
import io
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
PREFIX = "xau/sig/cache/"
_G = None


def _bucket():
    global _G
    if _G is None:
        import gb_rulesim as gb
        _G = gb.Gcs()
    return _G.b


def get(name):
    """回傳 dict 或 None；先睇本機 /tmp，再睇 GCS。"""
    local = f"/tmp/datacache_{name.replace(chr(47), chr(95))}"     # 名可以帶子目錄（例如 mt5x/…）
    if not os.path.exists(local):
        try:
            blob = _bucket().blob(PREFIX + name)
            if not blob.exists():
                return None
            blob.download_to_filename(local)
        except Exception as exc:  # noqa: BLE001
            print(f"  快取讀唔到 {name}：{exc}", flush=True)
            return None
    z = np.load(local)
    return {k: z[k] for k in ("t", "o", "h", "l", "c")}


def exists(name):
    return _bucket().blob(PREFIX + name).exists()


def put(name, d):
    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: d[k] for k in ("t", "o", "h", "l", "c")})
    _bucket().blob(PREFIX + name).upload_from_string(buf.getvalue(), content_type="application/octet-stream")
    return len(buf.getvalue())


def merge(parts, t0=None, t1=None):
    parts = [p for p in parts if p is not None and len(p["t"])]
    if not parts:
        return {k: np.array([], dtype=np.int64 if k == "t" else np.float64) for k in ("t", "o", "h", "l", "c")}
    d = {k: np.concatenate([p[k] for p in parts]) for k in ("t", "o", "h", "l", "c")}
    order = np.argsort(d["t"], kind="stable"); d = {k: v[order] for k, v in d.items()}
    keep = np.r_[True, np.diff(d["t"]) > 0]
    if t0 is not None:
        keep &= d["t"] >= t0
    if t1 is not None:
        keep &= d["t"] < t1
    return {k: v[keep] for k, v in d.items()}
