import OpenAI from "openai"

const deepseek = new OpenAI({
  baseURL: "https://api.deepseek.com",
  apiKey: process.env.DEEPSEEK_API_KEY,
  timeout: 30000,
  maxRetries: 2,
})

interface TeamStats {
  summary: string
}

interface MatchForAnalysis {
  homeTeam: string
  awayTeam: string
  startTime: Date
  oddsSummary?: string
  /** 比賽階段（小組賽／16強／8強／4強／季軍戰／決賽） */
  stage?: string
  /** 主隊本屆世界盃戰績摘要 */
  homeTeamStats?: string
  /** 客隊本屆世界盃戰績摘要 */
  awayTeamStats?: string
}

/**
 * 呼叫 DeepSeek API 生成比賽分析與投注建議（繁體中文）
 */
export async function generateMatchAnalysis(
  matches: MatchForAnalysis[],
  historicalContext?: string
): Promise<string> {
  if (matches.length === 0) {
    return "今日沒有安排賽程。"
  }

  const matchList = matches
    .map((m, i) => {
      let line = `${i + 1}. ${m.homeTeam} vs ${m.awayTeam}（${m.startTime.toLocaleString("zh-TW", { timeZone: "Asia/Hong_Kong" })}）`
      if (m.stage) {
        line += `\n   🏟 比賽階段：${m.stage}`
      }
      if (m.oddsSummary) {
        line += `\n   賠率參考：${m.oddsSummary}`
      }
      if (m.homeTeamStats || m.awayTeamStats) {
        line += `\n   📊 本屆世界盃戰績（真實數據，請以此為準）：`
        if (m.homeTeamStats) {
          line += `\n   ${m.homeTeam}：${m.homeTeamStats}`
        }
        if (m.awayTeamStats) {
          line += `\n   ${m.awayTeam}：${m.awayTeamStats}`
        }
      }
      return line
    })
    .join("\n")

  const isSingle = matches.length === 1

  const systemPrompt = `你是一位專業的 2026 世界盃足球分析師，擅長結合盤口數據與實際比賽數據進行博弈預測。

任務：對每場提供的比賽生成結構化分析報告。

【重要】你將在下方收到以下結構化數據，請**嚴格基於這些數據進行分析**，不要憑空臆測：
- 比賽階段（小組賽第N輪 或 淘汰賽階段）
- 兩隊在本屆世界盃的**真實完整戰績**（含進球/失球/勝平負）
- 兩隊近 5 場各項賽事表現
- 歷史交鋒紀錄（若有）

對於以下資訊，你可以結合自身知識補充：
- FIFA 排名
- 關鍵球員狀態
- 戰術風格與對位分析

報告格式（繁體中文，每節簡潔）：

## [主隊] vs [客隊]

### 對戰背景
- **比賽階段**：明確寫出這是小組賽第幾輪／16強／8強／4強／季軍戰／決賽
- **FIFA 排名**與**本屆世界盃戰績**（使用下方提供的實際數據，含進球/失球）
- **晉級形勢**：
  - 若為小組賽：分析小組排名與出線條件
  - 若為淘汰賽：分析兩隊晉級路徑，以及本場勝者將面對的下一輪對手
- 近 5 場各項賽事表現簡述
- 歷史交鋒（若數據中無則明確寫「無正式交鋒紀錄」）
- 各隊 2-3 名關鍵球員狀態

### 賠率解讀
- **標準盤（HAD）**：列出主勝/和局/客勝賠率，分析市場信號
- **讓球盤（HDC）**：列出主要讓球盤口與賠率，分析莊家意圖
- **讓球主客和（HHA）**：列出讓球後的主勝/和局/客勝賠率（如有）。
  
  **【重要規則】** HHA 是三選一盤口（只有主勝/和/客勝，**沒有走水/退本金**），與讓球盤（HDC）有走水機制截然不同。解讀時請嚴格按照以下定義，切勿與 HDC 混淆：
  
  **HHA (-1)：主隊讓 1 球（主隊扣 1 球後再判勝/和/負）**
  | 選項 | 等價實際條件 |
  |------|-------------|
  | 主勝 (-1) | 主隊贏 **2 球或以上** |
  | 和 (-1) | 主隊贏 **剛好 1 球** |
  | 客勝 (-1) | 主隊**不勝（和或輸）** |
  
  **HHA (+1)：主隊受讓 1 球（主隊加 1 球後再判勝/和/負）**
  | 選項 | 等價實際條件 |
  |------|-------------|
  | 主勝 (+1) | 主隊**不敗（贏或和）** |
  | 和 (+1) | 主隊**輸剛好 1 球** |
  | 客勝 (+1) | 主隊**輸 2 球或以上** |
  
  **常見錯誤（嚴禁）**：
  - ❌ 把 HHA (+1) 主勝說成「主隊不輸超過 1 球」→ 錯！輸 1 球時是「和」而非「主勝」。
  - ❌ 把 HHA (-1) 客勝說成「客隊不輸超過 1 球」→ 錯！主隊贏 1 球時是「和」而非「客勝」。
  - ❌ 用 HDC 的走水邏輯來理解 HHA → HHA 沒有走水，輸 1 球時 HDC 退本金但 HHA 直接輸。
- **入球大細（HIL）**：列出大小球盤口與賠率（如有）
- **角球讓球（CHD）**：列出角球讓球盤口（如有）
- **角球大細（CHL）**：列出角球大小盤口（如有）
- **盤口訊號**：總結莊家對比賽走向的判斷

### 投注建議
- **穩健推薦**：風險最低的投注方向 + 賠率 + 簡述理由
- **進取推薦**：回報較高的投注方向 + 賠率 + 簡述理由（可選）
- **風險提示**：應避免的投注方向

### 信心指數
使用 ★ 表示（1-5 星），對應上述每項推薦`

  const prefix = isSingle ? "請分析以下比賽" : `以下有 ${matches.length} 場比賽，請為每場產出完整分析`
  let userPrompt = `${prefix}（所有時間為香港時間）：\n\n${matchList}`
  if (historicalContext) {
    userPrompt += `\n\n--- 近況與往績參考 ---\n${historicalContext}`
  }
  userPrompt += `\n\n請為以上比賽生成完整分析報告。`

  const response = await (deepseek.chat.completions.create as any)({
    model: "deepseek-v4-flash",
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
    temperature: 0.3,
    reasoning_effort: "high",
    max_tokens: 4096,
    extra_body: {
      thinking: { type: "enabled" },
    },
  })

  return response.choices[0]?.message?.content || "分析生成失敗，請稍後再試。"
}

