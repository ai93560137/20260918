"""[IDEAS #1049] 價位回測家族合併：#1039 當日開市價、#1042 前日收市、#1045 前日中位、#1046 倫敦開市價、#1047 紐約開市價、#1048 亞洲中位，
六個價位全部收（唔揀最好嗰幾個），規則同各自一樣（E6S4 返原方向）；同一分鐘同方向只計一張。
**冇回測判決**：呢六條都睇過成績，合併唔可以用同一批數據驗；只做影子前向（#1028 影子總表）同 2010–2014 未見數據（#1050）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1037 as B37        # noqa: E402
import batch_1041 as B41        # noqa: E402
import batch_1045 as B45        # noqa: E402

PARTS = (B37.r1039, B41.r1042, B45.r1045, B45.r1046, B45.r1047, B45.r1048)


def r1049(d):
    seen, out = set(), []
    for fn in PARTS:
        for ts, sg, r in fn(d):
            if (ts, sg) in seen:
                continue
            seen.add((ts, sg)); out.append((ts, sg, r))
    return sorted(out)
