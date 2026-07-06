import cron from "node-cron"
import { Client, EmbedBuilder, TextChannel } from "discord.js"
import prisma from "../db/prisma"
import { fetchWorldCupMatches, type HkjcMatchData } from "./hkjc"
import { generateMatchAnalysis } from "./deepseek"
import { Match } from "@prisma/client"
import {
  fetchExternalResults,
  findTeamMatches,
  findH2HMatches,
  formatExternalResult,
  teamNameMatches,
  getMatchPhase,
  resolveMatchStage,
  resolvePhaseFromDate,
  formatStageLabel,
  getTeamWorldCupStats,
  formatTeamWorldCupStats,
} from "./externalResults"
import type { ExternalMatch } from "./externalResults"

export function startDailyAnalysisCron(client: Client): void {
  const cronTime = process.env.CRON_TIME || "0 8 * * *"
  cron.schedule(cronTime, async () => {
    console.log(`🔍 [Cron] 開始執行每日比賽分析 (${cronTime})...`)
    await runDailyAnalysis(client)
  }, { timezone: "Asia/Hong_Kong" })

  console.log(`⏰ 每日分析排程已設定：${cronTime}`)
}

async function runDailyAnalysis(client: Client): Promise<void> {
  try {
    const channelId = process.env.DAILY_PICKS_CHANNEL_ID
    if (!channelId) {
      console.error("❌ 未設定 DAILY_PICKS_CHANNEL_ID，跳過每日分析")
      return
    }

    const channel = (await client.channels.fetch(channelId)) as TextChannel
    if (!channel) {
      console.error(`❌ 找不到頻道 ${channelId}`)
      return
    }

    const today = new Date()
    const dateStr = formatDate(today)
    const tomorrow = new Date(today)
    tomorrow.setDate(tomorrow.getDate() + 1)
    const tomorrowStr = formatDate(tomorrow)

    console.log(`📡 正在從 HKJC 抓取今日 (${dateStr}) 世界盃賽事...`)
    let hkjcMatches = await fetchWorldCupMatches(dateStr, dateStr)

    if (hkjcMatches.length === 0) {
      console.log(`📡 今日無賽事，嘗試撈取明日 (${tomorrowStr})...`)
      hkjcMatches = await fetchWorldCupMatches(tomorrowStr, tomorrowStr)
      if (hkjcMatches.length === 0) {
        await channel.send("📭 暫無世界盃賽程資料。")
        return
      }
    }

    const matchRecords = await upsertMatchesToDb(hkjcMatches)
    await analyzeAndPost(client, matchRecords)
  } catch (error) {
    console.error("❌ 每日分析執行失敗:", error)
  }
}

export async function upsertMatchesToDb(
  hkjcMatches: HkjcMatchData[]
): Promise<Match[]> {
  return Promise.all(
    hkjcMatches.map(async (m) => {
      const existing = await prisma.match.findUnique({
        where: { hkjcMatchId: m.hkjcMatchId },
      })
      if (existing) {
        return prisma.match.update({
          where: { id: existing.id },
          data: {
            status: m.status,
            oddsData: m.odds as unknown as object,
            oddsUpdatedAt: new Date(),
          },
        })
      }
      return prisma.match.create({
        data: {
          hkjcMatchId: m.hkjcMatchId,
          homeTeam: m.homeTeam,
          awayTeam: m.awayTeam,
          startTime: m.startTime,
          status: m.status,
          oddsData: m.odds as unknown as object,
          oddsUpdatedAt: new Date(),
        },
      })
    })
  )
}

export async function analyzeSingleMatch(
  matchRecord: Match,
  channel: TextChannel
): Promise<void> {
  let externalMatches: ExternalMatch[] = []
  try {
    externalMatches = await fetchExternalResults()
  } catch {
    console.warn("⚠️ [analyzeSingleMatch] 外部 API 不可用，跳過階段/戰績解析")
  }

  const extra = resolveMatchExtra(matchRecord, externalMatches)
  const historicalContext = await buildHistoricalContext([matchRecord])

  const matchData = buildMatchForAnalysis(matchRecord, extra)

  console.log(`🤖 正在分析 ${matchRecord.homeTeam} vs ${matchRecord.awayTeam}...`)
  const analysis = await generateMatchAnalysis([matchData], historicalContext)

  const embed = buildAnalysisEmbed(matchRecord, analysis)

  await channel.send({ embeds: [embed] })
  console.log(`✅ 已發送 ${matchRecord.homeTeam} vs ${matchRecord.awayTeam} 分析`)
}

export async function analyzeAndPost(
  client: Client,
  matchRecords: Match[]
): Promise<void> {
  const channelId = process.env.DAILY_PICKS_CHANNEL_ID
  if (!channelId) {
    console.error("❌ 未設定 DAILY_PICKS_CHANNEL_ID，跳過分析發送")
    return
  }

  const channel = (await client.channels.fetch(channelId)) as TextChannel
  if (!channel) {
    console.error(`❌ 找不到頻道 ${channelId}`)
    return
  }

  const sorted = [...matchRecords].sort(
    (a, b) => a.startTime.getTime() - b.startTime.getTime()
  )

  let externalMatches: ExternalMatch[] = []
  try {
    externalMatches = await fetchExternalResults()
  } catch {
    console.warn("⚠️ [analyzeAndPost] 外部 API 不可用，跳過階段/戰績解析")
  }

  for (const match of sorted) {
    const extra = resolveMatchExtra(match, externalMatches)
    const historicalContext = await buildHistoricalContext([match])

    const matchData = buildMatchForAnalysis(match, extra)

    console.log(`🤖 正在分析 ${match.homeTeam} vs ${match.awayTeam}...`)
    const analysis = await generateMatchAnalysis([matchData], historicalContext)

    await channel.send({ embeds: [buildAnalysisEmbed(match, analysis)] })
  }

  console.log(`✅ 每日分析已發送 ${sorted.length} 場至頻道 ${channel.id}`)
}

/**
 * 從外部 API 解析單場比賽的階段、球隊戰績等額外資訊。
 * 用於 buildMatchForAnalysis 提供結構化數據給 AI prompt。
 */
function resolveMatchExtra(
  match: Match,
  externalMatches: ExternalMatch[]
): { stage?: string; homeTeamStats?: string; awayTeamStats?: string } {
  const result: { stage?: string; homeTeamStats?: string; awayTeamStats?: string } = {}

  const matchDate = formatDate(match.startTime)
  const round = getMatchPhase(match.homeTeam, match.awayTeam, externalMatches, matchDate)
    ?? resolvePhaseFromDate(match.startTime)
  const stage = resolveMatchStage(round)
  if (stage) {
    result.stage = formatStageLabel(stage)
  }

  const homeStats = getTeamWorldCupStats(match.homeTeam, externalMatches)
  if (homeStats.played > 0) {
    result.homeTeamStats = formatTeamWorldCupStats(homeStats)
  }

  const awayStats = getTeamWorldCupStats(match.awayTeam, externalMatches)
  if (awayStats.played > 0) {
    result.awayTeamStats = formatTeamWorldCupStats(awayStats)
  }

  return result
}

function buildMatchForAnalysis(
  match: Match,
  extra?: { stage?: string; homeTeamStats?: string; awayTeamStats?: string }
) {
  const oddsData = match.oddsData as Record<string, unknown> | null
  let oddsSummary = ""
  if (oddsData) {
    const had = oddsData["HAD"] as
      | { combinations?: Array<{ str: string; name: string; odds: number }> }
      | undefined
    if (had?.combinations) {
      oddsSummary = had.combinations
        .map((c) => `${c.name}: ${c.odds}`)
        .join(", ")
    }

    const hdc = oddsData["HDC"] as
      | { combinations?: Array<{ str: string; name: string; odds: number; status?: string; condition?: string }> }
      | undefined
    const hdcCombos = hdc?.combinations
    if (hdcCombos) {
      const hdcSummary = hdcCombos
        .filter((c) => !c.status || c.status === "AVAILABLE")
        .map((c) => `${c.name}${c.condition ? `(${c.condition})` : ""}: ${c.odds}`)
        .join(", ")
      if (hdcSummary) {
        oddsSummary += (oddsSummary ? " | " : "") + "讓球: " + hdcSummary
      }
    }

    const hha = oddsData["HHA"] as
      | { combinations?: Array<{ str: string; name: string; odds: number; status?: string; condition?: string }> }
      | undefined
    const hhaCombos = hha?.combinations
    if (hhaCombos) {
      const mainConds = [...new Set(hhaCombos.filter(c => c.status === "AVAILABLE" && c.condition).map(c => c.condition!))].slice(0, 1)
      const hhaSummary = mainConds.map(cond => {
        const parts = hhaCombos.filter(c => c.condition === cond).map(c => `${c.name}: ${c.odds}`).join(" / ")
        return `(${cond.replace(/\.0$/, "")}) ${parts}`
      }).join(" | ")
      if (hhaSummary) {
        oddsSummary += (oddsSummary ? " | " : "") + "讓球主客和: " + hhaSummary
      }
    }

    const hil = oddsData["HIL"] as
      | { combinations?: Array<{ str: string; name: string; odds: number; status?: string; condition?: string }> }
      | undefined
    const hilCombos = hil?.combinations
    if (hilCombos) {
      const main = hilCombos.find(c => c.status === "AVAILABLE" && c.condition)
      if (main) {
        const h = hilCombos.find(c => c.condition === main.condition && c.str === "H")
        const l = hilCombos.find(c => c.condition === main.condition && c.str === "L")
        oddsSummary += (oddsSummary ? " | " : "") + `入球大細 (${main.condition}): 大 ${h?.odds ?? "—"} / 細 ${l?.odds ?? "—"}`
      }
    }

    const chd = oddsData["CHD"] as
      | { combinations?: Array<{ str: string; name: string; odds: number; status?: string; condition?: string }> }
      | undefined
    const chdCombos = chd?.combinations
    if (chdCombos) {
      const main = chdCombos.find(c => c.status === "AVAILABLE" && c.condition)
      if (main) {
        const h = chdCombos.find(c => c.condition === main.condition && c.str === "H")
        const a = chdCombos.find(c => c.condition === main.condition && c.str === "A")
        oddsSummary += (oddsSummary ? " | " : "") + `角球讓球 (${main.condition}): 主 ${h?.odds ?? "—"} / 客 ${a?.odds ?? "—"}`
      }
    }

    const chl = oddsData["CHL"] as
      | { combinations?: Array<{ str: string; name: string; odds: number; status?: string; condition?: string }> }
      | undefined
    const chlCombos = chl?.combinations
    if (chlCombos) {
      const main = chlCombos.find(c => c.status === "AVAILABLE" && c.condition)
      if (main) {
        const h = chlCombos.find(c => c.condition === main.condition && c.str === "H")
        const l = chlCombos.find(c => c.condition === main.condition && c.str === "L")
        oddsSummary += (oddsSummary ? " | " : "") + `角球大細 (${main.condition}): 大 ${h?.odds ?? "—"} / 細 ${l?.odds ?? "—"}`
      }
    }
  }
  return {
    homeTeam: match.homeTeam,
    awayTeam: match.awayTeam,
    startTime: match.startTime,
    oddsSummary,
    stage: extra?.stage,
    homeTeamStats: extra?.homeTeamStats,
    awayTeamStats: extra?.awayTeamStats,
  }
}

function buildAnalysisEmbed(match: Match, analysis: string): EmbedBuilder {
  const time = match.startTime.toLocaleString("zh-TW", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })

  const truncated =
    analysis.length > 3800
      ? analysis.slice(0, 3800) + "\n\n⚠️ 分析內容過長，已截斷。完整內容請查詢資料庫。"
      : analysis

  return new EmbedBuilder()
    .setColor(0x1e90ff)
    .setTitle(`${match.homeTeam} vs ${match.awayTeam}`)
    .setDescription(`🕐 ${time}\n\n${truncated}`)
    .setFooter({
      text: "分析由 DeepSeek AI 生成 | 賠率來源：香港賽馬會 | 僅供參考，請理性投注",
    })
    .setTimestamp()
}

async function buildHistoricalContext(matches: Match[]): Promise<string> {
  const lines: string[] = []
  const teamNames = new Set<string>()
  matches.forEach((m) => {
    teamNames.add(m.homeTeam)
    teamNames.add(m.awayTeam)
  })

  // ── 優先使用外部 API (api-sports.io) 的可靠比分 ──
  let externalMatches: Awaited<ReturnType<typeof fetchExternalResults>> = []
  try {
    externalMatches = await fetchExternalResults()
  } catch {
    console.warn("⚠️ [HistoricalContext] 外部 API 不可用，降級至 DB 快取")
  }

  if (externalMatches.length > 0) {
    console.log(
      `📊 [HistoricalContext] 使用外部 API 數據 (${externalMatches.length} 場) 建立歷史背景`
    )

    for (const team of teamNames) {
      const recent = findTeamMatches(team, externalMatches).slice(0, 5)
      if (recent.length > 0) {
        const form = recent
          .map((m) => {
            const isHome = teamNameMatches(team, m.home_name!)
            const opponent = isHome ? m.away_name! : m.home_name!
            const score = formatExternalResult(m)
            return `${isHome ? "[主]" : "[客]"} ${opponent} (${score})`
          })
          .join(" → ")
        lines.push(`${team} 近況: ${form}`)
      }
    }

    for (const m of matches) {
      const h2h = findH2HMatches(m.homeTeam, m.awayTeam, externalMatches)
      if (h2h.length > 0) {
        const h2hStr = h2h
          .map(
            (em) =>
              `${em.home_name!} ${formatExternalResult(em)} ${em.away_name!}`
          )
          .join(" | ")
        lines.push(`⚔ ${m.homeTeam} vs ${m.awayTeam} 往績: ${h2hStr}`)
      }
    }

    return lines.join("\n")
  }

  // ── Fallback: 外部 API 無資料時降級至 ExternalDataCache ──
  console.log("📦 [HistoricalContext] 外部 API 無資料，降級至 ExternalDataCache")
  try {
    const dbCache = await prisma.externalDataCache.findFirst({
      orderBy: { fetchedAt: "desc" },
    })
    if (dbCache) {
      const cachedMatches = JSON.parse(dbCache.data) as ExternalMatch[]
      externalMatches = cachedMatches
    }
  } catch {
    console.warn("⚠️ [HistoricalContext] ExternalDataCache 不可用")
  }

  if (externalMatches.length === 0) return ""

  for (const team of teamNames) {
    const recent = findTeamMatches(team, externalMatches).slice(0, 5)
    if (recent.length > 0) {
      const form = recent
        .map((m) => {
          const isHome = teamNameMatches(team, m.home_name!)
          const opponent = isHome ? m.away_name! : m.home_name!
          const score = formatExternalResult(m)
          return `${isHome ? "[主]" : "[客]"} ${opponent} (${score})`
        })
        .join(" → ")
      lines.push(`${team} 近況: ${form}`)
    }
  }

  for (const m of matches) {
    const h2h = findH2HMatches(m.homeTeam, m.awayTeam, externalMatches)
    if (h2h.length > 0) {
      const h2hStr = h2h
        .map(
          (em) =>
            `${em.home_name!} ${formatExternalResult(em)} ${em.away_name!}`
        )
        .join(" | ")
      lines.push(`⚔ ${m.homeTeam} vs ${m.awayTeam} 往績: ${h2hStr}`)
    }
  }

  return lines.join("\n")
}

export function formatDate(date: Date): string {
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, "0")
  const dd = String(date.getDate()).padStart(2, "0")
  return `${yyyy}-${mm}-${dd}`
}

const HK_TIME = () =>
  new Date().toLocaleString("zh-HK", { timeZone: "Asia/Hong_Kong", hour12: false })

async function settleStaleMatches(): Promise<void> {
  const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000)

  const stale = await prisma.match.findMany({
    where: {
      status: "live",
      startTime: { lt: threeHoursAgo },
    },
  })

  if (stale.length === 0) return

  console.log(`[${HK_TIME()}] 🧹 [Cron Fetch] 發現 ${stale.length} 場過期比賽，標記為 finished...`)

  for (const m of stale) {
    await prisma.match.update({
      where: { id: m.id },
      data: { status: "finished" },
    })
  }

  console.log(`[${HK_TIME()}] ✅ [Cron Fetch] 已標記 ${stale.length} 場 finished`)
}

export function startMatchFetchCron(): void {
  const CRON_FETCH = process.env.CRON_FETCH || "*/5 * * * *"
  cron.schedule(CRON_FETCH, async () => {
    try {
      const todayStr = formatDate(new Date())
      const tomorrowDate = new Date()
      tomorrowDate.setDate(tomorrowDate.getDate() + 1)
      const tomorrowStr = formatDate(tomorrowDate)

      console.log(`[${HK_TIME()}] 📡 [Cron Fetch] 正在背景同步賽程 (${todayStr})...`)
      let matches = await fetchWorldCupMatches(todayStr, todayStr)
      if (matches.length === 0) {
        console.log(`[${HK_TIME()}] 📡 [Cron Fetch] 今日無賽事，嘗試撈取明日 (${tomorrowStr})...`)
        matches = await fetchWorldCupMatches(tomorrowStr, tomorrowStr)
      }
      if (matches.length > 0) {
        await upsertMatchesToDb(matches)
        console.log(`[${HK_TIME()}] ✅ [Cron Fetch] 已更新 ${matches.length} 場比賽賠率`)
      } else {
        console.log(`[${HK_TIME()}] 📭 [Cron Fetch] 暫無世界盃賽事`)
      }

      await settleStaleMatches()
    } catch (error) {
      console.error(`[${HK_TIME()}] ❌ [Cron Fetch] 背景同步失敗:`, error)
    }
  }, { timezone: "Asia/Hong_Kong" })

  console.log(`⏰ 背景賠率同步排程已設定：${CRON_FETCH}`)
}
