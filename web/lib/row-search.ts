// The one search matcher every row-heavy table delegates to (plan: "One shared search
// matcher, never six copies"). The caller passes the trimmed, lowercased query; joining
// turns null and undefined fields into empty strings, so no per-field null handling.

export function matchesQuery(fields: (string | null | undefined)[], query: string): boolean {
  return fields.join(" ").toLowerCase().includes(query);
}
