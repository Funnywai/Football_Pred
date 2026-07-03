import OpenAI from "openai"

const deepseek = new OpenAI({
  baseURL: "https://api.deepseek.com",
  apiKey: process.env.DEEPSEEK_API_KEY,
  timeout: 30000,
  maxRetries: 2,
})

interface MatchForAnalysis {
  homeTeam: string
  awayTeam: string
  startTime: Date
  oddsSummary?: string
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
      if (m.oddsSummary) {
        line += `\n   賠率參考：${m.oddsSummary}`
      }
      return line
    })
    .join("\n")

  const isSingle = matches.length === 1

  const systemPrompt = `你是一位專業的 2026 世界盃足球分析師，擅長結合盤口數據與球隊資訊進行博弈預測。

任務：對每場提供的比賽生成結構化分析報告。

請在分析前，基於你的知識庫簡要整理以下資訊：
1. 兩隊最新 FIFA 排名
2. 兩隊 2026 世界盃至今戰績與進球/失球數據
3. 兩隊過往歷史交鋒紀錄（若無則明確寫「無正式交鋒紀錄」）
4. 各隊 2-3 名關鍵球員及其當前狀態
5. 所在小組晉級形勢

報告格式（繁體中文，每節簡潔）：

## [主隊] vs [客隊]

### 對戰背景
- FIFA 排名、本屆戰績、小組形勢
- 近 5 場表現簡述
- 歷史交鋒（若無則明確寫「無正式交鋒紀錄」）
- 各隊 2-3 名關鍵球員狀態

### 賠率解讀
- **標準盤（HAD）**：列出主勝/和局/客勝賠率，分析市場信號
- **讓球盤（HDC）**：列出主要讓球盤口與賠率，分析莊家意圖
- **讓球主客和（HHA）**：列出讓球後的主勝/和局/客勝賠率（如有）。**【重要規則】** HHA 是三選一盤口，與讓球盤（HDC）不同：主隊「+1 主勝」代表實際賽果主隊必須**贏或和**（即不敗），若輸 1 球即算和局而非主勝。解讀時請勿與讓球盤混淆。
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
    userPrompt += `\n\n--- 歷史數據參考 ---\n${historicalContext}`
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

