/**
 * 世界盃賽事數據層 — 比賽階段解析 + 歷史戰績統計。
 *
 * 資料來源：
 *   1. openfootball/worldcup.json (GitHub) → 完整賽程 + 比分 + 階段標籤
 *   2. ExternalDataCache (DB) → 跨重啟持久化快取
 *
 * 階段標籤優先使用 openfootball 的 round 欄位；
 * getPhaseFromDate 僅作為備用 fallback。
 */

import prisma from "../db/prisma"

// ─── openfootball 原始格式 ───

interface OpenfootballMatch {
  round: string
  num?: number
  date: string
  time?: string
  team1: string
  team2: string
  score?: { ft: [number, number]; ht?: [number, number] }
  goals1?: { name: string; minute: string; penalty?: boolean }[]
  goals2?: { name: string; minute: string; penalty?: boolean }[]
  group?: string
  ground?: string
}

const OPENFOOTBALL_URL =
  "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

// ─── 內部統一格式 ───

export interface ExternalMatch {
  num: number
  date: string
  home: string
  away: string
  group: string | null
  venue: string
  phase: string
  slug: string
  datetime_utc: string
  score_home: number | null
  score_away: number | null
  status: string
  home_name: string | null
  away_name: string | null
  venue_name: string | null
  venue_city: string | null
  label?: string
}

// ─── 快取 ───

let cache: { data: ExternalMatch[]; fetchedAt: number } | null = null
const CACHE_TTL = 10 * 60 * 1000

// ─── 2026 世界盃賽程 → 階段映射 ───

function getPhaseFromDate(dateStr: string): string {
  if (dateStr >= "2026-06-11" && dateStr <= "2026-06-27") return "group"
  if (dateStr >= "2026-06-28" && dateStr <= "2026-07-03") return "Round of 32"
  if (dateStr >= "2026-07-04" && dateStr <= "2026-07-07") return "Round of 16"
  if (dateStr >= "2026-07-09" && dateStr <= "2026-07-11") return "Quarter-finals"
  if (dateStr >= "2026-07-14" && dateStr <= "2026-07-15") return "Semi-finals"
  if (dateStr === "2026-07-18") return "3rd Place Final"
  if (dateStr === "2026-07-19") return "Final"
  return "group"
}

/**
 * 根據比賽日期直接解析階段（不依賴外部資料）。
 * 用於未來賽事（HKJC 歷史 API 尚無資料時）的階段判定。
 */
export function resolvePhaseFromDate(date: Date): string {
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, "0")
  const dd = String(date.getDate()).padStart(2, "0")
  return getPhaseFromDate(`${yyyy}-${mm}-${dd}`)
}

// ─── openfootball → ExternalMatch ───

function mapRoundToPhase(round: string): string {
  if (round.startsWith("Matchday")) return "group"
  if (round === "Round of 32") return "Round of 32"
  if (round === "Round of 16") return "Round of 16"
  if (round === "Quarter-final") return "Quarter-finals"
  if (round === "Semi-final") return "Semi-finals"
  if (round === "Match for third place") return "3rd Place Final"
  if (round === "Final") return "Final"
  return "group"
}

function toAbbreviation(name: string): string {
  const MAP: Record<string, string> = {
    "South Korea": "KOR", "Korea Republic": "KOR",
    "North Korea": "PRK", "Korea DPR": "PRK",
    "United States": "USA", "Saudi Arabia": "KSA",
    "United Arab Emirates": "UAE", "Congo DR": "COD",
    "Cape Verde": "CPV", "Cape Verde Islands": "CPV",
    "Ivory Coast": "CIV", "New Zealand": "NZL",
    "Bosnia-Herzegovina": "BIH", "Bosnia and Herzegovina": "BIH",
    "Czech Republic": "CZE", "Czechia": "CZE",
  }
  if (MAP[name]) return MAP[name]
  const words = name.split(/\s+/)
  if (words.length === 1) return name.slice(0, 3).toUpperCase()
  return words.map(w => w.slice(0, 1)).join("").toUpperCase().slice(0, 3)
}

function openfootballToExternalMatch(m: OpenfootballMatch, index: number): ExternalMatch {
  const phase = mapRoundToPhase(m.round)
  const homeAbbr = toAbbreviation(m.team1)
  const awayAbbr = toAbbreviation(m.team2)
  const slug = `${homeAbbr}-vs-${awayAbbr}-${m.date}`.toLowerCase()
  const hasScore = m.score?.ft != null

  return {
    num: m.num ?? index + 1,
    date: m.date,
    home: homeAbbr,
    away: awayAbbr,
    group: m.group ?? (phase === "group" ? "?" : null),
    venue: m.ground ?? "",
    phase,
    slug,
    datetime_utc: `${m.date}T00:00:00Z`,
    score_home: hasScore ? m.score!.ft[0] : null,
    score_away: hasScore ? m.score!.ft[1] : null,
    status: hasScore ? "FINISHED" : "SCHEDULED",
    home_name: m.team1,
    away_name: m.team2,
    venue_name: m.ground ?? null,
    venue_city: null,
    label: phase !== "group" ? phase : undefined,
  }
}

// ─── 主要 fetch 函數 ───

export async function fetchExternalResults(): Promise<ExternalMatch[]> {
  if (cache && Date.now() - cache.fetchedAt < CACHE_TTL) {
    return cache.data
  }

  try {
    const dbCache = await prisma.externalDataCache.findFirst({
      orderBy: { fetchedAt: "desc" },
    })
    if (dbCache && Date.now() - dbCache.fetchedAt.getTime() < CACHE_TTL) {
      const parsed = JSON.parse(dbCache.data) as ExternalMatch[]
      cache = { data: parsed, fetchedAt: dbCache.fetchedAt.getTime() }
      console.log(`📦 [ExternalResults] 使用 DB 快取 (${parsed.length} 場)`)
      return parsed
    }
  } catch {
    // DB 不可用時跳過
  }

  try {
    const response = await fetch(OPENFOOTBALL_URL)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const json = await response.json() as { matches: OpenfootballMatch[] }
    const data = json.matches.map((m, i) => openfootballToExternalMatch(m, i))

    cache = { data, fetchedAt: Date.now() }
    await persistToDb(data)

    console.log(`📡 [ExternalResults] 已從 openfootball 獲取 ${data.length} 場賽果（${data.filter(m => m.status === "FINISHED").length} 場已完賽）`)
    return data
  } catch (error) {
    console.warn("⚠️ [ExternalResults] openfootball 請求失敗，嘗試降級:", error)

    if (cache) {
      console.log("📦 [ExternalResults] 使用過期記憶體快取")
      return cache.data
    }

    try {
      const staleDb = await prisma.externalDataCache.findFirst({
        orderBy: { fetchedAt: "desc" },
      })
      if (staleDb) {
        console.log("📦 [ExternalResults] 使用過期 DB 快取")
        return JSON.parse(staleDb.data) as ExternalMatch[]
      }
    } catch {
      // 最終降級失敗
    }

    return []
  }
}

async function persistToDb(data: ExternalMatch[]): Promise<void> {
  try {
    await prisma.externalDataCache.deleteMany()
    await prisma.externalDataCache.create({
      data: { data: JSON.stringify(data), fetchedAt: new Date() },
    })
  } catch (error) {
    console.warn("⚠️ [ExternalResults] DB 快取寫入失敗:", error)
  }
}

// ─── 隊名工具函數 ───

export function normalizeTeamName(name: string): string {
  const cjk = /[\u4e00-\u9fff\u3400-\u4dbf]/
  if (cjk.test(name)) {
    const parts = name.split(/\s+/)
    const enParts = parts.filter((p) => !cjk.test(p))
    if (enParts.length > 0) {
      return enParts.join(" ").toLowerCase().trim()
    }
  }
  return name.toLowerCase().trim()
}

export function teamNameMatches(dbName: string, apiName: string): boolean {
  const a = normalizeTeamName(dbName)
  const b = normalizeTeamName(apiName)

  if (a === b) return true

  const canonicalA = resolveCanonicalName(a)
  const canonicalB = resolveCanonicalName(b)

  if (canonicalA === canonicalB) return true

  if (canonicalA.includes(canonicalB) || canonicalB.includes(canonicalA)) return true

  return false
}

function resolveCanonicalName(name: string): string {
  const ALIASES: Record<string, string[]> = {
    "united states": ["usa", "us", "united states of america"],
    "korea republic": ["south korea", "korea"],
    "korea dpr": ["north korea"],
    "ir iran": ["iran"],
    "côte d'ivoire": ["cote d'ivoire", "ivory coast"],
    "czech republic": ["czechia"],
  }

  for (const [key, aliases] of Object.entries(ALIASES)) {
    if (name === key) return key
    if (aliases.includes(name)) return key
  }
  return name
}

// ─── 比賽搜尋 ───

export function findTeamMatches(
  teamName: string,
  matches: ExternalMatch[]
): ExternalMatch[] {
  return matches
    .filter(
      (m) =>
        m.status === "FINISHED" &&
        m.score_home !== null &&
        m.score_away !== null &&
        m.home_name != null &&
        m.away_name != null &&
        (teamNameMatches(teamName, m.home_name) ||
          teamNameMatches(teamName, m.away_name))
    )
    .sort(
      (a, b) =>
        new Date(b.datetime_utc).getTime() - new Date(a.datetime_utc).getTime()
    )
}

export function findH2HMatches(
  team1: string,
  team2: string,
  matches: ExternalMatch[]
): ExternalMatch[] {
  return matches.filter((m) => {
    if (m.status !== "FINISHED") return false
    if (m.home_name == null || m.away_name == null) return false
    const home =
      teamNameMatches(team1, m.home_name) && teamNameMatches(team2, m.away_name)
    const away =
      teamNameMatches(team1, m.away_name) && teamNameMatches(team2, m.home_name)
    return home || away
  })
}

export function formatExternalResult(match: ExternalMatch): string {
  return `${match.score_home ?? "?"}:${match.score_away ?? "?"}`
}

// ─── 比賽階段 ───

export type MatchStage =
  | "group"
  | "round_of_32"
  | "round_of_16"
  | "quarter_final"
  | "semi_final"
  | "third_place"
  | "final"

export function resolveMatchStage(phase: string | undefined): MatchStage | null {
  if (!phase) return null
  const r = phase.toLowerCase().trim()

  if (r === "group" || r.startsWith("group stage")) return "group"
  if (r.includes("round of 32") || r.includes("last-32") || r.includes("last32")) return "round_of_32"
  if (r.includes("round of 16") || r.includes("last-16") || r.includes("last16")) return "round_of_16"
  if (r.includes("quarter")) return "quarter_final"
  if (r.includes("semi")) return "semi_final"
  if (r.includes("3rd") || r.includes("third")) return "third_place"
  if (r === "final") return "final"

  return null
}

const STAGE_LABELS: Record<MatchStage, string> = {
  group: "小組賽",
  round_of_32: "32強淘汰賽",
  round_of_16: "16強淘汰賽",
  quarter_final: "8強淘汰賽",
  semi_final: "4強淘汰賽",
  third_place: "季軍戰",
  final: "冠軍決賽",
}

export function formatStageLabel(stage: MatchStage): string {
  return STAGE_LABELS[stage]
}

export function getMatchPhase(
  homeTeam: string,
  awayTeam: string,
  matches: ExternalMatch[],
  matchDate?: string
): string | undefined {
  const found = matches.find(
    (m) =>
      m.home_name != null &&
      m.away_name != null &&
      teamNameMatches(homeTeam, m.home_name) &&
      teamNameMatches(awayTeam, m.away_name)
  )
  if (found) return found.phase

  if (matchDate) {
    const byDate = matches.find(
      (m) =>
        m.date === matchDate &&
        m.phase != null &&
        !m.phase.toLowerCase().startsWith("group stage") &&
        m.phase.toLowerCase() !== "group"
    )
    if (byDate) return byDate.phase
  }

  return undefined
}

// ─── 球隊本屆戰績 ───

export interface TeamWorldCupStats {
  teamName: string
  played: number
  won: number
  drawn: number
  lost: number
  goalsFor: number
  goalsAgainst: number
  byStage: Record<string, { played: number; won: number; drawn: number; lost: number; gf: number; ga: number }>
}

export function getTeamWorldCupStats(
  teamName: string,
  matches: ExternalMatch[]
): TeamWorldCupStats {
  const completed = findTeamMatches(teamName, matches)

  const stats: TeamWorldCupStats = {
    teamName,
    played: 0,
    won: 0,
    drawn: 0,
    lost: 0,
    goalsFor: 0,
    goalsAgainst: 0,
    byStage: {},
  }

  for (const m of completed) {
    const isHome = teamNameMatches(teamName, m.home_name!)
    const gf = isHome ? (m.score_home ?? 0) : (m.score_away ?? 0)
    const ga = isHome ? (m.score_away ?? 0) : (m.score_home ?? 0)

    stats.played++
    stats.goalsFor += gf
    stats.goalsAgainst += ga
    if (gf > ga) stats.won++
    else if (gf === ga) stats.drawn++
    else stats.lost++

    const stageKey = resolveMatchStage(m.phase) || "unknown"
    if (!stats.byStage[stageKey]) {
      stats.byStage[stageKey] = { played: 0, won: 0, drawn: 0, lost: 0, gf: 0, ga: 0 }
    }
    const ss = stats.byStage[stageKey]
    ss.played++
    ss.gf += gf
    ss.ga += ga
    if (gf > ga) ss.won++
    else if (gf === ga) ss.drawn++
    else ss.lost++
  }

  return stats
}

export function formatTeamWorldCupStats(stats: TeamWorldCupStats): string {
  const lines: string[] = []

  const stageOrder: MatchStage[] = [
    "group",
    "round_of_32",
    "round_of_16",
    "quarter_final",
    "semi_final",
    "third_place",
    "final",
  ]
  for (const stage of stageOrder) {
    const s = stats.byStage[stage]
    if (!s || s.played === 0) continue
    const label = STAGE_LABELS[stage]
    lines.push(`  ${label}: ${s.played}場 ${s.won}勝${s.drawn}和${s.lost}負, 進${s.gf}球 失${s.ga}球`)
  }

  const uk = stats.byStage["unknown"]
  if (uk && uk.played > 0) {
    lines.push(`  其他: ${uk.played}場 ${uk.won}勝${uk.drawn}和${uk.lost}負, 進${uk.gf}球 失${uk.ga}球`)
  }

  const prefix = `總計 ${stats.played}場 ${stats.won}勝${stats.drawn}和${stats.lost}負, 進${stats.goalsFor}球 失${stats.goalsAgainst}球`
  return lines.length > 0 ? `${prefix}\n${lines.join("\n")}` : prefix
}
