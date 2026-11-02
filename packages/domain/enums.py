from enum import StrEnum


class MarketType(StrEnum):
    HAD = "HAD"
    HDC = "HDC"
    HIL = "HIL"


class Side(StrEnum):
    H = "H"
    D = "D"
    A = "A"
    L = "L"


class LineupType(StrEnum):
    PREDICTED = "predicted"
    STANDARD = "standard"


class AvailabilityStatus(StrEnum):
    INJURY = "injury"
    SUSPENSION = "suspension"
    DOUBTFUL = "doubtful"
    AVAILABLE = "available"


class MatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class CoverageFlag(StrEnum):
    UCL_XG_MISSING = "ucl_xg_missing"
    LINEUP_UNCONFIRMED = "lineup_unconfirmed"
    LINEUP_LINK_MISSING = "lineup_link_missing"
    ODDS_STALE = "odds_stale"
    NEWS_MISSING = "news_missing"
    SOURCE_DEGRADED = "source_degraded"


class BetStatus(StrEnum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    HALF_WON_HALF_PUSH = "half_won_half_push"
    HALF_LOST_HALF_PUSH = "half_lost_half_push"
    PUSH = "push"
    VOID = "void"


class SettlementSource(StrEnum):
    HKJC_CONFIRMED = "hkjc_confirmed"
    HKJC_PROVISIONAL = "hkjc_provisional"
    EXTERNAL_PROVISIONAL = "external_provisional"
    PENDING = "pending"


class FetchRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class HkjcResultSemantics(StrEnum):
    UNVERIFIED = "unverified"
    REGULATION_TIME = "regulation_time"


class SnapshotKind(StrEnum):
    T24H = "t-24h"
    T3H = "t-3h"
    T30M = "t-30m"
    T5M = "t-5m"
    MANUAL = "manual"


class AvailabilityBasis(StrEnum):
    OBSERVED_SNAPSHOT = "observed_snapshot"
    PROVIDER_POINT_IN_TIME = "provider_point_in_time"
    AVAILABILITY_ASSUMED = "availability_assumed"
    UNAVAILABLE = "unavailable"


class SourceStatus(StrEnum):
    VERIFIED = "verified"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


class UclCoverageLevel(StrEnum):
    FULL = "full"
    REDUCED = "reduced_coverage"
    INSUFFICIENT = "insufficient_coverage"


class ReservationStatus(StrEnum):
    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"
