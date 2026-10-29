"""Lineups-only B analyst client for StrikerAPI.

The client deliberately exposes only ``list_games`` and ``get_lineups``. It has
no odds method, and no code path ever calls a StrikerAPI odds endpoint.
"""

from __future__ import annotations

import difflib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.agents.striker_parse import (
    LineupSide,
    StrikerGame,
    parse_games,
    parse_lineups,
)
from app.config import Settings

USER_AGENT = "football-pred-agent/1.0"
GAME_MATCH_THRESHOLD = 0.62
LEAGUE_SLUGS = {
    "EPL": "soccer",
    "LALIGA": "laliga",
    "SERIEA": "seriea",
    "BUNDESLIGA": "bundesliga",
    "LIGUE1": "ligue1",
    "UCL": "ucl",
}
_CLUB_TOKEN_SUFFIXES = frozenset({"fc", "afc", "cf", "sc", "ac", "club"})
_STANDARD_STARTERS = 11


class StrikerError(RuntimeError):
    """StrikerAPI is unavailable, misconfigured, or returned unusable JSON."""


@dataclass(frozen=True)
class LineupFetch:
    game_id: str | None
    home: LineupSide | None
    away: LineupSide | None
    home_name: str | None = None
    away_name: str | None = None
    home_score: float | None = None
    away_score: float | None = None
    missing: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    raw: dict[str, object] = field(default_factory=dict)


def league_slug(league_code: str) -> str:
    slug = LEAGUE_SLUGS.get(league_code.upper())
    if slug is None:
        raise StrikerError(f"no StrikerAPI league mapping for {league_code!r}")
    return slug


def season_year(kickoff: datetime) -> int:
    """European seasons start in July: pre-July kickoffs belong to the prior year."""
    return kickoff.year if kickoff.month >= 7 else kickoff.year - 1


def normalize_team_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in ascii_text)
    tokens = [token for token in cleaned.split() if token not in _CLUB_TOKEN_SUFFIXES]
    return " ".join(tokens)


_TEAM_ALIASES = {
    "wolves": "wolverhampton wanderers",
    "brighton": "brighton hove albion",
    "ath madrid": "atletico madrid",
    "ath bilbao": "athletic club",
    "bilbao": "athletic club",
    "betis": "real betis",
    "sociedad": "real sociedad",
    "vallecano": "rayo vallecano",
    "sp gijon": "sporting gijon",
    "deportivo": "deportivo la coruna",
    "la coruna": "deportivo la coruna",
    "nott m forest": "nottingham forest",
    "man city": "manchester city",
    "man united": "manchester united",
    "newcastle": "newcastle united",
    "tottenham": "tottenham hotspur",
    "west ham": "west ham united",
    "hull": "hull city",
    "psg": "paris saint germain",
    "m gladbach": "borussia m gladbach",
    "monchengladbach": "borussia m gladbach",
    "gladbach": "borussia m gladbach",
    "ein frankfurt": "eintracht frankfurt",
    "frankfurt": "eintracht frankfurt",
    "hertha": "hertha berlin",
    "rb leipzig": "rasenballsport leipzig",
    "leverkusen": "bayer leverkusen",
    "dortmund": "borussia dortmund",
    "stuttgart": "vfb stuttgart",
    "hamburg": "hamburger sv",
    "nuernberg": "nurnberg",
    "greuther fuerth": "greuther furth",
    "fortuna duesseldorf": "fortuna dusseldorf",
    "sd huesca": "huesca",
    "parma": "parma calcio 1913",
    "spal": "spal 2013",
}


def _canonical_name(name: str) -> str:
    normalized = normalize_team_name(name)
    return _TEAM_ALIASES.get(normalized, normalized)


def team_similarity(left: str, right: str) -> float:
    left_key = _canonical_name(left)
    right_key = _canonical_name(right)
    ratio = difflib.SequenceMatcher(None, left_key, right_key).ratio()
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    if left_tokens and right_tokens and (
        left_tokens <= right_tokens or right_tokens <= left_tokens
    ):
        ratio = max(ratio, 0.9)
    return ratio


def find_game(
    games: Sequence[StrikerGame], home_name: str, away_name: str
) -> tuple[StrikerGame | None, float, float]:
    """Pick the best game whose two team-name similarities both clear the threshold."""
    best: StrikerGame | None = None
    best_scores = (0.0, 0.0)
    best_combined = -1.0
    for game in games:
        home_score = team_similarity(home_name, game.home_name)
        away_score = team_similarity(away_name, game.away_name)
        combined = home_score + away_score
        if min(home_score, away_score) < GAME_MATCH_THRESHOLD:
            continue
        if combined > best_combined:
            best, best_scores, best_combined = game, (home_score, away_score), combined
    if best is None:
        return None, 0.0, 0.0
    return best, best_scores[0], best_scores[1]


def classify_lineups(
    home: LineupSide | None, away: LineupSide | None
) -> tuple[list[str], list[str]]:
    if home is None and away is None:
        return ["lineups"], ["lineups not published"]
    if home is None or away is None:
        return ["lineups"], ["partial lineups: one side missing"]
    if (
        len(home.starters) != _STANDARD_STARTERS
        or len(away.starters) != _STANDARD_STARTERS
    ):
        return ["partial_starters"], ["partial starting XI"]
    return [], []


class StrikerLineupsClient:
    def __init__(
        self, settings: Settings, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url: str = settings.striker_base_url.rstrip("/")
        self._api_key: str = settings.striker_api_key
        self._owns_client: bool = http_client is None
        self._client: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=settings.striker_timeout_seconds
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        if not self._api_key:
            raise StrikerError("striker_api_key is not configured")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            response = await self._client.post(
                f"{self._base_url}{path}", headers=headers, json=payload
            )
        except httpx.HTTPError as exc:
            raise StrikerError(f"StrikerAPI request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise StrikerError(f"StrikerAPI returned HTTP {response.status_code}")
        try:
            body: object = response.json()
        except ValueError as exc:
            raise StrikerError("StrikerAPI response body is not JSON") from exc
        if not isinstance(body, dict):
            raise StrikerError("StrikerAPI response body is not an object")
        return body

    async def list_games(
        self, *, league_code: str, kickoff: datetime
    ) -> list[StrikerGame]:
        body = await self._post(
            "/v1/list_games",
            {
                "league": league_slug(league_code),
                "date": kickoff.date().isoformat(),
                "season": season_year(kickoff),
                "status": "scheduled",
                "limit": 50,
            },
        )
        return parse_games(body)

    async def get_lineups(
        self, *, league_code: str, game_id: str
    ) -> tuple[LineupSide | None, LineupSide | None]:
        body = await self._post(
            "/v1/get_lineups",
            {"league": league_slug(league_code), "game_id": game_id},
        )
        return parse_lineups(body)

    async def fetch_lineups(
        self,
        *,
        league_code: str,
        kickoff: datetime,
        home_name: str,
        away_name: str,
    ) -> LineupFetch:
        list_body = await self._post(
            "/v1/list_games",
            {
                "league": league_slug(league_code),
                "date": kickoff.date().isoformat(),
                "season": season_year(kickoff),
                "status": "scheduled",
                "limit": 50,
            },
        )
        games = parse_games(list_body)
        game, home_score, away_score = find_game(games, home_name, away_name)
        if game is None:
            return LineupFetch(
                None,
                None,
                None,
                missing=("striker_game",),
                uncertainties=("team mapping failure",),
                raw={"list_games": list_body},
            )
        lineup_body = await self._post(
            "/v1/get_lineups",
            {"league": league_slug(league_code), "game_id": game.game_id},
        )
        home, away = parse_lineups(lineup_body)
        missing, uncertainties = classify_lineups(home, away)
        return LineupFetch(
            game.game_id,
            home,
            away,
            home_name=game.home_name,
            away_name=game.away_name,
            home_score=home_score,
            away_score=away_score,
            missing=tuple(missing),
            uncertainties=tuple(uncertainties),
            raw={"list_games": list_body, "get_lineups": lineup_body},
        )
