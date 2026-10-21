# Football_Pred Mission Control Design System

> Scope: the `web` service (sub-system D), a read-only Next.js dashboard for the football
> betting model. This file is the implementation contract. Every colour, font size, spacing
> value, and component pattern in the dashboard traces back to a token defined here. No
> component is written before this file exists, and no token is used before it is added here.
>
> Loaded references (one sentence): `design-system-architecture.md` (Layer 0, the mandatory
> 7-section structure), `taste-skill.md` (Layer A, the documented default for an operational
> dashboard brief), and `voltagent.md` (Layer B, the user-chosen AI-agent-framework aesthetic:
> void-black canvas, emerald accent, terminal-native). No second Layer A or Layer B style skill
> was loaded, per the stacking rules.

---

## 1. Atmosphere & Identity

A dark mission-control room at 2am, where the only light is the instrument panel telling you
the machine is alive. The canvas is void-black, the data is dense, and a single emerald signal
carries every "power on" moment: a pipeline stage igniting, a heartbeat staying green, a bet
settling into profit. This is not a friendly SaaS dashboard. It is an engineering console that
lets you watch a betting model think, and it earns trust by showing its work, not by decorating
it.

The signature is **the living pipeline**: six stages (`INGEST -> FEATURES -> PREDICT -> BET ->
SETTLE -> RETRAIN`) rendered as a horizontal node chain where the active node glows emerald and
the equity curve extends at its right edge the moment a bet settles. The screen should read like
an instrument panel: quiet chrome, loud data, motion only where the machine actually changes
state.

### 1.1 The three dials

| Dial | Value | Justification |
| --- | --- | --- |
| `DESIGN_VARIANCE` | **4** | Data grids demand alignment; a table that scans cleanly cannot be artsy-chaos. Variance comes from composition (a full-bleed equity curve, a horizontal pipeline chain, left-aligned section headers over right-aligned numerals), not from breaking the grid. Above 4 the tables stop scanning; below 4 the page reads as a generic symmetric admin template. |
| `MOTION_INTENSITY` | **6** | The brief makes motion first-class ("see the system thinking"), but every animation must map to a real state change. 6 is the fluid-CSS tier with spring physics: enough to make a node ignite and a curve extend with weight, without the scroll-hijack choreography (8-10) that this product explicitly forbids. |
| `VISUAL_DENSITY` | **8** | Cockpit density, matching the ui-ux-pro-max `--density 8` target. Tight paddings, hairline dividers instead of a sea of identical rounded cards, and `font-mono` on every number. This is the whole point of a mission-control surface: maximum signal per screen. |

### 1.2 Non-default decisions and their source (anti-flattening self-check)

If this file could describe any generic dark SaaS, it has been flattened. Each non-default
decision below is named with the reference it came from:

| Decision | Value | Source |
| --- | --- | --- |
| Void-black canvas, not "dark grey" | `#050507` | voltagent (Abyss Black) |
| Warm-neutral borders, not cold blue-grey | `#3d3a39` | voltagent (Warm Charcoal) |
| Single emerald accent, used with intent | `#00d992` | voltagent (Emerald Signal Green) |
| Border-weight-as-elevation, not shadow-everywhere | 1px -> 2px -> 3px | voltagent (Depth philosophy) |
| Two named shadow levels only | Ambient Glow + Dramatic Float | voltagent (Level 4 / Level 5) |
| Green signal glow on the active node | `drop-shadow(0 0 2px -> 8px #00d992)` | voltagent (Green Signal Glow) |
| Terminal-native mono for all data | JetBrains Mono + tabular numerals | taste-skill (VISUAL_DENSITY 8) + ui-ux-pro-max (Terminal CLI Monospace) |
| Hairline dividers over card boxes | `1px --border-hairline` | taste-skill (density > 7 bans generic card containers) |
| Motion only on real state changes | number roll, node ignition, curve extension | taste-skill (motion must be motivated) |

---

## 2. Color

Dark-only by brief. The product is a mission-control terminal; a light mode is a non-goal
(voltagent: "Don't use bright or light backgrounds as primary surfaces"). The palette is
strictly emerald + warm neutrals on near-black. Warm colours (amber, coral) appear only as
semantic status, never as decoration.

### 2.1 Palette

| Role | Token | Value | Usage |
| --- | --- | --- | --- |
| Surface/void | `--surface-void` | `#050507` | Page canvas (Abyss Black) |
| Surface/base | `--surface-base` | `#101010` | Panels, table rows (Carbon Surface) |
| Surface/raised | `--surface-raised` | `#17171b` | Popovers, modals, hovered rows |
| Border/default | `--border-default` | `#3d3a39` | Panel containment (Warm Charcoal, the signature) |
| Border/hairline | `--border-hairline` | `#232326` | Row dividers, dense separators |
| Text/primary | `--text-primary` | `#f2f2f2` | Numerals, headings (Snow White) |
| Text/secondary | `--text-secondary` | `#b8b3b0` | Labels, secondary text (Warm Parchment) |
| Text/tertiary | `--text-tertiary` | `#8b949e` | Metadata, axis ticks (Steel Slate) |
| Accent/signal | `--accent-signal` | `#00d992` | System-active: pipeline ignition, heartbeat, focus ring, active tab, primary data series |
| Accent/mint | `--accent-mint` | `#2fd6a1` | Readable accent variant: CTA text on dark, and profit-positive values |
| Status/neg | `--status-neg` | `#fb565b` | Loss, failed run, stale data |
| Status/warn | `--status-warn` | `#ffba00` | Queued, ageing, degraded |
| Status/info | `--status-info` | `#4cb3d4` | Informational callouts |

`--surface-raised` and `--border-hairline` are the only two tokens derived beyond the voltagent
source set: the raised shade is required for popovers and hovered rows, and the hairline is
required because density 8 puts a divider on every table row where the full Warm Charcoal
containment border would be too loud. Both are documented extensions, not freestyle additions.

### 2.2 Rules

- **One accent, used with intent.** `--accent-signal` is reserved for system-active states and
  the primary data series. It is never a background fill and never decorative.
- **Colour is never the only carrier of meaning.** Every semantic colour is paired with a second
  channel:
  - Profit: `--accent-mint` **and** a `+` sign **and** an up-arrow glyph (Lucide `arrow-up`).
  - Loss: `--status-neg` **and** a `-` sign **and** a down-arrow glyph (Lucide `arrow-down`).
  - Running: `--accent-signal` **and** a spinner glyph **and** the label "running".
  - Success: `--accent-mint` **and** a check glyph (Lucide `check`) **and** the label "success".
  - Failed: `--status-neg` **and** an alert glyph (Lucide `alert-triangle`) **and** the label "failed".
  - Never-tracked: `--text-tertiary` **and** a dash glyph (Lucide `minus`) **and** the label "never tracked".
- **Never introduce a colour not in this table.** Extend the table first, then use it.
- **No pure `#000000` and no pure `#ffffff`.** The canvas is `#050507`; the brightest text is
  `#f2f2f2`.

---

## 3. Typography

Three families, justified: two are the voltagent signature (system-ui headings + Inter body),
the third is the terminal data voice this product requires.

### 3.1 Font stack

- **Display / headings**: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (native
  authority, zero download, instant render).
- **Prose / body**: `Inter, system-ui, sans-serif` (help text, empty states, the CLV note).
- **Data / UI / mono**: `"JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace` (the
  terminal voice; every number, label, and table cell).

### 3.2 Scale

| Level | Size | Weight | Line height | Tracking | Font | Usage |
| --- | --- | --- | --- | --- | --- | --- |
| Display | 28px / 1.75rem | 600 | 1.1 | -0.02em | mono | Header headline number (bankroll) |
| H1 | 20px / 1.25rem | 600 | 1.2 | -0.01em | system-ui | Page title |
| H2 | 16px / 1rem | 600 | 1.3 | 0 | system-ui | Section headers |
| H3 | 14px / 0.875rem | 600 | 1.4 | 0 | system-ui | Card titles |
| Body | 14px / 0.875rem | 400 | 1.5 | 0 | Inter | Prose, help text |
| Data | 13px / 0.8125rem | 400 | 1.4 | 0 | mono | Table cells, values |
| Caption | 12px / 0.75rem | 500 | 1.4 | 0.02em | mono | Labels, metadata |
| Overline | 11px / 0.6875rem | 600 | 1.3 | 0.08em | mono | Uppercase section labels |

### 3.3 Rules

- **Tabular numerals are mandatory.** Every price, stake, probability, money value, and count
  carries `font-variant-numeric: tabular-nums` and `font-feature-settings: "tnum" 1`. Digits
  must never jitter when a value updates.
- Body text never below 12px. Table cells live at 12-13px; prose at 14px.
- Headings use compressed line heights (1.1-1.4) for dense, authoritative blocks.
- Uppercase appears only as the Overline level, always with wide tracking. Never on headings.
- No serif anywhere. The system is geometric sans + monospace only.

---

## 4. Spacing & Layout

### 4.1 Base unit

All spacing derives from a base of **4px**. Density 8 keeps the scale tight.

| Token | Value | Usage |
| --- | --- | --- |
| `--space-1` | 4px | Tight: icon-to-label, cell padding |
| `--space-2` | 8px | Compact: list items, inline groups |
| `--space-3` | 12px | Default: table cell padding, form field padding |
| `--space-4` | 16px | Standard: panel padding, input height context |
| `--space-5` | 20px | Comfortable: section inner spacing |
| `--space-6` | 24px | Generous: panel padding (default) |
| `--space-8` | 32px | Separated: between panel groups |
| `--space-10` | 40px | Sections within a tab |
| `--space-12` | 48px | Major section breaks |
| `--space-16` | 64px | Page-level vertical rhythm |

### 4.2 Grid

- Max content width: **1440px**, centred.
- Column system: 12-column, 16px gutter at desktop, 12px gutter at mobile.
- Breakpoints: sm 640px, md 768px, lg 1024px, xl 1280px, 2xl 1536px.
- The shared header is a single sticky row at `lg` and above; it collapses to a two-row stack
  below `md`.

### 4.3 Rules

- No magic numbers. Every spacing value maps to a token.
- Asymmetric spacing is intentional: the equity curve is full-bleed within the content column,
  the pipeline chain spans the full width, and section headers are left-aligned while their
  numerals are right-aligned. This is documented, not accidental.
- Below `md`, every multi-column layout collapses to a strict single column (`w-full`, `px-4`).

---

## 5. Components

Primitives are defined before implementation. Each is assembled from the voltagent component
anatomy and adapted to this product. Every primitive is exercised in a component showcase at
375 / 768 / 1280px across all states before product screens are composed.

### Panel

- **Structure**: `<section>` with a header row (title + optional action) and a body slot.
- **Variants**: `default` (1px `--border-default`), `accent` (2px `--accent-signal`, for the
  active pipeline panel).
- **Spacing**: `--space-6` padding, `--space-4` header-to-body gap.
- **States**: default, hover (border shifts toward `--accent-signal` at low opacity), focus-within
  (focus ring), loading (skeleton rows matching final shape), empty (composed empty state with a
  Lucide glyph and a one-line explanation), error (inline message with `--status-neg` + alert glyph).
- **Accessibility**: `<section>` with `aria-labelledby` pointing at the header title.
- **Motion**: none on entry. Border colour transition on hover is 150ms ease-out.

### DataTable

- **Structure**: `<table>` with a sticky `<thead>`, `--border-hairline` row dividers, and
  right-aligned numeric columns.
- **Variants**: `default`, `dense` (12px cells), `highlight-new` (a row that just arrived).
- **Spacing**: `--space-3` cell padding, `--space-2` header padding.
- **States**: default, hover (row background to `--surface-raised`), focus (row focus ring),
  loading (skeleton rows), empty (empty state), error (inline error row).
- **Accessibility**: real `<table>` semantics, `<th scope="col">`, `aria-sort` on sortable
  columns, keyboard-navigable rows.
- **Motion**: a new row plays a one-shot background highlight (`--surface-raised` -> transparent)
  over 600ms. No other row motion.

### StatusPill

- **Structure**: inline-flex pill with a Lucide glyph, a text label, and a colour token.
- **Variants**: `running`, `success`, `failed`, `never-tracked`, `queued`, `ageing`, `stale`,
  `overdue`, `unavailable`.
  (`stale` is a documented extension: Section 2.2 already assigns stale data to `--status-neg`,
  and the pipeline needs a distinct stale state separate from `ageing`; it pairs `--status-neg`
  with a `TimerOff` glyph and the label "stale". `overdue` is a stalled scheduler — a job whose
  `next_run_time` passed without firing — and pairs `--status-warn` with an `AlarmClock` glyph
  and the label "overdue". `unavailable` is a missing `/ops/*` source, distinct from
  "never tracked"; it pairs `--status-warn` with a `CloudOff` glyph and the label "unavailable".)
- **Spacing**: `--space-1` vertical, `--space-2` horizontal.
- **States**: static only (status is data, not interactive).
- **Accessibility**: the text label is always present; colour is supplementary. `role="status"`
  where the pill reflects a live value.
- **Motion**: none. A status pill does not animate; the pipeline node it belongs to does.

### PipelineNode / PipelineFlow

- **Structure**: `PipelineFlow` is a horizontal flex chain of six `PipelineNode`s connected by
  hairline connectors. Each node carries a stage name, a last-action time, and a `StatusPill`.
- **Variants**: `idle`, `active`, `success`, `failed`, `never-tracked`.
- **Spacing**: `--space-4` node padding, `--space-6` connector length.
- **States**: default, active (2px `--accent-signal` border + signal glow), success (mint check),
  failed (`--status-neg` + alert glyph), never-tracked (tertiary dash).
- **Accessibility**: an ordered list (`<ol>`) of stages; each node exposes stage name, status
  text, and last-action time to screen readers. The chain is also rendered as a table fallback
  (stage, status, last action).
- **Motion**: the signature interaction (Section 6.2).

### KpiTile / BulletChart

- **Structure**: a tile with a label, a large tabular numeral, and a bullet bar showing the value
  against a target range.
- **Variants**: `money`, `percent`, `count`.
- **Spacing**: `--space-4` padding, `--space-2` label-to-value gap.
- **States**: default, loading (skeleton numeral), empty (dash glyph + "no data").
- **Accessibility**: the numeral and target are always visible as text; the bullet bar is
  supplementary. A one-row table fallback accompanies the KPI strip.
- **Motion**: the numeral rolls on change (Section 6.1).

### ChartFrame

- **Structure**: a wrapper that renders a chart and, beneath it, a toggleable accessible table
  fallback plus a one-line trend summary.
- **Variants**: `line` (equity curve), `bullet` (KPI), `timeline` (ingestion runs).
- **Spacing**: `--space-6` padding, `--space-4` chart-to-fallback gap.
- **States**: default, loading (skeleton chart), empty (empty state), error (inline error).
- **Accessibility**: **every chart has a visible table fallback** (a real `<table>` of the
  underlying points) plus a short summary. Keyboard: focus reveals point values; the fallback
  toggle is a real button.
- **Motion**: the equity curve extends at its right edge on a new settlement (Section 6.2).

### HeartbeatDot

- **Structure**: a small dot with a Lucide glyph and a freshness label.
- **Variants**: `healthy` (mint), `degraded` (`--status-warn`), `stale` (`--status-neg`).
- **Spacing**: `--space-1` gap to label.
- **States**: static; the colour and label update with the heartbeat.
- **Accessibility**: `role="status"` with an `aria-label` carrying the freshness in words.
- **Motion**: a slow, subtle pulse only while `healthy` and only when motion is allowed
  (Section 6.3). No pulse under reduced motion.

### TabBar

- **Structure**: two tabs (`Performance`, `Technical`) with an active indicator.
- **Variants**: none.
- **Spacing**: `--space-3` tab padding.
- **States**: default, hover, active (indicator in `--accent-signal`), focus (focus ring).
- **Accessibility**: `role="tablist"` / `role="tab"` / `role="tabpanel"`, arrow-key navigation.
  The two tabs are real routes (`/performance`, `/technical`), so each tab is an anchor and
  the page's `<main>` carries `role="tabpanel"` with `aria-labelledby` pointing at the active
  tab; arrow keys move focus between tabs.
- **Motion**: the active indicator slides between tabs over 200ms ease-in-out.

### LogLine

- **Structure**: a mono line with a level tag, a timestamp, and the message.
- **Variants**: `debug`, `info`, `warning`, `error`.
- **Spacing**: `--space-1` vertical, `--space-3` horizontal.
- **States**: default, hover (background to `--surface-raised`).
- **Accessibility**: the level is a text tag, not colour alone.
- **Motion**: none. The stream scrolls; lines do not animate in.

### Note

- **Structure**: a `<p>` carrying the Info glyph and one caption sentence. This is the
  shared caption primitive for both tabs (Performance and Technical): every window label,
  disclosure and caveat renders through it, so the two tabs read as one product.
- **Variants**: none. The Info glyph is always present — one rule, no per-site variation.
- **Spacing**: `--space-2` glyph-to-text gap. The note carries no padding of its own; it
  sits flush with the panel body's content edge (`--space-6`), and the surrounding
  container owns the vertical rhythm (`--space-3` gaps).
- **Placement**: a Note sits above the content it describes.
- **States**: static only.
- **Accessibility**: the glyph is `aria-hidden`; the sentence is plain text.
- **Motion**: none.

### SearchInput

A labelled `<input type="search">` plus a visible scope line and a clear control. Used by the
row-heavy tables on both tabs.

- Tokens: `text-body` input, `text-caption text-text-tertiary` scope line, `border-border-default`
  border, `rounded-md`, `px-2 py-1`, `bg-surface-base`, focus ring on `--accent-signal`.
- The scope line is mandatory and must name the fetched row count: `searches the N rows in this window`.
- The clear control (Lucide `X`) renders only when the value is non-empty and carries
  `aria-label="Clear search"`.
- Never submits a form, never navigates, never fetches.

### RevealFooter

The footer for a revealing table: one honest count sentence on the left, the reveal controls on
the right.

- Left, `text-caption text-text-tertiary tnum`, inside `aria-live="polite"`:
  `{base} · {shown} of {matching} shown`, with ` · matching "{query}"` appended when filtered.
- Right: `Expand +10` (primary), `Show all N` (secondary), `Collapse` (always rendered; disabled
  until the reveal has grown past its initial size). Buttons reuse the existing footer button
  class from `BetsTable`. The footer's controls are action buttons and carry no `aria-expanded`;
  the count sentence already announces changes via `aria-live`.
- Both expand controls are disabled when everything is already shown.
- No entrance animation (see §6.3).

---

## 6. Motion & Interaction

Motion exists to show the machine changing state. Nothing else moves.

### 6.1 Timing

| Type | Duration | Easing | Usage |
| --- | --- | --- | --- |
| Micro | 100-150ms | ease-out | Button press, toggle, hover border |
| Standard | 200-300ms | ease-in-out | Tab switch, panel open, indicator slide |
| Emphasis | 400-600ms | cubic-bezier(0.16, 1, 0.3, 1) | Pipeline node ignition, curve extension |
| Number roll | 400ms | spring (stiffness 100, damping 20) | KPI and bankroll value changes |

### 6.2 Signature interaction

**The living pipeline.** When a pipeline stage advances, the newly-active node's border
transitions from `1px --border-default` to `2px --accent-signal`, its label shifts to
`--accent-signal`, and a green signal glow (`drop-shadow(0 0 2px #00d992)` growing to
`drop-shadow(0 0 8px #00d992)`) pulses once over 600ms while the previous node settles to a mint
success check; at the same moment, when a bet settles, the equity curve appends its new point and
draws the final segment in over 500ms with the new point marker scaling from 0 to 1.

**Reduced-motion fallback.** Under `prefers-reduced-motion: reduce`, the glow pulse, the
draw-in, and the marker scale are all removed. The node's border and colour change apply
instantly, and the equity curve re-renders with the new point already present. No information is
lost: the stage status is still carried by the glyph and the text label, and the new curve point
is still visible as a static marker.

### 6.3 Rules

- **Animate only real state changes**: number roll on change, a brief row highlight on a new bet,
  pipeline node ignition, curve extension at the right edge, heartbeat pulse while healthy.
- **Forbidden slop**: scroll-triggered section entrances, hover-transition-everywhere, decorative
  micro-animations on non-interactive elements, infinite loops with no informational purpose.
- **GPU-composited properties only**: `transform`, `opacity`, `filter`. Never animate `top`,
  `left`, `width`, `height`, or any layout property.
- **`prefers-reduced-motion` is respected everywhere.** Every animation above collapses to an
  instant final state under reduced motion.
- **No `window.addEventListener("scroll", ...)`.** If scroll-driven motion is ever needed, use
  `IntersectionObserver` or CSS scroll-driven animations. (This product does not use scroll
  motion.)

---

## 7. Depth & Surface

### 7.1 Strategy

**Mixed, border-first.** Depth is communicated primarily by border weight and colour, not by
shadows. The standard `1px --border-default` border IS the elevation; a heavier border or a
switch to `--accent-signal` communicates importance more than a shadow does. Shadows appear only
at the two named levels below.

| Level | Treatment | Usage |
| --- | --- | --- |
| Flat (0) | No border, no shadow | Page canvas (`--surface-void`), inline text |
| Contained (1) | `1px solid --border-default`, no shadow | Panels, table rows, the header bar |
| Emphasized (2) | `3px solid --border-default`, no shadow | Large interactive containers |
| Accent (3) | `2px solid --accent-signal`, no shadow | Active pipeline node, selected row |
| Ambient Glow (4) | `rgba(92, 88, 85, 0.2) 0px 0px 15px` | Elevated panels, hover lift |
| Dramatic Float (5) | `rgba(0, 0, 0, 0.7) 0px 20px 60px` + `rgba(148, 163, 184, 0.1) 0px 0px 0px 1px inset` | Modals, popovers, maximum-elevation content |

### 7.2 Decorative depth

- **Green signal glow**: `drop-shadow(0 0 2px #00d992)` animating to `drop-shadow(0 0 8px #00d992)`
  on the active pipeline node. This is the one decorative glow in the system, and it is tied to a
  real state change.
- **Warm containment lines**: the warm tone of `--border-default` (`#3d3a39`) against the cool
  black canvas is the signature warmth. Do not replace it with a cold blue-grey.
- **Hairline dividers**: `1px --border-hairline` separates dense table rows without the weight of
  full containment borders.

### 7.3 Rules

- Depth comes from border treatment first. Shadows are reserved for Levels 4-5 only.
- No pure-black drop shadows on the dark canvas; the Dramatic Float shadow is the only heavy
  shadow and it is reserved for modals and popovers.
- Border radius: 4px for small inline elements, 6px for buttons and interactive elements, 8px for
  content panels. Pills (9999px) only for status tags and badges. No radius larger than 8px on
  content panels.

---

## 8. React Dev Tooling Gate

The `web` service ships React (Next.js App Router). Three dev-only tools are installed before any
UI implementation, and all three are gated behind `process.env.NODE_ENV === 'development'` so
they never reach production:

- **react-grab** (`npx grab@latest init`): UI element to AI source context.
- **react-doctor** (`npx react-doctor@latest install`): agent-skill install plus static scan.
- **react-scan** (`npx react-scan@latest init`): render highlighter.

Verification: grep the entry file (`app/layout.tsx`) for `react-grab` and `react-scan`, and
confirm each sits behind a `NODE_ENV === 'development'` check. If a tool is not gated, fix the
gate before proceeding. The user opts out, not in.

---

## 9. Validation

After every component implementation, check it against this contract:

- [ ] Every colour references a token from Section 2. No raw hex outside this file.
- [ ] Every font size matches the Section 3 scale. No arbitrary sizes.
- [ ] Every spacing value is a multiple of `--space-1` (4px). No magic numbers.
- [ ] Every numeric cell carries tabular numerals.
- [ ] Every interactive element has default, hover, active, and focus states.
- [ ] Every chart has a visible table fallback.
- [ ] Every semantic colour is paired with a glyph, sign, or label.
- [ ] Depth treatment matches the Section 7 strategy.
- [ ] Motion follows the Section 6 timing table and animates only real state changes.
- [ ] No emojis anywhere (code, markup, alt text, UI). Icons come from Lucide only.
- [ ] The component passes visual QA at 375 / 768 / 1280px across all required states.

**What counts as a contract violation:**

- A raw hex value, an arbitrary px value, or an ad-hoc font size that bypasses a token.
- A new colour, spacing value, or component pattern used before it is added to this file.
- A chart without a table fallback, or a semantic state carried by colour alone.
- An animation on a non-interactive element, a scroll-triggered entrance, or a hover that changes
  nothing.
- An emoji used as an icon.
- A numeric cell without tabular numerals.

A surface that is bug-free but flat (generic dark SaaS, no signature moment, no material depth)
is also a failure, not a finish.

---

## 10. Technical additions

Added by the TECHNICAL tab increment (2026-10-15). These patterns extend the primitives in
Section 5; every value traces to a token already defined above. No new colour, type size or
spacing value is introduced.

### LogLevelFilter

- **Structure**: a `<nav aria-label="Log level filter">` of links (`all`, `debug`, `info`,
  `warning`, `error`, `critical`). The active link carries `aria-current="true"`.
- **Spacing**: `--space-1` gap, `--space-2` horizontal padding, `--space-1` vertical.
- **States**: default (`--text-secondary`), hover (`--text-primary`), active
  (`--accent-signal` text plus a 1px `--accent-signal` underline), focus (global focus ring).
- **Accessibility**: real links; the active filter is carried by `aria-current` and the
  underline, not colour alone.
- **Motion**: none.

### LogAutoRefresh

- **Structure**: a caption (`auto-refresh 15s · live|paused`) plus a real `<button>` with a
  Pause/Play glyph and a `pause`/`resume` label; `aria-pressed` mirrors the paused state.
- **Spacing**: `--space-2` gap, `--space-2` horizontal padding, `--space-1` vertical.
- **States**: default, hover (border toward `--accent-signal` at low opacity), focus ring.
- **Motion**: 150ms ease-out border transition only.

### LogViewport

- **Structure**: an `<ol>` of `LogLine`s inside a bounded viewport (`max-h-96` = 24rem, a
  multiple of the 4px base) with internal scrolling and `--border-hairline` dividers.
- **Accessibility**: the level is a glyph plus the raw level text; the message is escaped
  text. The tail window and the active filter are stated above the viewport.
- **Motion**: none; lines do not animate in.

### TimelineList

- **Structure**: an `<ol>` with `--border-hairline` dividers; each item carries a
  `StatusPill`, mono identifiers, and tabular timestamps. Used by the ingestion runs
  timeline and the model version timeline. It is a list, not a chart: no chart fallback.
- **Spacing**: `--space-2` vertical per item, `--space-3` horizontal gap.
- **Motion**: none.

### MetricGrid

- **Structure**: a `<dl>` grid of metric cells; each cell is an Overline key over a Data
  value with tabular numerals. A metric the target does not track renders as `—` (never 0).
- **Spacing**: `--space-4` column gap, `--space-1` row gap.
- **Motion**: none.

---

## 11. Provenance: ui-ux-pro-max queries

The following queries were run against `~/.agents/skills/ui-ux-pro-max/scripts/search.py` (the
working path; the skill's own `SKILL.md` prints a Claude-only path that does not work here). Note
that `--stack` and `--domain` are mutually exclusive in this CLI, so domain queries were run
without `--stack`.

| Query | Domain | Key guidance returned |
| --- | --- | --- |
| `line chart time series equity curve` | chart | Trend-over-time -> **Line Chart** (not candlestick; candlestick is for financial audiences only). A11y fallback: visible data table plus a concise trend summary. Never distinguish series by hue alone. |
| `bullet chart KPI comparison gauge` | chart | Performance-vs-target -> **Bullet Chart** for 3-10 KPIs in a grid; a gauge is too large. Label every range and target with text; colour is supplementary. |
| `workflow pipeline node graph process stages` | chart | Sequential multi-stage process -> **Funnel / Process Map**; keep stage names and values visible and distinguish stages with text and boundaries, not only a gradient. A11y fallback: linear stage table plus a summary. |
| `dark terminal dashboard mission control` | color | RPA / Automation Dashboard palette: dark terminal + running green + failed red + queued amber. Confirms the emerald-on-near-black direction with semantic status colours. |
| `monospace tabular numerals data table` | typography | **Terminal CLI Monospace** (JetBrains Mono, single family, strict 12/14/16 sizes, line height 1.2x) and **Dashboard Data** (Fira Code + Fira Sans). Confirms mono for data, sans for labels. |
| `dashboard density information hierarchy` | ux | Colour-only is a High-severity a11y issue (use icons/text in addition to colour); use a consistent modular type scale (12 14 16 18 24 32), never arbitrary sizes. |
| `dark tech terminal developer` | style | **Dark Mode (OLED)** and **Cyberpunk UI** both confirm dark-only, monospace, visible focus, and reduced-motion support. The cyberpunk neon/glitch treatment is explicitly rejected as too loud for a mission-control surface. |
| `server components data fetching` | stack (nextjs) | Fetch data in Server Components; keep components server by default; push Client Components down to interactive leaves. Confirms the server-side-only fetch architecture. |

---

## Performance additions

The second performance increment (sections f, g and h of the spec) adds three composed
patterns. **No new colour, type, spacing, radius or motion token was introduced**; every
value below traces to Sections 2-7.

### MatchesPredictionsTable (section f)

- **Structure**: a window note (Info glyph + Caption prose) above a `DataTable` of
  `/predictions` rows joined in memory to `/bets` on `(match_id, target, outcome)`.
- **Columns**: kickoff, league, match, target, outcome, prob, implied, edge, bet state,
  bet odds, bet stake. Every numeric cell is right-aligned with tabular numerals.
- **States**: default, unavailable (`/predictions` or `/bets` missing), empty (no
  predictions). The window note always names the fetched window and the display order; a
  full page is never stated as a total.
- **Semantics**: the bet column carries the words "placed" or "no bet"; the edge cell
  carries its sign and colour. Colour is never the sole carrier.

### ResultsTable (section g)

- **Structure**: a window note above a `DataTable` of `/results` rows.
- **Columns**: kickoff, league, match, score, confirmed, payout, source, confirmed at.
- **States**: default, unavailable, empty.
- **Semantics**: `confirmed` and `payout_confirmed` render as `StatusPill`s — a glyph plus
  the words "confirmed"/"unconfirmed" and "payout confirmed"/"payout unconfirmed" — never
  colour alone.

### ClvCard (section h)

- **Structure**: a five-cell metric grid (the KpiTile anatomy: Overline label over an H1
  tabular numeral) above the champion identity line and three mandatory prose notes.
- **States**: default, unavailable (`/models` missing), no champion 1x2 version, no
  metrics reported.
- **Semantics**: the notes state on screen that CLV is the only evidence available before
  wins and losses accumulate (naming `clv_n`), that no CLV time series and no per-bet CLV
  exist in v1, and that the ledger's execution price never enters CLV. No trend line is
  drawn.
