import { FootballAPI, FootballMatch, FootballPool, HistoricFootballMatch, HistoricFootballMatchDetails } from "hkjc-api"

const api = new FootballAPI()

export interface HkjcMatchData {
  hkjcMatchId: string
  homeTeam: string
  awayTeam: string
  tournamentName: string
  startTime: Date
  status: "scheduled" | "live" | "finished"
  result?: string
  odds: Record<string, HkjcOddsPool>
  /** 即時賽事才有的角球數據（用於結算 CHD/CHL） */
  homeCorner?: number
  awayCorner?: number
}

export interface HkjcOddsPool {
  oddsType: string
  name: string
  inplay: boolean
  combinations: HkjcOddsCombination[]
}

export interface HkjcOddsCombination {
  str: string
  name: string
  odds: number
  status: string
  condition?: string
}

/**
 * 從 HKJC API 獲取世界盃賽事
 * 支援篩選日期範圍（用於 Cron 抓取明日賽事）
 */
export async function fetchWorldCupMatches(
  startDate?: string,
  endDate?: string
): Promise<HkjcMatchData[]> {
  const [batch1, batch2] = await Promise.all([
    api.getAllFootballMatches({ oddsTypes: ["HAD", "HDC", "HIL", "CRS"] }),
    api.getAllFootballMatches({ oddsTypes: ["HHA", "CHD", "CHL"] }),
  ])

  const pass = (m: FootballMatch) => {
    const tNameCn = m.tournament?.name_ch?.toLowerCase() || ""
    const tNameEn = m.tournament?.name_en?.toLowerCase() || ""
    const tName = tNameCn + " " + tNameEn
    if (!(tName.includes("世盃") || tName.includes("wc finals") || tName.includes("world cup"))) return false
    if (!startDate) return true
    const dp = (m.matchDate || "").split("+")[0]
    return !!dp && dp >= startDate && (!endDate || dp <= endDate)
  }

  const transformed1 = batch1.filter(pass).map(transformMatch)
  const transformed2 = batch2.filter(pass).map(transformMatch)

  const extra = new Map<string, Record<string, HkjcOddsPool>>()
  for (const m of transformed2) {
    extra.set(m.hkjcMatchId, m.odds)
  }
  for (const match of transformed1) {
    const odds = extra.get(match.hkjcMatchId)
    if (odds) Object.assign(match.odds, odds)
  }

  return transformed1
}

/**
 * 獲取即時賽事比分（用於更新進行中的比賽）
 */
export async function fetchRunningMatches(
  matchIds: string[]
): Promise<HkjcMatchData[]> {
  const results: HkjcMatchData[] = []
  for (const id of matchIds) {
    const data = await api.getRunningMatch(id)
    if (data.length > 0) {
      results.push(transformMatch(data[0]))
    }
  }
  return results
}

function transformMatch(match: FootballMatch): HkjcMatchData {
  const odds: Record<string, HkjcOddsPool> = {}

  for (const pool of match.foPools) {
    odds[pool.oddsType] = {
      oddsType: pool.oddsType,
      name: pool.name_ch,
      inplay: pool.inplay,
      combinations: pool.lines.flatMap((line) =>
        line.combinations.map((comb) => ({
          str: comb.str,
          name: comb.selections.map((s) => s.name_ch).join(" / "),
          odds: parseFloat(comb.currentOdds),
          status: comb.status,
          condition: line.condition || undefined,
        }))
      ),
    }
  }

  const score = match.runningResult
    ? `${match.runningResult.homeScore}:${match.runningResult.awayScore}`
    : undefined

  const statusMap: Record<string, HkjcMatchData["status"]> = {
    Scheduled: "scheduled",
    Live: "live",
    Running: "live",
    FIRSTHALF: "live",
    SECONDHALF: "live",
    HALFTIME: "live",
    ETFIRSTHALF: "live",
    ETSECONDHALF: "live",
    BREAK: "live",
    INTBREAK: "live",
    INTFIRSTHALF: "live",
    INTSECONDHALF: "live",
    Finished: "finished",
    Fulltime: "finished",
    Closed: "finished",
    Paying: "finished",
  }

  return {
    hkjcMatchId: match.id,
    homeTeam: `${match.homeTeam.name_ch} ${match.homeTeam.name_en}`.trim(),
    awayTeam: `${match.awayTeam.name_ch} ${match.awayTeam.name_en}`.trim(),
    tournamentName: match.tournament?.name_ch || match.tournament?.name_en || "",
    startTime: new Date(match.kickOffTime),
    status: statusMap[match.status] || "live",
    result: score,
    odds,
    homeCorner: match.runningResult?.homeCorner ?? undefined,
    awayCorner: match.runningResult?.awayCorner ?? undefined,
  }
}

/**
 * 從 HKJC 歷史結果 API 獲取已完賽世界盃賽事比數。
 * 用於賽後自動結算。
 */
export async function fetchHistoricMatchResults(
  startDate: string,
  endDate: string
): Promise<{
  hkjcMatchId: string
  homeScore: number
  awayScore: number
  ttlCorner: number
}[]> {
  const matches = await api.getHistoricFootballMatches({ startDate, endDate })

  const worldCupMatches = matches.filter((m) => {
    const t = (m.tournament?.name_ch || "").toLowerCase()
    return t.includes("世盃") || t.includes("world cup")
  })

  return worldCupMatches.flatMap((m) => {
    const primaryResult = m.results?.[0]
    if (!primaryResult) return []

    return [{
      hkjcMatchId: m.id,
      homeScore: primaryResult.homeResult,
      awayScore: primaryResult.awayResult,
      ttlCorner: primaryResult.ttlCornerResult,
    }]
  })
}

/** HKJC 歷史賽事完整資料（用於建立 ExternalMatch） */
export interface HistoricMatchFull {
  homeTeam: string
  awayTeam: string
  matchDate: string
  homeScore: number
  awayScore: number
}

/**
 * 從 HKJC 歷史 API 獲取世界盃完整賽果（含隊名、日期、比分）。
 * 用於建立 ExternalMatch 供戰績統計與 H2H 分析。
 */
export async function fetchAllWorldCupResults(): Promise<HistoricMatchFull[]> {
  const matches = await api.getHistoricFootballMatches({
    startDate: "2026-06-11",
    endDate: "2026-07-19",
  })

  return matches
    .filter((m) => {
      const t = (m.tournament?.name_ch || "").toLowerCase()
      return t.includes("世盃") || t.includes("world cup")
    })
    .flatMap((m) => {
      const r = m.results?.[0]
      if (!r) return []
      return [
        {
          homeTeam: m.homeTeam.name_en,
          awayTeam: m.awayTeam.name_en,
          matchDate: m.matchDate,
          homeScore: r.homeResult,
          awayScore: r.awayResult,
        },
      ]
    })
}

/**
 * 從 HKJC 獲取單場賽事各玩法的派彩結果（winOrd）。
 * 用於驗證結算或取得角球細項數據。
 */
export async function fetchMatchResultDetails(
  matchId: string
): Promise<HistoricFootballMatchDetails | null> {
  return api.getHistoricFootballMatchDetails(matchId)
}
