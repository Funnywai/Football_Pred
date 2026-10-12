"""Label derivation for the ML prediction engine (1X2 and Asian handicap)."""

from __future__ import annotations

QUARTER_EPSILON = 1e-9


def label_1x2(home_score: int, away_score: int) -> str:
    """Return "H", "D" or "A" for a final score."""
    if home_score > away_score:
        return "H"
    if home_score < away_score:
        return "A"
    return "D"


def parse_handicap_line(condition: str | None) -> float | None:
    """Parse an HKJC HDC ``condition`` string (e.g. "-1", "+0.5", "0") into a float."""
    if condition is None:
        return None
    text = condition.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_whole_or_half(line: float) -> bool:
    """True for whole (0, -1) and half (-0.5, +1.5) lines; False for quarter lines."""
    doubled = line * 2.0
    return abs(doubled - round(doubled)) < QUARTER_EPSILON


def handicap_label(home_score: int, away_score: int, line: float) -> str | None:
    """Home-cover label for the main line.

    Returns "H" when the home side covers, "A" when the away side covers, and
    ``None`` when the match is skipped: quarter lines (v1 simplification) and
    whole-line pushes (net + line == 0).
    """
    if not is_whole_or_half(line):
        return None
    adjusted = (home_score - away_score) + line
    if adjusted > 0:
        return "H"
    if adjusted < 0:
        return "A"
    return None
