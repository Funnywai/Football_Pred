# WorldCup 2026 世盃分析 Discord Bot

自動從香港賽馬會 (HKJC) 同步世界盃賽程與賠率，搭配 DeepSeek AI 提供每日賽事分析。

## 功能

- **賽程查詢** — 查看即將到來的世界盃賽程與即時賠率（6 種玩法）
- **AI 分析** — DeepSeek 定時自動分析賽事，產出專業投注建議
- **自動同步** — 背景每 5 分鐘從 HKJC API 拉取最新賠率，無需手動操作

## 指令

| 指令 | 說明 |
|------|------|
| `/match` | 從 HKJC 同步賽程與賠率（含 🔄 重新整理按鈕） |
| `/analyst run` | 對明日比賽執行 DeepSeek AI 分析 |
| `/analyst match <match_id>` | 分析指定單場賽事 |

## 排程

| 任務 | 排程 | 說明 |
|------|------|------|
| 賠率同步 | 每 5 分鐘（`CRON_FETCH`） | 背景自動抓取未來 30 天賽事賠率並更新資料庫 |
| 每日分析 | 每日 18:00（`CRON_TIME`） | DeepSeek AI 分析明日賽事並發送至指定頻道 |

排程時間可透過 `.env` 中的 `CRON_FETCH` 與 `CRON_TIME` 環境變數自訂。

## 技術棧

| 項目 |  |
|------|--|
| Runtime | Node.js (TypeScript) |
| Bot Framework | Discord.js v14 |
| 資料庫 | SQLite (Prisma ORM) |
| 賠率來源 | HKJC API (`hkjc-api`) |
| AI 分析 | DeepSeek API (`deepseek-chat`) |
| 排程 | node-cron |

## HKJC API 參考

詳細 API 資料請見 [`API.md`](API.md)。

## 快速開始

```bash
# 安裝相依套件
npm install

# 初始化資料庫
npx prisma generate

# 編譯 TypeScript
npm run build

# 啟動
npm start
```

環境變數請參考 `.env`（需自行設定 `DISCORD_TOKEN`、`DEEPSEEK_API_KEY` 等）。
