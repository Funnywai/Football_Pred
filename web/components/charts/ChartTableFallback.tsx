import type { ReactNode } from "react";

export interface ChartTableFallbackProps {
  caption: string;
  columns: string[];
  rows: ReactNode[][];
}

// Every chart has a visible table fallback (DESIGN.md 5 ChartFrame). The toggle is a real
// <details>/<summary> so it works without JavaScript.
export function ChartTableFallback({ caption, columns, rows }: ChartTableFallbackProps) {
  return (
    <details className="text-caption text-text-tertiary">
      <summary className="cursor-pointer select-none">table view</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-data">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-border-default">
              {columns.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="whitespace-nowrap px-3 py-2 text-left text-overline uppercase text-text-tertiary"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-border-hairline">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="whitespace-nowrap px-3 py-2 tnum">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
