/**
 * 從 wheniskickoff.com 免費 API 獲取 2026 世界盃賽事結果。
 * 用於 buildHistoricalContext() 提供可靠的近況／往績數據，
 * 取代可能出錯的本地 DB result 欄位。
 */

/** wheniskickoff.com API 回傳的單場比賽結構 */
interface ExternalMatch {
  id: number
  home_team: { name: string; code: string }
  away_team: { name: string; code: string }
  home_score: number | null
  away_score: number | null
  status: string // "completed" | "live" | "scheduled"
  datetime: string // ISO 8601
  round?: string
}

interface ExternalApiResponse {
  meta: { version: string; generated: string; source: string }
  count: number
  data: ExternalMatch[]
}

/** 記憶體快取，避免每次分析都打 API */
let cache: { data: ExternalMatch[]; fetchedAt: number } | null = null
const CACHE_TTL = 10 * 60 * 1000 // 10 分鐘

const EXTERNAL_API_URL = "https://wheniskickoff.com/data/v1/matches.json"

/**
 * 從 wheniskickoff.com 獲取全部 104 場世界盃比賽（含比分）。
 * 結果會快取 10 分鐘。
 */
export async function fetchExternalResults(): Promise<ExternalMatch[]> {
  if (cache && Date.now() - cache.fetchedAt < CACHE_TTL) {
    return cache.data
  }

  try {
    const res = await fetch(EXTERNAL_API_URL, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10_000),
    })

    if (!res.ok) {
      throw new Error(`External API returned ${res.status}`)
    }

    const json = (await res.json()) as ExternalApiResponse

    if (!json.data || !Array.isArray(json.data)) {
      throw new Error("Unexpected external API response format")
    }

    cache = { data: json.data, fetchedAt: Date.now() }
    console.log(`📡 [ExternalResults] 已從 wheniskickoff.com 獲取 ${json.data.length} 場比賽`)
    return json.data
  } catch (error) {
    console.warn("⚠️ [ExternalResults] 外部 API 請求失敗，返回快取或空陣列:", error)

    // 若有舊快取，延長使用
    if (cache) {
      console.log("📦 [ExternalResults] 使用過期快取資料")
      return cache.data
    }
    return []
  }
}

/**
 * 正規化隊名：從 HKJC 格式 "中文 English" 提取英文部分。
 * 也用於標準化 wheniskickoff.com 的隊名，確保比對一致。
 *
 * 例如:
 *   "墨西哥 Mexico" → "mexico"
 *   "England"        → "england"
 *   "United States"  → "united states"
 */
export function normalizeTeamName(name: string): string {
  // 若包含中文（Unicode CJK 範圍），取最後一個空格後的英文名
  const cjk = /[\u4e00-\u9fff\u3400-\u4dbf]/
  if (cjk.test(name)) {
    const parts = name.split(/\s+/)
    // 取最後一段純英文部分
    const enParts = parts.filter((p) => !cjk.test(p))
    if (enParts.length > 0) {
      return enParts.join(" ").toLowerCase().trim()
    }
  }
  return name.toLowerCase().trim()
}

/**
 * 比對兩個隊名是否指向同一隊。
 * 支援 HKJC "中文 English" 格式 vs wheniskickoff.com 純英文格式。
 */
export function teamNameMatches(dbName: string, apiName: string): boolean {
  const a = normalizeTeamName(dbName)
  const b = normalizeTeamName(apiName)

  if (a === b) return true
  // 雙向 substring 比對（處理 "Korea Republic" vs "South Korea" 等變體）
  if (a.includes(b) || b.includes(a)) return true

  // 特殊縮寫對照
  const ALIASES: Record<string, string[]> = {
    "united states": ["usa", "us", "united states of america"],
    "korea republic": ["south korea", "korea"],
    "korea dpr": ["north korea"],
    "ir iran": ["iran"],
    "côte d'ivoire": ["cote d'ivoire", "ivory coast"],
    "czech republic": ["czechia"],
  }

  for (const [key, aliases] of Object.entries(ALIASES)) {
    const hit = [key, ...aliases].some(
      (alias) => a === alias || b === alias || a.includes(alias) || b.includes(alias)
    )
    if (hit) return true
  }

  return false
}

/**
 * 從外部 API 資料中找出某隊參與的所有已完賽比賽。
 */
export function findTeamMatches(
  teamName: string,
  matches: ExternalMatch[]
): ExternalMatch[] {
  return matches
    .filter(
      (m) =>
        m.status === "completed" &&
        m.home_score !== null &&
        m.away_score !== null &&
        (teamNameMatches(teamName, m.home_team.name) ||
          teamNameMatches(teamName, m.away_team.name))
    )
    .sort(
      (a, b) =>
        new Date(b.datetime).getTime() - new Date(a.datetime).getTime()
    )
}

/**
 * 從外部 API 資料中找出兩隊之間的過往交鋒紀錄。
 */
export function findH2HMatches(
  team1: string,
  team2: string,
  matches: ExternalMatch[]
): ExternalMatch[] {
  return matches.filter((m) => {
    if (m.status !== "completed") return false
    const home = teamNameMatches(team1, m.home_team.name) && teamNameMatches(team2, m.away_team.name)
    const away = teamNameMatches(team1, m.away_team.name) && teamNameMatches(team2, m.home_team.name)
    return home || away
  })
}

/**
 * 將外部 API 比賽轉換為可讀的比數字串，格式與 DB result 欄位一致。
 */
export function formatExternalResult(match: ExternalMatch): string {
  return `${match.home_score ?? "?"}:${match.away_score ?? "?"}`
}
