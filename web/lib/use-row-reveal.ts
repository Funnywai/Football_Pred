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
