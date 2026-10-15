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
