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
cp .env.example .env                       # 預設指向本機 Postgres
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
cp deploy/env.example .env        # 編輯 POSTGRES_PASSWORD（有網域時再填 TUNNEL_TOKEN）
docker compose build              # 在目標主機上 build（image 要對應主機 CPU 架構）
docker compose up -d postgres
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.cli seed-leagues
docker compose run --rm app python -m app.cli backfill --from 2010    # 首次，一次性
docker compose up -d
```

- **對外存取**：見 [`deploy/cloudflare-tunnel.md`](deploy/cloudflare-tunnel.md)
  —— 不開 firewall port、不用固定 IP、附 email OTP 門禁（Cloudflare Tunnel + Zero Trust Access）。
- **單寫入者鐵律**：`app` 服務**不可** scale 到多個實例、uvicorn **不可**多 worker。
  APScheduler 在 process 內，否則 HKJC 會被重複輪詢、帳本會被重複寫入。
- **artifact 持久化**：`artifacts` named volume 掛在 `/app/artifacts`（`ML_ARTIFACT_DIR=artifacts/ml`）。
  沒有它，重部署後 `model_versions.artifact_path` 會指向不存在的檔案。
- **LightGBM**：image 已安裝 `libgomp1`（OpenMP runtime）。
- **上線檢查單**：見 [`deploy/launch-checklist.md`](deploy/launch-checklist.md)（主機前置 → 啟動 → 回填 → 手動跑出第一個 champion → Tunnel，逐步打勾）。

## 環境變數

以 [`deploy/env.example`](deploy/env.example)（部署）與 [`.env.example`](.env.example)（開發）為準。常用者：

| 變數 | 預設 | 說明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` | Postgres 連線（compose 會自動覆寫成服務名 `postgres`） |
| `ENABLE_SCHEDULER` | `true` | 是否在 app process 內啟動 APScheduler |
| `LEAGUE_WHITELIST` | EPL,LALIGA,SERIEA,BUNDESLIGA,LIGUE1,UCL | 要收錄的聯賽 |
| `SYNC_ODDS_INTERVAL` / `SYNC_SETTLE_INTERVAL` | 600 / 900 | 賠率同步／賽果結算間隔（秒） |
| `ML_ENABLE` | `false`（部署範本設 `true`） | 是否啟用 ML 預測／重訓排程 |
| `ML_ARTIFACT_DIR` | `artifacts/ml` | 模型 artifact 目錄（需持久化） |
| `ML_RETRAIN_INTERVAL` | 604800 | 重訓間隔（秒，預設每週） |
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
| 更新程式碼 | `git pull && docker compose build && docker compose up -d` |

重訓與預測預設由排程自動觸發（`ML_RETRAIN_INTERVAL`／每小時）；也可隨時手動觸發：`retrain` / `predict` / `ledger`（見上表）。

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

## 測試

```bash
uv run pytest            # 143 passed（2 個 live 測試預設 deselected）
uv run ruff check .      # lint（line-length 100）
```

## 已知限制與後續

- **ML（B）** 延後項：market Brier 基準線、CLV 只算 value bets、champion/challenger 同視窗重評、
  train/serve 先驗對齊（見 `docs/superpowers/specs/2026-10-12-football-agent-ml-engine-design.md`）。
- **Ledger（C）** follow-up：`status` DB 端 default、未知 `target` 防禦、cap rounding、
  API 篩選器測試覆蓋等（見 `docs/superpowers/specs/2026-10-12-paper-ledger-design.md`）。
- **D／E／F**：Next.js Web UI、編排、自我改進循環升級——尚未開始。

## 舊專案對照

舊版為 Node.js + TypeScript 的 Discord bot（Discord.js + Prisma/SQLite + DeepSeek API）。
重建後改為 Python + FastAPI + PostgreSQL，並把「AI 直接給建議」升級為
「可回測、可驗證、有 champion/challenger 閘門與模擬帳本績效」的系統。
