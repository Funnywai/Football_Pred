"""Pure parsing helpers for StrikerAPI game and lineup payloads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrikerGame:
    game_id: str
    home_name: str
    away_name: str


@dataclass(frozen=True)
class LineupSide:
    abbreviation: str | None
    formation: str | None
    starters: tuple[str, ...]


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int):
            return str(value)
    return None


def _team_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _first_str(
            value.get("name"),
            value.get("team_name"),
            value.get("teamName"),
            value.get("short_name"),
        )
    return None


def parse_games(body: dict[str, object]) -> list[StrikerGame]:
    root = body.get("data") if isinstance(body.get("data"), dict) else body
    items = root.get("games") if isinstance(root, dict) else None
    if not isinstance(items, list):
        return []
    games: list[StrikerGame] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        game_id = _first_str(item.get("id"), item.get("game_id"), item.get("gameId"))
        home_name = _team_name(
            item.get("home_team") or item.get("home") or item.get("homeTeam")
        )
        away_name = _team_name(
            item.get("away_team") or item.get("away") or item.get("awayTeam")
        )
        if game_id is not None and home_name is not None and away_name is not None:
            games.append(StrikerGame(game_id, home_name, away_name))
    return games


def _player_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _first_str(value.get("name"), value.get("player_name"), value.get("playerName"))
    return None


def _parse_side(payload: object) -> LineupSide | None:
    if not isinstance(payload, dict):
        return None
    raw_team = payload.get("team")
    team = raw_team if isinstance(raw_team, dict) else {}
    abbreviation = _first_str(
        payload.get("abbreviation"),
        payload.get("abbrev"),
        payload.get("abbr"),
        payload.get("code"),
        team.get("abbreviation"),
        team.get("abbrev"),
    )
    formation = _first_str(payload.get("formation"), payload.get("shape"))
    raw_starters = (
        payload.get("starters")
        or payload.get("starting_xi")
        or payload.get("startingXI")
        or payload.get("lineup")
        or payload.get("players")
        or []
    )
    if isinstance(raw_starters, dict):
        raw_starters = raw_starters.get("players") or raw_starters.get("starters") or []
    starters = (
        tuple(
            name for item in raw_starters if (name := _player_name(item)) is not None
        )
        if isinstance(raw_starters, list)
        else ()
    )
    if abbreviation is None and formation is None and not starters:
        return None
    return LineupSide(abbreviation, formation, starters)


def _lineup_team_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    team = payload.get("team")
    if not isinstance(team, dict):
        team = {}
    return _first_str(payload.get("team_id"), team.get("id"), team.get("team_id"))


def _game_team_id(game: dict[str, object], side: str) -> str | None:
    value = game.get(side)
    if not isinstance(value, dict):
        return None
    return _first_str(value.get("team_id"), value.get("id"))


def parse_lineups(body: dict[str, object]) -> tuple[LineupSide | None, LineupSide | None]:
    root = body.get("data") if isinstance(body.get("data"), dict) else body
    if not isinstance(root, dict):
        return None, None
    raw_lineups = root.get("lineups")
    if isinstance(raw_lineups, list):
        game = root.get("game") if isinstance(root.get("game"), dict) else {}
        home_id = _game_team_id(game, "home")
        away_id = _game_team_id(game, "away")
        home: LineupSide | None = None
        away: LineupSide | None = None
        for item in raw_lineups:
            side = _parse_side(item)
            if side is None:
                continue
            team_id = _lineup_team_id(item)
            if team_id is not None and team_id == home_id:
                home = side
            elif team_id is not None and team_id == away_id:
                away = side
        if home is None and away is None:
            parsed = [_parse_side(item) for item in raw_lineups]
            if len(parsed) >= 1:
                home = parsed[0]
            if len(parsed) >= 2:
                away = parsed[1]
        return home, away
    section = root.get("lineups") if isinstance(root.get("lineups"), dict) else root
    if not isinstance(section, dict):
        return None, None
    home_payload = section.get("home") or section.get("home_lineup") or section.get("home_team")
    away_payload = section.get("away") or section.get("away_lineup") or section.get("away_team")
    return _parse_side(home_payload), _parse_side(away_payload)
