"""HKEX 行情抓取 — Google Colab 版（三源比對的第三源）。

Colab 設定（一次性）：
  1. GitHub 建 fine-grained PAT：只授權 ai93560137/20260918 這一個 repo 的
     Contents: Read and write 權限
  2. Colab 左側 🔑 Secrets 加入 GH_TOKEN = 該 PAT，並允許本 notebook 存取
  3. 每次運行整個 cell 貼上此檔內容執行（或 !wget raw 檔後 %run）
  4. 定時：用 Colab 的 Scheduled notebooks，建議 HKT 14:30（與 Actions 快照對齊）

輸出推到 repo 分支 claude/dazzling-curie-f3xzb8 的
tradingview/data_external/quotes_colab/，與 Actions 的 quotes/ 分開存放。
"""
import json
import os
import re
import subprocess
import time

import requests

REPO = 'ai93560137/20260918'
BRANCH = 'claude/dazzling-curie-f3xzb8'
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer': 'https://www.hkex.com.hk/'}
S = requests.Session()
S.headers.update(H)


def get_token():
    page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
                 'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en', timeout=30).text
    return re.search(r'return\s*"(evLts[^"]+)"', page).group(1)


def call(token, ep, **params):
    qid = str(int(time.time() * 1000))
    q = '&'.join(f"{k}={v}" for k, v in params.items() if v is not None)
    u = f'https://www1.hkex.com.hk/hkexwidget/data/{ep}?lang=eng&token={token}&{q}&qid={qid}&callback=j'
    body = S.get(u, timeout=30).text
    m = re.search(r'^j\((.*)\)\s*$', body, re.S)
    return json.loads(m.group(1)) if m else None


def fetch_all(outdir):
    os.makedirs(outdir, exist_ok=True)
    token = get_token()
    stamp = time.strftime('%Y%m%d_%H%M')
    fut = call(token, 'getderivativesfutures', ats='HSI', type=0)
    json.dump(fut, open(f'{outdir}/futures_{stamp}.json', 'w'), ensure_ascii=False)
    cl = call(token, 'getoptioncontractlist', ats='HSI', type=0)
    cons = [(c.get('id'), c.get('mon')) for c in cl['data'].get('conlist', [])]
    for cid, mon in cons[:3]:
        opt = call(token, 'getderivativesoption', ats='HSI', con=cid, fr='null', to='null', type=0)
        if opt:
            safe = str(mon or cid).replace('/', '-').replace(' ', '')
            json.dump(opt, open(f'{outdir}/options_{safe}_{stamp}.json', 'w'), ensure_ascii=False)
    print(f'fetched {stamp}: futures + {min(3, len(cons))} option chains')
    return stamp


def push_to_repo():
    try:
        from google.colab import userdata  # noqa
        gh = userdata.get('GH_TOKEN')
    except Exception:
        gh = os.environ.get('GH_TOKEN')
    assert gh, '缺 GH_TOKEN（Colab Secrets 或環境變數）'
    work = '/content/hsi_repo'
    if not os.path.exists(work):
        subprocess.run(['git', 'clone', '--depth', '1', '-b', BRANCH,
                        f'https://x-access-token:{gh}@github.com/{REPO}.git', work], check=True)
    else:
        subprocess.run(['git', '-C', work, 'pull', '--rebase'], check=True)
    out = f'{work}/tradingview/data_external/quotes_colab'
    fetch_all(out)
    subprocess.run(['git', '-C', work, 'config', 'user.name', 'colab-fetcher'], check=True)
    subprocess.run(['git', '-C', work, 'config', 'user.email', 'colab@invalid'], check=True)
    subprocess.run(['git', '-C', work, 'add', 'tradingview/data_external/quotes_colab'], check=True)
    r = subprocess.run(['git', '-C', work, 'diff', '--cached', '--quiet'])
    if r.returncode != 0:
        subprocess.run(['git', '-C', work, 'commit', '-m', 'data: HKEX 行情快照（Colab 自動）'], check=True)
        subprocess.run(['git', '-C', work, 'push'], check=True)
        print('pushed to repo')


if __name__ == '__main__':
    push_to_repo()
