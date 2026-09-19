#!/usr/bin/env python3
"""
錦囊桌布 — iPhone 17 Pro Max（1320 × 2868）

鎖定畫面上，時鐘大約落在 y=260–520、小工具在 y=520–700、
底部 y>2450 是手電筒與相機。所以可讀區間留在 y≈780–2280。

內容只有一句問題和三個數字。桌布的用途不是好看，是在你伸手拿手機
準備下單的那三秒鐘，先被問一次。
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1320, 2868
F = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

BG    = (14, 16, 19)
INK   = (238, 240, 243)
MUTE  = (122, 130, 140)
LINE  = (40, 45, 52)
SEAL  = (176, 58, 58)
OK    = (62, 122, 82)

def font(sz): return ImageFont.truetype(F, sz)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# 極淡的垂直漸層，避免純色在 OLED 上顯得死板
for y in range(H):
    t = y / H
    v = int(2 + 10 * (t ** 1.6))
    d.line([(0, y), (W, y)], fill=(BG[0] + v // 3, BG[1] + v // 3, BG[2] + v // 2))

def center(y, text, f, fill, spacing=0):
    if spacing == 0:
        w = d.textbbox((0, 0), text, font=f)[2]
        d.text(((W - w) / 2, y), text, font=f, fill=fill)
        return
    widths = [d.textbbox((0, 0), c, font=f)[2] for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = (W - total) / 2
    for c, cw in zip(text, widths):
        d.text((x, y), c, font=f, fill=fill)
        x += cw + spacing

# ── 上：一條細線與標記（時鐘下方）──────────────────────────────
d.line([(W / 2 - 40, 792), (W / 2 + 40, 792)], fill=LINE, width=3)
center(836, "錦 囊", font(34), MUTE, spacing=14)

# ── 中：那一句問題 ────────────────────────────────────────────
y = 1090
for line in ["如果我這個月", "不缺錢，", "我還會做這一筆嗎？"]:
    center(y, line, font(86), INK)
    y += 132

# ── 分隔 ──────────────────────────────────────────────────────
d.line([(220, 1560), (W - 220, 1560)], fill=LINE, width=2)

# ── 下：三個硬數字 ────────────────────────────────────────────
rows = [
    ("52%", "的交易是虧的。中位數是負的。", MUTE),
    ("5%", "的交易養活整套系統。所以要抱滿。", MUTE),
    ("10 根", "＝ 2.5 小時。中間不碰。", MUTE),
]
y = 1660
for big, small, col in rows:
    bw = d.textbbox((0, 0), big, font=font(64))[2]
    sw = d.textbbox((0, 0), small, font=font(38))[2]
    total = bw + 24 + sw
    x = (W - total) / 2
    d.text((x, y), big, font=font(64), fill=INK)
    d.text((x + bw + 24, y + 22), small, font=font(38), fill=col)
    y += 128

# ── 底：兩條紅線（停止條件）───────────────────────────────────
d.line([(220, 2110), (W - 220, 2110)], fill=LINE, width=2)
center(2170, "想加碼？想提早走？想做訊號以外的？", font(40), MUTE)
center(2240, "那不是直覺，是壓力。", font(52), SEAL)

# ── 最底：落款 ────────────────────────────────────────────────
center(2372, "曝險上限 ＝ (20% - 目前回撤) ÷ 最壞跳空", font(32), (78, 84, 92))

img.save("jinnang_wallpaper_1320x2868.png", "PNG", optimize=True)
print("saved", img.size)
