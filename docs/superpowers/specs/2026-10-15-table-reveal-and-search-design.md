# Table reveal and search (dashboard refinement)

> Date: 2026-10-15
> Scope: the read-only Next.js dashboard (`web`) only. No change to the API, the model, the
> ledger, the scheduler, or any write path. No schema change, no migration, no new dependency.
> Related: `docs/superpowers/specs/2026-10-15-dashboard-design.md` (the dashboard this
> refines), `web/DESIGN.md` (the implementation contract), `2026-10-15-ops-readonly-endpoints-design.md`.

---

## 1. Context and problem

Every table **except** the bets table renders its **entire fetched window** at once, so on the
real host three Performance tables and one Technical table each open as a 200-row wall.

The bets table is the exception: it was built as a Client Component with `PAGE_SIZE = 25` and
Prev/Next buttons. So the dashboard currently has **two different idioms** for the same
problem ("too many rows"), which reads as two products rather than one instrument panel.

Requested change:

- show **10 rows by default**, with an **expand** control that reveals **10 more per click**,
  so a huge table never dumps everything on screen;
- add a **search box** for the matches x predictions table and the results table.

## 2. Decision (scope) - all five row-heavy tables adopt ONE pattern

| # | Table | Component | Tab | Note |
| --- | --- | --- | --- | --- |
| 1 | All bets | `tables/BetsTable.tsx` | Performance | Prev/Next pagination is **removed**; reveal replaces it |
| 2 | Signal vs execution | `tables/SignalVsExecutionTable.tsx` | Performance | |
| 3 | Matches x predictions | `tables/MatchesPredictionsTable.tsx` | Performance | |
| 4 | Results | `tables/ResultsTable.tsx` | Performance | |
| 5 | Ingestion runs timeline | `technical/IngestionRunsTimeline.tsx` | Technical | |

Rationale for folding in the bets table: replacing Prev/Next removes the second idiom, and
search plus reveal is strictly more useful than paging 25 at a time through 250 bets. The
small tables (scheduler: 6 jobs; DB size: ~10 counts; model timeline: 2 versions) are
**out of scope** - they cannot reach 10 rows.

## 3. Decision (architecture) - client-side, in memory

Each of the five tables becomes a Client Component that receives the **already-fetched
window** as props and owns two pieces of state: the query string and how many rows are
visible. Filtering and slicing happen in the browser, in memory.

**Why not server-side (`?q=` searchParams) or a hybrid:**

- the API has **no search** and must not be modified, so a server-side search could not
  search beyond the window either - the only advantage of the round trip does not
  materialise;
- a round trip per keystroke (or a submit button) makes the control feel dead;
- two mechanisms for one control is complexity without benefit at this scale (YAGNI).

**The iron rule is preserved.** The filtering runs on data the server already fetched; the
browser still never calls the API. The existing visual-QA check that counts browser-to-API
requests must stay at zero.

**Load-bearing claim, verified against the official docs.** The pages auto-refresh every 60
seconds (Performance, `RefreshOnInterval`) or 15 seconds (Technical log stream,
`LogAutoRefresh`) via `router.refresh()`. The Next.js `use-router` reference states that a
refresh makes a new server request, re-renders Server Components, and that "the client will
merge the updated React Server Component payload **without losing unaffected client-side
React (e.g. `useState`) or browser state (e.g. scroll position)**". Therefore a refresh does
**not** reset the reveal count, the query, or the scroll position. Without this property the
whole approach would be unusable, so it is an explicit acceptance criterion, not an
assumption.

**Trade-offs accepted, stated honestly:**

1. **Search covers the fetched window only** (200 rows), not the whole table in the database.
   The control must say so on screen (section 4).
2. **The window's rows are serialised to the client.** This is not new - the bets table
   already shipped 200 bets to the client - but it is now true of five tables, so the
   Performance gate still applies: Lighthouse 100 in every category, measured against a
   production build with real Playwright Chromium.

## 4. The honesty contract (non-negotiable)

This refinement can easily introduce a lie, so the rules are explicit and each one is pinned
by a test.

1. **Window sentences stay exactly as they are.** Each table's `<Note>` window disclosure
   describes the *fetch* window and is unchanged by this work. No sentence is reworded,
   removed, or softened.
2. **The reveal never silently changes a derived count.** The slice happens only at the
   `DataTable` boundary, so the array the counts are computed from stays whole by default
   (`MatchesPredictionsTable` computes its join counts from `rows` at lines 115-116; that
   array must remain the full window). If a count is instead recomputed over the filtered
   set, the sentence **must name that base** (rule 3). A silently re-based count is exactly
   the failure mode this rule exists to prevent.
3. **When a filter is active, the sentence names its base.** A bare "198 of these have no
   place in the ledger" is unreadable once the user has filtered to one visible row, and
   silently recomputing it over the filtered set would be worse. So:
   - no filter: `198 of the 200 fetched rows have no place in the ledger; 2 matched a placed bet.`
   - filter active: `of the 12 rows matching "arsenal" in this window, 11 have no place in the ledger; 1 matched a placed bet.`
4. **The qualification from the truncation fix is preserved.** The "fetched bets window is
   not the whole ledger" caveat (`isTruncated(bets) || !bets.newestFirst`) must survive any
   rewording of the join summary.
5. **The search states its scope on screen.** Next to the input: "searches the N rows in this
   window" (N = the fetched count), never a bare placeholder that implies the whole table.
6. **A revealed count is never stated as a total.** The footer names both numbers, e.g.
   `showing 10 of 200 rows in this window` - "10" is never allowed to read as the window.
7. **Nothing else changes.** No new counter, no new field, no new route, no fabricated number.

## 5. Primitives

Three new building blocks. Per the Design System Gate they are documented in `web/DESIGN.md`
**section 5 (Components)** - alongside `Panel`, `DataTable`, `StatusPill`, `Note` - **before**
any component uses them. They are shared by both tabs, so section 5 is their home, not the
tab-specific `## Performance additions` / `## 10. Technical additions` sections.

### 5.1 `useRowReveal` (hook, `web/lib/use-row-reveal.ts`)

A pure, testable hook. No DOM, no fetch.

```ts
export const REVEAL_INITIAL = 10;
export const REVEAL_STEP = 10;

export interface RowReveal<T> {
  query: string;
  setQuery: (next: string) => void;
  clear: () => void;
  /** rows matching the query, in the caller's order, never sliced for the counts */
  filtered: T[];
  /** the slice to hand to <DataTable rows={...} /> */
  shown: T[];
  visible: number;
  canExpand: boolean;
  expand: () => void;
  expandAll: () => void;
  collapse: () => void;
  isFiltered: boolean;
}

export function useRowReveal<T>(
  rows: T[],
  matches: (row: T, query: string) => boolean,
  options?: { initial?: number; step?: number },
): RowReveal<T>;
```

Behaviours that must be tested:

- initial `visible` is 10 (or `rows.length` when fewer);
- `expand()` adds exactly 10, clamped to `filtered.length`;
- `setQuery()` **resets `visible` to the initial 10**;
- `matches` is called with the **trimmed, lowercased** query, and the caller lowercases the
  fields it compares; an empty or whitespace-only query matches every row;
- `filtered` is never sliced - it is the full matching set, so window counts stay correct;
- when the `rows` prop changes (a 60-second refresh), `visible` is **clamped** to the new
  `filtered.length` and never exceeds it;
- `canExpand` is false exactly when `visible >= filtered.length`;
- `expandAll()` sets `visible = filtered.length`; `collapse()` returns to the initial 10.

### 5.2 `SearchInput` (`web/components/ui/SearchInput.tsx`)

- A labelled text input (`<label>` + `id`, or `aria-label`), type `search`.
- A visible scope line beside or beneath it: `searches the N rows in this window`.
- A clear control (an `X` glyph button, `aria-label="Clear search"`) shown only when non-empty.
- No debounce is needed (in-memory filtering over <=200 rows).
- Never submits a form, never navigates, never fetches.

### 5.3 `RevealFooter` (`web/components/ui/RevealFooter.tsx`)

- Left: the honest count sentence from the caller (e.g. `showing 10 of 200 rows in this window`).
- Right: `Expand +10` (primary) and `Show all N` (secondary), plus `Collapse` once expanded.
  `Expand` and `Show all` are disabled/hidden when `canExpand` is false.
- One button style, reused from the existing footer button class in `BetsTable`.
- `aria-expanded` on the expand control; the count sentence is an `aria-live="polite"` region so
  a screen reader hears the new count after a click.
- No entrance animation of any kind (the design contract bans scroll/entrance animation).

**"Show all N" is deliberate, not scope creep.** The bets table's Prev/Next let a user reach
the end of the list in a few clicks; reveal-only would make row 199 take 19 clicks. Search
covers the "find a specific row" case, and `Show all` restores the "get to the end" case in
one click. If this is unwanted it is a one-line removal.

## 6. Behaviour

- Default: the first **10** rows of the window.
- `Expand +10` per click, until the filtered set is exhausted.
- Search semantics per table (case-insensitive substring over these fields):

| Table | Searchable fields |
| --- | --- |
| All bets | home team, away team, league code, target, outcome, status |
| Signal vs execution | home team, away team, league code, outcome |
| Matches x predictions | home team, away team, league code, target, outcome, bet presence (`placed` / `no bet`) |
| Results | home team, away team, league code, source, score (`2-1`) |
| Ingestion runs timeline | job name, status, error text |

- Searching **resets** the reveal to 10; clearing the query also resets the reveal to 10 (it
  does not reveal the whole window).
- No match: the table's existing `EmptyState` renders with an honest reason
  (`No row in this window matches "xyz"`), never a generic "no data" that would read as an
  empty table.
- Existing empty and unavailable states are unchanged: a window with zero rows, and every
  `... unavailable` / `the API did not return ...` state, behave exactly as today.

## 7. Interaction with the auto-refresh

The pages re-render server-side every 60 s / 15 s. Three rules follow from that, all tested:

1. `visible` is clamped to the new filtered length (the window can shrink: e.g. the bets
   window shifts as `n_bets` grows).
2. An active query is re-applied to the new data (matches can appear and disappear).
3. Every derived count is recomputed from the **new** window, never carried over from the old
   props.

Client state (query, reveal count) and scroll position survive the refresh, per section 3.

## 8. Motion and accessibility

- **No new animation.** Revealing rows is not a state change of a value; entrance animations
  are banned by the design contract. Rows simply appear.
- `prefers-reduced-motion` therefore needs nothing new, and the existing reduced-motion
  behaviour must not regress.
- Keyboard: the search input and every footer button are reachable and operable; the clear
  control has an accessible name; focus is not stolen when rows appear.
- Colour is never the sole carrier of meaning (unchanged from the base dashboard).
- The table keeps its `<caption class="sr-only">` and `<th scope="col">` semantics
  (`DataTable` already provides them; it is not modified).

## 9. Testing

Unit / component tests (Vitest + Testing Library), extending the existing suites:

1. **`useRowReveal`** - every behaviour listed in 5.1, including the refresh clamp.
2. **Honesty regression, per affected table** - the load-bearing test:
   - with a window of 200 rows and a 2-row result set, the join summary still names the
     **window** count and not `2`;
   - with an active filter, the sentence names its base (section 4.3);
   - the truncation qualification still appears when the bets window is the oldest-page
     fallback;
   - the window `<Note>` sentence is byte-identical before and after filtering/revealing.
3. **Reveal** - 10 by default, +10 per click, `Show all`, `Collapse`, and the footer wording.
4. **Search** - each table's fields, case-insensitivity, the no-match `EmptyState` reason, and
   the reset-to-10 rule.
5. **a11y** - the input's accessible name, `aria-expanded`, the live-region count.
6. The full existing suite (**230 tests**) must stay green; no existing test may be weakened
   or deleted.

Then the mandated completion gates, unchanged from the base dashboard:

- `/visual-qa` on a real browser at 375 / 768 / 1280 px, on both tabs, driving the search, the
  expand, `Show all` and `Collapse`, in the populated and degraded states;
- **Lighthouse 100** in every category on a production build with real Playwright Chromium;
- zero browser-to-API requests (the iron rule);
- `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build` all green.

## 10. Non-goals

- No API, model, ledger, scheduler or schema change; no new endpoint; no new dependency.
- No server-side search, no URL/`?q=` state, no bookmarked search state.
- No search beyond the fetched window (it cannot be done without changing the API).
- No sorting controls, no column choosers, no virtualised scrolling, no pagination numbers.
- No entrance/scroll animation.
- No change to `DataTable`, `EmptyState`, `Note`, or any window-sentence function's wording.
- No change to the three small tables (scheduler, DB size, model timeline).

## 11. Acceptance

On the host, after the change is deployed:

1. Each of the five tables shows **10** rows by default and an expand control.
2. Search narrows rows instantly with no network request, and the scope line is visible.
3. The window sentence above each table is unchanged, and every derived count still describes
   the fetched window, naming its base when a filter is active.
4. Expanding or searching never changes a derived count or a total.
5. A 60-second auto-refresh does not reset the query, the reveal, or the scroll position.
6. Nothing in the browser calls the API; the Network tab shows no request to the API host.
7. Lighthouse 100 in every category on a production build, measured with real Playwright
   Chromium.
