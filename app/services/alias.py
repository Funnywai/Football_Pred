import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ALIASES_PATH = Path(__file__).resolve().parent.parent / "data" / "team_aliases.json"
FUZZY_THRESHOLD = 0.85
_STRIP_TOKENS = {"fc", "afc", "cf", "sc", "club", "football", "futbol", "calcio"}


def normalize_team_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    tokens = [token for token in text.split() if token and token not in _STRIP_TOKENS]
    return " ".join(tokens)


def load_alias_map(path: Path | None = None) -> dict[str, str]:
    raw = json.loads((path or ALIASES_PATH).read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for canonical, aliases in raw.items():
        index[normalize_team_name(canonical)] = canonical
        for alias in aliases:
            index[normalize_team_name(alias)] = canonical
    return index


class TeamMatcher:
    """Matches a source team name against known teams by exact key, curated alias, then fuzzy."""

    def __init__(self, teams: list[Any], alias_map: dict[str, str] | None = None) -> None:
        self._teams = list(teams)
        self._alias_map = alias_map if alias_map is not None else load_alias_map()
        self._by_key: dict[str, Any] = {}
        for team in self._teams:
            candidates = [team.name_en, team.name_ch, *(team.aliases or [])]
            for candidate in candidates:
                if not candidate:
                    continue
                key = normalize_team_name(candidate)
                self._by_key.setdefault(key, team)
                canonical = self._alias_map.get(key)
                if canonical:
                    self._by_key.setdefault(normalize_team_name(canonical), team)

    def match(self, name: str) -> Any | None:
        key = normalize_team_name(name)
        if not key:
            return None
        if key in self._by_key:
            return self._by_key[key]
        canonical = self._alias_map.get(key)
        if canonical is not None:
            canonical_key = normalize_team_name(canonical)
            if canonical_key in self._by_key:
                return self._by_key[canonical_key]
        best: Any | None = None
        best_ratio = 0.0
        for candidate_key, team in self._by_key.items():
            ratio = SequenceMatcher(None, key, candidate_key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = team
        if best is not None and best_ratio >= FUZZY_THRESHOLD:
            return best
        return None
