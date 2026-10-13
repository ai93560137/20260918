"""小樣本冒煙測試：用假 proposer／solver 跑一遍 harness_learning 的完整流程，不需要真模型。

    python3 research/harness_learning/demo_small_sample.py

接真模型時，把 `fake_solver` / `make_fake_proposer()` 換成 `str -> str` 的呼叫函式即可。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness_learning as hl  # noqa: E402

TASK = hl.Task(
    description="Answer integer arithmetic questions such as 'What is 3 + 4?' with only the number.",
    grader=hl.exact_match,
)

GOOD_EDIT = """<<<<<<< SEARCH
def solve(model, question):
    return model(question).strip()
=======
import re

def solve(model, question):
    m = re.search(r"(-?\\d+)\\s*([+\\-*])\\s*(-?\\d+)", question)
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        return str(a + b if op == "+" else a - b if op == "-" else a * b)
    return model(question).strip()
>>>>>>> REPLACE"""

BAD_EDIT = "<<<<<<< SEARCH\nthis line is not in the harness\n=======\nx = 1\n>>>>>>> REPLACE"


def questions(n: int, seed: int) -> list[hl.Question]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        a, b, op = rng.randint(1, 50), rng.randint(1, 50), rng.choice("+-*")
        ans = a + b if op == "+" else a - b if op == "-" else a * b
        out.append(hl.Question(f"What is {a} {op} {b}?", str(ans)))
    return out


def fake_solver(prompt: str) -> str:
    """弱 solver：永遠答 42。"""
    return "42"


def make_fake_proposer():
    """第 1 次給對不上的 SEARCH（測重試回饋），之後給正確修改。"""
    n = {"calls": 0}

    def proposer(prompt: str) -> str:
        n["calls"] += 1
        return BAD_EDIT if n["calls"] == 1 else GOOD_EDIT

    return proposer


def main() -> None:
    dev, held = questions(8, seed=1), questions(20, seed=2)

    print("== adapt(select='improve_only') ==")
    best, hist = hl.adapt(TASK, dev, make_fake_proposer(), fake_solver, rounds=3, candidates=1,
                          select="improve_only", timeout=5)
    for i, r in enumerate(hist, 1):
        print(f"  round {i}: dev={r.dev_score:.3f} candidates={r.candidate_scores}")
    print(f"  held-out: {hl.evaluate(best, TASK, held, fake_solver):.3f}")
    assert hist[-1].dev_score == 1.0, "demo should reach dev score 1.0"

    print("== adapt(select='best_of_g', disjoint feedback/scoring) ==")
    best, hist = hl.adapt(TASK, questions(12, seed=3), make_fake_proposer(), fake_solver, rounds=2,
                          candidates=2, select="best_of_g", n_feedback=4, n_score=6)
    for i, r in enumerate(hist, 1):
        print(f"  round {i}: dev={r.dev_score:.3f} candidates={r.candidate_scores}")

    print("== collect_group (RL) ==")
    g = hl.collect_group(TASK, hl.SEED_HARNESS, dev[:4], dev[4:], make_fake_proposer(), fake_solver,
                         group_size=4)
    print("  rewards:   ", [round(r, 3) for r in g["rewards"]])
    print("  advantages:", [round(a, 3) for a in g["advantages"]])
    print("  best_harness is revised:", "import re" in g["best_harness"])
    print("OK")


if __name__ == "__main__":
    main()
