# 新 session 開場指示（stock_research/NEW_SESSION_PROMPT.md）

開新 session 接手股票研究時，把下面整段貼上去即可。

```text
【接手：股票研究（新高／VCP／Minervini／相場師朗／9 國樣本外）】

倉庫：ai93560137/20260918
基準分支：claude/gifted-carson-v2tvhw（每日 Telegram 工作流程、Actions、Release 都綁在這個分支）
開新分支的方法：
  git fetch origin claude/gifted-carson-v2tvhw
  git checkout -b <新分支名> origin/claude/gifted-carson-v2tvhw
注意：改每日報告（scripts/daily_topdown.py、daily_topdown.yml）或 Actions 工作流程的改動，
      必須推回 claude/gifted-carson-v2tvhw，不要只推新分支（Actions 固定 checkout 這個分支）。

開工先讀（按次序）：
1. stock_research/STOCK_RESEARCH_HANDOFF.md（交接總結、下一步選項）
2. stock_research/README.md（策略、數據、執行方法、踩過的坑）
3. stock_research/VERDICTS.md（全部判決、9 策略 × 9 市場矩陣、多重測試帳本；已判決的不重測）
4. RESEARCH_HANDBOOK.md（方法論鐵律）
5. stock_research/MARKET_DATA_CATALOG.md（9 國數據目錄）

數據（不進 git，存 GitHub Release）：
  python3 scripts/get_market_data.py            # 9 國全部，約 1.2 GB，自動重建品質排除檔
  python3 scripts/get_market_data.py --market hk us
注意：雲端沙盒連不到交易所網站、Yahoo、Nasdaq；要連外網的步驟（抓新數據、第二來源核對）用 GitHub Actions 跑。

現況一句話：
  唯一通過兩輪樣本外的是「VCP Minervini 忠實版」（台韓澳合併 alpha t 2.84（台灣基準修正後）、加印新 3.39），
  依賴少數大贏家，2015 年後轉弱；美日韓最弱。「紀律本身」回測（DISCIPLINE_BACKTEST.md）判不確定：
  效果主要來自 VCP 形態＋樞紐點入場，不是止損紀律（不看形態只靠紀律：合併 1.41、與隨機對照相同）。
  低勝率 30:1（RRR30_BACKTEST.md，兩輪）判不確定：VCP 入場＋3% 止損，200 日線出場 RRR 13.2、純兩極出場 21.7；alpha 3.0 不隨出場變、與隨機對照同水平；這條線已停。
  ETF 擇時（ETF_TIMING_BACKTEST.md）☠️：VCP 突破日對 ETF 無擇時資訊（隨機日更好），純 MA 日頻過濾扣成本跑輸持有。
  趨勢模板動量組合（TT_MOMENTUM_BACKTEST.md）判「只是動量 beta」：合併 3.13、相對等權 1.85 差 0.15；排序有害（隨機模板股 3.93）。
  事後候選（未判，要另開登記）：模板股全部等權月換倉＋大市過濾。港日美數據已用 12 次。
  數據：一日 >+100% 的縫接斷點要剔除（tt_momentum_backtest.py 的 bad）；基準 ETF 修正表 universes/full/etf_fixes.csv。核心配置建議仍是指數 ETF；按登記最多 10% 衛星倉試行（尚未開始）。

待我決定的方向（先問我，不要自行開始）：
  A. 把 Minervini 每日訊號（樞紐點、7.5% 止損價、50 日線出場）加進 Telegram，開始衛星倉前向記錄
  B. 衛星倉放哪些市場（登記寫港日美，但美日最弱；改的話要另外預先登記）
  C.（已做，不確定，見 DISCIPLINE_BACKTEST.md）事後浮現的候選：「剛進入趨勢模板＋一年持有」（D2 合併 5.13）——
     要測須另開登記（港日美第 9 次、門檻 ≥ 2.5、9 國一次、先算換手與成本）
  D. ETF 核心配置回測（多市場比例、回撤、再平衡）
  E. 用 9 國數據補 VERDICTS.md 矩陣的空格

常設規矩：
- 用繁體中文回覆；只做股票／ETF；不加歐洲市場
- 任何回測先寫預先登記並 commit，才寫程式跑數；只測一次；只修程式錯誤並揭露改前改後數字
- 判決追加到 stock_research/VERDICTS.md（不要再寫進共用手冊第二節）
- 不 force-push、不 rebase 別人的 commit，合併用 git pull --no-rebase；不開 PR 除非我要求；commit 不寫模型名
- Telegram token 只在 GitHub Secrets（TG_BOT_TOKEN／TG_CHAT_ID），不要寫進程式或對話；不要用 .github/tg_outbox.txt
```
