import type { ReactNode } from "react";

/**
 * Focusable, labelled horizontal scroll region for wide data tables. The hint is
 * mobile-only so the desktop composition stays quiet.
 */
export function TableFrame({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`table-frame${wide ? " table-frame--wide" : ""}`}>
      <p className="table-frame__hint" aria-hidden="true">
        Scroll horizontally →
      </p>
      <div
        className="table-wrap"
        role="region"
        aria-label={label}
        tabIndex={0}
      >
        {children}
      </div>
    </div>
  );
}
