import {
  Interaction,
  EmbedBuilder,
  ChatInputCommandInteraction,
  AutocompleteInteraction,
  ButtonBuilder,
  ActionRowBuilder,
  ButtonStyle,
  ButtonInteraction,
  TextChannel,
} from "discord.js"
import prisma from "../db/prisma"
import { fetchWorldCupMatches } from "../services/hkjc"
import { upsertMatchesToDb, analyzeAndPost, analyzeSingleMatch, formatDate } from "../services/dailyAnalysis"

function flipPart(part: string): string {
  if (part.startsWith("-")) return "+" + part.slice(1)
  if (part.startsWith("+")) return "-" + part.slice(1)
  if (part === "0" || part === "0.0") return part
  return "-" + part
}

function flipCondition(condition: string): string {
  if (!condition.includes("/")) return flipPart(condition)
  return condition.split("/").map(flipPart).join("/")
}

export async function onInteractionCreate(
  interaction: Interaction
): Promise<void> {
  if (interaction.isAutocomplete()) {
    await handleAutocomplete(interaction)
    return
  }

  if (interaction.isButton()) {
    if (interaction.customId === "refresh_match") {
      await handleRefreshMatch(interaction)
      return
    }
  }

  if (!interaction.isChatInputCommand()) return

  const { commandName } = interaction

  switch (commandName) {
    case "match":
      await handleFetch(interaction)
      break
    case "analyst":
      await handleAnalyst(interaction)
      break
  }
}

// ─── Autocomplete ──────────────────────────────────────────────────────────

async function handleAutocomplete(
  interaction: AutocompleteInteraction
): Promise<void> {
  const { commandName } = interaction

  if (commandName === "analyst") {
    const focusedOption = interaction.options.getFocused(true)

    if (focusedOption.name === "match_id") {
      const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000)
      const matches = await prisma.match.findMany({
        where: {
          OR: [
            { status: "scheduled" },
            { status: "live", startTime: { gt: threeHoursAgo } },
          ],
        },
        orderBy: { startTime: "asc" },
      })

      const choices = matches.map((m) => ({
        name: `${m.homeTeam} vs ${m.awayTeam}`,
        value: m.id,
      }))
      await interaction.respond(choices)
    }
  }
}

// ─── /match ────────────────────────────────────────────────────────────────

async function handleFetch(
  interaction: ChatInputCommandInteraction
): Promise<void> {
  try {
    await interaction.deferReply()

    const todayStr = formatDate(new Date())
    const tomorrowDate = new Date()
    tomorrowDate.setDate(tomorrowDate.getDate() + 1)
    const tomorrowStr = formatDate(tomorrowDate)

    console.log(`📡 [/match] 正在從 HKJC 抓取今日 (${todayStr}) 世界盃賽事...`)
    let matches = await fetchWorldCupMatches(todayStr, todayStr)

    if (matches.length === 0) {
      console.log(`📡 [/match] 今日無賽事，嘗試撈取明日 (${tomorrowStr})...`)
      matches = await fetchWorldCupMatches(tomorrowStr, tomorrowStr)
    }

    if (matches.length === 0) {
      await interaction.editReply("📭 暫無世界盃賽程資料。")
      return
    }

    const records = await upsertMatchesToDb(matches)

    const matchLines = records.map((m, i) => {
      const oddsData = m.oddsData as Record<string, unknown> | null
      let oddsLines: string[] = []
      if (oddsData) {
        const had = oddsData["HAD"] as
          | { combinations?: Array<{ str: string; odds: number }> }
          | undefined
        if (had?.combinations) {
          const home = had.combinations.find((c) => c.str === "H")
          const draw = had.combinations.find((c) => c.str === "D")
          const away = had.combinations.find((c) => c.str === "A")
          oddsLines.push(
            `主 ${home?.odds.toFixed(2) ?? "—"} | ` +
            `和 ${draw?.odds.toFixed(2) ?? "—"} | ` +
            `客 ${away?.odds.toFixed(2) ?? "—"}`
          )
        }
      }
      const time = m.startTime.toLocaleString("zh-TW", {
        timeZone: "Asia/Hong_Kong",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
      return (
        `**#${i + 1}** ${m.homeTeam} vs ${m.awayTeam}\n` +
        `　🕐 ${time}\n` +
        `　📊 ${oddsLines.join("\n　")}`
      )
    })

    const embed = new EmbedBuilder()
      .setColor(0x00ff00)
      .setTitle("📡 賽程同步完成")
      .setDescription(`成功同步 ${records.length} 場比賽至資料庫：\n\n${matchLines.join("\n\n")}`)
      .setFooter({ text: `來源：香港賽馬會` })
      .setTimestamp()

    await interaction.editReply({ embeds: [embed] })
  } catch (error) {
    console.error("❌ /match 執行錯誤:", error)
    const content = "❌ 同步賽程時發生錯誤，請稍後再試。"
    if (interaction.deferred) {
      await interaction.editReply(content)
    } else {
      await interaction.reply({ content, ephemeral: true })
    }
  }
}

// ─── 重新整理按鈕 ──────────────────────────────────────────────────────────

async function handleRefreshMatch(
  interaction: ButtonInteraction
): Promise<void> {
  try {
    await interaction.deferUpdate()

    const matches = await queryUpcomingMatches()
    if (matches.length === 0) {
      await interaction.editReply({ content: "📭 目前沒有即將到來的賽程。", embeds: [], components: [] })
      return
    }

    const embed = buildMatchEmbed(matches)
    const row = buildMatchActionRow()
    await interaction.editReply({ embeds: [embed], components: [row] })
  } catch (error) {
    console.error("❌ 重新整理賽程錯誤:", error)
    await interaction.editReply({ content: "❌ 重新整理時發生錯誤。", embeds: [], components: [] })
  }
}

async function queryUpcomingMatches() {
  const startOfToday = new Date()
  startOfToday.setHours(0, 0, 0, 0)
  const endOfToday = new Date()
  endOfToday.setHours(23, 59, 59, 999)

  let matches = await prisma.match.findMany({
    where: {
      status: { in: ["scheduled", "live"] },
      startTime: { gte: startOfToday, lte: endOfToday },
    },
    orderBy: { startTime: "asc" },
  })

  if (matches.length === 0) {
    const startOfTomorrow = new Date()
    startOfTomorrow.setDate(startOfTomorrow.getDate() + 1)
    startOfTomorrow.setHours(0, 0, 0, 0)
    const endOfTomorrow = new Date()
    endOfTomorrow.setDate(endOfTomorrow.getDate() + 1)
    endOfTomorrow.setHours(23, 59, 59, 999)

    matches = await prisma.match.findMany({
      where: {
        status: { in: ["scheduled", "live"] },
        startTime: { gte: startOfTomorrow, lte: endOfTomorrow },
      },
      orderBy: { startTime: "asc" },
    })
  }

  return matches
}

function buildMatchEmbed(matches: Awaited<ReturnType<typeof queryUpcomingMatches>>): EmbedBuilder {
  const matchLines = matches.map((m, i) => {
    const oddsData = m.oddsData as Record<string, unknown> | null
    const oddsLines: string[] = []
    if (oddsData) {
      const had = oddsData["HAD"] as
        | { combinations?: Array<{ str: string; odds: number }> }
        | undefined
      if (had?.combinations) {
        const home = had.combinations.find((c) => c.str === "H")
        const draw = had.combinations.find((c) => c.str === "D")
        const away = had.combinations.find((c) => c.str === "A")
        oddsLines.push(
          `主 ${home?.odds.toFixed(2) ?? "—"} | ` +
          `和 ${draw?.odds.toFixed(2) ?? "—"} | ` +
          `客 ${away?.odds.toFixed(2) ?? "—"}`
        )
      }

      const hdc = oddsData["HDC"] as
        | { combinations?: Array<{ str: string; odds: number; status: string; condition?: string }> }
        | undefined
      const hdcCombos = hdc?.combinations
      if (hdcCombos) {
        const conds = [...new Set(hdcCombos.filter(c => c.status === "AVAILABLE" && c.condition).map(c => c.condition!))]
        const condsShown = conds.slice(0, 2)
        const hdcParts = condsShown.map((cond) => {
          const h = hdcCombos.find((c) => c.condition === cond && c.str === "H")
          const a = hdcCombos.find((c) => c.condition === cond && c.str === "A")
          return `主 ${cond} (${h?.odds.toFixed(2) ?? "—"}) | 客 ${flipCondition(cond)} (${a?.odds.toFixed(2) ?? "—"})`
        })
        const hdcSuffix = conds.length > 2 ? ` ...共 ${conds.length} 個盤口` : ""
        if (hdcParts.length > 0) {
          oddsLines.push(`⚖️ ${hdcParts.join(" | ")}${hdcSuffix}`)
        }
      }

      const hha = oddsData["HHA"] as
        | { combinations?: Array<{ str: string; odds: number; status: string; condition?: string }> }
        | undefined
      const hhaCombos = hha?.combinations
      if (hhaCombos) {
        const conds = [...new Set(hhaCombos.filter(c => c.status === "AVAILABLE" && c.condition).map(c => c.condition!))]
        const condsShown = conds.slice(0, 2)
        const hhaParts = condsShown.map((cond) => {
          const h = hhaCombos.find((c) => c.condition === cond && c.str === "H")
          const d = hhaCombos.find((c) => c.condition === cond && c.str === "D")
          const a = hhaCombos.find((c) => c.condition === cond && c.str === "A")
          return `主 ${cond} (${h?.odds.toFixed(2) ?? "—"}) | 和 (${d?.odds.toFixed(2) ?? "—"}) | 客 ${flipCondition(cond)} (${a?.odds.toFixed(2) ?? "—"})`
        })
        if (hhaParts.length > 0) {
          oddsLines.push(`🏟️ ${hhaParts.join(" | ")}`)
        }
      }

      const hil = oddsData["HIL"] as
        | { combinations?: Array<{ str: string; odds: number; status: string; condition?: string }> }
        | undefined
      const hilCombos = hil?.combinations
      if (hilCombos) {
        const conds = [...new Set(hilCombos.filter(c => c.status === "AVAILABLE" && c.condition).map(c => c.condition!))]
        const condsShown = conds.slice(0, 2)
        const hilParts = condsShown.map((cond) => {
          const h = hilCombos.find((c) => c.condition === cond && c.str === "H")
          const l = hilCombos.find((c) => c.condition === cond && c.str === "L")
          return `大 ${cond} (${h?.odds.toFixed(2) ?? "—"}) | 細 ${cond} (${l?.odds.toFixed(2) ?? "—"})`
        })
        if (hilParts.length > 0) {
          oddsLines.push(`⚽ ${hilParts.join(" | ")}`)
        }
      }

      const chd = oddsData["CHD"] as
        | { combinations?: Array<{ str: string; odds: number; status: string; condition?: string }> }
        | undefined
      const chdCombos = chd?.combinations
      if (chdCombos) {
        const avail = chdCombos.filter(c => c.status === "AVAILABLE")
        const chdParts = avail.slice(0, 4).map((c) => {
          const teamName = c.str === "H" ? m.homeTeam : m.awayTeam
          const cond = c.str === "H" ? c.condition : (c.condition ? flipCondition(c.condition) : undefined)
          const suffix = cond ? ` ${cond}` : ""
          return `${teamName}${suffix} (${c.odds.toFixed(2)})`
        })
        if (chdParts.length > 0) {
          oddsLines.push(`🏳️ ${chdParts.join(" | ")}`)
        }
      }

      const chl = oddsData["CHL"] as
        | { combinations?: Array<{ str: string; odds: number; status: string; condition?: string }> }
        | undefined
      const chlCombos = chl?.combinations
      if (chlCombos) {
        const conds = [...new Set(chlCombos.filter(c => c.status === "AVAILABLE" && c.condition).map(c => c.condition!))]
        const condsShown = conds.slice(0, 2)
        const chlParts = condsShown.map((cond) => {
          const h = chlCombos.find((c) => c.condition === cond && c.str === "H")
          const l = chlCombos.find((c) => c.condition === cond && c.str === "L")
          return `角大 ${cond} (${h?.odds.toFixed(2) ?? "—"}) | 角細 ${cond} (${l?.odds.toFixed(2) ?? "—"})`
        })
        if (chlParts.length > 0) {
          oddsLines.push(`🪣 ${chlParts.join(" | ")}`)
        }
      }
    }
    const time = m.startTime.toLocaleString("zh-TW", {
      timeZone: "Asia/Taipei",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
    return (
      `**#${i + 1}** ${m.homeTeam} vs ${m.awayTeam}\n` +
      `　🕐 ${time}\n` +
      `　📊 ${oddsLines.join("\n　")}`
    )
  })

  return new EmbedBuilder()
    .setColor(0x00aaff)
    .setTitle("📅 即將到來的賽程")
    .setDescription(matchLines.join("\n\n"))
    .setFooter({ text: "可使用 /analyst run 進行 AI 分析" })
    .setTimestamp()
}

function buildMatchActionRow(): ActionRowBuilder<ButtonBuilder> {
  const refreshButton = new ButtonBuilder()
    .setCustomId("refresh_match")
    .setLabel("🔄 重新整理")
    .setStyle(ButtonStyle.Primary)

  return new ActionRowBuilder<ButtonBuilder>().addComponents(refreshButton)
}

// ─── /analyst ──────────────────────────────────────────────────────────────

async function handleAnalyst(
  interaction: ChatInputCommandInteraction
): Promise<void> {
  const subcommand = interaction.options.getSubcommand()

  try {
    switch (subcommand) {
      case "run":
        await handleAnalystRun(interaction)
        break
      case "match":
        await handleAnalystMatch(interaction)
        break
    }
  } catch (error) {
    console.error(`❌ /analyst ${subcommand} 執行錯誤:`, error)
    const content = "❌ 執行分析操作時發生錯誤，請稍後再試。"
    if (interaction.deferred) {
      await interaction.editReply(content)
    } else if (!interaction.replied) {
      await interaction.reply({ content, ephemeral: true })
    }
  }
}

async function handleAnalystRun(
  interaction: ChatInputCommandInteraction
): Promise<void> {
  await interaction.deferReply()

  const matches = await queryUpcomingMatches()

  if (matches.length === 0) {
    await interaction.editReply(
      "❌ 目前沒有待分析的賽程。請先執行 `/match` 拉取賽程。"
    )
    return
  }

  await analyzeAndPost(interaction.client, matches)

  await interaction.editReply(
    `✅ 分析完成！已將 ${matches.length} 場報告送至 <#${process.env.DAILY_PICKS_CHANNEL_ID}>。`
  )
}

async function handleAnalystMatch(
  interaction: ChatInputCommandInteraction
): Promise<void> {
  await interaction.deferReply()

  const matchId = interaction.options.getString("match_id", true)
  const match = await prisma.match.findUnique({ where: { id: matchId } })

  if (!match) {
    await interaction.editReply("❌ 找不到該比賽。")
    return
  }

  const channelId = process.env.DAILY_PICKS_CHANNEL_ID
  if (!channelId) {
    await interaction.editReply("❌ 未設定 DAILY_PICKS_CHANNEL_ID。")
    return
  }

  const channel = (await interaction.client.channels.fetch(channelId)) as TextChannel
  if (!channel) {
    await interaction.editReply(`❌ 找不到頻道 ${channelId}。`)
    return
  }

  await analyzeSingleMatch(match, channel)

  await interaction.editReply(
    `✅ 分析完成！已將 **${match.homeTeam} vs ${match.awayTeam}** 的報告送至 <#${channelId}>。`
  )
}
