from dataclasses import dataclass, field

from app.services.alias import TeamMatcher, load_alias_map, normalize_team_name


@dataclass
class _Team:
    name_en: str
    name_ch: str | None = None
    aliases: list[str] = field(default_factory=list)


def _teams() -> list[_Team]:
    return [
        _Team("Manchester United", "曼聯", ["Man Utd", "Man United"]),
        _Team("Manchester City", "曼城", ["Man City"]),
        _Team("Tottenham Hotspur", "熱刺", ["Tottenham", "Spurs"]),
        _Team("Liverpool", "利物浦", ["Liverpool FC"]),
    ]


def test_normalize_team_name():
    assert normalize_team_name("Manchester United FC") == "manchester united"
    assert normalize_team_name("Nott'm Forest") == "nott m forest"
    assert normalize_team_name("Atlético Madrid") == "atletico madrid"
    assert normalize_team_name("  曼聯  ") == "曼聯"


def test_alias_map_loads_canonical_names():
    alias_map = load_alias_map()
    assert alias_map[normalize_team_name("曼聯")] == "Manchester United"
    assert alias_map[normalize_team_name("Spurs")] == "Tottenham Hotspur"


def test_match_by_chinese_name():
    matcher = TeamMatcher(_teams())
    assert matcher.match("曼聯").name_en == "Manchester United"


def test_match_by_alias():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Man Utd").name_en == "Manchester United"
    assert matcher.match("Spurs").name_en == "Tottenham Hotspur"


def test_match_by_canonical_name():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Manchester United").name_en == "Manchester United"


def test_match_fuzzy_typo():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Manchester Untied").name_en == "Manchester United"


def test_match_returns_none_for_unknown():
    matcher = TeamMatcher(_teams())
    assert matcher.match("Real Madrid") is None
