"""Telegram 白話版（使用者 2026-10-19：投資人睇唔明術語，以後自動摘要用白話）。

hsi_scan.py 嘅 ALERTS／DIGEST 係技術格式，digest.txt 照寫（yunchui_public.py 同例行用 regex 讀，唔好改）；
呢度逐行轉白話，寫 alert_plain.txt／digest_plain.txt，fetch-quotes.yml 優先發白話版。
認唔到嘅行原樣保留，所以 hsi_scan.py 加新行唔會出錯，只係未有白話。
"""
import re

MONTHS = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
          'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

PREM_NOTE = "（溢價＝市場預期波動減實際波動；正數越大，賣期權收嘅保費越抵）"
DELTA_NOTE = "（方向風險 Δ：正數＝指數升有利、跌不利，負數相反；以期貨手數計，超過 ±0.5 手先對沖）"


def _mon(s):
    """Oct-26 → 2026 年 10 月"""
    m = re.match(r'([A-Z][a-z]{2})-(\d{2})', s)
    return f"20{m.group(2)} 年 {MONTHS[m.group(1)]} 月" if m and m.group(1) in MONTHS else s


def _act(s):
    s = s.strip()
    if '無動作' in s:
        return '喺界線內，唔使對沖'
    m = re.search(r'(再)?(賣|買)\s*(\d+)\s*手 MHI', s)
    if m:
        return f"需要{m.group(2)} {m.group(3)} 手小型恒指期貨（MHI）對沖"
    m = re.search(r'對沖\s*(\d+)\s*手 MES', s)
    if m:
        return f"需要用 {m.group(1)} 手 MES 期貨對沖"
    return s.lstrip('→ ').strip()


def plain_alert(a):
    m = re.match(r'(\S+) IV−HV = ([+\-][\d.]+) 為負', a)
    if m and not a.startswith('美股'):
        return (f"恒指 {_mon(m.group(1))}期權：市場預期波動反而低過實際波動 {abs(float(m.group(2))):.1f}，"
                f"賣期權收嘅保費唔夠補償風險 → 暫停賣新倉")
    m = re.match(r'(\S+) IV−HV = ([+\-][\d.]+) 異常厚', a)
    if m and not a.startswith('美股'):
        return (f"恒指 {_mon(m.group(1))}期權保費異常高（溢價 {m.group(2)}），"
                f"通常代表市場預期有大事，要先查清楚有冇事件風險")
    m = re.match(r'(\S+) (call|put|c|p) (單調性破壞|垂直價差超上界) (\S+)', a)
    if m:
        return f"恒指 {_mon(m.group(1))}期權報價唔合理（{m.group(4)}），可能係報價錯誤，數據要再核實"
    m = re.match(r'期貨 (\S+) 價差 (\d+) 點', a)
    if m:
        return f"恒指期貨 {m.group(1)} 買賣差價 {m.group(2)} 點，異常闊，落單要小心價錢"
    m = re.match(r'期貨曲線倒掛：(\S+) 結算 (\d+) < 前月 (\d+)', a)
    if m:
        return f"恒指遠月期貨 {m.group(1)}（{m.group(2)}）平過近月（{m.group(3)}），少見，市場預期可能轉差"
    if '金絲雀深紅' in a:
        return ("🟣🚨 市場預警燈轉深紅：中期（3 個月）都比短期平靜，屬歷史上大跌前常見嘅訊號"
                "（以往誤報只有約一成）。我哋全面加密檢查、再核對止損線同保證金；"
                "紀律不變：唔加倉、亦唔提早平倉")
    m = re.search(r'金絲雀紅：VIX9D−VIX = ([+\-][\d.]+)', a)
    if m:
        p = re.search(r'機率 (\d+)%', a)
        return ("🔴 市場預警燈轉紅：市場對未來 9 日嘅緊張程度高過未來 30 日，即係覺得近排可能有大波動。"
                + (f"歷史上出現呢個訊號，一星期內有約 {p.group(1)}% 機會出現單日跌 2% 或以上。" if p else "")
                + "我哋本週方向風險檢查由每日一次加到兩次（恒指、美股各加一次），"
                  "預計對沖調整約係平時兩倍。紅燈唔代表要平倉，只係加密監察")
    m = re.match(r'美股數據呆滯：VIX 最後日期 (\S+)', a)
    if m:
        return f"美股數據停咗更新（最後日期 {m.group(1)}），自動抓數可能出咗事，美股數字只作參考"
    m = re.match(r'美股 VIX−HV = ([+\-][\d.]+) 為負', a)
    if m:
        return f"美股：市場預期波動低過實際波動 {abs(float(m.group(1))):.1f}，保費唔夠補償風險 → 暫停賣新 MES 期權"
    m = re.match(r'美股 VIX−HV = ([+\-][\d.]+) 異常厚', a)
    if m:
        return f"美股保費異常高（溢價 {m.group(1)}），可能有大事（議息、通脹數據、業績季），要先查清楚"
    m = re.match(r'MES 滾倉窗口：(\d+) 天後到期', a)
    if m:
        return f"標普 MES 期權 {m.group(1)} 日後到期：到期日美東 16:00 前要平倉，之後開下一期"
    m = re.match(r'HSI 滾倉窗口：(\d+) 天後持倉結算（(\S+)）', a)
    if m:
        return f"恒指期權 {m.group(1)} 日後結算（{m.group(2)}）：持有到結算，第二日開下個月新倉"
    m = re.match(r'滾倉窗口：(\d+) 天後月度結算', a)
    if m:
        return f"恒指本月期權 {m.group(1)} 日後結算，準備之後開下個月新倉"
    return a


def plain_line(s):
    """單行摘要轉白話；回傳 None ＝ 呢行唔發。"""
    if s == '✅ 無警報':
        return '✅ 今日冇警報'
    m = re.match(r'HSI 期貨\(近月(\S+?)\) ([\d,]+)(.*)', s)
    if m:
        note = '（收市價）' if '收市後' in m.group(3) or m.group(1) == '昨結' else '（延遲報價）'
        return f"📈 恒指期貨 {m.group(2)}{note}"
    m = re.match(r'HSI (\S+): ATM (\d+) IV ([\d.]+) 溢價([+\-][\d.]+)（(.+)）', s)
    if m:
        if '到期月' in m.group(5):
            return f"恒指 {_mon(m.group(1))}期權：本月到期，唔評估"
        p = float(m.group(4))
        verdict = '唔夠，唔賣' if p < 0 else ('低過歷史平均' if p < 2.4 else '達到歷史平均或以上')
        return f"恒指 {_mon(m.group(1))}期權保費溢價 {m.group(4)}（歷史平均 +2.4）→ {verdict}"
    m = re.match(r'HSI 月度到期剩 (\d+) 天', s)
    if m:
        return f"🗓 恒指本月期權 {m.group(1)} 日後結算"
    m = re.match(r'HSI 持倉 (\S+) 跨式 到期剩 (-?\d+) 天', s)
    if m:
        return f"📌 恒指持倉：行使價 {m.group(1)} 跨式（同時賣出認購同認沽），{m.group(2)} 日後到期"
    if s.startswith('HSI 結算週'):
        return '🗓 恒指結算週：聽朝 10:00 加一次方向風險檢查'
    m = re.match(r'美股: VIX ([\d.]+) HV ([\d.]+) 溢價([+\-][\d.]+)', s)
    if m:
        p = float(m.group(3))
        verdict = '唔夠，唔賣' if p < 0 else ('低過歷史平均' if p < 4.1 else '高過歷史平均，保費偏厚')
        return (f"🇺🇸 美股：市場預期波動 {m.group(1)}、實際波動 {m.group(2)}，"
                f"溢價 {m.group(3)}（歷史平均 +4.1）→ {verdict}")
    m = re.match(r'ES 期貨 ([\d,]+)', s)
    if m:
        return f"📈 標普期貨約 {m.group(1)}（延遲報價）"
    m = re.match(r'金絲雀 (\S+?)(綠|黃·(.+)升溫|紅·倒掛|深紅·災難級)｜', s)
    if m:
        lv = m.group(2)
        if lv == '綠':
            return '🟢 市場預警燈：綠，市場平靜'
        if lv.startswith('黃'):
            return f"🟡 市場預警燈：黃，部分風險指標升溫（{m.group(3)}），留意"
        if lv.startswith('紅'):
            return '🔴 市場預警燈：紅，短期緊張過長期，近排波動可能加大'
        return '🟣 市場預警燈：深紅，中期都緊張過長期，屬大跌前常見訊號'
    m = re.match(r'MES 持倉 (\S+) 跨式 到期剩 (-?\d+) 天', s)
    if m:
        return f"📌 標普 MES 持倉：行使價 {m.group(1)} 跨式（同時賣出認購同認沽），{m.group(2)} 日後到期"
    if s.startswith('港金絲雀'):
        return ('⚪ 港股預警燈（試用中，只作參考）：有倒掛' if '倒掛' in s
                else '🟢 港股預警燈（試用中，只作參考）：正常')
    m = re.match(r'HSI 跨式Δ ([+\-][\d.]+) 對沖 ([+\-]\d+) → 淨Δ ([+\-][\d.]+)（[^）\s]+ ([^）\s]+)）(.*?)(  ⚠.*)?$', s)
    if m:
        return (f"⚖️ 恒指方向風險：跨式 {m.group(1)}，加埋 {m.group(2)} 手期貨對沖後淨 {m.group(3)} → "
                f"{_act(m.group(5))}" + (m.group(6) or ''))
    m = re.match(r'(HSI|MES) 跨式Δ ([+\-][\d.]+)（[^）\s]+ ([^）\s]+)）(.*?)(  ⚠.*)?$', s)
    if m:
        name = '恒指' if m.group(1) == 'HSI' else '標普 MES '
        ref = '（未持倉，參考值）' if m.group(3) == '參考' else ''
        return f"⚖️ {name}方向風險：{m.group(2)}{ref} → {_act(m.group(4))}" + (m.group(5) or '')
    return s


def plain_digest(lines):
    out, prem_noted, delta_noted = [], False, False
    for s in lines:
        if s.startswith('⚠ '):
            out.append('⚠ ' + plain_alert(s[2:]))
            continue
        t = plain_line(s)
        if t is None:
            continue
        if '保費溢價' in t and not prem_noted:
            out.append(PREM_NOTE)
            prem_noted = True
        if '方向風險' in t and not delta_noted:
            out.append(DELTA_NOTE)
            delta_noted = True
        out.append(t)
    return out
