import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  numeric?: boolean;
  wrap?: boolean;
  render: (row: T) => ReactNode;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  caption: string;
  empty?: ReactNode;
  rowClassName?: (row: T) => string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  empty,
  rowClassName,
}: DataTableProps<T>) {
  if (rows.length === 0 && empty !== undefined) {
    return <>{empty}</>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-data">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-surface-base">
          <tr className="border-b border-border-default">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`whitespace-nowrap px-3 py-2 text-overline uppercase text-text-tertiary ${
                  column.numeric === true ? "text-right" : "text-left"
                }`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={`border-b border-border-hairline transition-colors duration-150 ease-out hover:bg-surface-raised ${
                rowClassName === undefined ? "" : rowClassName(row)
              }`}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-3 py-3 ${
                    column.wrap === true ? "whitespace-normal" : "whitespace-nowrap"
                  } ${column.numeric === true ? "text-right tnum" : "text-left"}`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
