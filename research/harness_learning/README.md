# Harness Learning（研究用，不部署）

依 Zhang et al., *Harness Learning Enables Generalizable Test-Time Adaptation*（arXiv:2609.35738）
實作的核心迴圈，單一檔案、只用標準庫。與本 repo 的交易系統無關，放在 `research/` 下
（`.gcloudignore` 已排除，不會進 Cloud Run 映像）。

| 檔案 | 用途 |
|---|---|
| `harness_learning.py` | 核心：`execute`（Eq.3）、`build_report`、`apply_edits`／`propose`（SEARCH/REPLACE）、`adapt`（Eq.4／7）、`evaluate`、`collect_group`／`revision_reward`（Eq.6／8）、`grpo_advantages` |
| `demo_small_sample.py` | 小樣本冒煙測試：假 proposer／solver 跑完整流程 |
| `test_harness_learning.py` | 單元測試 |

```bash
python3 research/harness_learning/demo_small_sample.py
python3 -m unittest research/harness_learning/test_harness_learning.py -v
```

## 用法

```python
import harness_learning as hl

task = hl.Task(description="...", grader=hl.exact_match)
best, history = hl.adapt(task, dev_questions, proposer, solver,
                         rounds=5, candidates=1, select="improve_only", timeout=30)
score = hl.evaluate(best, task, held_out_questions, solver)
```

`proposer` 與 `solver` 都是 `str -> str`。`select="improve_only"` 是 Reasoning Gym 做法（Eq.7，只在
dev 分數嚴格進步時保留）；`select="best_of_g"` 是 QA 做法（每輪取最高分候選，即使比 parent 差；
全部候選失敗才留在原地），搭配 `n_feedback`／`n_score` 每輪抽不相交的回饋／計分子集。

## 要留意

- harness 是模型生成的程式碼，用 `exec()` 直接執行。**請在沙盒（容器或受限子程序）裡跑。**
  `timeout` 只是每題牆鐘時間上限（Unix 主執行緒用 `signal`），不是安全邊界。
- 沒有 GRPO 的梯度更新；`collect_group()` 回傳 `prompt`／`responses`／`rewards`／`advantages`，
  接到自己的訓練器。
- 檢索工具（BM25 等）沒有內建；harness 介面只有 `solve(model, question)`，做 QA 要自己把檢索函式
  包進 `solver` 或放進 harness 可見的命名空間。
- `Proposal.parsed` 對應 Eq.8 的 `1[y parses]`：回應有合法 SEARCH/REPLACE 區塊或 `NO_CHANGE` 即為
  True，即使 SEARCH 對不上（失敗的修訂只拿已累積的效度分 0.05）。
- SEARCH 只接受對齊行邊界的命中，避免半行命中把縮排疊加成語法錯誤。
