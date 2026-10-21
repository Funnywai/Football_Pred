# 上線檢查單（Launch Checklist）— 自架 Linux + Docker Compose（+ 可選 Cloudflare Tunnel）

逐項打勾即可上線。遇到問題對照 §9；判讀數據前先看 §10 的已知限制。

---

## 0. 主機前置

- [ ] Linux（x86_64 / arm64）、Docker Engine + Compose v2：`docker --version && docker compose version`
- [ ] 磁碟 ≥ 10 GB（Postgres 資料 + ML 模型 artifact + 映像層）
- [ ] 記憶體 ≥ 2 GB（LightGBM 訓練峰值數百 MB）
- [ ] **能連到 HKJC**：`curl -s -o /dev/null -w '%{http_code}\n' https://info.cld.hkjc.com/graphql/base/`
      → 只要**不是 timeout** 即可（GraphQL 端點回 4xx 是正常的）。若是 timeout/403，換出口 IP 或區域。
- [ ] （要對外才需要）一個網域，且 Nameserver 已交給 Cloudflare 管理

## 1. 取得程式碼與設定

```bash
git clone <repo> Football_Pred && cd Football_Pred     # main 已含 A 資料層 + B ML 引擎 + C 帳本 + 部署包
cp deploy/env.example .env
chmod 600 .env
# 至少修改：POSTGRES_PASSWORD 與 DATABASE_URL（host 必須是 compose 服務名 `postgres`，密碼與 POSTGRES_PASSWORD 一致）
# 依需求：LEDGER_INITIAL_BANKROLL（本金）、LEDGER_MIN_STAKE（最低注，預設 10 HKD）、ML_ENABLE=true（範本已設）
```

- [ ] `.env` 不在 git 裡（`.gitignore` 已排除），且權限 600

## 2. 建置與啟動

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose build   # ★ 一定要在「目標主機」上 build（映像要對應 CPU 架構；GIT_SHA 顯示於 /ops/status）
docker compose up -d postgres
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.cli seed-leagues
docker compose up -d
curl -s localhost:8000/health   # 期望 {"status":"ok"}
```

- [ ] 遷移三支都套用（0001 → 0002_ml_tables → 0003_ledger_bets），輸出可見 `Running upgrade`

## 3. 首次歷史回填（一次性，數分鐘）

```bash
docker compose run --rm app python -m app.cli backfill --from 2010
```

- [ ] 筆數合理（Big-5、2010 起 → 數萬場）
- [ ] 回填**不會**產生假注單（下注只認「現任冠軍的預測」+「開賽前的未來場次」）
- [ ] 抽查：`curl -s "localhost:8000/matches?limit=1"`、`curl -s "localhost:8000/results?limit=1"` 有資料

## 4. 立刻跑出第一個 champion（不必等 7 天）

> 排程的 `interval` 任務**首次執行要等一整個間隔**（重訓預設 7 天）。用 CLI 手動提前：

```bash
docker compose run --rm app python -m app.cli retrain
curl -s localhost:8000/models | python3 -m json.tool | head -40    # 應出現 status="champion"
```

- [ ] 有 champion（若沒有：`ML_MIN_TRAIN_ROWS` 可能太大、或回填筆數不足；看 `docker compose logs app | tail -30`）

## 5. 立即驗證整條迴路（預測 → 下注 → 帳本）

```bash
docker compose run --rm app python -m app.cli predict
docker compose run --rm app python -m app.cli ledger
curl -s localhost:8000/predictions | head -c 400
curl -s localhost:8000/bets/summary
```

- [ ] `/predictions` 出現冠軍模型的預測列（未來 48 小時內有賽事才會有）
- [ ] 有價值注時 `/bets/summary` 的 `n_open` > 0；沒有賽事時全 0 是**正常**的
- [ ] `ledger` 也會順手結算：已確認賽果且未結算的注會變成 won/lost/push

## 6. 排程自動運轉（部署後你應該看到的時序）

| 時間點 | 會發生 | 怎麼驗證 |
|---|---|---|
| +10 分鐘 | 首次賠率同步 | `docker compose logs app \| tail -50`；`/matches/{id}/odds` |
| +15 分鐘 | 首次賽果結算 | logs 內 `settle_results` |
| +1 小時 | 首次預測、首次帳本更新 | `/predictions`、`/bets` |
| +7 天 | 首次**自動**重訓（challenger 可能在閘門通過後接任） | `/models` 多一筆、status 變化 |

- [ ] `ENABLE_SCHEDULER=true`
- [ ] **`app` 只有一個 instance**：`docker compose ps`（多開會造成 HKJC 重複輪詢、帳本重複寫入）

## 7. 對外門面（有網域時）

照 [`deploy/cloudflare-tunnel.md`](cloudflare-tunnel.md)：

- [ ] Zero Trust → Tunnel 建立 → token 寫入 `.env`，並加 `COMPOSE_PROFILES=tunnel`
- [ ] `docker compose up -d`；`docker compose logs -f cloudflared` 見 "Registered tunnel connection"
- [ ] Public hostname：`fp.你的網域` → Service `HTTP` / `web:3000`（公開入口是 dashboard；API 不對外）
- [ ] Access 應用 + 政策：Action `Allow`、Include `Emails` = 你的 email
- [ ] 驗證：未登入 `curl -sI https://fp.你的網域/` 應為 302（被 Access 攔）；瀏覽器登入後見 dashboard
- [ ] （僅非 dashboard 的機器對機器呼叫需要）建 Access **Service Token**，呼叫端帶 `CF-Access-Client-Id/Secret`

## 8. 上線後維運（例行）

- [ ] 每日：`docker compose ps`、`curl -s localhost:8000/health`
- [ ] 每週：看 `/models`（champion 是否被更優 challenger 取代）、`/bets/summary`（ROI / yield / 未結算注碼）
- [ ] 每日備份：`docker compose exec postgres pg_dump -U football football > backup-$(date +%F).sql`
- [ ] 磁碟與日誌：compose 已設 log rotation（10MB × 3）；留意 `artifacts` volume 用量
- [ ] 更新程式：`git pull && GIT_SHA=$(git rev-parse --short HEAD) docker compose build && docker compose up -d`

## 9. 常見問題

| 症狀 | 處理 |
|---|---|
| compose 直接報 `required variable … is missing a value` | `.env` 缺 `POSTGRES_PASSWORD` 或 `DATABASE_URL`（兩者都是必填；`DATABASE_URL` 的 host 要用服務名 `postgres`） |
| app 起不來 / 一直 restart | `docker compose logs app`；多為 `.env` 的 DSN 帳密與 Postgres 不一致，或 Postgres 尚未 healthy |
| `/models` 一直空 | 回填筆數不足或 `ML_MIN_TRAIN_ROWS` 過大 → 手動 `retrain` 看 `ingestion_runs` 的 failed 訊息 |
| 完全沒有注單 | 正常條件未滿足：需「有 champion」+「未來 48h 有賽事」+「edge 超過 `ML_VALUE_EDGE_THRESHOLD`」；看 `/predictions` 的 `recommended_fraction` |
| HKJC 拉不到資料 | 主機出口被擋 → 換 IP/區域；不要調小 `HKJC_THROTTLE_SECONDS` |
| 重複輪詢 / 重複注單 | 你開了多個 app 實例 → 收回到單一 instance |
| 模型檔不見（artifact missing） | `artifacts` volume 被刪 → 重新 `retrain` |
| 網站 502/1033 | Tunnel 的 Service URL 不是 `web:3000`，或 web 不健康；dashboard 起得來但顯示 API 錯誤時改查 app |

## 10. 已知限制（判讀數據前務必知道）

- **ML（B）**：尚無 market Brier 基準線、CLV 以全部 outcome 計算（非僅 value bets）、champion 閘門目前比較「challenger 新分數 vs champion 舊分數」（非同視窗）、訓練用收盤價但上線用盤前快照（train/serve 先驗落差）。
- **Ledger（C）**：最低一注 HKD 10（不足直接跳過，不上夾）；單注上限為批次本金的 5%；讓球**整球盤平線**（push）退本、**四分之一線**不下注；本金由注單推導、永不儲存。
- **時序**：自動重訓每 7 天一次（可用 `retrain` 手動提前）；預測與帳本每小時一次。
- **單寫入者**：所有排程都在 app process 內——**永遠只跑一個 app 實例**。
