# 《TW-SelfSelect》 解說腳本 — 回測怎麼看

> **短片旁白稿 · 直式 9:16**
> 對應 `plans/ppt/about_backtest/about_backtest.pptx`（6 頁；文案與 6 張示意圖由
> `plans/ppt/about_backtest/make_about_backtest.py` 產生）。
> **目標總長 3 分鐘內**（2026-11-05 使用者要求）⇒ **實測 169.8 秒（2 分 50 秒）**：
> 10.63／36.79／23.47／29.21／31.01／36.41 秒（段間 0.4 秒 ×5）。各頁標題的秒數即實測值。
> 使用方式：逐頁照讀；「講師提示」不需唸出（`build` 會剝掉，只寫進備註）。
>
> 配音＋出片：
> ```bash
> bash plans/generate_narration.sh build \
>   "plans/ppt/about_backtest/about_backtest.pptx" "plans/ppt/about_backtest/about_backtest-解說腳本.md"
> # 出片：音源要 audio_44k，timeline 也要指到本尊（不要用 cp 的副本，會與新配音錯位）
> mkdir -p TMP/abt_build/narr44
> ln -sfn "$PWD/plans/ppt/about_backtest/_narration_about_backtest/timeline.json" TMP/abt_build/narr44/timeline.json
> ln -sfn "$PWD/plans/ppt/about_backtest/_narration_about_backtest/audio_44k" TMP/abt_build/narr44/audio
> HOME=$PWD/TMP/lohome RENDER_SCALE=2.45 OUT_SIZE=1080:1920 bash plans/ppt_to_mp4.sh \
>   "plans/ppt/about_backtest/about_backtest-講稿版.pptx" "TMP/abt_build/narr44" \
>   "plans/ppt/about_backtest/about_backtest-配音版.mp4"
> ```
>
> 〔口徑〕數字全部是 2026-11-05 快照：宇宙 672 檔（610 存活＋62 下市）、月營收 645/672、PER 672/672，
> 前向驗證取自 `results/walk_forward/wf_presets_2020_2025.md`。旁白只講畫面上看得到的東西。

---

## slide-1 封面：回測怎麼看（11 秒）

這部短片講回測跟實盤的差異。
回測可以讓一個策略看起來很賺，但有四件事，會讓它比實盤好看。

**講師提示**：封面就把四件事列完——倖存者偏差、前向驗證、滑價、買不到；上面的曲線落差圖就是整支片的主題。四件事裡的「前向驗證」佔兩頁（P3 講方法、P4 講結果）。

---

## slide-2 第一件：倖存者偏差（37 秒）

第一件，倖存者偏差。
只用今天還活著的股票回測，等於先偷看誰會倒。
2016 年初市值前五名，後來全部下市或被併。
62 檔補回宇宙，變成 672 檔。
池 150 從 +1289.5% 掉到 +1070.5%，池 20 反而上升。
偏差不是單向的，一定要重跑。

**講師提示**：重點是「補完不一定變好、也不一定變差」，所以不能靠推理、只能重跑。下市股的價格是用原始價加現金股利自建還原（與存活股的 yfinance 還原價不同源），上櫃（TPEX）下市股仍缺，見 `cairn/backtest-data-pitfalls.md` §七與開放問題。

---

## slide-3 第二件：前向驗證（方法）（23 秒）

第二件，前向驗證。
回測看過的資料，不能再拿來挑參數，否則會有後見之明。
做法是：只用過去挑，隔年才看結果。訓練段逐年變長，測試那年不參與挑選，一共六輪。
紅線右邊的資料，任何一輪都不能看。

**講師提示**：這就是 walk-forward。藍色訓練段是擴張式（anchored、起點固定 2016-01-01）；橘色 OOS 是逐年獨立回測、每年重新以 NT$1,000,000 起跑，所以**不能**和全期回測的年度切片相加。

---

## slide-4 第二件：前向驗證（結果）（29 秒）

結果四勝兩負，輸在 2022 和 2024。
六輪串接 +687.7%，同期 0050 是 +206.4%。
但六輪都挑回同一組，換任何一個參數就掉 382 到 959 個百分點。
所以這是尖峰，不是平台。

**講師提示**：兩個敗點要照講，不要只講串接報酬。下半部的鄰居表是 **in-sample（2016-2025）**，不是 OOS；它的用途是量「最佳那格有多孤立」。另外 OOS 串接換算年化約 +41%，只涵蓋 2020–2025，不能拿去跟全期 in-sample 年化比大小。

---

## slide-5 第三件：滑價（31 秒）

第三件，滑價。
回測用當日收盤價成交，實盤做不到——下單時還不知道成交價。
回測只算了手續費 0.1425% 和證交稅 0.3%，滑價是零。
而我們每月全部換手，一年 24 倍，乘上 0.15%，大約就是每年 3.6%。
所以結論要先打折，再看還站不站得住。

**講師提示**：24 × 0.15% ＝ 3.6% 是**估算**（不是回測量到的值），用途是壓測結論；真正的修法是加一個 `SLIPPAGE` 旋鈕重跑，看優勢還在不在。回測程式裡 `buy_cost`／`sell_net` 只有 `COMMISSION_RATE` 與 `tax_rate`，沒有滑價項。

---

## slide-6 第四件：買不到（36 秒）

第四件，買不到。
漲跌停鎖死、停牌、量太小、零股整張、限價單掛不到、T+2 交割，這些在模擬裡永遠不會發生。
右邊是回測已經算進去的：手續費、證交稅、大盤年線濾網、下市宇宙、PER 和營收資格、暖機、股災防護加硬停損。
還沒算的是滑價，和期末平倉成本，大約 0.44%。

**講師提示**：左欄是「實盤會發生」，右欄是程式裡真的有的規則（`core/backtest_rules.py`、`core/scoring.py`、`core/market_filter.py`），不要讓聽眾以為回測什麼都算了。另外兩個已知落差：法人確認快取全期只有 41 個交易日（那道濾網實質沒作用）、`IMM_OVERHEAT` 預設 0（實盤會擋掉約 1/5 名單）。
