# AI 分析師效能優化建議書

> **分析對象**：`src/services/deepseek.ts`、`src/services/dailyAnalysis.ts`、`src/services/hkjc.ts`  
> **目標**：在維持或提升預測品質的前提下，降低 API 成本、縮短響應時間、提升輸出可用性。

## 實作狀態

| 階段 | 項目 | 狀態 | 實作日期 |
|------|------|------|----------|
| **S1** | 合併 API Call（移除 `fetchTeamResearch`） | ✅ 已完成 | 2026-07-04 |
| **S2** | 調降 Temperature 0.8→0.3 | ✅ 已完成 | 2026-07-04 |
| **S3** | 下調 max_tokens 8192→4096 | ✅ 已完成 | 2026-07-04 |
| **S4** | 統一 Batch/Single Prompt | ✅ 已完成 | 2026-07-04 |
| M1 | 結構化輸出（JSON） | ⏳ 待實作 | — |
| M2 | TeamProfile 快取表 | ⏳ 待實作 | — |
| M3 | Analysis 追蹤表 | ⏳ 待實作 | — |
| M4 | 價值過濾器 | ⏳ 待實作 | — |
| L1 | 外部數據源 | ⏳ 待實作 | — |
| L2 | 多模型 Ensemble | ⏳ 待實作 | — |
| L3 | 強化學習 Prompt 迭代 | ⏳ 待實作 | — |

### S1-S4 實作摘要

- **`deepseek.ts`**：移除 `fetchTeamResearch()` 函式；System prompt 新增球隊資訊整理區塊（FIFA 排名、戰績、關鍵球員等）；統一單場/多場 prompt 品質；`temperature: 0.3`、`max_tokens: 4096`。
- **`dailyAnalysis.ts`**：移除 `fetchTeamResearch` 引入與呼叫，`analyzeSingleMatch()` 和 `analyzeAndPost()` 簡化為直接使用 `buildHistoricalContext()`。

---

## 一、現行 workflow 盤點

### 1.1 排程觸發流程（Cron）

```
startDailyAnalysisCron() ─┬─► 抓取今日 HKJC 賽事 → 若無則抓明日
                          │
                          ├─► upsertMatchesToDb() — 寫入/更新 Match table
                          │
                          └─► analyzeAndPost() ─┬─► 對每場比賽依序：
                                                │    1. fetchTeamResearch()  ──► DeepSeek API #1（每場 1 call）
                                                │    2. generateMatchAnalysis() ──► DeepSeek API #2（每場 1 call）
                                                │    3. buildAnalysisEmbed() + channel.send()
                                                └─► 循環直到全部發完
```

### 1.2 手動觸發流程（`/analyst run`、`/analyst match`）

與 Cron 相同，只是由 Discord interaction 觸發。

### 1.3 現行 Prompt 結構

| 元件 | 用途 | 模型 | 參數 |
|------|------|------|------|
| `fetchTeamResearch()` | 查詢兩隊 FIFA 排名、近況、關鍵球員、歷史交鋒 | `deepseek-v4-flash` | `temperature: 0.3`, `max_tokens: 4096` |
| `generateMatchAnalysis()` | 生成完整分析報告（對戰分析、賠率解讀、投注建議、信心指數） | `deepseek-v4-flash` | `temperature: 0.8`, `max_tokens: 8192`, `reasoning_effort: "high"` |

---

## 二、現行架構的 8 個瓶頸

### 瓶頸 1：每場比賽 2 次 API Call，成本翻倍

- `fetchTeamResearch()` 為每場比賽獨立呼叫一次 DeepSeek。
- `generateMatchAnalysis()` 再為每場比賽獨立呼叫一次。
- **5 場比賽 = 10 次 API Call**，其中 5 次是「資料搜集」、5 次是「分析生成」。
- 兩次呼叫的內容高度重疊（都要求近期狀態、歷史對戰、關鍵球員）。

> **成本影響**：假設每場輸入 ~2k tokens、輸出 ~3k tokens，以 `deepseek-v4-flash` 計價，10 次呼叫的費用約為合併成 5 次的 **2 倍**。

---

### 瓶頸 2：`fetchTeamResearch()` 與主分析 Prompt 資訊重疊

`fetchTeamResearch()` 回傳的內容（FIFA 排名、近 5 場、關鍵球員、歷史交鋒）與 `generateMatchAnalysis()` 的 System Prompt 中要求的「對戰分析」幾乎完全一致。等於花了一次 API 錢請模型「搜集資料」，再花一次錢請同一模型「根據資料分析」。

> **優化方向**：將 team research 的資訊需求直接併入主分析 prompt，讓模型在一次呼叫中同時完成「資料回憶」與「分析推理」。DeepSeek 的 reasoning model 本身具備 retrieval 與 reasoning 能力，不需要人工拆分 pipeline。

---

### 瓶頸 3：Temperature 0.8 過高，不利於預測穩定性

- `generateMatchAnalysis()` 使用 `temperature: 0.8`，這對創意寫作是合理值，但對**博弈預測**過高。
- 高溫度容易導致：
  - 同一場比賽多次分析結果不一致（今天推主勝、明天推客勝）。
  - 過度「創意化」解讀賠率，偏離數據事實。
  - 信心指數隨機波動（同樣的盤口這次 3 星、下次 5 星）。

> **建議**：預測類任務使用 `temperature: 0.3 ~ 0.5`，保留少量變化但確保核心邏輯穩定。

---

### 瓶頸 4：無結構化輸出（Unstructured Output）

現行輸出是自由格式繁體中文長文，Embed 直接貼上。帶來以下問題：

1. **無法自動提取「最佳推薦」**：需要人工閱讀全文才能知道模型最看好哪個盤口。
2. **無法追蹤預測準確率**：無法與實際賽果比對來計算模型勝率。
3. **無法做 A/B testing**：不能比較 prompt 版本 A 與版本 B 的預測品質差異。
4. **Embed 排版受限**：長文容易被截斷（已經有 `> 3800` 截斷邏輯）。

> **建議**：在 prompt 中要求模型輸出 **JSON + Markdown 雙格式**，或至少在最後附上一段可被正規表示式提取的結構化區塊。

---

### 瓶頸 5：`max_tokens: 8192` 過於寬鬆

- 8192 tokens 約等於 6,000+ 中文字。
- 實際觀察：單場分析很少需要超過 2,000 中文字。
- 過高的 `max_tokens` 不會直接收費（按實際輸出計價），但會：
  - 佔用 KV Cache，可能影響推理速度。
  - 增加模型「胡亂填充」的傾向（為了寫滿而冗長）。

> **建議**：將 `max_tokens` 下調至 `2048 ~ 4096`，並在 prompt 中明確要求「簡潔、每節 2-3 句話」。

---

### 瓶頸 6：無快取機制，重複球隊天天查

- `fetchTeamResearch()` 沒有任何快取。如果「巴西 vs 阿根廷」今天分析過，明天又有一場「巴西 vs 德國」，模型會重新查一次巴西的資訊。
- 世界盃賽程中同一球隊可能 3-4 天內連續出賽，每次重複查詢浪費 tokens。

> **建議**：在 `Match` table 或新增 `TeamProfile` table 中快取 team research，設定 TTL（如 48 小時）。

---

### 瓶頸 7：本地歷史數據過於單薄

`buildHistoricalContext()` 只從本地 SQLite 撈取「已完賽的世界盃賽事」。問題：

1. **樣本量極小**：世界盃小組賽每隊只踢 3 場，進入淘汰賽才有更多樣本。
2. **無友誼賽/聯賽數據**：本地 DB 只存 HKJC 盤口賽事，不包含國家隊近期友誼賽或球員聯賽表現。
3. **H2H（歷史交鋒）數據可能為零**：很多隊伍在世界盃從未交手。

> **現實**：`fetchTeamResearch()` 已經彌補了這點（讓模型用內部知識補充），所以 `buildHistoricalContext()` 的價值很低。可以精簡或移除。

---

### 瓶頸 8：Batch 分析與 Single 分析品質不一致

- `isSingle` 判斷分支導致 **Batch（Cron）** 使用較簡短的 prompt：「請對每場比賽提供：1. 對戰分析 2. 賠率解讀 3. 投注建議 4. 信心指數」。
- **Single（`/analyst match`）** 使用詳細格式 prompt：明確分 4 大節、細分子項。
- 結果：Cron 產出的分析品質可能低於手動單場分析，使用者會覺得「自動分析不夠準」。

> **建議**：統一使用高品質 prompt，或讓 Batch 也要求模型為每場產出完整格式。

---

## 三、優化方案（分短期 / 中期 / 長期）

### 🔵 短期（可立即執行，零風險）

#### S1. 合併 `fetchTeamResearch()` 與 `generateMatchAnalysis()`

**動作**：刪除 `fetchTeamResearch()` 函式，將其 prompt 內容併入 `generateMatchAnalysis()` 的 system prompt。

**預期效果**：
- API Call 數量減半（5 場比賽從 10 次 → 5 次）。
- 總延遲降低（省去等待 team research 的時間）。
- 成本降低約 40-50%。

**實作方式**：
```
新 System Prompt 增加一段：
「請在分析前，基於你的知識庫簡要整理以下資訊：
1. 兩隊最新 FIFA 排名
2. 兩隊 2026 世界盃至今戰績與進球/失球數據
3. 兩隊過往歷史交鋒紀錄
4. 各隊 2-3 名關鍵球員及其當前狀態
5. 所在小組晉級形勢」
```

---

#### S2. 調降 Temperature

| 函數 | 現行 | 建議 | 理由 |
|------|------|------|------|
| `generateMatchAnalysis()` | `0.8` | `0.3` | 預測需穩定，降低隨機性 |
| `fetchTeamResearch()`（若保留） | `0.3` | `0.3` | 已合理，不需改 |

---

#### S3. 下調 `max_tokens`

| 函數 | 現行 | 建議 | 理由 |
|------|------|------|------|
| `generateMatchAnalysis()` | `8192` | `4096` | 單場分析 2000-3000 字已足夠 |
| `fetchTeamResearch()`（若保留） | `4096` | `2048` | 條列式簡報 800-1200 字足夠 |

---

#### S4. 統一 Batch / Single Prompt 品質

移除 `isSingle` 分支，全部使用同一個高品質 prompt。Batch 時在 user prompt 加註：「以下有 N 場比賽，請為每場產出完整分析」。

---

### 🟡 中期（需改動資料結構或程式邏輯）

#### M1. 引入結構化輸出（Structured Output）

**目標**：讓分析結果可被程式解析，用於自動統計與 A/B test。

**實作方案 A — JSON Mode**（最乾淨）：

在 `generateMatchAnalysis()` 的 prompt 最後加上：
```
請在最後輸出一段可被程式解析的 JSON，格式如下：
{
  "recommendedBet": {
    "market": "HAD|HDC|HHA|HIL|CHD|CHL",
    "selection": "主勝|客勝|大|細|...",
    "odds": 1.85,
    "confidence": 4,
    "rationale": "一句話摘要"
  },
  "alternateBet": { ... },
  "avoid": "應避免的選項"
}
```

並在程式端用正規表示式提取 JSON 區塊存入新 table `Analysis`。

**實作方案 B — 更激進：直接使用 Function Calling / Tool Use**：

定義一個 `submit_analysis` tool schema，讓模型以 tool call 形式回傳結構化數據。這比 JSON parsing 更可靠。

---

#### M2. 建立 TeamProfile 快取表

**Schema 建議**：
```prisma
model TeamProfile {
  id        String   @id @default(uuid())
  teamName  String   @unique
  data      Json     // 存放研究結果
  updatedAt DateTime @updatedAt
}
```

**邏輯**：
- 呼叫 DeepSeek 前先查 `TeamProfile`，若 `updatedAt` 在 48 小時內則直接使用。
- 避免同一球隊 3 天內被重複研究。

---

#### M3. 建立 `Analysis` 結果追蹤表

**Schema 建議**：
```prisma
model Analysis {
  id           String   @id @default(uuid())
  matchId      String
  triggerType  String   // "cron" | "manual"
  modelVersion String   // "deepseek-v4-flash-t0.3"
  promptHash   String   // sha256 of system prompt，用於 A/B test
  rawContent   String   // 完整分析文字
  recommendedMarket   String?
  recommendedSelection String?
  recommendedOdds     Float?
  confidence   Int?
  createdAt    DateTime @default(now())

  match Match @relation(fields: [matchId], references: [id])
}
```

**用途**：
- 賽後比對 `Analysis.confidence` 與實際賽果，計算模型勝率。
- 比較不同 `promptHash` 的準確率，迭代優化 prompt。
- 建立「分析師 leaderboard」：哪個模型版本 / prompt 版本最準。

---

#### M4. 加入「預測價值過濾器」（Value Filter）

**問題**：目前每場比賽都分析，但有些比賽的盤口極度傾斜（如強隊 1.05 賠率），分析價值很低。

**實作**：
```typescript
function hasAnalysisValue(match: Match): boolean {
  const oddsData = match.oddsData as Record<string, unknown> | null
  const had = oddsData?.["HAD"] as { combinations?: Array<{ str: string; odds: number }> } | undefined
  if (!had?.combinations) return true // 無法判斷，預設保留

  const odds = had.combinations.map(c => c.odds)
  const minOdds = Math.min(...odds)
  const maxOdds = Math.max(...odds)

  // 若最低賠率 < 1.15（極度熱門），或最高賠率 > 12（極度冷門），標記為低價值
  if (minOdds < 1.15 || maxOdds > 12.0) return false

  return true
}
```

在 `analyzeAndPost()` 中 skip 低價值比賽，或改發簡短提醒：「本場盤口極度傾斜，建議觀望」。

---

### 🟢 長期（需要額外資料源或模型調校）

#### L1. 引入外部數據源增強 Context

目前模型的「歷史數據」完全依賴自身知識庫（cutoff 可能為 2024 年中）。建議接入：

| 數據源 | 用途 | 成本 |
|--------|------|------|
| FIFA API / RSSSF | 最新 FIFA 排名、近期友誼賽結果 | 免費 |
| Transfermarkt API | 球員身價、傷病情報 | 免費（scraping 需注意 ToS） |
| Opta / StatsBomb | xG、射門數據、控球率 | 付費 |
| 自建 odds trend DB | 追蹤盤口變化（開盤 → 即時） | 已有 HKJC cron 可擴充 |

將這些數據以文字形式注入 prompt 的 `historicalContext`，讓模型基於**即時數據**而非記憶做判斷。

---

#### L2. 多模型 Ensemble（集成預測）

**概念**：同一場比賽同時送給 2-3 個模型分析（如 DeepSeek + GPT-4o + Claude），然後：

- 若 **3 模型一致看好同一方向** → 信心指數最高。
- 若 **2:1 分歧** → 標註「存在分歧，建議輕注或觀望」。
- 記錄各模型長期勝率，未來自動加權採信勝率高的模型。

**成本**：3 倍 API 費用，但可選擇性執行（只對焦點大戰啟用 ensemble）。

---

#### L3. 強化學習式 Prompt 迭代（RL for Prompting）

**概念**：
1. 每場分析存入 DB（含 `promptHash`）。
2. 賽後根據實際結果計算該分析的「回報」：推薦命中 = +1，未命中 = -1，推薦觀望 = 0。
3. 每月統計各 `promptHash` 的累積回報。
4. 自動採用累積回報最高的 prompt 版本，淘汰低回報版本。
5. 定期（如每週）讓 DeepSeek / GPT-4 根據勝率數據「自我反思」並產出 prompt 改良建議。

---

## 四、Prompt 改良建議（可直接複製使用）

### 4.1 新版 System Prompt（統一 Batch & Single）

```
你是一位專業的 2026 世界盃足球分析師，擅長結合盤口數據與球隊資訊進行博弈預測。

任務：對每場提供的比賽生成結構化分析報告。

報告格式（繁體中文，每節簡潔，總長不超過 2000 中文字）：

## [主隊] vs [客隊]

### 對戰背景
- FIFA 排名、本屆戰績、小組形勢
- 近 5 場表現簡述
- 歷史交鋒（若無則明確寫「無正式交鋒」）
- 各隊 2-3 名關鍵球員狀態

### 賠率解讀
- 標準盤（HAD）：主/和/客賠率與市場信號
- 讓球盤（HDC）：主力讓球條件與賠率
- 讓球主客和（HHA）：三選一盤口解讀（注意：+1 主勝 = 主隊實際贏或和即中）
- 入球大細（HIL）：大小球盤口
- 角球盤（CHD/CHL，如有）
- 盤口趨勢總結

### 投注建議
- 穩健推薦：風險最低的方向 + 賠率 + 一句理由
- 進取推薦（可選）：回報較高的方向
- 風險提示：應避免的選項

### 信心指數
★ 1-5 星，5 星 = 極高信心，1 星 = 純粹猜測。

---
結尾請輸出一段可被程式解析的 JSON：
{
  "recommended": {"market":"","selection":"","odds":0,"confidence":0,"rationale":""},
  "alternate": {"market":"","selection":"","odds":0},
  "avoid": ""
}
```

### 4.2 參數調整

```typescript
const response = await deepseek.chat.completions.create({
  model: "deepseek-v4-flash",      // 或考慮升級到 reasoning 系列
  messages: [
    { role: "system", content: systemPrompt },
    { role: "user", content: userPrompt },
  ],
  temperature: 0.3,                // 降低隨機性
  reasoning_effort: "high",      // 保留深度推理
  max_tokens: 4096,              // 單場 2000 字足夠
  response_format: { type: "json_object" }, // 若 API 支援 JSON mode
})
```

---

## 五、執行優先序建議

| 優先序 | 項目 | 預期效益 | 實作難度 | 狀態 |
|--------|------|---------|---------|------|
| **P0** | S1：合併 API Call（移除 `fetchTeamResearch`） | 成本 -50%、速度 +100% | 低 | ✅ |
| **P0** | S2：調降 Temperature 至 0.3 | 預測穩定性大幅提升 | 低 | ✅ |
| **P1** | S4：統一 Batch/Single Prompt | 品質一致 | 低 | ✅ |
| **P1** | M1：結構化輸出（JSON） | 可追蹤、可自動化 | 中 | ⏳ |
| **P1** | M4：價值過濾器 | 減少無意義分析 | 低 | ⏳ |
| **P2** | S3：下調 max_tokens | 略微加速、減少冗長 | 低 | ✅ |
| **P2** | M2：TeamProfile 快取 | 進一步降低成本 | 中 | ⏳ |
| **P3** | M3：Analysis 追蹤表 | 長期迭代基礎 | 中 | ⏳ |
| **P4** | L1：外部數據源 | 預測準確率核心提升 | 高 | ⏳ |
| **P5** | L2：多模型 Ensemble | 最高準確率 | 高 | ⏳ |
| **P6** | L3：強化學習 Prompt 迭代 | 全自動優化 | 極高 | ⏳ |

---

## 六、結論

現行 AI 分析師功能的核心問題是 **pipeline 過度拆分 + 參數調校偏創意化 + 輸出無法追蹤**。短期內只需 3 個低風險改動（合併 API Call、降 temperature、統一 prompt）即可在**不增加任何基礎設施**的前提下，達到：

- **API 成本降低 40-50%**
- **響應時間縮短 50%**
- **預測一致性顯著提升**

中期加入結構化輸出與結果追蹤後，可進入「數據驅動迭代」的正向循環，持續提升預測準確率。
