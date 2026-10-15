// Bet status mapping. The ledger writes one of: pending, won, lost, push, half_won,
// half_lost (app/services/ledger.py). Each maps to a glyph + label + colour so status is
// never carried by colour alone.

export type BetStatusKind =
  | "pending"
  | "won"
  | "lost"
  | "push"
  | "half-won"
  | "half-lost"
  | "unknown";

export function betStatusKind(status: string): BetStatusKind {
  switch (status) {
    case "pending":
      return "pending";
    case "won":
      return "won";
    case "lost":
      return "lost";
    case "push":
      return "push";
    case "half_won":
      return "half-won";
    case "half_lost":
      return "half-lost";
    default:
      return "unknown";
  }
}

export function betStatusLabel(kind: BetStatusKind): string {
  switch (kind) {
    case "half-won":
      return "half won";
    case "half-lost":
      return "half lost";
    default:
      return kind;
  }
}
