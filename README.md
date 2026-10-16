# 世盃分析 Agent（Python / FastAPI 重建）

自動從香港賽馬會（HKJC）同步賽程與賠率、以 ML 模型預測 1X2 與讓球盤、並用**模擬帳本（paper ledger）**
驗證策略績效，同時提供唯讀 API 給未來的 Web UI。

> 本專案為舊 TypeScript Discord bot 的**重建**（舊程式已移除）。
> 進度：**A 資料層 ✅**、**B ML 預測引擎 ✅**、**C Paper Ledger ✅**；**D（Next.js Web UI）／E（編排）／F（自我改進循環）尚未開始**。
> 設計規格：`docs/superpowers/specs/`；實作計畫：`docs/superpowers/plans/`。

## 架構

```
HKJC GraphQL ─┐
football-data ┴─▶ A 資料層 ─▶ PostgreSQL ─┬─▶ B ML 引擎（LightGBM + isotonic 校準、
              （providers/services/db）   │      champion/challenger 閘門、model_versions）
                                           ├─▶ C Paper Ledger（fractional Kelly 下注、自動結算、
                                           │      predictions / ledger_bets / match_features）
                                           └─▶ FastAPI 唯讀 API（app/api）
APScheduler（app/scheduler.py）：賠率同步、賽果結算、ML 預測／重訓、ledger 更新
                              —— 全部跑在**同一個 app process** 內
```

| 子系統 | 位置 | 職責 |
|---|---|---|
| A 資料層 | `app/providers/`、`app/services/`、`app/db/` | HKJC / football-data 抓取、別名比對、賽果對帳（HKJC 優先）、排程與遷移 |
| B ML 引擎 | `app/ml/` | 防洩漏特徵、標籤／去水／Kelly／CLV、LightGBM 訓練與校準、模型註冊表、預測服務 |
| C Paper Ledger | `app/services/ledger.py` | 冠軍價值注自動入帳（HKD、最低一注 10）、自動結算（含讓球退本）、績效／資金曲線 |
| API | `app/api/` | 唯讀端點（見下） |
| 排程 | `app/scheduler.py` | 單一行程內的 APScheduler 任務（單寫入者） |

## 快速開始（本機開發）

```bash
uv sync                                    # 安裝依賴（Python 3.11+，使用 uv）
cp .env.example .env                       # 編輯：填 DATABASE_URL 與 POSTGRES_PASSWORD（compose 必填）
docker compose up -d postgres              # 只起資料庫（也可用你自己的 Postgres）
uv run alembic upgrade head                # 建立所有表（0001 → 0002 → 0003）
uv run python -m app.cli seed-leagues      # 種入白名單聯賽
uv run uvicorn app.api.main:create_app --factory --reload    # http://127.0.0.1:8000
uv run pytest                              # 測試（live 測試預設跳過；單獨跑：pytest -m live）
```

載入歷史資料（football-data.co.uk，2010 起）：

```bash
uv run python -m app.cli backfill --from 2010
```

> 注意：`app.api.main` 只提供 `create_app()` 工廠，**啟動必須加 `--factory`**。

## 部署（Docker Compose + Cloudflare Tunnel）

適用於「自有 Linux 主機」：單寫入者排程、artifact 本機磁碟、HKJC 出口 IP 乾淨。

```bash
cp deploy/env.example .env        # 編輯 POSTGRES_PASSWORD 與 DATABASE_URL（host 用 postgres；有網域時再填 TUNNEL_TOKEN）
GIT_SHA=$(git rev-parse --short HEAD) docker compose build   # 在目標主機上 build（image 要對應主機 CPU 架構；GIT_SHA 顯示於 /ops/status）
docker compose up -d postgres
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.cli seed-leagues
docker compose run --rm app python -m app.cli backfill --from 2010    # 首次，一次性
docker compose up -d
```

- **對外存取**：見 [`deploy/cloudflare-tunnel.md`](deploy/cloudflare-tunnel.md)
  —— 不開 firewall port、不用固定 IP、附 email OTP 門禁（Cloudflare Tunnel + Zero Trust Access）。
  公開入口是 dashboard（`web:3000`），API 只在 compose 網路內（`app:8000`）與主機本機可達，刻意不對外。
- **單寫入者鐵律**：`app` 服務**不可** scale 到多個實例、uvicorn **不可**多 worker。
  APScheduler 在 process 內，否則 HKJC 會被重複輪詢、帳本會被重複寫入。
- **artifact 持久化**：`artifacts` named volume 掛在 `/app/artifacts`（`ML_ARTIFACT_DIR=artifacts/ml`）。
  沒有它，重部署後 `model_versions.artifact_path` 會指向不存在的檔案。
- **GIT_SHA**：build 時帶 `GIT_SHA=$(git rev-parse --short HEAD)`（或把 `GIT_SHA` 寫進 `.env`，compose 會自動代入），
  否則 `/ops/status.git_sha` 會是 `unknown`。
- **LightGBM**：image 已安裝 `libgomp1`（OpenMP runtime）。
- **上線檢查單**：見 [`deploy/launch-checklist.md`](deploy/launch-checklist.md)（主機前置 → 啟動 → 回填 → 手動跑出第一個 champion → Tunnel，逐步打勾）。

## 環境變數

以 [`deploy/env.example`](deploy/env.example)（部署）與 [`.env.example`](.env.example)（開發）為準。常用者：

| 變數 | 預設 | 說明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` | Postgres 連線（compose 會自動覆寫成服務名 `postgres`） |
| `ENABLE_SCHEDULER` | `true` | 是否在 app process 內啟動 APScheduler |
| `LOG_LEVEL` | `INFO` | app 日誌等級（`DEBUG` 更吵）。`app` 現在會把 INFO 以上送進 `docker compose logs app` |
| `LEAGUE_WHITELIST` | EPL,LALIGA,SERIEA,BUNDESLIGA,LIGUE1,UCL | 要收錄的聯賽 |
| `SYNC_ODDS_INTERVAL` / `SYNC_SETTLE_INTERVAL` | 600 / 900 | 賠率同步／賽果結算間隔（秒） |
| `ML_ENABLE` | `false`（部署範本設 `true`） | 是否啟用 ML 預測／重訓排程 |
| `ML_ARTIFACT_DIR` | `artifacts/ml` | 模型 artifact 目錄（需持久化） |
| `ML_PRIOR_LEAD_HOURS` | 48 | 市場先驗對齊時點：訓練／評估／服務都用「開賽前 N 小時的最後一筆 HKJC 快照」（`0`＝舊行為：賽前最後一筆；CLV 恆用真實收盤） |
| `ML_RETRAIN_INTERVAL` | 604800 | 重訓間隔（秒，預設每週） |
| `ML_EXEC_OVERROUND` | `1.13` | 閘門經濟指標用的抽水：`roi` 用公平價（`1.0`，理論值、買不到），`roi_real` 用此值（實測 HKJC HAD 中位 `1.1327`）＝實際可下注價。`n_bets_real` 一併記錄：**`0` 注 ＝ 這個配置在真實價下一注都不會下**，不是「打平」 |
| `ML_GATE_MIN_REAL_BETS` | `50` | 閘門要求 `n_bets_real` 至少這麼多注，`roi_real` 才可信：真實價下 **0 注** 會讓 `roi_real = 0.0`，沒有這個下限時「一注都不下」會靠絕對條件通過。設 `0` 可關閉（測試用）|
| `LEDGER_ENABLE` | `true` | 是否啟用帳本排程 |
| `LEDGER_INITIAL_BANKROLL` | `1000` | 模擬本金（HKD） |
| `LEDGER_MIN_STAKE` | `10` | 最低一注（HKD＝HKJC bet unit；低於跳過，不上夾） |
| `POSTGRES_USER/PASSWORD/DB` | football | compose 的資料庫帳密 |
| `TUNNEL_TOKEN` | 空 | Cloudflare Tunnel token（見部署文件） |

## 維運 Runbook

| 情境 | 指令 |
|---|---|
| 套用資料庫遷移 | `docker compose run --rm app alembic upgrade head` |
| 手動觸發重訓（不必等 7 天） | `docker compose run --rm app python -m app.cli retrain` |
| 手動觸發預測 | `docker compose run --rm app python -m app.cli predict` |
| 手動觸發帳本（結算＋下注） | `docker compose run --rm app python -m app.cli ledger` |
| 看日誌 | `docker compose logs -f app cloudflared` |
| 健康檢查 | `curl -s localhost:8000/health`（主機直連，繞過 Access） |
| 備份資料庫 | `docker compose exec postgres pg_dump -U football football > backup.sql` |
| 還原資料庫 | `cat backup.sql \| docker compose exec -T postgres psql -U football football` |
| 改 tunnel token／網域 | 改 `.env` 後 `docker compose up -d cloudflared` |
| 更新程式碼 | `git pull && GIT_SHA=$(git rev-parse --short HEAD) docker compose build && docker compose up -d` |

重訓與預測預設由排程自動觸發（`ML_RETRAIN_INTERVAL`／每小時）；也可隨時手動觸發：`retrain` / `predict` / `ledger`（見上表）。

### CLI 子命令

```bash
docker compose run --rm app python -m app.cli <子命令> [參數]
```

| 子命令 | 作用 | 排程對應 |
|---|---|---|
| `backfill --from 2010` | 從 football-data.co.uk 灌歷史賽果／賠率 | 無（一次性） |
| `seed-leagues` | 種入 `LEAGUE_WHITELIST` 聯賽，並回填 `hkjc_tourn_id`（只補 NULL） | 無（一次性） |
| `retrain` | 立刻訓練 challenger，過閘即升 champion | `ML_RETRAIN_INTERVAL`（7 天） |
| `predict` | 立刻跑一次冠軍預測（寫 `predictions` / `match_features`） | 每小時 |
| `ledger` | 立刻結算＋下注 | 每小時 |

- 建表／遷移**不是** CLI：用 `docker compose run --rm app alembic upgrade head`
- 手動觸發**用 `run` 不要用 `exec`**：`run` 開新容器一定會讀到最新 `.env`；`exec` 沿用舊容器的環境變數
- 避開整點（排程每小時跑 `predict` / `ledger`），避免兩個 process 同時處理同一批資料

### 改 `.env` 之後，確認「真的生效」

```bash
sed -i 's/^LEDGER_INITIAL_BANKROLL=.*/LEDGER_INITIAL_BANKROLL=10000/' .env
docker compose up -d app                                            # 看到 Started / Recreated = 生效
docker compose exec app printenv LEDGER_INITIAL_BANKROLL             # 容器內的真相
```

> 不要用 `grep -q KEY .env || echo "KEY=…" >> .env`：鍵已存在時 `grep` 成功、`echo` 被跳過 → **靜默失敗**。
> `docker compose up -d` 只顯示 `Running` 就是「環境變數沒變」的訊號。

## API 端點（唯讀）

| 端點 | 說明 |
|---|---|
| `GET /health` | 存活檢查 |
| `GET /matches` | 賽程（`date_from`/`date_to`/`league`/`status` 篩選） |
| `GET /matches/{match_id}/odds` | 某場的賠率快照 |
| `GET /results` | 賽果 |
| `GET /models` | 模型版本與 metrics（champion/challenger 狀態） |
| `GET /predictions` | 預測（預設僅現任冠軍；`?champion_only=false` 看歷史） |
| `GET /bets` | 帳本注單（`status`/`match_id`/`target` 篩選） |
| `GET /bets/summary` | 本金、ROI、yield、已／未結算注碼等 |
| `GET /bets/equity-curve` | 資金曲線（初始 → 各次結算事件 → 現值） |
| `GET /ops/status` | 運維狀態：版本、git SHA、DB 連線、排程開關 |
| `GET /ops/jobs` | 排程任務清單與各任務最近一次執行紀錄 |
| `GET /ops/runs` | 最近 `ingestion_runs`（`limit` 預設 50、上限 200） |
| `GET /ops/logs` | 記憶體內日誌尾巴（`limit` 預設 100、上限 500；`level` 最低等級篩選） |
| `GET /ops/data` | 資料表筆數、資料新鮮度、模型 params、alembic revision |

## 測試

```bash
uv run pytest            # 224 passed（2 個 live 測試預設 deselected）
uv run ruff check .      # lint（line-length 100）
```

## 資料生命週期（HKJC 賠率快照）

HKJC 賠率每 `SYNC_ODDS_INTERVAL`（預設 600 秒）抓一次，但**不會無限累積**：

| 階段 | 觸發 | 動作 |
|---|---|---|
| 原始流 | 每次同步 | 每 `(match × odds_type × inplay)` 每 10 分鐘一筆 |
| **壓縮** | 每天 04:00 UTC（`prune_odds` 排程；只處理開踢超過 6 小時的比賽） | 每組只留 **3 個 anchor**：入場價、`kickoff − ML_PRIOR_LEAD_HOURS`（預設 48h）之前的**最後一筆**（＝ ML 市場先驗）、開踢前的**最後一筆**（＝ 收盤價，CLV 用） |
| **清除** | 每天 04:00 UTC（同上） | 只刪「**還沒被壓縮**的殘渣」（>3 筆的組）且 `captured_at` 早於 `ODDS_RETENTION_DAYS`（120 天）者 |

- **壓縮後的 3 個 anchors 永久保存**；`source='football_data'` 的歷史收盤價也永不被壓縮或清除
- ⚠️ `odds_snapshots.inplay` 是 **HKJC 的盤口屬性**（＝該盤口可即時投注；實測連未開賽的 `PREEVENT` 比賽也是 `true`），**不是**「此快照為賽中」的時序標記。
  先驗與 CLV 一律用**時間**判斷賽前（`captured_at < 開踢`，先驗再加 `− ML_PRIOR_LEAD_HOURS`），**不得**再用這個欄位過濾
  （2026-10-14 修正：原本誤用該旗標 → 所有「馬會有開即時投注」的熱門比賽永久取不到先驗、永不入帳）
- 所以**開踢 6 小時後就無法重建「賠率漂移路徑」**：未來若要做盤口移動特徵，需先調 `COMPACT_KEEP_PER_GROUP`（`app/services/odds.py`）
- **停機風險**：開踢前後 app 沒跑 → 該場收盤快照永久缺失 → CLV 永久缺失（HKJC 不提供賽後賠率）

## 怎麼看績效（帳本）

| 欄位 | 意義 | 陷阱 |
|---|---|---|
| `prob` | 模型機率 | — |
| `implied_prob` | HKJC 賠率**去水後**的市場機率 | 不是 `1/賠率`（含約 12% 水錢） |
| `edge` | `prob − implied_prob` | **對「公平價」**，天生比真實可下注邊際大 3～5 倍 |
| `market_odds` | 實際可下注賠率 | `NULL` ＝ 尚無市場先驗 → 不能下注。若馬會明明有開盤，先查 `odds_snapshots` 有沒有 `source='hkjc'`、`odds_type='HAD'`、且 `captured_at < 開踢 − ML_PRIOR_LEAD_HOURS` 的快照 |
| `recommended_fraction` | 半凱利建議比例（`kelly_fraction(prob, market_odds) × LEDGER_KELLY_MULTIPLIER`） | 用**真實賠率**算 → 扣水錢後的邊際才是真的 |
| `stake` | 注碼（**整元**，向下取整；低於 `LEDGER_MIN_STAKE` 不下注） | — |
| `payout` | 派彩（**四捨五入至 0.1 元**，依 HKJC 足球博彩規例 2.19(a)） | 退本金（push）不是彩金 → 原樣退回 |

- 驗收看 **CLV**（我們取的價 vs 收盤價，`/models` 的 `clv_*` metrics），**不要看 ROI**：統計上要分辨 1% 等級的邊際需要上萬注
- **帳本成交價（`ledger_bets.odds`）＝「下注當刻、開踢前的最新一筆 HKJC HAD 快照」**，注碼由 `kelly_fraction(prob, 該價)` 重算（2026-10-14 起；在此之前記的是「開踢前 48h 的先驗價」）
  → `ledger_bets.edge` 的語意因此改變：**新注單＝對「可下注賠率」的邊際**，舊注單＝對「先驗價」的邊際；沒有回填，跨期比較績效時必須看下注日期
- 找不到「開踢前的 HKJC 價」、或該價算出的 Kelly 已 ≤ 0 → **不下注**（價格跑到對面＝價值沒了）
- 讓球（HDC）每注最低投注總額為 **HK$200**（數碼平台 1X2 才 HK$10）——Phase 2b 上線讓球時需 per-target 最低注

## 已知限制與後續

- **ML（B）** 延後項：market Brier 基準線、CLV 只算 value bets、champion/challenger 同視窗重評、
  train/serve 先驗對齊（見 `docs/superpowers/specs/2026-10-12-football-agent-ml-engine-design.md`）。
- **升級注意（ML_PRIOR_LEAD_HOURS）**：既有部署的 champion 是以 lead-0 先驗訓練的；升級後請先執行
  `python -m app.cli retrain`（或等排程重訓完成）再信任 live 預測。
- **Ledger（C）** follow-up：`status` DB 端 default、未知 `target` 防禦、cap rounding、
  API 篩選器測試覆蓋等（見 `docs/superpowers/specs/2026-10-12-paper-ledger-design.md`）。
- **HKJC 賽果只回看 2 天**（`HKJC_LOOKBACK_DAYS=2`）：停機超過 2 天會永久漏掉那幾天的賽果
  （football-data.co.uk 的 CSV 有落後，補不到最近幾週）。
- **讓球最低注 HK$200**：目前 `LEDGER_MIN_STAKE` 是全域 10（對 1X2 正確）；Phase 2b 上線讓球前需 per-target。
- **D／E／F**：Next.js Web UI、編排、自我改進循環升級——尚未開始。

## 舊專案對照

舊版為 Node.js + TypeScript 的 Discord bot（Discord.js + Prisma/SQLite + DeepSeek API）。
重建後改為 Python + FastAPI + PostgreSQL，並把「AI 直接給建議」升級為
「可回測、可驗證、有 champion/challenger 閘門與模擬帳本績效」的系統。
