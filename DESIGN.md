# TOUCHLINE/LAB Design System

## 1. Identity

A dark research terminal: graph-paper black, warm off-white type, one amber
deterministic accent, one cool teal LLM accent. Surfaces are instrument panels,
not rounded SaaS cards. Numbers are tabular and mono; rules are thin and sharp;
motion reads as a live signal travelling through an instrument, never as
decoration.

The LLM lane is the same terminal after hours: an operations floor of small
line-drawn agent sprites, status rails, scanlines and work packets. It is
continuous but low-amplitude, and it must always distinguish **standby** from
**live execution** in text.

## 2. Tokens

Canonical tokens live in `web/app/globals.css` under `:root` and `.llm-shell`.

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#0a0b0d` | page |
| `--bg-2` | `#0c0e11` | recessed bands |
| `--surface` | `#101318` | panel |
| `--surface-2` | `#14181e` | raised/active panel |
| `--surface-3` | `#191e25` | hover/terminal |
| `--line` | `#232830` | default rule |
| `--line-strong` | `#333b46` | emphasised rule |
| `--text` | `#e9e7e1` | primary |
| `--text-dim` | `#aab0b8` | secondary |
| `--text-muted` | `#8b929b` | explanatory |
| `--text-faint` | `#7b828c` | labels/meta |
| `--accent` | `#f0b429` | deterministic accent |
| `--positive` | `#58c68f` | success |
| `--negative` | `#e06c62` | failure |
| `--info` | `#6aa7d8` | informational |
| `--llm-accent` | `#7cc9c1` | LLM lane accent |
| `--llm-accent-strong` | `#a3e2da` | LLM emphasis |
| `--llm-accent-soft` | `rgba(124,201,193,.10)` | LLM tint |
| `--llm-line` | `rgba(124,201,193,.30)` | LLM rule |
| `--font-sans` | system UI stack | prose and display |
| `--font-mono` | SFMono / Cascadia / Menlo | labels, data, terminal copy |
| `--shell` | `1400px` | content width |
| `--gutter` | `clamp(16px,4vw,48px)` | page gutter |
| `--radius` | `2px` | maximum radius |

New LLM workflow tokens are declared in `.llm-shell`: `--llm-stage`,
`--llm-stage-soft`, `--llm-scan`, `--llm-scan-soft`, `--llm-scan-strong`,
`--llm-live`, `--llm-standby`, `--llm-motion-fast`, `--llm-motion-ambient`.

## 3. Typography

- Display: sans, 800 weight, tight tracking, line-height 0.86–0.95.
- Section title: sans, 600–700, 20–30px, tight tracking.
- Labels: mono, 8.5–10.5px, uppercase, 0.08–0.18em tracking.
- Body: 11.5–13px, 1.55–1.65 line-height, max 65ch.
- All numeric data: mono and `font-variant-numeric: tabular-nums`.
- Never use more than one accent colour in one component. LLM components use
  teal; amber is reserved for deterministic handoff or warning.

## 4. Layout

- Use `.shell` for page width; do not introduce a second max-width container.
- Sections use `.section` + `SectionHeader`; index numbers are part of identity.
- KPI strips and tables are flush grids with 1px gutters, no rounded cards.
- The LLM overview is a 5-column KPI strip over a 2-column body: fixtures
  (wide) + lane state (narrow). At <=1000px it stacks.
- The LLM workflow is a three-stage horizontal floor at desktop:
  `01 Signal desk` (six specialists) → `02 Challenge + synthesis` →
  `03 Pool + risk gate`. At <=1100px it becomes a single vertical sequence.
- Keep optical spacing: section 48–64px, panel 16–24px, micro labels 6–8px.

## 5. Primitives

Existing: `Panel`, `SectionHeader`, `StatusTag`, `HealthPill`, `Metric`,
`MatchCell`, `TableFrame`, `EmptyState`, `DataWarning`.

New LLM primitives:

- `LlmOverviewSection`: KPI strip, next-fixtures table, lane-state facts.
- `LlmAgentWorkflow`: workflow frame, stage rail, stage labels, status copy.
- `AgentSprite`: decorative inline SVG character; `aria-hidden`; unique glyph
  per agent; no emoji and no external image.
- `SignalRail`: stage nodes, moving signal, direction arrows; decorative.
- `WorkPacket`: a moving signal band with a bright core dot between stages; the
  direction is meaningful, the motion is decorative and `aria-hidden`.

States: `standby` (no runs; ambient slow motion), `recorded` (runs exist; faster
sprite pulse and packet travel, text says `runs recorded`, never per-agent live),
`degraded` (status error; motion stops, warning shown), `empty` (no agents;
explicit empty state, no invented roster). All interactive links have hover and
focus-visible states.

## 6. Motion

- GPU properties only: `transform`, `opacity`, `filter`.
- Ambient idle: 5–8s breathing/head-bob/antenna-flicker loops.
- Runs recorded: faster sprite pulse (`--llm-motion-fast`) and 3.6s floor packet
  travel; still no per-agent live claim.
- Meaning: motion shows direction of data and which stage is queued. If there
  are zero agent runs, the page must say `standby`; never imply a live run.
- Signature moment: a teal signal band with a bright core dot crossing the whole
  floor from the specialist desks through challenge/synthesis to the weighted
  pool.
- `prefers-reduced-motion: reduce` disables all animation and packet travel;
  static rail and sprite remain legible.

## 7. Accessibility

- Characters are decorative; agent names and scopes are real text.
- Do not animate layout properties; do not hide content to buy performance.
- Maintain WCAG AA contrast on all labels, including 8.5px mono labels.
- Provide visible focus rings; tables keep captions; status uses text + colour.
- The LLM lane remains read-only and paper-only in all copy.
