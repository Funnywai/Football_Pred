from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Team
from packages.domain.errors import UnresolvedTeamError

TEAM_ALIASES: dict[str, str] = {
    "Arsenal": "arsenal",
    "Arsenal FC": "arsenal",
    "Manchester City": "manchester-city",
    "Manchester City FC": "manchester-city",
    "Man City": "manchester-city",
    "Manchester United": "manchester-united",
    "Manchester United FC": "manchester-united",
    "Man United": "manchester-united",
    "Man Utd": "manchester-united",
    "Man U": "manchester-united",
    "Liverpool": "liverpool",
    "Liverpool FC": "liverpool",
    "Tottenham": "tottenham",
    "Spurs": "tottenham",
    "Tottenham Hotspur": "tottenham",
    "Tottenham Hotspur FC": "tottenham",
    "Chelsea": "chelsea",
    "Chelsea FC": "chelsea",
    "Newcastle": "newcastle-united",
    "Newcastle United": "newcastle-united",
    "Newcastle United FC": "newcastle-united",
    "Aston Villa": "aston-villa",
    "Aston Villa FC": "aston-villa",
    "Everton": "everton",
    "Everton FC": "everton",
    "Fulham": "fulham",
    "Fulham FC": "fulham",
    "Brentford": "brentford",
    "Brentford FC": "brentford",
    "Crystal Palace": "crystal-palace",
    "Crystal Palace FC": "crystal-palace",
    "Nottingham Forest": "nottingham-forest",
    "Nottingham Forest FC": "nottingham-forest",
    "Nott'm Forest": "nottingham-forest",
    "West Ham": "west-ham-united",
    "West Ham United": "west-ham-united",
    "West Ham United FC": "west-ham-united",
    "Brighton": "brighton-hove-albion",
    "Brighton & Hove Albion": "brighton-hove-albion",
    "Brighton & Hove Albion FC": "brighton-hove-albion",
    "Wolves": "wolverhampton-wanderers",
    "Wolverhampton Wanderers": "wolverhampton-wanderers",
    "Wolverhampton Wanderers FC": "wolverhampton-wanderers",
    "Bournemouth": "afc-bournemouth",
    "AFC Bournemouth": "afc-bournemouth",
    "Leicester": "leicester-city",
    "Leicester City": "leicester-city",
    "Leicester City FC": "leicester-city",
    "Ipswich": "ipswich-town",
    "Ipswich Town": "ipswich-town",
    "Ipswich Town FC": "ipswich-town",
    "Leeds": "leeds-united",
    "Leeds United": "leeds-united",
    "Leeds United FC": "leeds-united",
    "Burnley": "burnley",
    "Burnley FC": "burnley",
    "Sunderland": "sunderland",
    "Sunderland AFC": "sunderland",
    "Sheffield United": "sheffield-united",
    "Sheffield United FC": "sheffield-united",
    "Sheffield Utd": "sheffield-united",
    "Sheffield Wednesday": "sheffield-wednesday",
    "Sheffield Wednesday FC": "sheffield-wednesday",
    "Southampton": "southampton",
    "Southampton FC": "southampton",
    "Norwich City": "norwich-city",
    "Norwich City FC": "norwich-city",
    "Watford": "watford",
    "Watford FC": "watford",
    "Paris Saint-Germain": "paris-saint-germain",
    "Paris SG": "paris-saint-germain",
    "PSG": "paris-saint-germain",
    "Bayern Munich": "bayern-munich",
    "Bayern München": "bayern-munich",
    "Borussia Dortmund": "borussia-dortmund",
    "Dortmund": "borussia-dortmund",
    "Internazionale": "inter-milan",
    "Inter": "inter-milan",
    "Inter Milan": "inter-milan",
    "AC Milan": "ac-milan",
    "Milan": "ac-milan",
    "Atletico Madrid": "atletico-madrid",
    "Atlético Madrid": "atletico-madrid",
    "Athletic Club": "athletic-bilbao",
    "Athletic Bilbao": "athletic-bilbao",
    "Barcelona": "barcelona",
    "FC Barcelona": "barcelona",
    "Real Madrid": "real-madrid",
    "Real Madrid CF": "real-madrid",
    "Real Sociedad": "real-sociedad",
    "Real Betis": "real-betis",
    "Villarreal": "villarreal",
    "Villarreal CF": "villarreal",
    "Valencia": "valencia",
    "Valencia CF": "valencia",
    "Sevilla": "sevilla",
    "Sevilla FC": "sevilla",
    "Girona": "girona",
    "Girona FC": "girona",
    "Celta Vigo": "celta-vigo",
    "Rayo Vallecano": "rayo-vallecano",
    "Osasuna": "osasuna",
    "CA Osasuna": "osasuna",
    "Mallorca": "mallorca",
    "RCD Mallorca": "mallorca",
    "Getafe": "getafe",
    "Getafe CF": "getafe",
    "Alaves": "alaves",
    "Deportivo Alavés": "alaves",
    "Espanyol": "espanyol",
    "RCD Espanyol": "espanyol",
    "Elche": "elche",
    "Elche CF": "elche",
    "Levante": "levante",
    "Levante UD": "levante",
    "Real Oviedo": "real-oviedo",
    "RB Leipzig": "rb-leipzig",
    "Bayer Leverkusen": "bayer-leverkusen",
    "Bayer 04 Leverkusen": "bayer-leverkusen",
    "Eintracht Frankfurt": "eintracht-frankfurt",
    "VfB Stuttgart": "vfb-stuttgart",
    "Borussia Monchengladbach": "borussia-monchengladbach",
    "Borussia Mönchengladbach": "borussia-monchengladbach",
    "Wolfsburg": "vfl-wolfsburg",
    "VfL Wolfsburg": "vfl-wolfsburg",
    "Union Berlin": "union-berlin",
    "1. FC Union Berlin": "union-berlin",
    "Freiburg": "sc-freiburg",
    "SC Freiburg": "sc-freiburg",
    "Mainz 05": "mainz-05",
    "1. FSV Mainz 05": "mainz-05",
    "Werder Bremen": "werder-bremen",
    "SV Werder Bremen": "werder-bremen",
    "Augsburg": "augsburg",
    "FC Augsburg": "augsburg",
    "Hoffenheim": "hoffenheim",
    "TSG Hoffenheim": "hoffenheim",
    "St Pauli": "st-pauli",
    "FC St. Pauli": "st-pauli",
    "Heidenheim": "heidenheim",
    "1. FC Heidenheim": "heidenheim",
    "Holstein Kiel": "holstein-kiel",
    "Bochum": "vfl-bochum",
    "VfL Bochum": "vfl-bochum",
    "Juventus": "juventus",
    "Napoli": "napoli",
    "SSC Napoli": "napoli",
    "Roma": "roma",
    "AS Roma": "roma",
    "Lazio": "lazio",
    "SS Lazio": "lazio",
    "Atalanta": "atalanta",
    "Fiorentina": "fiorentina",
    "ACF Fiorentina": "fiorentina",
    "Bologna": "bologna",
    "Torino": "torino",
    "Genoa": "genoa",
    "Udinese": "udinese",
    "Como": "como",
    "Cagliari": "cagliari",
    "Lecce": "lecce",
    "Parma": "parma",
    "Verona": "verona",
    "Hellas Verona": "verona",
    "Empoli": "empoli",
    "Venezia": "venezia",
    "Monza": "monza",
    "Marseille": "olympique-marseille",
    "Olympique de Marseille": "olympique-marseille",
    "Monaco": "as-monaco",
    "AS Monaco": "as-monaco",
    "Lyon": "olympique-lyonnais",
    "Olympique Lyonnais": "olympique-lyonnais",
    "Lille": "lille",
    "Lille OSC": "lille",
    "Nice": "ogc-nice",
    "OGC Nice": "ogc-nice",
    "Rennes": "stade-rennais",
    "Stade Rennais": "stade-rennais",
    "Lens": "rc-lens",
    "RC Lens": "rc-lens",
    "Nantes": "fc-nantes",
    "FC Nantes": "fc-nantes",
    "Strasbourg": "rc-strasbourg-alsace",
    "RC Strasbourg": "rc-strasbourg-alsace",
    "Toulouse": "toulouse",
    "Toulouse FC": "toulouse",
    "Montpellier": "montpellier",
    "Montpellier HSC": "montpellier",
    "Brest": "stade-brestois-29",
    "Stade Brestois": "stade-brestois-29",
    "Auxerre": "auxerre",
    "AJ Auxerre": "auxerre",
    "Angers": "angers",
    "Angers SCO": "angers",
    "Le Havre": "le-havre",
    "Le Havre AC": "le-havre",
    "Reims": "stade-reims",
    "Stade de Reims": "stade-reims",
    "Saint-Etienne": "saint-etienne",
    "AS Saint-Etienne": "saint-etienne",
    "Betis": "real-betis",
    "Atletico de Madrid": "atletico-madrid",
    "Atlético de Madrid": "atletico-madrid",
    "Celta de Vigo": "celta-vigo",
    "FC Bayern München": "bayern-munich",
    "FC Bayern Munich": "bayern-munich",
    "Stade Brestois 29": "stade-brestois-29",
    "RC Strasbourg Alsace": "rc-strasbourg-alsace",
}


_ALIASES_CASEFOLD: dict[str, str] = {
    name.casefold(): slug for name, slug in TEAM_ALIASES.items()
}


def canonical_team_slug(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("team name must be a non-empty string")
    normalized_name = name.strip()
    alias = TEAM_ALIASES.get(normalized_name)
    if alias is None:
        alias = _ALIASES_CASEFOLD.get(normalized_name.casefold())
    if alias is not None:
        return alias
    normalized = unicodedata.normalize(
        "NFKD", normalized_name
    ).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        raise ValueError(f"team name {name!r} has no canonical slug")
    return slug


def resolve_team_id(session: Session, name: str) -> uuid.UUID:
    slug = canonical_team_slug(name)
    team = session.execute(select(Team).where(Team.slug == slug)).scalar_one_or_none()
    if team is None:
        raise UnresolvedTeamError(f"no team with slug {slug} for source name {name}")
    return team.id


def ensure_team(
    session: Session,
    name: str,
    *,
    country: str,
    short_name: str | None = None,
    football_data_id: int | None = None,
) -> uuid.UUID:
    """Create the canonical team row when the source fixture is first seen."""
    slug = canonical_team_slug(name)
    team = session.execute(select(Team).where(Team.slug == slug)).scalar_one_or_none()
    if team is None:
        cleaned = name.strip()
        team = Team(
            slug=slug,
            name=cleaned,
            short_name=(short_name or cleaned)[:48],
            country=(country.strip() or "Unknown")[:64],
            football_data_id=football_data_id,
        )
        session.add(team)
        session.flush()
    elif football_data_id is not None and team.football_data_id is None:
        team.football_data_id = football_data_id
    return team.id
