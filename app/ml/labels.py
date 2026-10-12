"""Label derivation for the ML prediction engine (1X2 and Asian handicap)."""

from __future__ import annotations

QUARTER_EPSILON = 1e-9
QUARTER_STEP = 0.25


def label_1x2(home_score: int, away_score: int) -> str:
    """Return "H", "D" or "A" for a final score."""
    if home_score > away_score:
        return "H"
    if home_score < away_score:
        return "A"
    return "D"


def parse_handicap_line(condition: str | None) -> float | None:
    """Parse an HKJC HDC ``condition`` (e.g. "-1", "+0.5", "0") into a float.

    Quarter lines ("-0.5/-1.0") return their **midpoint** (-0.75) so the value can be
    stored as the ``hdc_line`` feature; ``quarter_halves`` recovers the two halves.
    """
    if condition is None:
        return None
    text = condition.strip()
    if not text:
        return None
    if "/" in text:
        parts = text.split("/")
        if len(parts) != 2:
            return None
        try:
            first, second = float(parts[0]), float(parts[1])
        except ValueError:
            return None
        return round((first + second) / 2.0, 10)
    try:
        return float(text)
    except ValueError:
        return None


def quarter_halves(line: float) -> tuple[float, float] | None:
    """The two half-lines a quarter line splits into, as ``(low, high)``.

    ``-0.75 -> (-1.0, -0.5)``. Returns ``None`` for whole/half lines (they are not
    quarter lines) and for values that are not odd multiples of 0.25.
    """
    if is_whole_or_half(line):
        return None
    low = round(line - QUARTER_STEP, 10)
    high = round(line + QUARTER_STEP, 10)
    if not (is_whole_or_half(low) and is_whole_or_half(high)):
        return None
    return low, high


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
