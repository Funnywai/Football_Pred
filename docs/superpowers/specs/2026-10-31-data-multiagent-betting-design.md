# 免費資料 + 多 Agent 足球投注系統設計

- 日期：2026-10-31
- 狀態：v2.1：architecture approved; phase-gated implementation
- 分支：`new-method`（空白分支）
- 舊系統：`archive/agent-v1` / tag `archive-agent-v1`，只作參考，不繼承實作

## Revision 2 changes

本次修訂回應 2026-10-31 external review，重點是把「尚未驗證」的假設降級為待驗證項，並把不可靠的簡化公式換成可測試的 payoff contract。

- **Payoff 不再假設二元**：HDC／HIL 的 split line 與 push 不能用單一 `p * odds - 1` 計算。新增 `packages/payoff`，以 return distribution 定義 win／half win／push／half lose／lose 五種情境，EV 與 Kelly 都由此推導；HAD 只是一種特例。
- **LLM 由 production voter 降為 shadow**：production probability baseline 只由 deterministic model 提供；LLM agents 先產生 shadow forecasts／signals，經 A/B/C 實驗證明 incremental value 後才可能獲得權重。
- **Critic／Arbiter 不再參與選擇**：Critic 只做證據檢查、不投票；Arbiter 只做解釋、不選注；選注由 deterministic policy 完成。
- **時間基準改為 decision time**：prospective 用 `first_seen_at <= decision_at`；retrospective 用 `available_at <= decision_at` 加 `availability_basis`。不以 kickoff 作 leak-free 的唯一界線；補上 `event_time`、`published_at`、`first_seen_at`、`available_at`、`decision_at`。
- **Calibration 與權重更新降級**：200 樣本 isotonic 與 30 個 forecast 更新權重降為 monitoring，不再是 validated threshold；改為 time-block walk-forward 與 match-level cluster 評估。
- **FotMob 不再是保證核心**：標記為 `conditional` primary，實作前必須通過 source feasibility gate；UCL 覆蓋拆分為 `reduced_coverage` 與 `insufficient_coverage`。
- **500 bets 是 checkpoint**：500+ settled bets 只代表「可以開始檢討」，不代表策略已證明穩定盈利；同時要求保存所有 eligible matches 的預測、回報不確定區間，並分開 decision-time 與 closing market 比較。

## Revision 2.1

本次修訂回應 v2.1 external review，重點是收緊 probability contract、移除 split-line 假設、補上 idempotency 與 bankroll reservation，並把 acceptance gates 按 phase 拆開。

- **Probability contract**：取消 `[0.01, 0.99]` 全域 clipping；probability 必須 finite、`[0, 1]`、總和為 1（容差內）；不可能結果必須是 0。Epsilon 只用於 log-loss／JSD 等數值運算的工作副本，不可覆寫已儲存的 forecast distribution。
- **Split-line de-vig**：不再假設 split line 的兩個半注可以各自 de-vig。payoff 可以按規則拆 stake，但市場概率推論不可由一個 split-line quote 發明兩條 component-line 價格。第一版 HDC／HIL market baseline 標為 `unavailable`；HDC／HIL EV 用 model score distribution 加實際 quoted price，不阻塞 EPL+HAD MVP。
- **Idempotency 與 bankroll**：run key 拆成 `analysis_run_key`、`decision_slot_key`、`bet_intent_key` 三層；`bet_intent_key` 有 DB unique constraint；bankroll check、reserve、write bet 在同一 transaction；新增 `cash_available` 與 `reserved_stake`。Shadow 不影響 production uniqueness 或 bankroll。
- **Phase gates**：acceptance 由單一「上線前」改為 G0 到 G4；G1（EPL+HAD paper MVP）不被 G2／G3／G4 阻塞。
- **Historical availability**：prospective 仍用 `first_seen_at <= decision_at`；retrospective 新增 `available_at`、`availability_basis` 與 evidence-grade labels，禁止把今天的下載時間回填成歷史可用時間。

## 1. 目標

建立一套以香港賽馬會（HKJC）足球賠率為市場價格的 paper-only 預測與投注研究系統。

系統要做到：

1. 盡量收集免費足球資料，建立可追溯的資料層。
2. 用 deterministic 模型產生 production probability baseline，輸出 score distribution 與各 market 的 return distribution。
3. 用 payoff engine 把「score distribution × market line × selection」映射成 return distribution，再據此計 EV、Kelly 與結算期望值。
4. LLM agents 初期只產生 shadow forecasts／signals，不進入 production 概率；必須經 A/B/C 實驗證明 incremental value 才可取得權重。
5. 將 model return distribution 與 HKJC 賠率比較，找出 +EV 注項。
6. 由 deterministic policy 決定是否落注、注碼與曝險；Critic 不投票、Arbiter 不選注。
7. 完整記錄 paper bet、結算、CLV、Brier、ROI、最大回撤。
8. 只用免費資料；testing phase 只支付 agent API 費用。
9. 不接真錢、不自動登入 HKJC、不自動落注。

第一個要驗證的 decision slice 是 **EPL + HAD**：資料最完整、市場最深、結算規則最簡單。完整目標仍是 5 大聯賽＋UCL 的 HAD／HDC／HIL，但在 EPL + HAD 的 deterministic baseline、walk-forward 與 decision-time gate 通過之前，不擴展到 HDC／HIL。

## 2. 已鎖定決策

| 項目 | 決策 |
|---|---|
| 聯賽 | 5 大聯賽（EPL、La Liga、Bundesliga、Serie A、Ligue 1）＋ UEFA Champions League |
| 市場 | 主客和（HAD）、讓球（HDC）、入球大細（HIL）；`HHA`（讓球主客和）不在範圍 |
| 資金 | 完全 paper-only；paper bankroll 初始 HK$10,000 |
| 資料成本 | 免費 API、免費 tier、公開頁面；不買 paid data |
| Agent API | DeepSeek Flash（OpenAI-compatible） |
| 架構 | Modular monolith：FastAPI + Postgres + Redis worker + Scheduler + Next.js |
| 概率決策 | Production baseline 只由 deterministic model 提供；LLM agents 初期只做 shadow forecasts／signals；Critic 不投票；Arbiter 不選注；selection 由 deterministic policy 執行 |
| Payoff | 必需共享元件 `packages/payoff`：以 return distribution 處理 HAD／HDC／HIL，包括 push 與 split line；EV、Kelly、backtest 與 settlement 共用 |
| 時間基準 | Prospective 用 `first_seen_at <= decision_at`；retrospective 用 `available_at <= decision_at` 加 `availability_basis`；不可把今天下載時間回填為歷史可用時間 |
| 首個驗證 slice | EPL + HAD；full target 仍為 5 大聯賽＋UCL 的 HAD／HDC／HIL |
| 觸發 | T-24h 收集、T-3h 更新、T-75m confirmed lineup gate、T-30m 完整決策；T-75m → T-30m 之間對 confirmed lineup 再檢查一次 |
| Paper run 檢討門檻 | 500+ settled bets 只是 review checkpoint，不是穩定盈利的證明；另需 Brier/log-loss 優於 market、正 CLV、扣佣金 ROI > 0、最大回撤 < 15%，並附不確定區間 |
| Lineup 核心 | FotMob 為 `conditional` primary，不是保證核心；EPL 用 PL pulselive + FPL 交叉驗證；未通過 source feasibility gate 前不得假設可用 |

## 3. 非目標

- 不接受真錢注項，不產生自動下注指令。
- 不登入 HKJC 帳戶，不繞過任何登入或驗證。
- 不做 in-play／live betting。
- 不做所有 HKJC 聯賽、所有玩法；只做上述 5 聯賽＋UCL 的三個核心市場。
- UCL 只覆蓋 football-data.org 免費 tier 提供的主賽事；資格賽不保證。
- HKJC 若某場某市場沒有提供或已停售，該市場直接 no-bet，不用外部賠率代替。
- 不轉售、不再散布任何資料源內容。
- 不把 LLM 當成唯一 probability source；LLM 不能直接改 stake。
- 不使用二元 `p * odds - 1` 作為 HDC／HIL 的通用 EV／Kelly 公式；split line 與 push 必須由 return distribution 處理。
- 不預設 LLM agents 有任何 production probability weight；沒有 A/B/C 證據前，權重為 0。
- 不以「資料時間 < kickoff」作為唯一的 leakage 定義；backtest 必須以 `decision_at` 為界。
- 不把 500+ settled bets 當成穩定盈利的證明；它只是 review checkpoint。
- 不保證盈利；系統目標是建立可審計、可校準的研究流程。

## 4. 免費資料現實與限制

### 4.1 主要來源

Source 狀態定義：

- `verified`：已用當前賽季真實 fixtures 確認 endpoint／schema／欄位／更新時間，且允許用途已確認。每筆 `verified` 必須附 `verification_date`、`schema_scope`、`field_scope` 與 `test_evidence_ref`；只有 design review 不可標為 `verified`。Design review 不證明 API availability、價格覆蓋或 licensing。
- `conditional`：目前可用，但覆蓋、更新時間、允許用途或長期穩定性未完全確認；必須有 degradation policy。
- `blocked`：不可用，或 ToS／技術限制使其不可作核心依賴。

未經 real-fixture 驗證的 endpoint、價格與免費覆蓋一律不得標為 `verified`。

| 資料 | 來源 | 覆蓋 | 角色 | 狀態 |
|---|---|---|---|---|
| 賽程、賽果、積分 | football-data.org v4 | 5 聯賽＋UCL | 賽程與結果 backbone | `conditional`（free tier 當前賽季覆蓋待 real fixtures 確認） |
| xG、xGA、npxG、PPDA、deep | Understat | 5 聯賽 | 進攻／防守／戰術特徵 | `conditional`（非官方、無 SLA、賽後更新） |
| Predicted XI、confirmed XI、傷停／停賽 | FotMob `/api/data` | 5 聯賽＋UCL | Squad 主要來源（conditional primary） | `conditional` |
| EPL lineup cross-check | PL pulselive API | EPL | 官方 lineup 驗證 | `conditional` |
| EPL 傷停 cross-check | FPL API | EPL | `status`、`news`、`chance_of_playing` | `conditional` |
| 歷史 xG／賠率 | football-data.co.uk | 5 聯賽 | 回測、CLV baseline | `verified`（靜態 CSV，規則穩定） |
| HKJC 賠率 | HKJC GraphQL | 5 聯賽＋UCL | 主要市場價格 | `conditional`（endpoint 已驗證；逐場逐市場價格覆蓋未保證） |
| HKJC 賽果／派彩確認 | HKJC `matchResults` | 5 聯賽＋UCL | 最終結算 | `conditional` |
| 新聞／記者會 | BBC、Guardian、Google News RSS、球會官網 | 全部 | News agent 文字證據 | `verified`（公開 feed；內容完整性不保證） |
| 天氣 | Open-Meteo | 全部 | Context 特徵 | `verified` |
| 多間莊家賠率 | The Odds API | 視 free tier | 可選 enrichment，不是核心依賴 | `conditional` |

表中狀態是 proposed status。任何標為 `verified` 的 source，仍必須在 `source_fetch_runs` 有 `verification_date`、`schema_scope`、`field_scope`、`test_evidence_ref` 與 `licensing_check`；未記錄前不可在 acceptance 中當成已驗證。

### 4.2 已驗證的重要限制

**HKJC**

- 舊 `getJSON.aspx` 已失效，現在使用 `https://info.cld.hkjc.com/graphql/base/`。
- 免登入，但只接受官網自己的 GraphQL query 字串；自訂 query 會回 `WHITELIST_ERROR`。
- `HAD`、`HDC`、`HIL` 必須分開請求；不能合併成一次。
- 賠率是 fixed odds；paper ledger 必須使用落注時 snapshot，不是 closing odds。
- `matchResults` 的 `payoutConfirmed=true` 是 finalise 條件。
- `HAD`／`HDC`／`HIL` 以法定比賽時間結算，不包括加時、十二碼、重賽。
- `HDC` 的 `condition` 套用於主隊；`+` 為主隊受讓，`-` 為主隊讓球。
- `HDC`／`HIL` 的 `condition` 可能是 `1.0/1.5` 這類 split line，必須拆成兩個半注獨立結算。
- HKJC 派彩以最接近 HK$0.10 計算。

**FotMob**

- 目前觀察到同時提供 5 聯賽＋UCL 的 predicted XI、confirmed XI、injury/suspension、expectedReturn 的免費來源；這是待驗證的覆蓋假設，不是保證。
- 定位為 `conditional` primary，不是 guaranteed core；未通過 source feasibility gate 前，不得讓 pipeline 假設它一定可用。
- `robots.txt` 明文 `Disallow: /api/*`，並有官方 takedown request。
- 設計接受此風險，但只作低頻、快取、個人研究用途；必須有 adapter 抽象與 fallback。
- `lineupType=predicted` 可在 T-24~48h 取得；`lineupType=standard` 在官方名單後取得。
- 若 FotMob 被封、schema 改變或 feasibility gate 不通過，降級至 PL pulselive／FPL（只 EPL）及最近先發頻率推算；UCL 若無可靠 fallback，標記 `insufficient_coverage`，該場 lineup-dependent market no-bet。

**Understat**

- 5 聯賽有 xG／xGA／PPDA／deep；沒有 UCL。
- 賽後更新，不是賽前即時訊號。
- UCL 場次必須標記 `ucl_xg_missing`，並按 §4.5 分為 `reduced_coverage` 或 `insufficient_coverage`；不可假裝有同等 xG 覆蓋。

**其他來源**

- FBref：Cloudflare 阻擋，ToS 禁止 scraper；不作核心。
- Sofascore：實測 403，ToS 禁止；不作核心。
- WhoScored：403 + Incapsula；不作核心。
- Transfermarkt HTML：AWS WAF 405；只可選用不穩定 JSON API，不作核心。
- API-Football free：season window 滯後，不能保證當前賽季；不作核心。
- StrikerAPI：付費，違反免費資料條件；不使用。
- The Odds API：免費 tier 對足球／spreads／totals 的覆蓋不確定；只作 optional，不阻塞核心 pipeline。

### 4.3 資料品質原則

- 每個 source 必須有 `source_name`、`source_url`、`fetched_at`、`schema_version`、`payload_hash`。
- Historical records 另需 `available_at`、`availability_basis`、`evidence_grade`（見 §6.3）；`fetched_at` 不可代替 `available_at`。
- Raw payload 保留但不可變；normalized data 可重建。
- 每個 match 有 coverage flags：`ucl_xg_missing`、`lineup_unconfirmed`、`odds_stale`、`news_missing`、`source_degraded`；UCL 另外有 `reduced_coverage`／`insufficient_coverage` 分級。
- 結果資料必須分開保存 `home_goals_90`／`away_goals_90` 與 `home_goals_final`／`away_goals_final`；只有 final score 的來源不可用作目標市場結算。
- 任何缺資料的 market 都要可以被 Risk Agent veto；不可用預設值假裝完整。

### 4.4 Source feasibility gate（實作前必須完成）

任何 source 在成為 pipeline 依賴前，必須逐項通過：

1. **允許用途**：確認 ToS、robots、授權與個人研究用途是否允許；不允許即標 `blocked`，不得靠技術繞過。
2. **欄位／覆蓋／更新時間**：用當前賽季真實 fixtures 驗證必要欄位、聯賽覆蓋率、更新延遲與缺值率；未驗證前維持 `conditional`。
3. **Degradation／stop policy**：為每個 `conditional` source 定義失敗偵測、fallback、no-bet 條件與停止使用條件；沒有 fallback 的 source 不得支撐不可替代的 market。
4. **不得預先假設**：endpoint 存在、價格可讀、免費 tier 覆蓋某一市場，都不等於已驗證；未經第 2 步確認前，不得在 backtest 或 acceptance 中當成既定事實。

Feasibility gate 的結果要記錄在 `source_fetch_runs` 與 data-health UI，至少包括 `verification_date`、`schema_scope`、`field_scope`、`test_evidence_ref`、`licensing_check`。狀態可隨驗證結果在 `verified`／`conditional`／`blocked` 之間更新；沒有上述證據時不可升級為 `verified`。

### 4.5 UCL coverage 分級

UCL 不再用單一 `coverage_gap=true` 混在一起：

- `reduced_coverage`：核心欄位（賽果、賽程、HKJC 賠率）可用，但 xG 或 lineup 覆蓋不完整。允許 goals-based fallback model，但必須獨立驗證其 calibration 與 ROI，且在 UI 與 ledger 標記；只可降低信心與 stake，不可假裝等同 5 聯賽覆蓋。
- `insufficient_coverage`：缺少可結算的賽果、缺少目標 market 價格，或 lineup-dependent market 無可靠 fallback。此狀態對該 market 直接 veto，不產生 paper bet。

「goals-based fallback 可用」不是預設允許，而是要在 `reduced_coverage` 下另外通過獨立驗證；未通過前，UCL 只可做 HAD 的 goals-based baseline，不可做 HDC／HIL。

### 4.6 T-75m 與 T-30m 的 fallback／retry

- **T-75m**：先取 `lineupType=standard`；若未出，最多 3 次（T-75m、T-65m、T-55m）。Retry cadence 由 §14 的 single source-level FotMob rate limiter 統一控制，retry 邏輯不另設 cadence。仍無 confirmed lineup，標記 `lineup_unconfirmed`，由 Risk Agent 決定是否 veto 或降級至 predicted。
- **T-30m**：決策前再檢查一次 confirmed lineup；若有更新，重跑 feature builder 與 deterministic model，並使舊 shadow ensemble 與舊 forecasts 失效。若 T-30m 仍只有 predicted，維持 `lineup_unconfirmed`，lineup-dependent market 預設 no-bet。
- **Retry 失敗**：每次 retry 記錄 `source_fetch_runs`；連續失敗達 3 次即標 `source_degraded`，套用該 source 的 degradation policy，不得無限重試。
- **Odds**：T-75m 與 T-30m 各自保存 snapshot；若 T-30m 無可用 snapshot，使用最近一次且未超過 10 分鐘的 snapshot，否則 no-bet。

## 5. 系統架構

### 5.1 Runtime

```text
apps/
  api/            FastAPI：查詢、trigger、dashboard API
  worker/         RQ worker：ingest、feature、model、agent、settle
  scheduler/      APScheduler：T-24h / T-3h / T-75m / T-30m
  web/            Next.js dashboard

packages/
  domain/         canonical IDs、market semantics、errors
  adapters/       每個資料源一個 adapter
  features/       rolling features、lineup strength、context
  models/         Dixon-Coles、Elo、GBM、calibration
  payoff/         pure functions：score distribution × line × selection → return distribution
  agents/         deterministic agents + LLM agents（shadow）
  ensemble/       shadow aggregation、disagreement（非 production 概率）
  value/          de-vig、EV、Kelly（呼叫 payoff）
  risk/           hard veto、exposure
  policy/         deterministic bet selection、stake sizing
  ledger/         paper bets、settlement、CLV
  backtest/       歷史重跑
  shared/         config、logging、schema
```

技術選擇：

- Python 3.12 + `uv`
- FastAPI + Pydantic v2
- SQLAlchemy 2 + Alembic
- Postgres 16
- Redis 7 + RQ
- APScheduler
- Next.js
- `httpx`、`feedparser`、`pandas`、`numpy`、`scipy`、`scikit-learn`、`lightgbm`
- OpenAI-compatible client 呼叫 DeepSeek Flash

### 5.2 Module 邊界

| Module | 負責 | 不負責 |
|---|---|---|
| `adapters` | 抓取、schema 驗證、raw payload、source timestamp | 特徵、模型、注碼 |
| `domain` | canonical match/team/player/market line | 外部 API 格式 |
| `features` | rolling xG、PPDA、rest days、lineup strength、odds movement | 預測 |
| `models` | deterministic score distribution、calibration | 文字解釋 |
| `payoff` | 把 score distribution、market line、selection 映射成 return distribution；提供 EV 與 Kelly 所需的 `R(s)` | 抓資料、選注、寫 ledger |
| `agents` | shadow probability forecast、signal extraction、理由、反方證據 | production 概率、直接落注 |
| `ensemble` | shadow aggregation、disagreement、confidence；只用於實驗與比較 | production 概率、風控否決 |
| `value` | 去水、EV、Kelly fraction；必須經 `payoff` 計算 return distribution | 最終批准 |
| `risk` | hard veto、曝險、資料新鮮度 | 估概率 |
| `policy` | deterministic bet selection、stake sizing、no-bet 判定 | 改概率、覆寫 Risk veto |
| `ledger` | paper bet、HKJC 結算、CLV、Brier、ROI | 真實下注 |
| `backtest` | 歷史重跑、校準、策略比較；用 `payoff` 重算 EV／Kelly | production 寫入 |

`settlement` 與 `payoff` 的界線：

- `settlement` 用實際 90 分鐘賽果與 HKJC 規則，計算「這張 bet 的實際 payout」；輸入是賽果與 bet，輸出是 `won`／`lost`／`half_won_half_push`／`half_lost_half_push`／`push`／`void` 與金額。
- `payoff` 在賽前用 score distribution、market line 與 selection 計算「每種 score 對應的 return」，輸出 return distribution；它不接觸實際賽果，也不寫 ledger。
- `settlement` 直接 import `payoff` 的 line parser 與 settlement-class mapping，再以實際賽果取代 score distribution 去計 payout；兩者不可各自實作一套 split-line 規則。

## 6. Data Model

### 6.1 核心 tables

```text
competitions
teams
players
matches
lineups
availability
odds_snapshots
market_lines
features
model_predictions
agent_reports
agent_forecasts
ensemble_forecasts
value_bets
risk_decisions
paper_bets
bankroll_accounts
bankroll_reservations
settlements
news_signals
raw_payloads
source_fetch_runs
agent_runs
calibration_metrics
```

### 6.2 關鍵欄位

`matches`

- `id` canonical UUID
- `competition_id`
- `season`
- `event_time` UTC（賽事預定發生時間；足球等於 kickoff）
- `kickoff_at` UTC
- `first_seen_at` UTC（本系統第一次取得此 match 的時間）
- `home_team_id`、`away_team_id`
- `status`
- `home_goals_90`、`away_goals_90`
- `home_goals_final`、`away_goals_final`（只作顯示／覆核，不用於目標市場結算）
- `result_available_at` UTC
- `result_availability_basis`
- `result_evidence_grade`
- `source_match_ids` JSONB

`lineups`

- `match_id`
- `team_id`
- `lineup_type`：`predicted` / `standard`
- `formation`
- `starters` JSONB
- `subs` JSONB
- `source`
- `fetched_at`
- `available_at` UTC
- `availability_basis`
- `evidence_grade`
- `inferred` boolean

`availability`

- `match_id`
- `team_id`
- `player_id`
- `status`：`injury` / `suspension` / `doubtful` / `available`
- `reason`
- `expected_return`
- `source`
- `source_url`
- `fetched_at`
- `available_at` UTC
- `availability_basis`
- `evidence_grade`

`market_lines`

- `snapshot_id`
- `odds_type`：`HAD` / `HDC` / `HIL`
- `condition_raw`：例如 `1.0/1.5`
- `line_index`
- `side`：`H` / `D` / `A` / `L`
- `odds_decimal`
- `pool_status`
- `line_status`
- `is_main`
- `offer_early_settlement`
- `source_update_at`
- `available_at` UTC
- `availability_basis`

`agent_forecasts`

- `agent_run_id`
- `agent_name`
- `market`
- `line_key`
- `outcome`
- `probability`（binary selection 用）或 `return_distribution` JSONB（multi-outcome 用）
- `confidence`
- `decision_at` UTC
- `evidence_refs` JSONB
- `counter_evidence` JSONB
- `abstained` boolean
- `prompt_version`
- `model_version`

`ensemble_forecasts`

- `match_id`
- `market`
- `line_key`
- `outcome`
- `probability`
- `return_distribution` JSONB
- `decision_at` UTC
- `weights_snapshot` JSONB
- `disagreement`
- `coverage_flags` JSONB

`model_predictions`

- `match_id`
- `market`
- `line_key`
- `outcome` 或 `return_distribution` JSONB
- `decision_at` UTC
- `model_version`

`news_signals`

- `source_name`
- `source_url`
- `published_at` UTC
- `first_seen_at` UTC
- `available_at` UTC
- `availability_basis`
- `evidence_grade`
- `fetched_at` UTC
- `payload_hash`

`paper_bets`

- `match_id`
- `market`
- `line_key`
- `selection`
- `odds_decimal`
- `stake`
- `bankroll_before`
- `analysis_run_key`
- `decision_slot_key`
- `bet_intent_key`（UNIQUE constraint）
- `decision_at` UTC
- `placed_at`
- `odds_snapshot_id`
- `status`

`bankroll_accounts`

- `account_id`
- `currency`
- `bankroll_balance`
- `updated_at`

`bankroll_reservations`

- `reservation_id`
- `bet_intent_key`
- `amount`
- `status`：`held` / `committed` / `released`
- `created_at`
- `updated_at`

`settlements`

- `paper_bet_id`
- `result_status`：`pending` / `won` / `lost` / `half_won_half_push` / `half_lost_half_push` / `push` / `void`
- `payout`
- `clv`
- `brier_score`
- `settled_at`
- `hk_result_ref`
- `provisional` boolean

### 6.3 Temporal integrity

時間欄位的語義必須分開：

| 欄位 | 定義 | 用途 |
|---|---|---|
| `event_time` | 賽事預定發生時間（足球為 kickoff） | 排程、T-offset、避免用未來事件 |
| `published_at` | 來源聲稱的發布時間 | 顯示、新聞時序；不可單獨當作本系統可知時間 |
| `first_seen_at` | 本系統第一次取得該資料的時間 | prospective paper run 的 leakage gate |
| `available_at` | 該資料在歷史上最早可被知道的時間，由 observed snapshot 或 provider point-in-time 推得 | retrospective research 的 availability gate |
| `availability_basis` | `observed_snapshot` / `provider_point_in_time` / `availability_assumed` / `unavailable` | 標示 `available_at` 的證據等級 |
| `decision_at` | 本次預測／選注的決策時間 | 定義「當時可知」的資料切片 |

規則：

- **Prospective paper run**：只可使用 `first_seen_at <= decision_at` 的資料；`published_at` 較早但 `first_seen_at` 較晚的資料，在該次決策中視為不可知。
- **Retrospective research**：使用 `available_at <= decision_at`，並以 `availability_basis` 標示證據等級。只有 `observed_snapshot` 與 `provider_point_in_time` 可作主要結果；`availability_assumed` 只可作 sensitivity analysis；`unavailable` 必須排除。
- 不可把今天的下載時間 `first_seen_at` 回填成歷史 `available_at`。`available_at` 必須有當時 snapshot 或 provider point-in-time timestamp 支撐。
- 不可把 retrospective 的賽果、新聞、lineup、weather 當成與 decision time 當時可知的資料等價。每項 historical news／injury／lineup／weather 必須有 `evidence_grade`，值為 `observed_snapshot`、`provider_point_in_time`、`availability_assumed` 或 `unavailable`。
- Prospective paper-run report 與 retrospective backtest report 必須分開輸出；不可混合樣本、混合指標，或把 retrospective 結果標成 prospective evidence。
- 需要 `available_at`／`availability_basis`／`evidence_grade` 的 historical records 至少包括：matches 的賽果、lineups、availability、news_signals，以及 retrospective 版本的 odds／market_lines。缺少者標 `unavailable`，不可進入 retrospective primary analysis。
- `event_time` 只界定比賽何時發生；不能因為資料時間早於 kickoff 就假設沒有 leakage。Prospective 的判準是 `first_seen_at` 與 `decision_at` 的關係；retrospective 的判準是 `available_at` 與 `decision_at` 的關係。
- 歷史新聞不可用「事後重新搜尋」重建當時的 evidence packet；backtest 必須使用當時已保存的 raw payload／news snapshot。若沒有當時快照，該場的新聞特徵標記 `news_unavailable_at_decision`，不可用後見內容補上。
- `decision_at` 在 production 是 T-30m；backtest 必須模擬同一個 decision time，不可用賽後或 closing 資料回填。
- 30 場歷史 dry run 只作 engineering／settlement 驗證，不構成 LLM predictive evidence；不得用它推論 LLM agent 的預測能力。
- T-75m 取得 confirmed lineup 後，必須在 T-30m 再檢查一次；若 lineup 在 T-75m 與 T-30m 之間改變，T-30m 的 `decision_at` 必須使用更新後的 evidence packet，舊預測失效。

## 7. Pipeline

### 7.1 每日與每場 trigger

```text
每日 06:00 HKT
  更新賽程、球隊、球員、歷史結果、Understat rolling data

T-24h
  收集初盤 HKJC odds、新聞、天氣、預測陣容
  不跑 LLM agents

T-3h
  更新傷停、記者會、賠率
  不跑 LLM agents

T-75m
  confirmed lineup gate
  若 lineupType=standard：凍結 lineup
  若仍 predicted：標記 inferred=true，按 §4.6 retry

T-30m
  confirmed lineup recheck（T-75m → T-30m）
  feature builder
  deterministic model（production probability baseline）
  LLM agents（4 shadow analysts + 1 arbiter）→ shadow reports / signals
  shadow ensemble（只記錄，不進 production 概率）
  payoff engine → return distribution
  value + risk（基於 deterministic return distribution）
  deterministic policy：paper bet 或 no-bet
  Arbiter 只產生解釋，不選注

T-5m
  最後 odds snapshot，作 CLV closing reference
  不再改 paper bet

賽後
  HKJC matchResults（payoutConfirmed）
  settlement engine
  CLV / Brier / ROI / drawdown
```

### 7.2 Idempotency、bankroll reservation 與成本控制

**三層 idempotency key**

- `analysis_run_key`：`match_id + trigger + model_version + prompt_version + analysis_run_id`。允許同一場用不同 model／prompt 重跑分析；它不授權新的 official bet。
- `decision_slot_key`：`strategy_version + match_id + decision_window`（例如 `T-30m`）。代表一個 strategy 在一場比賽的一個官方決策；同一 slot 只可有一個 official decision。
- `bet_intent_key`：`decision_slot_key + market + line_key + selection`。代表一張 official bet intent；worker retry 必須重用同一個 key。
- `paper_bets.bet_intent_key` 必須有 database unique constraint。Worker retry 撞到 unique constraint 時，視為已寫入，不可再寫第二張 bet。
- Worker retry 必須重用 decision 時的 `odds_snapshot_id`；不可因 retry 時 odds 更新而另寫第二張 bet。
- Shadow runs 使用自己的 `analysis_run_key` 命名空間與 shadow tables，不建立 `bet_intent_key`，也不影響 production bet uniqueness 或 bankroll。

**Bankroll reservation transaction**

- `cash_available = bankroll_balance - reserved_stake`。
- `reserved_stake = sum(active bankroll_reservations.amount)`。
- 一次 official bet 必須在同一個 database transaction 完成：`SELECT ... FOR UPDATE` 鎖定 `bankroll_accounts` row → 檢查 `cash_available` 與所有 exposure limits → 插入 `bankroll_reservation` → 寫入 `paper_bet`（含 `bet_intent_key`）。全部成功才 commit。
- 若 `cash_available` 不足或 exposure 超限，整個 transaction rollback，該 bet 為 no-bet，不可先寫 bet 後補檢查。
- 同時進行的多個 decisions 會在同一 bankroll row 上序列化，不能花用同一筆 `cash_available`。
- 結算或取消時，reservation 由 `held` 轉 `committed` 或 `released`；`released` 後才回到 `cash_available`。

- T-24h、T-3h 不呼叫 LLM。
- T-30m 每場最多 5 次 LLM 呼叫：Performance、Tactics、Context/News、Critic、Arbiter；全部都只產生 shadow 輸出。
- Shadow 輸出只寫入 `agent_reports`／`agent_forecasts` 與實驗紀錄，不可改 production probability、stake、selection 或 Risk veto。
- LLM 回應快取：同一 evidence hash + prompt version 重用。
- 每日 agent 成本硬上限：預設 US$5/day；每月 US$50/month；超過即停止 LLM shadow，deterministic pipeline 照常運作。
- 若 agent API 失敗，該 agent abstain；不可用其他 agent 的回應補上，也不可因 shadow 缺失而阻塞 deterministic paper bet。

## 8. Deterministic Models

### 8.1 模型組合

1. **Dixon-Coles / Poisson**
   - 以主隊攻擊、客隊防守、主場優勢、時間衰減估計入球率。
   - 產生 score matrix（0–10 球），再經 payoff 推導 1X2、HDC、HIL 的 outcome／return distribution。
2. **Elo baseline**
   - 由歷史賽果自行計算；不依賴 ClubElo 的可用性。
   - 作為獨立 strength prior。
3. **Gradient Boosting**
   - LightGBM 或 HistGradientBoosting。
   - 特徵：rolling xG/xGA、PPDA、deep、rest days、schedule density、lineup strength、home/away splits、opponent strength、weather。
4. **Calibration**
   - 每個 market 獨立校準，但評估時要檢查跨 market 一致性。
   - 小樣本先用 raw probability；需要平滑時用 sigmoid／Platt scaling，不要一開始就用 isotonic。
   - Isotonic regression 只在樣本足夠、且以 time-block walk-forward 驗證有改善時才使用；200 場不是 validated threshold，只是過去曾使用的起點，不得當作充分條件。
   - Calibration mapping 與任何 ensemble 權重（包括 shadow ensemble）都必須在較早 time block 訓練、較晚 time block 測試；不得用同一批資料同時 fit 與 evaluate。
   - 評估 correlated markets（同一場的 HAD／HDC／HIL）時，以 match 為 cluster 計算不確定性，不可把同場注項當獨立樣本。
   - 校準後要重新檢查跨市場一致性（例如 HAD implied probabilities 與 HDC／HIL return distribution 是否矛盾），不是只在校準前檢查。

### 8.2 輸出

- 1X2：`p_home`、`p_draw`、`p_away`，由 score matrix 聚合。
- Total goals：score matrix，以及各 HIL line 每個 selection 的 return distribution（包括 over／under 與 push）。
- Handicap：各 HDC line 每個 selection 的 return distribution；split line 由兩個半注的 return 合併，不可只輸出單一 cover probability。
- 所有 market 都必須輸出完整 outcome／return distribution；「某 selection 的單一 probability」只是衍生摘要，不可作為 EV／Kelly 的唯一輸入。

**Distribution contract（所有 model、payoff、agent schema 共用）**

- 每個 probability 必須是 finite number，且落在 `[0, 1]`。
- 同一 distribution 的 total 必須為 1，容差由設定常數控制（預設 `1e-6`）；超出容差即 schema invalid。
- 不可能發生的 outcome 必須是 exactly `0`，不可用 `0.01` 或其他 floor 代替。
- Epsilon 只用於數值運算（例如 log-loss、JSD）的工作副本；它不可覆寫已儲存的 forecast distribution，也不可改變回報／結算類別的真實 0。
- 不可再使用全域 `[0.01, 0.99]` clipping。舊規則廢除。
- 此 contract 必須兼容 0–10 球的 121-cell joint score distribution，以及可以合法為 0 的 settlement categories（例如不可能 push 的 line）。

**0–10 score matrix 的 tail mass**

- Score matrix 固定覆蓋主隊 0–10、客隊 0–10，共 121 cells。
- 若 model 在 0–10 以外的 tail 仍有 mass，必須二選一並記錄：
  - 擴展 grid 直到 tail mass 低於設定的 mass tolerance（預設 `1e-6`），或
  - 明確記錄 `truncation_mass`，並在輸出前 renormalize，且在 model output 標記 `tail_handling=truncated_renormalized`。
- 不可靜默丟棄 tail mass。Model output 必須記錄 `score_grid_max`、`tail_mass`、`tail_handling`。

### 8.3 訓練與驗證

- 5 聯賽：football-data.co.uk 歷史結果＋odds；Understat xG 2014/15 起。
- UCL：goals-based features；Understat 無 xG，按 §4.5 分 `reduced_coverage`／`insufficient_coverage`。
- Walk-forward validation；不得用未來賽果或 closing odds 做特徵。
- HAD 用 proportional de-vig 作 adopted market benchmark；decision-time 與 closing 分開計算與報告。
- HDC／HIL 的 market baseline 在第一版標為 `unavailable`，原因是無法從單一 split-line quote 可靠推導 component-line probability。不可用自製 de-vig 分佈假裝有 baseline。
- 比較 Brier、log-loss、calibration curve、ROI；HDC／HIL 在 baseline 可用前只比較 model-implied return distribution 與實際結算，不比較市場概率。

### 8.4 Payoff contract

HDC／HIL 不可只用 `H`／`A` 或 `H`／`L` 兩個概率去計 EV／Kelly。原因是 push、half win／half lose 與 split line 會令同一 selection 對不同 score 有不同回報；只用二元概率會系統性高估或低估 EV。

對一個 selection、decimal odds `o`（已包含本金）、market line `L`，定義每個 score `s` 的 per-unit-stake return `R(s)`：

| 情境 | Return `R(s)` |
|---|---|
| Full win | `o - 1` |
| Half win / half push | `(o - 1) / 2` |
| Push | `0` |
| Half lose / half push | `-1 / 2` |
| Full loss | `-1` |

定義：

```text
EV = sum_s P(s) * R(s)
f* = argmax_f sum_s P(s) * log(1 + f * R(s))
```

- `P(s)` 是 deterministic model 的 score distribution。
- Kelly 用數值方法求解，`f` 限制在 `[0, f_max]`，預設 `f_max = 0.99`；負 EV 時 `f* = 0`。
- 求得 `f*` 後再乘 fractional Kelly（0.25）與其他風控上限。
- 不可用 closed-form `(p*o - 1) / (o - 1)` 取代上述公式，除非已證明該 market 等價於二元、無 push 的單一 line。

**HAD 是特例**：HAD 沒有 push（除非 void），`R(s)` 只有 `o - 1` 與 `-1` 兩種，因此可退化為 `EV = p * (o - 1) - (1 - p)`。這是特例，不是通用公式。

**Split line**：先把 stake 分半，兩個半注各自用上表計 `R(s)`，再取平均作為整個 selection 的 per-unit return。不可用連續讓球公式近似 split line。

**Multi-outcome scoring**：Brier／log-loss 要對完整 outcome／return distribution 計算，不可只對「有冇中」的二元 selection probability 計算。

- HAD：對 `H`／`D`／`A` 三分類計 Brier／log-loss。
- HDC／HIL：對每個 line 的結算類別（`full_win`、`half_win_half_push`、`push`、`half_lose_half_push`、`full_loss`）計 multiclass Brier／log-loss，或使用 ranked probability score；不可把 push 與 half win／half lose 合併成二元。
- Calibration 也要按同一組 outcome class 檢查，而不是只看單一 selection probability。

## 9. Multi-Agent Layer

### 9.1 Agent roster

| Agent | 類型 | 職責 | Production 角色 |
|---|---|---|---|
| Data Steward | deterministic | 資料完整性、freshness、conflict、coverage flags | Gate；不產生概率 |
| Performance Analyst | LLM shadow | xG/xGA、form、home/away、opponent strength 的 structured signal | Shadow forecast；不進 production |
| Squad Analyst | deterministic | lineup、injury、suspension、rotation、strength adjustment | 提供 deterministic model adjustment |
| Tactics Analyst | LLM shadow | PPDA、deep、press height、style matchup、set pieces 的 structured signal | Shadow forecast；不進 production |
| Context/News Analyst | LLM shadow | motivation、schedule、travel、weather、news signals 的 structured signal | Shadow forecast；不進 production |
| Odds/Market Analyst | deterministic | HKJC odds、HAD de-vig、HDC／HIL quoted price、line movement、liquidity flags | Market context；不產生概率 |
| Model Agent | deterministic | Dixon-Coles／Elo／GBM 的 deterministic ensemble | **唯一 production probability baseline** |
| Value Agent | deterministic | 經 `payoff` 計算 EV、Kelly、market comparison | 產生 candidate；不批准 |
| Risk Agent | deterministic | hard veto、exposure、stale data、disagreement | 可否決；不估概率 |
| Policy Agent | deterministic | 按 deterministic 規則由 Risk-approved candidates 選出 paper bet、stake | **唯一 selection 來源** |
| Critic | LLM shadow | 反方論點、資料衝突、失效條件、evidence check | 不投票；不下結論 |
| Arbiter | LLM synthesis | 整合理由、矛盾、最終報告 | 不選注；不可改概率或 stake |
| Feedback Agent | deterministic | Brier、CLV、calibration、model drift、shadow 比較 | 監控；不自動改 production 權重 |

### 9.2 LLM shadow 輸出格式

每個 LLM shadow analyst 必須回傳 strict JSON：

```json
{
  "match_id": "uuid",
  "mode": "shadow",
  "market_forecasts": [
    {
      "market": "HAD",
      "line_key": "0.0",
      "probabilities": {"H": 0.45, "D": 0.27, "A": 0.28},
      "confidence": 0.72,
      "evidence_refs": ["understat:team_form", "fotmob:lineup"],
      "counter_evidence": ["away_rest_days"],
      "abstain": false
    }
  ],
  "notes": "short rationale"
}
```

規則：

- `market` 可為 `HAD`／`HDC`／`HIL`。
- `HAD` 的 probability keys 為 `H`／`D`／`A`。
- `HDC`／`HIL` 不可只回傳 `H`／`A` 或 `H`／`L` 兩個 probability 作 EV 輸入；必須提供以下其中一種：
  - `score_distribution`：主隊／客隊入球數的聯合分布（0–10 球），或
  - `return_distribution`：以 settlement class 為 key 的分布（`full_win`、`half_win_half_push`、`push`、`half_lose_half_push`、`full_loss`）。
- 若 LLM 只回傳 binary probability，該 market forecast 視為 schema invalid，不可用於任何 EV／Kelly 或 ensemble 實驗。
- `line_key` 使用 HKJC 的 `condition_raw`，例如 `0.0`、`1.0/1.5`、`3.5`。
- 每個 LLM shadow analyst 只對每個 market 的 `is_main=true` line 出 forecast；其他 line 由 deterministic model 提供，標記 `llm_coverage=false`。
- 只可引用 evidence packet 內出現的 factual numbers（比分、xG、賠率、傷停、日期等）。
- Evidence validator 只檢查 factual claims 是否有 packet 支撐；LLM 新產生的 forecast probabilities 不是 factual claim，不可因「packet 沒有提供這個概率」而被判 invalid。
- 不可生成不存在的球員、傷停或賠率。
- 資料不足時必須 `abstain=true`。
- 所有 probability 必須符合 §8.2 distribution contract：finite、`[0, 1]`、總和為 1（容差內）、不可能 outcome exactly 0；不可使用 `[0.01, 0.99]` clipping。
- `return_distribution` 的 class probability 可為 exactly 0（例如該 line 不可能 push），且必須 non-negative、sum to 1。
- 不符合 schema 或缺少 evidence refs → 該 agent abstain。
- `mode` 必須是 `shadow`；production 不接受 LLM probability 輸出。

### 9.3 Evidence packet

每個 LLM shadow analyst 收到的是已計算、可追溯的 evidence packet，不是整個 database：

- Match metadata
- Canonical team/player IDs
- FotMob lineup type、formation、starters、unavailable
- Understat rolling xG/xGA/PPDA/deep
- Schedule/rest/travel
- Weather
- HKJC current/opening odds（只作 market context，不用來直接抄概率）
- News signals with source URL and timestamp
- Data quality flags

Evidence packet 規則：

- Packet 必須以 `decision_at` 凍結；prospective 只包含 `first_seen_at <= decision_at` 的資料，retrospective 只包含 `available_at <= decision_at` 且 `availability_basis` 合格的資料。
- 每項資料都要帶 `available_at`、`availability_basis`、`evidence_grade`；prospective 另帶 `first_seen_at`，所有資料另帶 `published_at`。這些欄位不可互相替代。
- 不可包含決策後才出現的賽果、lineup 更新、賠率變動或新聞。
- Backtest 的 packet 必須由當時保存的 raw payload 重建；不可用事後重新抓取的資料補洞。

### 9.4 Production policy 與 shadow aggregation

**Production policy（唯一會影響 paper bet 的路徑）**

- Production probability baseline 只由 deterministic model 提供。
- LLM agents 的初始 production weight = **0**；不得以「先給 30% 再調」的方式起步。
- Value Agent 用 `payoff` 產生的 return distribution 計 EV／Kelly，列出 Risk-approved candidates。
- Policy Agent 按 deterministic 規則（edge 門檻、Kelly、單注／單日／單場上限、相關注項合併）選出最終 paper bet。
- Critic 不投票；Arbiter 不選注；兩者都不能改 production probability、stake 或 selection。

**Shadow aggregation（只用於實驗與監控）**

- LLM shadow forecasts 只寫入 `agent_reports`／`agent_forecasts`，可聚合成 shadow ensemble 作比較，但不進入 production probability。
- Shadow ensemble 的權重只用於實驗報告，不可用於 stake。
- 若未來要使用 LLM probability，必須先完成 §9.6 的 A/B/C 實驗，證明 incremental value，才可設定非零權重。
- 即使日後啟用 LLM probability，HDC／HIL 必須輸出 score distribution 或 full return distribution，不可只輸出 `H`／`A` 或 `H`／`L`。

**權重更新**

- 30 個 finalised forecasts 只是 monitoring 門檻，不是 weight-update trigger；達到 30 個只代表可以開始觀察，不代表可以改權重。
- 任何權重更新必須有預先登記的 A/B/C 比較、足夠樣本與 time-block out-of-sample 結果；未達前維持 LLM weight = 0。
- 更新時 shrink 回 prior，避免短期噪音；實際 shrink 比例由實驗結果決定，不預設 50% 為 validated 參數。

**Disagreement（JSD）**

Disagreement 用 Jensen-Shannon divergence，明確定義：

```text
M = (P + Q) / 2
JSD(P || Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)
KL(A || B) = sum_i A_i * log2(A_i / B_i)
```

- Log base 用 2；兩個 distribution 的 JSD 範圍是 `[0, 1]`。
- Zero handling：只在計算 JSD 的 working copy 上把 probability clamp 到 `[1e-9, 1]` 並 renormalize；不可對 `0` 取 log。已儲存的 forecast distribution 保持原值，epsilon 不可寫回。
- 初始階段只記錄 JSD，**不** 用 JSD 改 stake 或觸發 no-bet；等 shadow 與 production 的關係有實證後，才可定義門檻。
- 不可把舊的 `0.15`／`0.25` 門檻當成 validated threshold；它們只是待驗證的起點。

**沒有 LLM coverage 的 line**：只用 deterministic model；shadow 缺失不影響 production，Risk 只按 deterministic 規則決定是否減注或不落注。

### 9.5 Critic 與 Arbiter

- Critic 使用獨立 prompt，任務是找反例、資料衝突、失效條件；不可只重述其他 agent。
- Critic 只做 evidence check，不投票、不給 production probability、不建議 stake。
- Arbiter 只負責：
  - 整理最終理由。
  - 標記矛盾與反面證據。
  - 解釋 Policy Agent 已選出的 paper bet 與 no-bet 原因。
- Arbiter 不可選注；selection 只由 Policy Agent 按 deterministic 規則產生。
- Arbiter 不可改 shadow ensemble／deterministic probability、不可改 stake、不可新增市場、不可覆寫 Risk veto。
- Critic 或 Arbiter 的 shadow 輸出不可阻塞或改寫 deterministic paper bet；若 shadow 失敗，production 照常運行。

### 9.6 A/B/C 實驗（LLM incremental value）

在 LLM 取得任何 production weight 前，必須完成同條件 A/B/C 比較：

| 組別 | Probability 來源（實驗） | 用途 |
|---|---|---|
| A | Deterministic model only | 基準 |
| B | Deterministic + LLM structured signals（只作特徵／adjustment，不直接投票） | 測試 signal 是否有增量 |
| C | Deterministic + LLM probability voting（LLM 輸出經 payoff 轉成 return distribution） | 測試 probability 是否有增量 |

實驗規則：

- A 是 production 現狀；B／C 只在 shadow experiment 運行，未通過前 production 不切換。
- 同一批 matches、同一 `decision_at`、同一 evidence packet 版本、同一 evaluation method。
- A／B／C 都必須用相同的 payoff、EV、Kelly、Risk 與 Policy 規則，只改 probability 來源。
- 主要指標：out-of-sample log-loss／Brier（multi-outcome）、calibration、ROI、CLV、最大回撤；同時報不確定區間。
- 以 time block 切分訓練與測試；不可用同一批資料調參再評估。
- 只有在 C 或 B 對 A 顯示可重現的 incremental value，且通過預先登記的門檻後，才可給 LLM 非零權重。
- 30 個 forecasts 只可作 monitoring；不可作為 A/B/C 的結論樣本。
- 若 B／C 未勝過 A，LLM 維持 shadow，production 不改。

## 10. Value 與 Risk

### 10.1 De-vig 與 market baseline

- HAD：使用 proportional de-vig，`p_implied_i = (1/odds_i) / sum(1/odds_j)`。這是第一版 adopted market benchmark。
- HDC／HIL：第一版不做 line-probability inference。payoff 可以按規則把 stake 拆成兩個 half-bets 作結算與回報計算，但 market probability inference 不可由一個 split-line quote 發明兩條 component-line 價格，也不可把兩個半注各自 de-vig。
- HDC／HIL 的 EV 直接用 model score distribution 加實際 quoted price，不需要 de-vig market probability。
- 在可靠 line-probability inference 方法通過 real-quote 驗證前，HDC／HIL market baseline 一律標為 `unavailable`；不可用自製 de-vig 分佈假裝有完整 settlement probability，也不可填入假 baseline。
- HDC／HIL baseline 未可用不阻塞 EPL+HAD MVP；G1 只用 HAD proportional de-vig。
- De-vig probability 只作 market benchmark 與 EV 比較，不可當成 production probability。
- 不使用跨線比較；HDC 的 `0.5` 線不可與 `0/0.5` 線直接相減。
- 只在同一 line、同一市場、同一結算規則下比較；split line 的 payoff 拆注不等於市場概率可拆。

### 10.2 EV 與 Kelly

所有 EV／Kelly 計算都必須經 `packages/payoff` 產生 return distribution；不得在 `value` 內另寫一套二元公式。

```text
R(s) = payoff(score s, market_line, selection, odds_decimal)
EV   = sum_s P(s) * R(s)
edge = EV
f*   = argmax_{0 <= f <= 0.99} sum_s P(s) * log(1 + f * R(s))
stake = bankroll * f* * 0.25
```

- `edge` 以 per-unit-stake EV 表示；最低 edge：3%。
- `f*` 由數值求解；負 EV 時 `f* = 0`，不落注。
- HAD 可退化為 `f* = (p * (o - 1) - (1 - p)) / (o - 1)`，但這是特例，不是通用路徑。
- HDC／HIL 的 split line：兩個半注各自用 payoff 計 `R(s)`，再合成整個 selection 的 return distribution；Kelly 用合成後 distribution 求 `f*`，不可用單一 cover probability 取代。
- Fractional Kelly：0.25，且再受下列上限約束。
- 單注上限：bankroll 2%。
- 單日總曝險上限：bankroll 10%。
- 單場總曝險上限：bankroll 5%。
- 同時段相關注項（同一 match、同一 result dependency）合併計算曝險。
- 賠率 < 1.01、line suspended、pool 非 `SELLINGSTARTED`、odds stale → no-bet。

### 10.3 Risk Agent hard veto

Risk Agent 可以不落注，但不能估概率。Veto 條件：

- confirmed lineup 未出，且 predicted lineup 缺失。
- 關鍵球員傷停資訊衝突（FotMob vs PL/FPL）。
- HKJC odds snapshot 超過 10 分鐘。
- 目標 line 已 suspended。
- Data Steward 標記 `source_degraded` 且無 fallback。
- UCL 標記 `insufficient_coverage`，或 goals-based fallback 未通過獨立驗證。
- 單日／單場曝險超限。
- Agent API 成本超限（只停止 LLM shadow，不停止 deterministic pipeline）。

Shadow agent disagreement 不是 production veto 條件：因為 production 沒有 LLM probability weight，disagreement 只記錄與警示，不可用來否決 deterministic paper bet。若日後 LLM 取得權重，disagreement 門檻必須重新經實驗驗證，不可直接沿用舊數值。

Veto 時要記錄 `risk_reason`，UI 要顯示 no-bet 原因。

## 11. HKJC 賠率與結算

### 11.1 賠率 adapter

- 使用 HKJC GraphQL endpoint；免登入。
- 必須 replay 官網 whitelist query 字串；query 版本要記錄。
- 每個市場分開請求：`HAD`、`HDC`、`HIL`。
- 只接受：
  - pool `status == SELLINGSTARTED`
  - line `status == AVAILABLE`
- `currentOdds` 是字串，轉 decimal。
- `condition_raw` parser 接受 `^[+-]?\d+(\.\d+)?(/[+-]?\d+(\.\d+)?)?$`；不符合即拒絕該 line。
- 記錄 `snapshot_at`、`first_seen_at`、`source_update_at`、`is_main`、`condition_raw`。
- T-30m 落注 snapshot 與 T-5m closing snapshot 分開保存。
- 若 HKJC 該場沒有提供目標 market 或所有 line 已停售，該 market no-bet。

### 11.2 Settlement engine

目標市場以法定比賽時間結算：90 分鐘＋傷停補時，不包括加時、十二碼、重賽。

`settlement` 用實際賽果與 HKJC 規則計算「這張 bet 的實際 payout」；賽前的 `payoff` 用 score distribution、line 與 selection 計算 return distribution。兩者共用同一套 line parser 與結算類別，但 `settlement` 不推測未來，`payoff` 不接觸實際賽果。

**HAD**

- 比較 `home_goals_90`、`away_goals_90`。
- `H` / `D` / `A` 三選一。

**HDC**

- `condition` 套用於主隊。
- `+` = 主隊受讓；`-` = 主隊讓球。
- 單線：
  - `adjusted = home_goals_90 - away_goals_90 + handicap`
  - `> 0`：主隊 cover 贏
  - `= 0`：push，退款
  - `< 0`：主隊 cover 輸
- Split line (`L1/L2`)：
  - stake 分半。
  - 每半注獨立結算。
  - 彙總成 `won`、`lost`、`half_won_half_push`、`half_lost_half_push`、`push`、`void`。
- 不可用連續讓球公式近似 split line。

**HIL**

- `total_goals = home_goals_90 + away_goals_90`。
- 單線：
  - `total_goals > line`：大於 line 的一方贏。
  - `total_goals = line`：push，退款。
  - `total_goals < line`：小於 line 的一方贏。
- Split line (`L1/L2`)：stake 分半，各自用上述規則結算。
- 大／細方向由 `side` 決定：`H` = 大，`L` = 細。

**Rounding**

- 每張 paper bet 的最終 payout round 到最接近 HK$0.10。
- 不先對 odds 取整。
- 10-cent tie 規則寫成常數；預設 round half up，並在測試中固定。

**Void / odds correction**

- 取消、腰斬、賠率明顯錯誤：以 HKJC `payoutRefundPools`／`refundPools` 為準。
- 不可自行判定 void。
- 若 HKJC 更正賠率，按 HKJC 正確賠率結算；paper ledger 保留原本 snapshot 作審計。

### 11.3 結算來源優先順序

```text
1. HKJC matchResults + payoutConfirmed=true
2. HKJC matchResults + payoutConfirmed=false → provisional
3. 外部 90 分鐘賽果 + 自家 settlement engine → provisional
4. 無法確認 → pending，不計 ROI
```

`homeResult`／`awayResult` 在 UCL 加時賽是 90 分鐘還是最終比數，實作前必須用一場已知加時賽驗證；未驗證前不得用該欄位直接結算 UCL。

## 12. Paper Ledger

- 初始 bankroll：HK$10,000。
- `bankroll_balance` = 初始 bankroll 加 settled bets 的已實現損益；pending bets 與 reserved stake 不計入。
- Bankroll 以 `cash_available = bankroll_balance - reserved_stake` 管理；`reserved_stake` 來自 active `bankroll_reservations`。
- 每張 official bet 必須有 `bet_intent_key` UNIQUE，並在同一 transaction 完成 check、reserve、write。
- 費用模型：`fee_rate` 預設 0；若實際 HKJC 帳戶有佣金／回扣／手續費，於設定中調整，ROI 一律用扣除費用後金額計算。
- 每注記錄：market、line、selection、odds、stake、snapshot、`bet_intent_key`、deterministic model version、payoff version、return distribution 摘要、risk decision。Shadow agent 輸出另存於 `agent_forecasts`，不可寫成影響該注的 production weight。
- 結算狀態：`pending`、`won`、`lost`、`half_won_half_push`、`half_lost_half_push`、`push`、`void`。
- 指標：
  - ROI
  - CLV
  - Brier score（HAD 用三分類；HDC／HIL 用多結算類別）
  - Log-loss（同上）
  - Calibration curve（按 outcome class）
  - Max drawdown
  - 注數、勝率、平均 edge
- CLV：`bet_odds / closing_odds - 1`，只限同一 market、同一 line、同一 direction／selection、同一 settlement 規則。
- CLV closing reference：T-5m 最後可用 snapshot；若 closing 缺失、line 已改變、selection 方向不同，或 settlement 規則不同，CLV = `null`，不可填 0。
- 分開報告 decision-time market probability 與 closing market probability 的比較；不可把兩者混成單一「market baseline」。
- Prospective paper-run report 與 retrospective backtest report 分開輸出；不可混合樣本或指標，也不可把 retrospective 結果標成 prospective evidence。
- 保存所有 eligible matches 的 predictions 與 shadow scores，不只保存有落注的 matches；這樣才能做完整 calibration 與 selection bias 檢查。
- 所有指標要報不確定區間；同一 match 的多個 market／注項、以及同一 time block 的注項，以 cluster 方式處理相關性，不可當獨立樣本。
- 每次改動 strategy、prompt、weights、thresholds 或 payoff 規則都要版本化；新版本開始新的 evaluation period，不可與舊版本混合計算。
- 所有指標按 market、league、model version、line 分組。
- 每週產生 calibration report；每月檢討 deterministic model drift 與 shadow agent 表現。

## 13. UI

Pages：

1. `/matches`：未來賽程、資料完整度、是否有 paper bet。
2. `/matches/[id]`：deterministic probability 與 return distribution、HKJC odds、shadow agent signals、evidence、disagreement、risk reason、`decision_at`。
3. `/ledger`：paper bets、結算、CLV、ROI、drawdown、不確定區間。
4. `/models`：Brier、log-loss、calibration curve、champion/challenger、multi-outcome 分佈。
5. `/agents`：shadow agent 的表現、Brier、abstain rate、最近錯誤；明確標示 production weight = 0。
6. `/data-health`：adapter canary、freshness、coverage gaps、source failures、`verified`／`conditional`／`blocked` 狀態。

UI 原則：

- 每個數字都要有 source 與 timestamp，並顯示 `decision_at`。
- No-bet 必須顯示原因，不可只顯示空白。
- 區分 `confirmed` / `predicted` / `inferred` lineup。
- 區分 `provisional` / `final` settlement。
- 明確標示 LLM 輸出是 shadow，不是 production probability。
- 明確標示 source 狀態與 UCL `reduced_coverage`／`insufficient_coverage`。

## 14. Ops 與部署

- Docker Compose：`postgres`、`redis`、`api`、`worker`、`scheduler`、`web`、`cloudflared`。
- 部署在現有主機；不新增付費 infra。
- Secrets 只放 `.env`；不可 commit。
- Postgres 每日 backup；保留 14 日。
- Health endpoints：`/healthz`、`/readyz`。
- Adapter canary 每日跑一次；失敗 alert。
- Scheduler timezone：`Asia/Hong_Kong`；所有 DB 時間存 UTC。
- Log 結構化 JSON；每次 run 有 `run_id`、`match_id`、`trigger`。
- Rate limit：
  - football-data.org：≤10 req/min。
  - HKJC：跟官網 60 秒賽前刷新節奏，不快過官網。
  - FotMob：single source-level rate limiter；所有 calls（retry、ops、upcoming matchDetails）共用同一個 limiter，最小間隔 10 分鐘。
  - RSS：15 分鐘。
  - Open-Meteo：批次座標，每日一次。

## 15. Security / Legal / Compliance

- 不登入 HKJC、不自動落注、不處理真錢。
- 不轉售、不再散布 FotMob／HKJC／Understat 內容。
- 每個 adapter 有 `tos_risk` flag：`low`、`medium`、`high`。
- FotMob 標記 `high`；若收到 takedown 或持續 403，立即停用並降級。
- 不收集個人資料；只處理公開足球資料。
- 不在 log 印出 API keys、cookies、完整第三方 payload。
- LLM prompt 不包含 secrets；只包含比賽相關公開資料。

## 16. Testing

### 16.1 Unit / contract

- 每個 adapter 用 captured fixture 測 schema。
- HKJC GraphQL：query replay、whitelist error、pool/line status、odds string parsing。
- FotMob：predicted/standard lineup、unavailable、UCL coverage。
- Understat：5 聯賽、UCL 404、PPDA 欄位。
- football-data.org：fixtures/results/standings。

### 16.2 Payoff property tests

- 每個 market／line／selection 的 `R(s)` 只可落在 `{o-1, (o-1)/2, 0, -0.5, -1}`。
- 所有合法 score（0–10 球）都有對應 `R(s)`，沒有未覆蓋的 score。
- Score distribution probability mass sum to 1；`P(s) < 0` 或 `P(s) > 1` 即 fail。
- HAD 的 payoff 退化結果必須等於 `p*(o-1)-(1-p)` closed form。
- HDC／HIL 單線：win／push／lose 的 `R(s)` 與 settlement 規則一致。
- HDC／HIL split line：per-unit return 等於兩個半注 return 的平均。
- `EV = sum P(s) R(s)`；當 market 被公平定價時 EV 接近 0。
- Kelly 數值解：負 EV → `f*=0`；`R(s)=-1` 時 `f<1`，不可出現 `log(0)` 或 NaN；`f*` 對 odds 與 probability 單調。
- 只用 binary probability 的呼叫路徑必須 fail fast，不可靜默當成 HAD。
- Distribution contract：不可能 outcome 必須 exactly 0；不可用 `0.01` floor。
- Distribution contract：每個 distribution 的 total 必須在 `1e-6` 容差內為 1；超出即 fail。
- Distribution contract：不可有任何 `[0.01, 0.99]` 全域 clipping；stored forecast 的 0 必須保留。
- 121-cell score distribution：0–10 球共 121 cells 必須完整；tail mass 必須依 §8.2 擴展或記錄 `truncation_mass`／`tail_handling`，不可靜默丟棄。
- Settlement categories 可為 0（例如不可能 push）時，schema 必須接受 exactly 0，且 sum 仍為 1。

### 16.3 Settlement property tests

- HAD 主／和／客。
- HDC 單線贏／輸／push。
- HDC split line：win/win、half win/half push、half lose/half push、lose/lose。
- HIL 單線 push、split line 半贏半退。
- Void / refund。
- 10-cent rounding。
- UCL 90 分鐘 vs 加時：必須以 90 分鐘結算。
- Settlement 與 `payoff` 對同一 line 的 split-line parsing 必須一致。

### 16.4 Model tests

- Probability sum to 1。
- Score matrix 與 market probability／return distribution 一致。
- Decision-time leakage：prospective 用 `first_seen_at > decision_at` 的資料不得進入 features；`event_time < decision_at` 但 `first_seen_at > decision_at` 亦不得進入。
- Retrospective availability：只可用 `available_at <= decision_at`；`availability_basis=observed_snapshot` 或 `provider_point_in_time` 可作 primary；`availability_assumed` 只可作 sensitivity；`unavailable` 必須排除。
- 不可把今天的 `first_seen_at` 回填成歷史 `available_at`。
- Prospective paper-run report 與 retrospective backtest report 必須分開；混合即 fail。
- 歷史新聞 replay：只能用當時保存的 raw payload；re-fetch 後的內容不得補入 backtest packet。
- Walk-forward backtest，time-block 訓練／測試分離。
- Calibration report：小樣本用 raw／sigmoid；isotonic 只在驗證有改善時使用。
- 校準後跨 market 一致性檢查。
- Multi-outcome scoring：HAD 三分類；HDC／HIL 多結算類別；不可退化為二元。
- Market baseline comparison：decision-time 與 closing 分開報告。

### 16.5 Agent tests

- JSON schema validation；`mode=shadow` 必須存在。
- Evidence refs 必須存在，且符合該 run 的 availability gate（prospective 用 `first_seen_at`，retrospective 用 `available_at`）。
- Evidence validator 必須區分 factual numbers 與新 forecast probabilities：新 forecast probabilities 不可因 packet 未提供而被判 invalid。
- 不可回傳未提供的 factual numbers。
- HDC／HIL 只回傳 binary probability → schema invalid、不可用於 EV。
- Abstain path。
- Timeout / invalid JSON / API error。
- Prompt injection 防護：news 文字不可改變 system rules。
- Shadow isolation：shadow 輸出不可改 production probability、stake、selection 或 Risk veto。
- A/B/C shadow comparison：同一 matches／decision_at／evaluation method，B／C 未勝過 A 時權重維持 0。

### 16.6 End-to-end

- 用 30 場歷史賽事重跑 T-24h→T-75m→T-30m→settle；明確標記為 engineering／settlement 驗證，不作 predictive evidence。
- 檢查 paper bet、settlement、payoff、CLV、Brier 一致。
- 檢查所有 eligible matches 的 predictions 都有保存，不只 bet matches。
- 用一場 UCL 加時賽驗證 HKJC result semantics。
- 用一場 HDC split line 驗證半注結算與 payoff return distribution。

## 17. 實作順序（Full target，分 vertical slices）

1. **Spec v2（G0）**
   - 完成本文件修訂，鎖定 payoff contract、decision-time gate、source feasibility gate。
2. **Payoff engine + property tests（G0）**
   - `packages/payoff`：pure functions、return distribution、split line、數值 Kelly。
   - 先寫 property tests，再接 value／backtest。
3. **Data / ledger with temporal fields（G1）**
   - `first_seen_at`、`available_at`、`availability_basis`、`evidence_grade`、`decision_at`、raw payload replay。
   - Source feasibility gate、HKJC adapter、settlement engine。
   - 未通過 gate 的 source 只能標 `conditional`／`blocked`，不可假設可用。
4. **EPL + HAD deterministic baseline + walk-forward validation（G1）**
   - 用 EPL + HAD 作第一個 validated decision slice。
   - 必須通過 decision-time leakage、calibration、market baseline 測試。
5. **LLM shadow A/B/C（G2）**
   - 只產生 shadow forecasts／signals；production weight 維持 0。
   - 完成 A／B／C 比較後才檢討是否給權重。
6. **Ensemble（只在 incremental value 被證明後，G3）**
   - 只有在 B 或 C 對 A 顯示可重現 incremental value 後，才實作非零 production 權重。
   - 未證明前，ensemble 只作實驗工具。
7. **HDC / HIL expansion（G4）**
   - 在 payoff engine 與 EPL + HAD baseline 通過後，才擴展到 HDC／HIL。
   - 先 5 聯賽，再 UCL（按 `reduced_coverage`／`insufficient_coverage` 分級）。
8. **UI / feedback**
   - dashboard、calibration、shadow 表現、data health、source 狀態。

Full target 不變：5 大聯賽＋UCL 的 HAD／HDC／HIL。但 EPL + HAD 是第一個 validated slice；未通過前不擴展。

每個 slice 都必須有測試與可運行 demo；不可等全部寫完才第一次跑。

## 18. Acceptance Criteria

### 18.1 Phase gates

G1 不被 G2／G3／G4 阻塞。G1 只需 EPL+HAD 的 deterministic pipeline、ledger 與 source gate；LLM、HDC／HIL、UCL 可以在 G1 之後才做。

**G0：開始開發**

- 鎖定 payoff／distribution contract、market semantics、temporal fields。
- 完成 source verification plan：source 清單、allowed usage 檢查方法、real-fixture 驗證方法。
- 準備 HAD settlement 與 split-line payoff 的 fixtures。
- 不要求任何外部 API 已可用即可開始。

**G1：EPL+HAD paper MVP**

- EPL+HAD 所需 core sources 有明確狀態與驗證記錄；未通過 gate 的 source 不得成為依賴。
- HAD payoff／settlement property tests 通過：win／draw／loss、void、10-cent rounding。
- Decision-time gate 通過：`first_seen_at <= decision_at`。
- Ledger dedupe 通過：`bet_intent_key` unique constraint。
- Bankroll reservation 通過：`cash_available`、`reserved_stake`、check／reserve／write 同一 transaction；並行決策不可超額。
- 保存所有 eligible EPL matches 的 predictions，不只 bet matches。
- 30 場 dry run 無 duplicate bet、無 negative bankroll；只作 engineering／settlement 驗證。
- 不需要 LLM shadow，也不需要 HDC／HIL／UCL。

**G2：LLM shadow**

- Evidence packet 以 `decision_at` 凍結，只含當時可見資料。
- LLM schema 符合 §8.2 distribution contract。
- Evidence validator 區分 factual numbers 與新 forecast probabilities。
- Shadow isolation tests 通過：不可改 production probability、stake、selection、bankroll。
- 成本控制與 source-level rate limiter 有測試。
- A/B/C 實驗基建完成，但 production weight 仍為 0。

**G3：LLM production promotion**

- 預先登記的 A/B/C 實驗完成。
- Out-of-sample time-block 結果顯示可重現 incremental value，並通過不確定區間與預先登記門檻。
- 只有 G3 通過才可給 LLM 非零 production weight；未通過則維持 G2 shadow。

**G4：HDC／HIL／UCL**

- Split-line payoff／settlement、half win／half push、half lose／half push、void／refund 測試通過。
- 10-cent rounding 與 HKJC refund semantics 驗證通過。
- UCL coverage 分級、fallback、90 分鐘結算 semantics 驗證通過。
- HDC／HIL market baseline 在 line-probability inference 未驗證前維持 `unavailable`，不可用自製分佈假裝 baseline。
- UCL 加時 result semantics 已驗證。

### 18.2 Paper run 檢討門檻（500 bets 是 checkpoint）

500+ settled paper bets 只是 **review checkpoint**，不是穩定盈利的證明。達到 checkpoint 只代表可以開始正式檢討；不得因注數達標就宣稱策略有效。

檢討時要同時滿足：

- 500+ settled paper bets，且保存所有 eligible matches 的 predictions。
- HAD：Brier／log-loss 優於 de-vigged market baseline，並附不確定區間。HDC／HIL：market baseline 在 line-probability inference 未驗證前為 `unavailable`，只報告 model-implied calibration 與實際 settlement，不製造假的市場比較。
- CLV > 0，且只計同一 line／direction／settlement；missing closing 或 changed line 以 `null` 處理，不計入 0。
- 扣佣金後 ROI > 0，並附按 match／time-block cluster 的不確定區間。
- 最大回撤 < 15%。
- Calibration 可接受，且校準後跨 market 一致。
- 沒有任何版本混合：strategy、prompt、weights、thresholds、payoff 版本變更即開新 evaluation period。
- Decision-time market probability 與 closing market probability 分開比較，且有報告。

未達標：繼續 paper run，不轉真錢。即使全部達標，本系統仍維持 paper-only，不產生真錢下注指令。

## 19. 風險與緩解

| 風險 | 影響 | 緩解 |
|---|---|---|
| FotMob robots／takedown | lineup 中斷 | 標 `conditional`、adapter 抽象、低頻、快取、PL/FPL fallback、canary |
| HKJC GraphQL whitelist 變更 | 賠率中斷 | 保存 query version、canary、失敗即 no-bet |
| UCL 無 Understat xG | 模型覆蓋不足 | 分 `reduced_coverage`／`insufficient_coverage`；goals-based fallback 需獨立驗證 |
| 免費多莊家賠率不穩 | 市場比較不足 | HKJC 為主；The Odds API optional |
| LLM 過度自信／幻覺 | 錯誤概率 | shadow isolation、evidence refs、strict schema、abstain；不進 production |
| Agent API 成本失控 | 費用 | 只在 T-30m 跑、5 calls/match、daily/monthly cap；超限只停 shadow |
| Payoff 公式錯（push／split line） | EV／Kelly 錯 | payoff property tests、HAD 特例測試、binary fail-fast |
| Look-ahead leakage | backtest 虛高 | prospective `first_seen_at <= decision_at`、retrospective `available_at <= decision_at`、raw payload replay、leakage tests |
| Split-line de-vig 造假 | EV／baseline 錯 | HDC／HIL baseline 在推論方法驗證前標 `unavailable`；只用 model distribution 加 quoted price |
| 並行 decisions 重複用款 | bankroll 超支 | `bet_intent_key` unique、bankroll reservation transaction、`cash_available` |
| Retrospective availability 回填 | backtest 虛高 | `available_at`、`availability_basis`、evidence grade；prospective／retrospective 報告分開 |
| Settlement 規則誤解 | ROI 錯誤 | property tests、HKJC payoutConfirmed、UCL 驗證 |
| Model 無 edge | 長期虧損 | paper-only、market baseline、500 注只作 review checkpoint |
| Source schema 漂移 | pipeline 失效 | contract tests、canary、raw payload replay |

## 20. Verification Gates（按 phase）

- **G0**：start development
- **G1**：EPL+HAD paper MVP
- **G2**：LLM shadow
- **G3**：LLM production promotion
- **G4**：HDC／HIL／UCL

1. [G4] 抓一場已知 UCL 加時賽，對 `matchResults` 的 `homeResult`／`awayResult` 與 `payoutConfirmed`，確認是否 90 分鐘比數。
2. [G4] 用一場 HDC split line 的歷史紀錄，驗證 settlement engine 的 half win/half push。
3. [G4] 用一場 HIL split line，驗證 over/under 半贏半退。
4. [G4] 確認 HKJC `poolInfo.payoutRefundPools`／`refundPools` 的實際 JSON shape。
5. [G4] 確認 FotMob UCL matchDetails 是否有 xG 與可靠 lineup fallback；沒有就按 §4.5 分級，不可預設 reduced coverage 可用。
6. [G0] 確認 The Odds API free tier 是否真的包含 soccer spreads/totals；不確定就不依賴。
7. [G0] 確認 API-Football free 當前 season coverage；不通過就不使用。
8. [G2] 確認 agent API 成本 cap 與 DeepSeek Flash 的實際 token 價格；超限只停 shadow。
9. [G0] 對每個 core source 跑 §4.4 source feasibility gate，記錄 `verified`／`conditional`／`blocked`、verification date、schema／field scope 與 test evidence。
10. [G4] 用 HDC split line 與 HIL push 案例跑 payoff engine property tests，確認 `R(s)`、EV 與數值 Kelly 一致。
11. [G1] 用一場有 late lineup change 的歷史賽事驗證 T-75m → T-30m recheck，以及 `first_seen_at <= decision_at` gate。
12. [G3] 用 time-block 切分跑 calibration 與 A/B/C shadow 比較，確認 30 個 forecast 只作 monitoring，且 production 只在 G3 通過後才切換。
13. [G0] 驗證 distribution contract：121-cell score distribution、不可能 outcome exactly 0、總和容差、無 `[0.01, 0.99]` clipping、tail mass 有記錄。
14. [G1] 驗證 `bet_intent_key` unique constraint、`cash_available`／`reserved_stake`、check／reserve／write 同一 transaction，以及並行決策不超額。
15. [G1] 驗證 HAD payoff／settlement、void、10-cent rounding，以及 EPL+HAD 的 walk-forward baseline。
16. [G2] 驗證 evidence validator 區分 factual numbers 與新 forecast probabilities、shadow isolation、LLM schema 符合 distribution contract。

## 21. References

- HKJC football betting rules (Chinese PDFs): `https://www.hkjc.com/chinese/betting/template_betting_rule_files/pdf_ch/`
- HKJC football info / bet types: `https://is.hkjc.com/football/info/`
- HKJC GraphQL: `https://info.cld.hkjc.com/graphql/base/`
- football-data.org policies: `https://docs.football-data.org/general/v4/policies.html`
- football-data.org coverage: `https://www.football-data.org/coverage`
- Understat: `https://understat.com/`
- FotMob: `https://www.fotmob.com/`
- PL pulselive API: `https://footballapi.pulselive.com/football/competitions`
- FPL API: `https://fantasy.premierleague.com/api/bootstrap-static/`
- football-data.co.uk: `https://www.football-data.co.uk/`
- Open-Meteo: `https://open-meteo.com/`
- The Odds API: `https://the-odds-api.com/`
- BBC Sport RSS: `https://feeds.bbci.co.uk/sport/football/rss.xml`
- Guardian football RSS: `https://www.theguardian.com/football/rss`
- Google News RSS: `https://news.google.com/rss/search`
