# Table reveal and search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the five row-heavy dashboard tables one pattern — 10 rows by default, an expand control that reveals 10 more per click, a search box that filters the fetched window, and a "Show all" control — without changing a single honesty sentence or derived count.

**Architecture:** Each table becomes a Client Component that receives the already-fetched window as props and owns two pieces of state (query, visible count). Filtering and slicing happen in memory in the browser; the server keeps doing every fetch. Three new shared primitives (a hook plus two small components) are documented in `web/DESIGN.md` §5 before anything uses them.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind v4, Vitest + `@testing-library/react`.

**Spec:** `docs/superpowers/specs/2026-10-15-table-reveal-and-search-design.md` (the authority for every rule below).

## Global Constraints

- The browser must **never** call the API. All fetches stay server-side. The visual-QA count of browser-to-API requests must stay **0**.
- `web/DESIGN.md` §5 is updated in Task 2, **before** any component uses the primitives (Design System Gate).
- Every window `<Note>` sentence stays **byte-identical**.
- A derived count must **never silently change its base** (spec §4.2/§4.3).
- The M1 truncation qualification (`isTruncated(bets) || !bets.newestFirst`) is preserved.
- `DataTable` is **not modified** (8 consumers).
- No new dependency, no API/app change. No `any` / `as any` / `@ts-ignore` / `@ts-expect-error`. No emojis. Every file < 250 pure LOC.
- Baseline **25 test files / 230 tests** must not drop. Only the five assertions named in spec §9.7 may change, and only as specified there.
- **When a filter matches nothing**, render that table's existing `EmptyState` with the reason
  `No row in this window matches "{query}"` and a detail line `Search covers only the fetched window.`
  - never a generic "no data" that would read as an empty table.
- **Locked footer format:** `{base} · {shown} of {matching} shown`, where `base` is optional and,
  when a filter is active, ` · matching "{query}"` is appended.
- **Every `<RevealFooter>` call site passes `canCollapse={reveal.visible > REVEAL_INITIAL}`** —
  `canExpand` is false once the list is fully revealed, so it must not be reused for Collapse.
- **`SearchInput` uses `useId()`, never a constant id** — up to three of these tables share the
  Performance page, and duplicate DOM ids break the label association.
- **Tests use `fireEvent` from `@testing-library/react`.** `@testing-library/user-event` is NOT
  installed and must not be added (the no-new-dependency constraint binds). Where a snippet shows
  `await userEvent.click(el)` use `fireEvent.click(el)`, and where it shows
  `await userEvent.type(el, "value")` use `fireEvent.change(el, { target: { value: "value" } })`;
  drop the `user-event` import and any `async` that becomes unused. Assertions are unchanged.
- **One shared search matcher, never six copies.** Create `web/lib/row-search.ts` (in Task 3,
  consumed by Tasks 3-7) exporting:

  ```ts
  export function matchesQuery(fields: (string | null | undefined)[], query: string): boolean {
    return fields.join(" ").toLowerCase().includes(query);
  }
  ```

  It needs no null handling: joining turns `null` and `undefined` into empty strings. It gets its
  own test file, `web/tests/row-search.test.ts`, covering: a match, a non-match, case-insensitivity
  on the field side, an empty query matching everything, and `null`/`undefined` fields being
  harmless. Every table's matcher **keeps the name and the searchable-field set its task lists** and
  delegates, e.g.

  ```ts
  const predictionMatches = (row: PredictionBetRow, q: string) =>
    matchesQuery([row.prediction.home_team, row.prediction.away_team, row.prediction.league_code,
                  row.prediction.target, row.prediction.outcome, row.bet === null ? "no bet" : "placed"], q);
  ```

  A review that finds the same haystack expression repeated in two tables is a defect.
- **Locked join-summary formats:**
  - unfiltered: `{unmatched} of the {fetched} fetched rows have no place in the ledger; {matched} matched a placed bet.`
  - filtered: `of the {matching} rows matching "{query}" in this window, {unmatched} have no place in the ledger; {matched} matched a placed bet.`
  - when the bets window is the oldest-page fallback, the text after the semicolon becomes `{unmatched} have no match there — a bet outside the fetched window would not be seen.` (unchanged wording).
- Gates: `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`, then `/visual-qa` on a real browser at 375/768/1280 on both tabs in populated and degraded states, plus **Lighthouse 100** in every category on a production build with real Playwright Chromium.

## File structure (locked before task decomposition)

| File | Responsibility |
| --- | --- |
| `web/lib/use-row-reveal.ts` (create) | The reveal/filter state machine. Pure, DOM-free, testable. |
| `web/tests/use-row-reveal.test.ts` (create) | Its unit tests. |
| `web/components/ui/SearchInput.tsx` (create) | Labelled input + scope line + clear control. |
| `web/components/ui/RevealFooter.tsx` (create) | Count sentence + Expand +10 / Show all / Collapse. |
| `web/DESIGN.md` (modify, §5) | Document both components and the hook's contract. |
| `web/components/tables/MatchesPredictionsTable.tsx` (modify) | Adopt reveal+search; join summary gains a named base. |
| `web/components/tables/ResultsTable.tsx` (modify) | Adopt reveal+search. |
| `web/components/tables/SignalVsExecutionTable.tsx` (modify) | Adopt reveal+search. |
| `web/components/tables/BetsTable.tsx` (modify) | Drop Prev/Next; adopt reveal+search. |
| `web/components/technical/IngestionRunsTimeline.tsx` (modify) | Adopt reveal+search. |
| `web/tests/*.tsx` (modify) | 5 assertions reworded per §9.7 + new behaviour tests. |

`web/lib/predictions-window.ts`, `web/lib/results-window.ts`, `web/lib/bets-window.ts`, `web/lib/runs.ts` are **not modified**: their sentences are the byte-identical window text.

---

### Task 1: The `useRowReveal` hook

**Files:**
- Create: `web/lib/use-row-reveal.ts`
- Test: `web/tests/use-row-reveal.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `REVEAL_INITIAL = 10`, `REVEAL_STEP = 10`, `interface RowReveal<T>`, `useRowReveal<T>(rows: T[], matches: (row: T, query: string) => boolean, options?: { initial?: number; step?: number }): RowReveal<T>` — consumed by Tasks 3–7.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/use-row-reveal.test.ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { REVEAL_INITIAL, REVEAL_STEP, useRowReveal } from "@/lib/use-row-reveal";

const rows = Array.from({ length: 35 }, (_, i) => ({ id: i, name: `team ${i}` }));
const matches = (row: { name: string }, q: string) => row.name.includes(q);

describe("useRowReveal", () => {
  it("shows 10 rows by default", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    expect(REVEAL_INITIAL).toBe(10);
    expect(REVEAL_STEP).toBe(10);
    expect(result.current.shown).toHaveLength(10);
    expect(result.current.visible).toBe(10);
    expect(result.current.canExpand).toBe(true);
  });

  it("shows fewer than 10 when the window is shorter", () => {
    const { result } = renderHook(() => useRowReveal(rows.slice(0, 4), matches));
    expect(result.current.shown).toHaveLength(4);
    expect(result.current.canExpand).toBe(false);
  });

  it("expand adds exactly 10 and clamps at the end", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    act(() => result.current.expand());
    expect(result.current.visible).toBe(20);
    act(() => result.current.expand());
    expect(result.current.visible).toBe(30);
    act(() => result.current.expand());
    expect(result.current.visible).toBe(35);
    expect(result.current.canExpand).toBe(false);
  });

  it("filters case-insensitively on the normalised query without slicing filtered", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    act(() => result.current.setQuery("  TEAM 3  "));
    expect(result.current.query).toBe("  TEAM 3  ");
    expect(result.current.isFiltered).toBe(true);
    // matches "team 3" and "team 30".."team 34" -> 6 rows
    expect(result.current.filtered).toHaveLength(6);
    expect(result.current.shown).toHaveLength(6);
  });

  it("a whitespace-only query matches everything and is not 'filtered'", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    act(() => result.current.setQuery("   "));
    expect(result.current.isFiltered).toBe(false);
    expect(result.current.filtered).toHaveLength(35);
    expect(result.current.shown).toHaveLength(10);
  });

  it("setting a query resets the reveal to 10", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    act(() => result.current.expand());
    act(() => result.current.expand());
    expect(result.current.visible).toBe(30);
    act(() => result.current.setQuery("team"));
    expect(result.current.visible).toBe(10);
  });

  it("clearing the query resets the reveal to 10 and keeps the full window available", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    act(() => result.current.setQuery("team 1"));
    act(() => result.current.expand());
    act(() => result.current.clear());
    expect(result.current.query).toBe("");
    expect(result.current.visible).toBe(10);
    expect(result.current.filtered).toHaveLength(35);
    expect(result.current.shown).toHaveLength(10);
  });

  it("expandAll shows everything and collapse returns to 10", () => {
    const { result } = renderHook(() => useRowReveal(rows, matches));
    act(() => result.current.expandAll());
    expect(result.current.visible).toBe(35);
    expect(result.current.canExpand).toBe(false);
    act(() => result.current.collapse());
    expect(result.current.visible).toBe(10);
  });

  it("clamps visible when the window shrinks on a refresh", () => {
    const { result, rerender } = renderHook(
      ({ data }: { data: typeof rows }) => useRowReveal(data, matches),
      { initialProps: { data: rows } },
    );
    act(() => result.current.expandAll());
    expect(result.current.visible).toBe(35);
    rerender({ data: rows.slice(0, 3) });
    expect(result.current.visible).toBe(3);
    expect(result.current.shown).toHaveLength(3);
    expect(result.current.canExpand).toBe(false);
  });

  it("re-applies an active query to new data on a refresh", () => {
    const { result, rerender } = renderHook(
      ({ data }: { data: typeof rows }) => useRowReveal(data, matches),
      { initialProps: { data: rows } },
    );
    act(() => result.current.setQuery("team 2"));
    // "team 2" also matches team 20..29, so this is 11 of the 35 rows, not 10.
    expect(result.current.filtered).toHaveLength(11);
    rerender({ data: [...rows, { id: 99, name: "team 29" }] });
    expect(result.current.filtered).toHaveLength(12);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/use-row-reveal.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/use-row-reveal"`.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/lib/use-row-reveal.ts
"use client";

import { useCallback, useMemo, useState } from "react";

export const REVEAL_INITIAL = 10;
export const REVEAL_STEP = 10;

export interface RowReveal<T> {
  query: string;
  setQuery: (next: string) => void;
  clear: () => void;
  filtered: T[];
  shown: T[];
  visible: number;
  canExpand: boolean;
  expand: () => void;
  expandAll: () => void;
  collapse: () => void;
  isFiltered: boolean;
}

/** Filter rows in memory and reveal them REVEAL_INITIAL at a time. `matches` receives the
 *  trimmed, lowercased query; the caller lowercases the fields it compares. `filtered` is
 *  never sliced so callers can keep counting over the whole window. */
export function useRowReveal<T>(
  rows: T[],
  matches: (row: T, query: string) => boolean,
  options?: { initial?: number; step?: number },
): RowReveal<T> {
  const initial = options?.initial ?? REVEAL_INITIAL;
  const step = options?.step ?? REVEAL_STEP;
  const [query, setQueryState] = useState("");
  const [visible, setVisible] = useState(initial);

  const normalised = query.trim().toLowerCase();
  const isFiltered = normalised.length > 0;

  const filtered = useMemo(
    () => (isFiltered ? rows.filter((row) => matches(row, normalised)) : rows),
    [rows, matches, normalised, isFiltered],
  );

  const clamped = Math.min(visible, filtered.length);
  const shown = useMemo(() => filtered.slice(0, clamped), [filtered, clamped]);

  const setQuery = useCallback(
    (next: string) => {
      setQueryState(next);
      setVisible(initial);
    },
    [initial],
  );

  const clear = useCallback(() => setQuery(""), [setQuery]);
  const expand = useCallback(() => setVisible((n) => n + step), [step]);
  const expandAll = useCallback(() => setVisible(filtered.length), [filtered.length]);
  const collapse = useCallback(() => setVisible(initial), [initial]);

  return {
    query,
    setQuery,
    clear,
    filtered,
    shown,
    visible: clamped,
    canExpand: clamped < filtered.length,
    expand,
    expandAll,
    collapse,
    isFiltered,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/use-row-reveal.test.ts`
Expected: PASS — 10 tests.

- [ ] **Step 5: Commit**

```bash
git add web/lib/use-row-reveal.ts web/tests/use-row-reveal.test.ts
git commit -m "feat: 新增 useRowReveal（記憶體內過濾 ＋ 每次展開 10 筆）"
```

---

### Task 2: `SearchInput`, `RevealFooter`, and the DESIGN.md contract

**Files:**
- Create: `web/components/ui/SearchInput.tsx`
- Create: `web/components/ui/RevealFooter.tsx`
- Modify: `web/DESIGN.md` (§5 Components — add two entries)
- Test: `web/tests/reveal-search.test.tsx`

**Interfaces:**
- Consumes: `RowReveal<T>` from Task 1.
- Produces: `<SearchInput value onChange scope onClear label />` and `<RevealFooter base shown matching isFiltered canExpand onExpand onExpandAll onCollapse />` — consumed by Tasks 3–7.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/reveal-search.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";

describe("SearchInput", () => {
  it("has an accessible name and states its scope", () => {
    render(<SearchInput label="Search bets" scope="searches the 200 rows in this window" value="" onChange={() => {}} onClear={() => {}} />);
    expect(screen.getByLabelText("Search bets")).toBeInTheDocument();
    expect(screen.getByText("searches the 200 rows in this window")).toBeInTheDocument();
  });

  it("only shows Clear when non-empty and calls onClear", () => {
    const onClear = vi.fn();
    const { rerender } = render(<SearchInput label="Search bets" scope="s" value="" onChange={() => {}} onClear={onClear} />);
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
    rerender(<SearchInput label="Search bets" scope="s" value="arsenal" onChange={() => {}} onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onClear).toHaveBeenCalledOnce();
  });
});

describe("RevealFooter", () => {
  it("states both counts so the revealed number never reads as a total", () => {
    render(<RevealFooter base="showing the 200 most recent of 250 bets" shown={10} matching={200} isFiltered={false} canExpand canCollapse={false} onExpand={() => {}} onExpandAll={() => {}} onCollapse={() => {}} />);
    expect(screen.getByText("showing the 200 most recent of 250 bets · 10 of 200 shown")).toBeInTheDocument();
  });

  it("names the query when filtered", () => {
    render(<RevealFooter base="showing 200 of 250 bets" shown={6} matching={6} query="arsenal" isFiltered canExpand={false} canCollapse={false} onExpand={() => {}} onExpandAll={() => {}} onCollapse={() => {}} />);
    expect(screen.getByText(/· matching "arsenal"/)).toBeInTheDocument();
  });

  it("disables the expand controls when everything is shown but keeps Collapse usable", () => {
    render(<RevealFooter base="b" shown={35} matching={35} isFiltered={false} canExpand={false} canCollapse onExpand={() => {}} onExpandAll={() => {}} onCollapse={() => {}} />);
    expect(screen.getByRole("button", { name: /Expand/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Show all/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Collapse" })).toBeEnabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/reveal-search.test.tsx`
Expected: FAIL — cannot resolve `@/components/ui/SearchInput`.

- [ ] **Step 3: Document the primitives in DESIGN.md §5, then implement**

Append to `web/DESIGN.md` inside `## 5. Components`, after the `### Note` entry:

```markdown
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
- Right: `Expand +10` (primary), `Show all N` (secondary), `Collapse` (only once `shown > initial`).
  Buttons reuse the existing footer button class from `BetsTable`. `Expand` carries `aria-expanded`.
- Both expand controls are disabled when everything is already shown.
- No entrance animation (see §6.3).
```

```tsx
// web/components/ui/SearchInput.tsx
"use client";

import { useId } from "react";

import { Search, X } from "lucide-react";

export interface SearchInputProps {
  label: string;
  scope: string;
  value: string;
  onChange: (next: string) => void;
  onClear: () => void;
}

export function SearchInput({ label, scope, value, onChange, onClear }: SearchInputProps) {
  // useId, never a constant: three of these tables can appear on one page, and duplicate DOM
  // ids would break the label association and make getByLabelText ambiguous.
  const id = useId();
  return (
    <div className="flex flex-wrap items-center gap-3 px-6 py-3">
      <label htmlFor={id} className="flex items-center gap-2 text-body text-text-secondary">
        <Search className="size-3 text-text-tertiary" aria-hidden />
        {label}
      </label>
      <input
        id={id}
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-border-default bg-surface-base px-2 py-1 text-body text-text-primary placeholder:text-text-tertiary focus:border-accent-signal focus:outline-none"
      />
      {value === "" ? null : (
        <button
          type="button"
          aria-label="Clear search"
          onClick={onClear}
          className="inline-flex items-center gap-1 rounded-md border border-border-default px-2 py-1 text-caption text-text-secondary transition-colors duration-150 ease-out hover:border-accent-signal/60 hover:text-text-primary"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
      <span className="text-caption text-text-tertiary">{scope}</span>
    </div>
  );
}
```

```tsx
// web/components/ui/RevealFooter.tsx
"use client";

const BUTTON =
  "inline-flex items-center gap-1 rounded-md border border-border-default px-2 py-1 text-caption text-text-secondary transition-colors duration-150 ease-out hover:border-accent-signal/60 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40";

export interface RevealFooterProps {
  /** Optional window sentence. Tables that already show their window in a <Note> above omit this;
   *  the bets table, which shows its window here, passes it. */
  base?: string;
  shown: number;
  matching: number;
  query?: string;
  isFiltered: boolean;
  canExpand: boolean;
  /** True once the reveal has grown past its initial size, so Collapse stays usable when the
   *  list is fully shown (canExpand is false then). */
  canCollapse: boolean;
  onExpand: () => void;
  onExpandAll: () => void;
  onCollapse: () => void;
}

export function RevealFooter({
  base,
  shown,
  matching,
  query,
  isFiltered,
  canExpand,
  canCollapse,
  onExpand,
  onExpandAll,
  onCollapse,
}: RevealFooterProps) {
  const filterNote = isFiltered && query !== undefined ? ` · matching "${query.trim()}"` : "";
  const count = `${shown} of ${matching} shown${filterNote}`;
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-3 text-caption text-text-tertiary">
      <span className="tnum" aria-live="polite">
        {base === undefined ? count : `${base} · ${count}`}
      </span>
      <div className="flex items-center gap-2">
        <button type="button" className={BUTTON} onClick={onExpand} disabled={!canExpand} aria-expanded={canExpand}>
          Expand +10
        </button>
        <button type="button" className={BUTTON} onClick={onExpandAll} disabled={!canExpand}>
          Show all {matching}
        </button>
        <button type="button" className={BUTTON} onClick={onCollapse} disabled={!canCollapse}>
          Collapse
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/reveal-search.test.tsx`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add web/DESIGN.md web/components/ui/SearchInput.tsx web/components/ui/RevealFooter.tsx web/tests/reveal-search.test.tsx
git commit -m "feat: 新增 SearchInput 與 RevealFooter 積木（並先寫入 DESIGN.md 契約）"
```

---

### Task 3: Matches x predictions — reveal, search, and the named-base join summary

**Files:**
- Create: `web/lib/row-search.ts` (the shared matcher all five tables use)
- Create: `web/tests/row-search.test.ts`
- Modify: `web/components/tables/MatchesPredictionsTable.tsx` (add `"use client"`, hook, controls; counts keep using the full window)
- Modify: `web/lib/predictions-join.ts` (add the named-base summary function)
- Modify: `web/tests/matches-predictions.test.tsx` (:98 and :136 reworded; add reveal/search tests)

**Interfaces:**
- Consumes: `useRowReveal` (Task 1), `SearchInput` + `RevealFooter` (Task 2).
- Produces: `joinSummaryPhrase(matched, unmatched, betsWindowTruncated, base)` where `base` is `{ fetched: number; query?: string }` — used only here.

- [ ] **Step 1: Write the failing tests**

```ts
// web/tests/row-search.test.ts
import { describe, expect, it } from "vitest";

import { matchesQuery } from "@/lib/row-search";

describe("matchesQuery", () => {
  it("matches a lowercased query against any field, case-insensitively", () => {
    expect(matchesQuery(["Arsenal", "Chelsea", "EPL"], "arsenal")).toBe(true);
    expect(matchesQuery(["Arsenal", "Chelsea", "EPL"], "epl")).toBe(true);
  });

  it("does not match when no field contains the query", () => {
    expect(matchesQuery(["Arsenal", "Chelsea"], "liverpool")).toBe(false);
  });

  it("matches every row on an empty query", () => {
    expect(matchesQuery(["anything"], "")).toBe(true);
  });

  it("treats null and undefined fields as empty strings", () => {
    expect(matchesQuery([null, undefined, "Arsenal"], "arsenal")).toBe(true);
    expect(matchesQuery([null, undefined], "x")).toBe(false);
  });
});
```

```ts
// web/tests/predictions-join.test.ts (append)
import { joinSummaryPhrase } from "@/lib/predictions-join";

describe("joinSummaryPhrase named base", () => {
  it("names the fetched window when unfiltered", () => {
    expect(joinSummaryPhrase(0, 200, false, { fetched: 200 })).toBe(
      "200 of the 200 fetched rows have no place in the ledger; 0 matched a placed bet.",
    );
  });
  it("names the query when filtered", () => {
    expect(joinSummaryPhrase(1, 11, false, { fetched: 200, query: "arsenal" })).toBe(
      'of the 12 rows matching "arsenal" in this window, 11 have no place in the ledger; 1 matched a placed bet.',
    );
  });
  it("keeps the truncation wording byte-identical (filtered or not)", () => {
    expect(joinSummaryPhrase(1, 0, true, { fetched: 200, query: "arsenal" })).toBe(
      "1 matched a placed bet in the fetched bets window; 0 have no match there — a bet outside the fetched window would not be seen.",
    );
    expect(joinSummaryPhrase(0, 1, true, { fetched: 200 })).toBe(
      "0 matched a placed bet in the fetched bets window; 1 has no match there — a bet outside the fetched window would not be seen.",
    );
  });
});
```

```tsx
// web/tests/matches-predictions.test.tsx (append)
it("shows 10 rows by default and reveals 10 more", async () => {
  render(<MatchesPredictionsTable /* existing 200-row fixture */ />);
  expect(screen.getAllByRole("row")).toHaveLength(11); // header + 10
  await userEvent.click(screen.getByRole("button", { name: /Expand/ }));
  expect(screen.getAllByRole("row")).toHaveLength(21);
});

it("searching narrows rows and does NOT change the window counts", async () => {
  render(<MatchesPredictionsTable /* fixture: 200 rows, 2 matching a bet, one named "Arsenal" */ />);
  expect(screen.getByText(/200 of the 200 fetched rows have no place in the ledger; 2 matched a placed bet\./)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Search predictions"), "arsenal");
  expect(screen.getAllByRole("row").length).toBeLessThan(11);
  expect(screen.getByText(/rows matching "arsenal" in this window/)).toBeInTheDocument();
  expect(screen.getByText(/· matching "arsenal"/)).toBeInTheDocument();
});
```

And reword the two existing assertions (spec §9.7):

Also update the two **pre-existing** `joinSummaryPhrase` call sites in the same test file, which
the signature change breaks: `:121` gains the base and must read
`"54 of the 54 fetched rows have no place in the ledger; 0 matched a placed bet."`, and `:127`
takes the new fourth argument `{ fetched: 54 }` and must stay **byte-identical** to today's
truncation string.

```tsx
// :98  from /200 of these have no place in the ledger; 0 matched a placed bet\./
     to   /200 of the 200 fetched rows have no place in the ledger; 0 matched a placed bet\./
// :136 from /1 of these has no place in the ledger; 0 matched a placed bet\./
     to   /of the 1 row in this window, 1 has no place in the ledger; 0 matched a placed bet\./
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run tests/predictions-join.test.ts tests/matches-predictions.test.tsx`
Expected: FAIL — `joinSummaryPhrase` takes 3 arguments; the new UI assertions find no such text.

- [ ] **Step 3: Implement**

In `web/lib/predictions-join.ts`, replace `joinSummaryPhrase` with:

```ts
export function joinSummaryPhrase(
  matched: number,
  unmatched: number,
  betsWindowTruncated: boolean,
  base: { fetched: number; query?: string },
): string {
  const verb = unmatched === 1 ? "has" : "have";
  if (betsWindowTruncated) {
    // Byte-identical to the pre-change truncation wording: the existing assertions at
    // matches-predictions.test.tsx:123 and :150 must keep passing unchanged.
    return `${matched} matched a placed bet in the fetched bets window; ${unmatched} ${verb} no match there — a bet outside the fetched window would not be seen.`;
  }
  const query = base.query?.trim();
  const tally =
    query === undefined || query === ""
      ? `${unmatched} of the ${base.fetched} fetched rows`
      : `of the ${matched + unmatched} rows matching "${query}" in this window, ${unmatched}`;
  return `${tally} ${verb} no place in the ledger; ${matched} matched a placed bet.`;
}
```

> Implementer note: the two branches must produce exactly the strings pinned in Step 1. Write the function however you like as long as those three assertions pass; do not change the assertions to fit the code.

In `web/components/tables/MatchesPredictionsTable.tsx`:

```tsx
"use client"; // add at line 1

// inside the component, after the row-building:
const reveal = useRowReveal(rows, predictionMatches);
const matched = rows.filter((row) => row.bet !== null).length; // unchanged: full window
const unmatched = rows.length - matched;
const summaryBase = { fetched: rows.length, query: reveal.isFiltered ? reveal.query : undefined };
```

```tsx
<SearchInput
  label="Search predictions"
  scope={`searches the ${predictions.length} rows in this window`}
  value={reveal.query}
  onChange={reveal.setQuery}
  onClear={reveal.clear}
/>
<Note>{joinSummaryPhrase(matched, unmatched, isTruncated(bets) || !bets.newestFirst, summaryBase)}</Note>
<DataTable columns={COLUMNS} rows={reveal.shown} rowKey={/* keep the existing rowKey expression unchanged */} caption="Matches and predictions" />
<RevealFooter
  shown={reveal.shown.length}
  matching={reveal.filtered.length}
  query={reveal.query}
  isFiltered={reveal.isFiltered}
  canExpand={reveal.canExpand}
  onExpand={reveal.expand}
  onExpandAll={reveal.expandAll}
  onCollapse={reveal.collapse}
/>
```

with the searchable-field matcher added next to the row builder, delegating to the shared helper
(see the Global Constraint "One shared search matcher, never six copies"):

```ts
// web/lib/row-search.ts
export function matchesQuery(fields: (string | null | undefined)[], query: string): boolean {
  return fields.join(" ").toLowerCase().includes(query);
}

// web/components/tables/MatchesPredictionsTable.tsx
function predictionMatches(row: PredictionBetRow, query: string): boolean {
  return matchesQuery(
    [
      row.prediction.home_team,
      row.prediction.away_team,
      row.prediction.league_code,
      row.prediction.target,
      row.prediction.outcome,
      row.bet === null ? "no bet" : "placed",
    ],
    query,
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/predictions-join.test.ts tests/matches-predictions.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/tables/MatchesPredictionsTable.tsx web/lib/predictions-join.ts web/tests/predictions-join.test.ts web/tests/matches-predictions.test.tsx
git commit -m "feat: 比賽×預測表改為 10 筆＋展開＋視窗內搜尋，帳本摘要加上分母"
```

---

### Task 4: Results — reveal + search

**Files:**
- Modify: `web/components/tables/ResultsTable.tsx`
- Modify: `web/tests/performance-rest.test.tsx` (add behaviour tests; the window `<Note>` assertion at :76 stays byte-identical)

**Interfaces:** Consumes Task 1 + Task 2 primitives.

- [ ] **Step 1: Write the failing test**

```tsx
it("shows 10 rows, reveals 10 more, and searches the window", async () => {
  render(<ResultsTable /* existing fixture, >= 30 rows */ />);
  expect(screen.getAllByRole("row")).toHaveLength(11);
  await userEvent.click(screen.getByRole("button", { name: /Expand/ }));
  expect(screen.getAllByRole("row")).toHaveLength(21);
  await userEvent.type(screen.getByLabelText("Search results"), "hkjc");
  expect(screen.getByText(/· matching "hkjc"/)).toBeInTheDocument();
});

it("keeps the window sentence byte-identical while filtered", async () => {
  render(<ResultsTable /* fixture */ />);
  const note = "Window: the newest 200 results by kickoff time (newest first); newer results cannot fall outside this window, older ones can.";
  expect(screen.getByText(note)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Search results"), "zzz");
  expect(screen.getByText(note)).toBeInTheDocument();
  expect(screen.getByText(/No row in this window matches "zzz"/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/performance-rest.test.tsx`
Expected: FAIL — no search input, 200 rows rendered.

- [ ] **Step 3: Implement** — add `"use client"`, `const reveal = useRowReveal(results, resultMatches)`, render `<SearchInput>` above the existing `<Note>` (unchanged), pass `rows={reveal.shown}` to `DataTable`, and render:

```tsx
<RevealFooter
  shown={reveal.shown.length}
  matching={reveal.filtered.length}
  query={reveal.query}
  isFiltered={reveal.isFiltered}
  canExpand={reveal.canExpand}
  onExpand={reveal.expand}
  onExpandAll={reveal.expandAll}
  onCollapse={reveal.collapse}
/>
```

```ts
function resultMatches(row: Result, query: string): boolean {
  const haystack = [
    row.home_team.name_en,
    row.away_team.name_en,
    row.league_code,
    row.source,
    `${row.home_score}-${row.away_score}`,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}
```

Pass `empty={<EmptyState icon={SearchX} title={`No row in this window matches "${reveal.query.trim()}"`} detail="Search covers only the fetched window." />}` when filtered (keep the existing empty state otherwise).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/performance-rest.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/tables/ResultsTable.tsx web/tests/performance-rest.test.tsx
git commit -m "feat: 賽果表改為 10 筆＋展開＋視窗內搜尋"
```

---

### Task 5: Signal vs execution — reveal + search

**Files:**
- Modify: `web/components/tables/SignalVsExecutionTable.tsx`
- Modify: `web/tests/performance-rest.test.tsx` (add behaviour tests)

**Interfaces:** Consumes Task 1 + Task 2 primitives.

- [ ] **Step 1: Write the failing test**

```tsx
it("reveals and searches the signal table without touching its window sentence", async () => {
  render(<SignalVsExecutionTable /* fixture */ />);
  expect(screen.getAllByRole("row")).toHaveLength(11);
  await userEvent.click(screen.getByRole("button", { name: /Show all/ }));
  expect(screen.getAllByRole("row").length).toBeGreaterThan(11);
  await userEvent.type(screen.getByLabelText("Search signal vs execution"), "laliga");
  expect(screen.getByText(/· matching "laliga"/)).toBeInTheDocument();
  expect(screen.getByText(/joined with .*predictions\?limit=200/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/performance-rest.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement** — `"use client"`, `const reveal = useRowReveal(rows, signalMatches)`, keep the existing `<Note>` sentence byte-identical, pass `rows={reveal.shown}`, add `<SearchInput label="Search signal vs execution" scope={`searches the ${rows.length} rows in this window`} … />` and a `<RevealFooter … />` with no `base` (the `<Note>` above already carries the window sentence).

```ts
function signalMatches(row: SignalRow, query: string): boolean {
  // Read the component's own row type first and search exactly the fields it already renders:
  // home team, away team, league code, outcome (spec section 6).
  const haystack = [row.homeTeam, row.awayTeam, row.leagueCode, row.outcome]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}
```

> Field-name note: the names above match the row shape this component builds today; if the file
> uses different ones, use its names. The *set* of searchable fields is fixed by spec section 6.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/performance-rest.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/tables/SignalVsExecutionTable.tsx web/tests/performance-rest.test.tsx
git commit -m "feat: 訊號價vs成交價表改為 10 筆＋展開＋視窗內搜尋"
```

---

### Task 6: All bets — drop Prev/Next, adopt reveal + search

**Files:**
- Modify: `web/components/tables/BetsTable.tsx` (remove `PAGE_SIZE`, `page` state, Prev/Next buttons, `pageCount`; delete `footerText`'s pagination parameter)
- Modify: `web/tests/performance-sections.test.tsx` (:207, :214, :238 reworded per §9.7)

**Interfaces:** Consumes Task 1 + Task 2 primitives.

- [ ] **Step 1: Write the failing tests (rewording the three existing assertions)**

```tsx
// :207 reworded
expect(screen.getByText("2 bets · 2 of 2 shown")).toBeInTheDocument();
// :214 reworded
expect(
  screen.getByText("showing the 30 most recent of 250 bets · 10 of 30 shown"),
).toBeInTheDocument();
// :238 reworded - the oldest-page qualification MUST survive
expect(
  screen.getByText(
    "showing the oldest 2 bets · /bets/summary unavailable · 2 of 2 shown",
  ),
).toBeInTheDocument();
// new behaviour
it("reveals 10 more per click and searches", async () => {
  render(<BetsTable /* fixture: 30 bets */ />);
  expect(screen.getAllByRole("row")).toHaveLength(11);
  await userEvent.click(screen.getByRole("button", { name: /Expand/ }));
  expect(screen.getAllByRole("row")).toHaveLength(21);
  await userEvent.type(screen.getByLabelText("Search bets"), "chelsea");
  expect(screen.getByText(/· matching "chelsea"/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/performance-sections.test.tsx`
Expected: FAIL — the reworded strings do not exist; Prev/Next still render.

- [ ] **Step 3: Implement** — delete `PAGE_SIZE`, the `page` state, `pageCount`, both Prev/Next buttons and the removed imports; `const reveal = useRowReveal(bets.rows, betMatches)`; `base` keeps every existing branch of `footerText` but drops ` · page X of Y`:

```ts
function windowSentence(bets: BetsWindow): string {
  if (!bets.newestFirst) {
    return `showing the oldest ${bets.rows.length} bets · /bets/summary unavailable`;
  }
  if (isTruncated(bets)) return `showing ${betsWindowPhrase(bets)}`;
  return `${bets.rows.length} bets`;
}
```

```ts
function betMatches(bet: Bet, query: string): boolean {
  const haystack = [bet.home_team, bet.away_team, bet.league_code, bet.target, bet.outcome, bet.status]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}
```

Render `<SearchInput label="Search bets" scope={`searches the ${bets.rows.length} rows in this window`} … />`, pass `rows={reveal.shown}` to `DataTable`, and `<RevealFooter base={windowSentence(bets)} shown={reveal.shown.length} matching={reveal.filtered.length} … />`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/performance-sections.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/tables/BetsTable.tsx web/tests/performance-sections.test.tsx
git commit -m "refactor: 注單表改為 10 筆＋展開＋搜尋，移除 Prev/Next 翻頁"
```

---

### Task 7: Ingestion runs timeline — reveal + search

**Files:**
- Modify: `web/components/technical/IngestionRunsTimeline.tsx`
- Modify: `web/tests/technical-runs.test.tsx` (add behaviour tests)

**Interfaces:** Consumes Task 1 + Task 2 primitives.

- [ ] **Step 1: Write the failing test**

```tsx
it("reveals runs 10 at a time and searches job, status and error text", async () => {
  render(<IngestionRunsTimeline /* fixture: 30 runs incl. one failed with "503" */ />);
  expect(screen.getAllByRole("listitem")).toHaveLength(10);
  await userEvent.click(screen.getByRole("button", { name: /Expand/ }));
  expect(screen.getAllByRole("listitem")).toHaveLength(20);
  await userEvent.type(screen.getByLabelText("Search runs"), "503");
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/technical-runs.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement** — `"use client"`, `const reveal = useRowReveal(runs, runMatches)`, render `<SearchInput label="Search runs" … />`, map over `reveal.shown` instead of `runs`, leave the existing runs window label **exactly where it is** (do not also pass it as `base`), and add a `<RevealFooter … />` with no `base`.

```ts
function runMatches(run: OpsRun, query: string): boolean {
  const haystack = [run.job, run.status, run.error ?? ""].join(" ").toLowerCase();
  return haystack.includes(query);
}
```

Note: this component renders a `<ul>` of runs, not a `DataTable`; the comment stating it is a list and not a chart stays.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run tests/technical-runs.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/technical/IngestionRunsTimeline.tsx web/tests/technical-runs.test.tsx
git commit -m "feat: 擷取時間線改為 10 筆＋展開＋搜尋（job／status／error）"
```

---

### Task 8: Full gates

**Files:** none (verification only).

- [ ] **Step 1: The four gates**

Run: `cd web && npx tsc --noEmit && npm run lint && npm test && npm run build`
Expected: tsc clean, lint clean, **all test files pass with a total strictly greater than 230**, build succeeds.

- [ ] **Step 2: Prove no existing test was weakened**

Run: `git diff main -- web/tests | grep -E "^\+.*(it|expect)\(" | head -40`
Expected: every changed assertion is one of the five in spec §9.7 or a new test. If any assertion was loosened, revert it and fix the code instead.

- [ ] **Step 3: Real-browser visual QA**

Run `/visual-qa` with a production build against a mock API (a script under `/tmp`, shaped from `web/lib/types.ts`, at 250 bets so the truncation path renders). At 375 / 768 / 1280 on both tabs, in populated and degraded states, drive: 10 rows by default, Expand, Show all, Collapse, the search, and the clear control.
Expected: no page-level overflow, no console errors, **0 browser-to-API requests**, and every window sentence on screen matching its pre-change text character for character.

- [ ] **Step 4: Lighthouse 100**

Measure every category on the production build with **real Playwright Chromium** (never the `lighthouse` CLI, never a dev server).
Expected: 100 in every category. If a score drops, fix the architecture - do not remove the search, the reveal, or any honesty sentence.

- [ ] **Step 5: Commit any fixes and report**

```bash
git add web/components web/lib web/tests web/DESIGN.md && git commit -m "test: 表格收合與搜尋的完整驗收（視覺 QA ＋ Lighthouse）"
```
