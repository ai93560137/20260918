"""[IDEAS #231] 斐波那契區間：轉勢點 → 而家嘅極端（包影線）。逐根加入已收市 K 線，增量計算。

使用者 11-05：「斐波那契回撤選擇的區間是轉勢前，包影線」。
- 擺動點＝分形：高位高過左邊 K 根、唔低過右邊 K 根（右邊 K 根收咗先確認）；低點相反。
- 轉勢：收市升穿最近確認擺動高點（原本唔係升勢）→ 升勢，轉勢點＝嗰個擺動高點至今最低嗰根嘅低位；
  收市跌穿最近確認擺動低點（原本唔係跌勢）→ 跌勢，轉勢點＝嗰個擺動低點至今最高嗰根嘅高位。
- 升勢區間＝轉勢低點 → 之後最高影線；跌勢區間＝轉勢高點 → 之後最低影線。
"""

K = 2


class RevSwing:
    def __init__(self, k=K, prev_ext=False):
        """prev_ext=True（網頁圖用，使用者 11-05 檢查）：由升轉跌時轉勢點＝上一段升勢嘅最高影線（真頂），由跌轉升＝上一段跌勢最低影線（真底）；
        False（IDEAS #231 回測用，唔改）：轉勢點＝被突破嗰個擺動點至今嘅極端。"""
        self.k = k
        self.prev_ext = prev_ext
        self.H, self.L, self.C = [], [], []
        self.ph = None          # (價, index) 最近確認擺動高點
        self.pl = None
        self.trend = 0          # 1 升勢、-1 跌勢、0 未定
        self.anchor = None      # 轉勢點 index
        self.ext = None         # 轉勢之後嘅極端 index

    def add(self, h, l, c):
        H, L, C, k = self.H, self.L, self.C, self.k
        H.append(h); L.append(l); C.append(c)
        j = len(H) - 1
        i = j - k
        if i >= k:
            if H[i] > max(H[i - k:i]) and H[i] >= max(H[i + 1:j + 1]):
                self.ph = (H[i], i)
            if L[i] < min(L[i - k:i]) and L[i] <= min(L[i + 1:j + 1]):
                self.pl = (L[i], i)
        if self.trend != 1 and self.ph and c > self.ph[0]:
            a0 = self.ext if (self.prev_ext and self.trend == -1) else self.ph[1]
            a = min(range(a0, j + 1), key=lambda x: L[x])
            self.trend, self.anchor = 1, a
            self.ext = max(range(a, j + 1), key=lambda x: H[x])
        elif self.trend != -1 and self.pl and c < self.pl[0]:
            a0 = self.ext if (self.prev_ext and self.trend == 1) else self.pl[1]
            a = max(range(a0, j + 1), key=lambda x: H[x])
            self.trend, self.anchor = -1, a
            self.ext = min(range(a, j + 1), key=lambda x: L[x])
        elif self.trend == 1 and h > H[self.ext]:
            self.ext = j
        elif self.trend == -1 and l < L[self.ext]:
            self.ext = j

    def swing(self):
        """回傳 (hi_i, lo_i, up) 或 None。"""
        if self.trend == 0 or self.anchor is None:
            return None
        if self.trend == 1:
            return self.ext, self.anchor, True
        return self.anchor, self.ext, False

    def levels(self, ratios):
        s = self.swing()
        if s is None:
            return None
        hi_i, lo_i, up = s
        hi, lo = self.H[hi_i], self.L[lo_i]
        if hi <= lo:
            return None
        return {r: (hi - (hi - lo) * r) if up else (lo + (hi - lo) * r) for r in ratios}
