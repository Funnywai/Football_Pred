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
