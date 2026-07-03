# 清理未使用功能的 TODO 清單

> **背景**：目前 Bot 只用 **AI 分析師功能**（`/analyst run`、`/analyst match <match_id>`、賠率同步 Cron、每日分析 Cron）以及 `/match` 賽程同步指令。所有與**模擬下注系統**相關的代碼、資料模型、指令均無人使用，應清理以減少維護負擔與降低攻擊面。

---

## Phase 1 — 移除 Discord 斜線指令（Command Builders）

| # | 檔案 | 動作 | 影響 |
|---|------|------|------|
| 1.1 | `src/commands/login.ts` | 整檔刪除 | 移除 `/login` 指令 |
| 1.2 | `src/commands/bet.ts` | 整檔刪除 | 移除 `/bet place` / `/bet other` / `/bet history` / `/bet cancel` |
| 1.3 | `src/commands/check.ts` | 整檔刪除 | 移除 `/check list` / `/check win` / `/check loss` / `/check stop` |
| 1.4 | `src/commands/admin.ts` | 整檔刪除 | 移除 `/admin add` / `activate` / `deactivate` / `list` / `resetpw` / `delete` / `bet-place` / `bet-other` / `bet-cancel` / `check-*` |
| 1.5 | `src/commands/stat.ts` | 整檔刪除 | 移除 `/stat` 個人統計 |
| 1.6 | `src/commands/rank.ts` | 整檔刪除 | 移除 `/rank` 排行榜 |
| 1.7 | `src/commands/help.ts` | 整檔刪除 | 移除 `/help`（或保留但重寫為僅列出分析師指令） |
| 1.8 | `src/commands/fix.ts` | 整檔刪除 | 移除 `/fix profit` |

> **注意**：`src/commands/match.ts` 與 `src/commands/analyst.ts` **保留**。

---

## Phase 2 — 移除指令處理邏輯與事件分發

| # | 檔案 | 動作 | 細節 |
|---|------|------|------|
| 2.1 | `src/events/interactionCreate.ts` | 大幅精簡 | 移除 `case "login"`、`"admin"`、`"stat"`、`"bet"`、`"rank"`、`"help"`、`"check"`、`"fix"` 的 switch branch 與對應 handler function |
| 2.2 | `src/events/interactionCreate.ts` | 移除 Autocomplete | 移除 `commandName === "bet"` 與 `commandName === "admin"`（除 match_id 外）的 autocomplete 邏輯；保留 `commandName === "analyst"` 的 match_id autocomplete |
| 2.3 | `src/events/interactionCreate.ts` | 移除 auth guard 呼叫 | 移除所有 `requireAuth()` 與 `requireAdmin()` 的呼叫（這些 guards 只在 betting/admin 指令中使用） |
| 2.4 | `src/events/ready.ts` | 精簡 import | 移除對已刪除 command builders 的 import；`commands[]` 陣列只保留 `matchCommand`、`analystCommand` |

---

## Phase 3 — 移除服務層（Services）

| # | 檔案 | 動作 | 說明 |
|---|------|------|------|
| 3.1 | `src/services/auth.ts` | 整檔刪除 | `hashPassword`、`verifyPassword`、`requireAuth`、`requireAdmin` 全部移除 |
| 3.2 | `src/services/settlement.ts` | 整檔刪除 | `evaluateBet`、`settleMatchBets`、`updateMatchResultAndSettle`、`inferMainCondition` 全部移除 |
| 3.3 | `src/services/matchFetcher.ts` | 檢視後刪除或合併 | 該檔目前只有 type re-export（`HkjcOddsPool`），無實質邏輯；確認無引用後刪除 |

> **保留**：`src/services/hkjc.ts`、`src/services/dailyAnalysis.ts`、`src/services/deepseek.ts`

---

## Phase 4 — 精簡資料模型（Prisma Schema）

| # | 檔案 | 動作 | 細節 |
|---|------|------|------|
| 4.1 | `prisma/schema.prisma` | 移除 `User` model | 刪除整個 `model User`（含 `totalBets`、`totalWon`、`totalLost`、`totalProfit`、`role`、`status`、`passwordHash`、`username`、`discordId`、`lastLoginAt`、`bets` relation） |
| 4.2 | `prisma/schema.prisma` | 移除 `Bet` model | 刪除整個 `model Bet`（含 `userId`、`matchId`、`amount`、`odds`、`betType`、`prediction`、`status`、`refund`、relations） |
| 4.3 | `prisma/schema.prisma` | 精簡 `Match` model | 移除 Match 上不再需要的欄位或 relation（如 `bets Bet[]` relation 需移除） |
| 4.4 | — | 執行 `prisma migrate` / `prisma db push` | 將 schema 變更同步至 SQLite 資料庫 |
| 4.5 | — | 備份現有資料庫 | `.db` 檔若有歷史投注紀錄，執行前備份以防將來需要 |

---

## Phase 5 — 移除依賴套件

| # | 套件 | 動作 | 說明 |
|---|------|------|------|
| 5.1 | `bcrypt` | `npm uninstall bcrypt` | 密碼 hash 不再需要 |
| 5.2 | `@types/bcrypt` | `npm uninstall @types/bcrypt` | 對應 type definitions |

> **注意**：`node-cron`、`openai`、`discord.js`、`hkjc-api`、`prisma` 等 **保留**。

---

## Phase 6 — 環境變數清理

| # | 變數 | 動作 | 說明 |
|---|------|------|------|
| 6.1 | `.env` 或環境設定文件 | 移除無用變數 | 若存在任何僅供 betting 使用的環境變數（如 Admin 專用設定），清理註解或移除 |
| 6.2 | 文件更新 | 更新 README / API.md | 移除所有 betting 相關指令說明，文件只保留分析師功能與 `/match` |

---

## Phase 7 — 驗證與部署

| # | 動作 | 驗證標準 |
|---|------|----------|
| 7.1 | `npm run build` | `tsc` 零錯誤通過 |
| 7.2 | `npm start` 啟動測試 | Bot 正常登入、Cron 正常啟動、無 runtime error |
| 7.3 | Discord 指令同步 | Guild 中只剩 `/match` 與 `/analyst` 兩個指令（含子指令） |
| 7.4 | `/match` 測試 | 可正常抓取賽程與賠率 |
| 7.5 | `/analyst run` 測試 | 可正常觸發 AI 分析 |
| 7.6 | `/analyst match <id>` 測試 | Autocomplete 與單場分析正常 |
| 7.7 | Cron 觀察 | 賠率同步 Cron（每 5 分鐘）與每日分析 Cron（每日 08:00）正常運行 |

---

## 風險與注意事項

1. **Discord 指令快取**：即使刪除 code 並重新註冊，舊指令可能在 Discord client 快取中殘留數小時；屬正常現象。
2. **Prisma Migrate 破壞性**：移除 `User` / `Bet` model 後 `prisma migrate` 會嘗試 drop 對應 table；如想保留歷史資料，請先備份 `.db` 檔。
3. **`/help` 的處理**：若未來仍想保留一個簡易說明指令，可將 `help.ts` 保留並重寫內容（只介紹 `/match`、`/analyst`）。
4. **`interactionCreate.ts` 的 `handleFetch` 與 `handleAnalyst`**：這兩個 handler **保留**；刪除其餘所有 handler 時注意不要誤刪這兩個。

---

## 預估影響範圍總結

| 類別 | 刪除數量 | 保留數量 |
|------|---------|---------|
| 指令檔案 (`src/commands/*.ts`) | 8 個 | 2 個 (`match`, `analyst`) |
| 服務檔案 (`src/services/*.ts`) | 3 個 (`auth`, `settlement`, `matchFetcher`) | 3 個 (`hkjc`, `dailyAnalysis`, `deepseek`) |
| Prisma Model | 2 個 (`User`, `Bet`) | 1 個 (`Match`) |
| npm 套件 | 2 個 (`bcrypt`, `@types/bcrypt`) | 其餘保留 |
| 程式碼行數（估計） | ~1,800 行 | ~700 行 |
