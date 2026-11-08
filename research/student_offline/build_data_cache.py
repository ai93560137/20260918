"""建研究數據年度快取，寫 GCS xau/sig/cache/（使用者 11-08 批）。已有嘅年份跳過，除非 --force。只寫快取，唔刪任何嘢。
用法：python3 research/student_offline/build_data_cache.py --src duka --years 2015-2022
      python3 research/student_offline/build_data_cache.py --src mt5 --years 2022-2025
      python3 research/student_offline/build_data_cache.py --src h1gold --years 2005-2025   （h1silver 同樣）"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "strategy_search"))
ARGV = list(sys.argv)
import data_cache as DC   # noqa: E402


def arg(k, default=None):
    return ARGV[ARGV.index(k) + 1] if k in ARGV else default


def main():
    src = arg("--src"); y0, y1 = (int(x) for x in arg("--years").split("-")); force = "--force" in ARGV
    for y in range(y0, y1 + 1):
        if src in ("duka", "mt5"):
            name = f"m1_{src}_{y}.npz"
        else:
            name = f"h1_{'gold' if src == 'h1gold' else 'silver'}_{y}.npz"
        if not force and DC.exists(name):
            print(f"{name} 已有，跳過"); continue
        if src in ("duka", "mt5"):
            sys.argv = [sys.argv[0], "--src", src]
            import rev15_history as rh
            rh.SRC = src; rh.A, rh.B = f"{y}-01-01", f"{y}-12-31"
            d = rh._load_days(rh.A, rh.B)
        else:
            import h1_lab as L
            d = L._h1_raw("xau/sig/duka_h1_xagusd/" if src == "h1silver" else "xau/sig/duka_h1/", [y])
        if not len(d["t"]):
            print(f"{name}：冇數據，唔寫"); continue
        size = DC.put(name, d)
        print(f"{name}：{len(d['t'])} 根，{size / 1e6:.1f} MB 已寫入 GCS", flush=True)


if __name__ == "__main__":
    main()
