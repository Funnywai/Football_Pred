"""Phase 3a tests: lineups-only B briefs and the C decision agent (paper only)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from ml_helpers import make_db, seed_context, seed_finished_match, seed_team
from sqlalchemy import func, select

from app.agents.analyst import build_brief
from app.agents.decision import AGENT_DECISION, decide_abc
from app.agents.ledger import (
    AGENT_ABC_JOB_ID,
    agent_abc_update,
    place_agent_bets,
)
from app.agents.llm import (
    AgentLLMClient,
    AgentLLMError,
    redacted_headers,
    session_id_for,
)
from app.agents.risk import evaluate_risk
from app.agents.striker import (
    LineupFetch,
    LineupSide,
    StrikerError,
    StrikerGame,
    StrikerLineupsClient,
    find_game,
    season_year,
    team_similarity,
)
from app.agents.striker_parse import parse_lineups
from app.api.main import create_app
from app.cli import main
from app.config import Settings
from app.db.models import (
    AgentBet,
    AgentDecision,
    AnalystBrief,
    IngestionRun,
    LedgerBet,
    ModelVersion,
    Prediction,
    ShadowLedgerBet,
)

KICKOFF = datetime.now(UTC) + timedelta(days=30)
HAD = {"lines": [{"combinations": [
    {"str": "H", "currentOdds": "2.1"}, {"str": "D", "currentOdds": "3.4"},
    {"str": "A", "currentOdds": "3.8"}]}]}


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        striker_api_key="sk-striker",
        agent_llm_base_url="https://llm.test/v1",
        agent_llm_api_key="sk-llm",
        **overrides,
    )


def _side(abbreviation: str, *, count: int = 11) -> LineupSide:
    return LineupSide(
        abbreviation,
        "4-3-3",
        tuple(f"{abbreviation}-{index}" for index in range(count)),
    )


def _fetch(
    home: LineupSide | None = None,
    away: LineupSide | None = None,
    *,
    game_id: str | None = "g1",
) -> LineupFetch:
    return LineupFetch(
        game_id,
        home,
        away,
        home_name="Home FC",
        away_name="Away United",
        home_score=0.95,
        away_score=0.9,
        raw={"fake": True},
    )


class FakeStriker:
    def __init__(self, fetch: LineupFetch) -> None:
        self.fetch = fetch
        self.calls: list[dict[str, object]] = []

    async def fetch_lineups(self, **kwargs: object) -> LineupFetch:
        self.calls.append(kwargs)
        return self.fetch


class RaisingStriker:
    async def fetch_lineups(self, **kwargs: object) -> LineupFetch:
        raise StrikerError("upstream unavailable")


class FakeLLM:
    def __init__(
        self, response: dict[str, object] | None = None, error: Exception | None = None
    ) -> None:
        self.response = response or {}
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 500,
        session_id: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "session_id": session_id,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


async def _seed_world(tmp_path, *, had_payload: dict | None = HAD) -> tuple:
    db = await make_db(tmp_path)
    async with db.session_factory() as session:
        league, season = await seed_context(session)
        home = await seed_team(session, "Home")
        away = await seed_team(session, "Away")
        match = await seed_finished_match(
            session,
            league,
            season,
            home,
            away,
            match_id_label="M1",
            kickoff=KICKOFF,
            home_score=2,
            away_score=1,
            had_payload=had_payload,
        )
        version = ModelVersion(
            target="1x2",
            algorithm="lightgbm",
            params={},
            metrics={},
            artifact_path="/tmp/m1.joblib",
            status="champion",
        )
        session.add(version)
        await session.commit()
        return db, match.id, version.id


async def _add_prediction(
    db, match_id: int, version_id: int, *, outcome: str = "H", prob: float = 0.52
) -> None:
    async with db.session_factory() as session:
        session.add(
            Prediction(
                match_id=match_id,
                target="1x2",
                outcome=outcome,
                model_version_id=version_id,
                prob=prob,
                implied_prob=0.45,
                edge=0.05,
                fair_odds=1.0 / prob,
                market_odds=2.1,
                recommended_fraction=0.0,
            )
        )
        await session.commit()


async def _risk_run(db, settings: Settings) -> str:
    async with db.session_factory() as session:
        summary = await evaluate_risk(session, settings)
        await session.commit()
    return summary.run_id


async def _a_bet(db) -> AgentDecision:
    async with db.session_factory() as session:
        return (
            await session.execute(
                select(AgentDecision).where(
                    AgentDecision.agent == "risk", AgentDecision.action == "bet"
                )
            )
        ).scalar_one()


async def _c_decisions(db) -> list[AgentDecision]:
    async with db.session_factory() as session:
        return (
            await session.execute(
                select(AgentDecision)
                .where(AgentDecision.agent == AGENT_DECISION)
                .order_by(AgentDecision.id)
            )
        ).scalars().all()


async def _client(db) -> httpx.AsyncClient:
    app = create_app(settings=Settings(_env_file=None, enable_scheduler=False), db=db)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_season_year_starts_in_july() -> None:
    assert season_year(datetime(2026, 7, 1, tzinfo=UTC)) == 2026
    assert season_year(datetime(2026, 6, 30, tzinfo=UTC)) == 2025
    assert season_year(datetime(2027, 1, 15, tzinfo=UTC)) == 2026


def test_find_game_requires_both_names_above_threshold() -> None:
    games = [
        StrikerGame("g1", "Home FC", "Away FC"),
        StrikerGame("g2", "Other", "Team"),
    ]
    game, home_score, away_score = find_game(games, "Home", "Away")
    assert game is not None
    assert game.game_id == "g1"
    assert home_score >= 0.62
    assert away_score >= 0.62
    assert find_game([StrikerGame("g9", "Completely", "Different")], "Home", "Away") == (
        None,
        0.0,
        0.0,
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Brighton", "Brighton & Hove Albion"),
        ("Wolves", "Wolverhampton Wanderers"),
        ("Ath Madrid", "Atletico Madrid"),
        ("Betis", "Real Betis"),
        ("Hull", "Hull City"),
        ("Man City", "Manchester City"),
        ("Nott'm Forest", "Nottingham Forest"),
        ("PSG", "Paris Saint Germain"),
        ("Ein Frankfurt", "Eintracht Frankfurt"),
        ("M'gladbach", "Borussia M.Gladbach"),
        ("Leverkusen", "Bayer Leverkusen"),
        ("Dortmund", "Borussia Dortmund"),
        ("Hertha", "Hertha Berlin"),
        ("Stuttgart", "VfB Stuttgart"),
    ],
)
def test_team_similarity_handles_common_short_and_long_names(
    left: str, right: str
) -> None:
    assert team_similarity(left, right) >= 0.62


def test_find_game_matches_short_db_names_to_full_striker_names() -> None:
    games = [
        StrikerGame("g1", "Brighton & Hove Albion", "Wolverhampton Wanderers"),
        StrikerGame("g2", "Liverpool", "Brentford"),
    ]
    game, home_score, away_score = find_game(games, "Brighton", "Wolves")
    assert game is not None and game.game_id == "g1"
    assert home_score >= 0.62 and away_score >= 0.62


def test_parse_lineups_handles_live_list_shape_and_team_ids() -> None:
    body = {
        "data": {
            "game": {"home": {"team_id": "364"}, "away": {"team_id": "331"}},
            "lineups": [
                {
                    "team_id": "331",
                    "abbrev": "AWY",
                    "formation": "4-3-3",
                    "starting_xi": [{"name": f"A-{index}"} for index in range(11)],
                },
                {
                    "team_id": "364",
                    "abbrev": "HOM",
                    "formation": "4-2-3-1",
                    "starting_xi": [{"name": f"H-{index}"} for index in range(11)],
                },
            ],
        }
    }
    home, away = parse_lineups(body)
    assert home is not None and away is not None
    assert home.abbreviation == "HOM" and home.formation == "4-2-3-1"
    assert len(home.starters) == 11
    assert away.abbreviation == "AWY" and away.formation == "4-3-3"
    assert len(away.starters) == 11


async def test_striker_client_maps_game_and_parses_lineups_without_odds() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    home = _side("HOM")
    away = _side("AWY")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == "/v1/list_games":
            return httpx.Response(
                200,
                json={
                    "games": [
                        {"id": "g1", "home_team": "Home FC", "away_team": "Away FC"},
                        {"id": "g2", "home_team": "Other", "away_team": "Team"},
                    ]
                },
            )
        assert request.url.path == "/v1/get_lineups"
        return httpx.Response(
            200,
            json={
                "home": {
                    "abbreviation": "HOM",
                    "formation": "4-3-3",
                    "starters": list(home.starters),
                },
                "away": {
                    "abbreviation": "AWY",
                    "formation": "4-3-3",
                    "starters": list(away.starters),
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = StrikerLineupsClient(_settings(), http_client=http_client)
    try:
        result = await client.fetch_lineups(
            league_code="EPL",
            kickoff=datetime(2026, 8, 1, 12, tzinfo=UTC),
            home_name="Home",
            away_name="Away",
        )
    finally:
        await http_client.aclose()

    assert result.game_id == "g1"
    assert result.home is not None and len(result.home.starters) == 11
    assert result.away is not None and result.away.abbreviation == "AWY"
    assert result.missing == ()
    assert calls[0][0] == "/v1/list_games"
    assert calls[0][1] == {
        "league": "soccer",
        "date": "2026-08-01",
        "season": 2026,
        "status": "scheduled",
        "limit": 50,
    }
    assert calls[1] == ("/v1/get_lineups", {"league": "soccer", "game_id": "g1"})
    assert all("odds" not in path for path, _ in calls)


async def test_striker_client_unmapped_game_returns_missing_without_lineups_call() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200, json={"games": [{"id": "g9", "home": "Other", "away": "Team"}]}
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = StrikerLineupsClient(_settings(), http_client=http_client)
    try:
        result = await client.fetch_lineups(
            league_code="EPL",
            kickoff=datetime(2026, 8, 1, 12, tzinfo=UTC),
            home_name="Home",
            away_name="Away",
        )
    finally:
        await http_client.aclose()

    assert result.game_id is None
    assert result.home is None and result.away is None
    assert result.missing == ("striker_game",)
    assert "team mapping failure" in result.uncertainties
    assert paths == ["/v1/list_games"]


async def test_build_brief_is_idempotent_and_records_full_lineups(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        fake = FakeStriker(_fetch(_side("HOM"), _side("AWY")))
        async with db.session_factory() as session:
            first = await build_brief(session, _settings(), run_id, match_id, fake)
            await session.commit()
        async with db.session_factory() as session:
            second = await build_brief(session, _settings(), run_id, match_id, fake)
            await session.commit()
            total = (
                await session.execute(select(func.count()).select_from(AnalystBrief))
            ).scalar_one()

        assert first.id == second.id
        assert total == 1
        assert len(fake.calls) == 1
        assert first.source == "striker"
        assert first.trust_score == 1.0
        assert first.missing == []
        assert first.uncertainties == []
        assert first.facts["lineups_available"] is True
        assert first.facts["home_abbreviation"] == "HOM"
        assert first.facts["away_abbreviation"] == "AWY"
        assert first.facts["home_formation"] == "4-3-3"
        assert first.facts["home_starters"] == 11
        assert first.facts["away_starters"] == 11
        assert first.facts["game_id"] == "g1"
        assert first.facts["source"] == "striker"
        assert first.captured_at.tzinfo is not None
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    ("fetch", "trust", "missing", "available"),
    [
        (_fetch(_side("HOM"), _side("AWY", count=10)), 0.4545, ["partial_starters"], True),
        (_fetch(_side("HOM"), None), 0.0, ["lineups"], False),
        (_fetch(None, None), 0.0, ["lineups"], False),
    ],
)
async def test_build_brief_lowers_trust_for_partial_or_missing(
    tmp_path,
    fetch: LineupFetch,
    trust: float,
    missing: list[str],
    available: bool,
) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        async with db.session_factory() as session:
            brief = await build_brief(
                session, _settings(), run_id, match_id, FakeStriker(fetch)
            )
            await session.commit()
        assert brief.trust_score == pytest.approx(trust)
        assert brief.missing == missing
        assert brief.facts["lineups_available"] is available
    finally:
        await db.dispose()


async def test_build_brief_records_api_error_without_fabricating(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        async with db.session_factory() as session:
            brief = await build_brief(
                session, _settings(), run_id, match_id, RaisingStriker()
            )
            await session.commit()
        assert brief.trust_score == 0.0
        assert brief.missing == ["striker_api_error"]
        assert "upstream unavailable" in brief.uncertainties[0]
        assert brief.facts["lineups_available"] is False
    finally:
        await db.dispose()


async def test_decide_abc_window_skips_far_future_matches(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        llm = FakeLLM({"decision": "approve", "confidence": 0.9, "reason": "ok"})
        striker = FakeStriker(_fetch(_side("HOM"), _side("AWY")))
        async with db.session_factory() as session:
            summary = await decide_abc(
                session,
                _settings(),
                run_id,
                llm,
                striker_client=striker,
                max_kickoff_minutes=45,
            )
            await session.commit()
        assert summary.candidates == 0
        assert llm.calls == []
        assert striker.calls == []
        assert await _c_decisions(db) == []
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    "fetch",
    [
        _fetch(None, None),
        _fetch(_side("HOM"), _side("AWY", count=9)),
    ],
)
async def test_decide_abc_prefilter_skips_llm_when_lineups_missing(
    tmp_path, fetch: LineupFetch
) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        llm = FakeLLM({"decision": "approve", "confidence": 0.9, "reason": "ok"})
        async with db.session_factory() as session:
            brief = await build_brief(
                session, _settings(), run_id, match_id, FakeStriker(fetch)
            )
            summary = await decide_abc(
                session, _settings(), run_id, llm, briefs=[brief]
            )
            await session.commit()
        rows = await _c_decisions(db)
        assert summary.prefilters == 1
        assert summary.llm_calls == 0
        assert llm.calls == []
        assert len(rows) == 1
        assert rows[0].action == "no_bet"
        assert rows[0].agent == "decision"
        assert rows[0].reason.startswith("prefilter:")
        assert rows[0].stake is None and rows[0].odds is None
        assert rows[0].input_snapshot["llm_called"] is False
    finally:
        await db.dispose()


async def test_decide_abc_approve_inherits_a_values_and_snapshot(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        settings = _settings()
        run_id = await _risk_run(db, settings)
        a_decision = await _a_bet(db)
        llm = FakeLLM(
            {"decision": "approve", "confidence": 0.82, "reason": "lineups complete"}
        )
        async with db.session_factory() as session:
            brief = await build_brief(
                session,
                settings,
                run_id,
                match_id,
                FakeStriker(_fetch(_side("HOM"), _side("AWY"))),
            )
            summary = await decide_abc(session, settings, run_id, llm, briefs=[brief])
            await session.commit()

        rows = await _c_decisions(db)
        assert summary.approved == 1 and summary.rejected == 0
        assert summary.llm_calls == 1 and summary.briefs == 1
        assert len(llm.calls) == 1
        assert llm.calls[0]["session_id"] == session_id_for(run_id, match_id)
        row = rows[0]
        assert row.action == "bet"
        assert row.outcome == a_decision.outcome
        assert row.stake == pytest.approx(a_decision.stake)
        assert row.odds == pytest.approx(a_decision.odds)
        assert row.edge == pytest.approx(a_decision.edge)
        assert row.confidence == pytest.approx(0.82)
        assert "lineups complete" in row.reason
        snapshot = row.input_snapshot
        assert snapshot["a_decision_id"] == a_decision.id
        assert snapshot["brief_id"] == brief.id
        assert snapshot["model"] == "deepseek-v4.1-flash"
        assert "prompt" in snapshot and "response" in snapshot
        assert "sk-llm" not in json.dumps(snapshot)
    finally:
        await db.dispose()


async def test_decide_abc_reject_writes_no_bet_without_inheriting_values(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        llm = FakeLLM(
            {"decision": "reject", "confidence": 0.4, "reason": "late team news"}
        )
        async with db.session_factory() as session:
            brief = await build_brief(
                session,
                _settings(),
                run_id,
                match_id,
                FakeStriker(_fetch(_side("HOM"), _side("AWY"))),
            )
            summary = await decide_abc(
                session, _settings(), run_id, llm, briefs=[brief]
            )
            await session.commit()
        rows = await _c_decisions(db)
        assert summary.rejected == 1 and summary.approved == 0
        assert rows[0].action == "no_bet"
        assert rows[0].stake is None
        assert rows[0].odds is None
        assert rows[0].edge is None
        assert rows[0].confidence == pytest.approx(0.4)
        assert "late team news" in rows[0].reason
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    ("response", "error", "reason_prefix"),
    [
        ({"decision": "maybe", "confidence": 0.5}, None, "llm_malformed"),
        ({"decision": "approve", "confidence": 2.0}, None, "llm_malformed"),
        (None, AgentLLMError("timeout"), "llm_error"),
    ],
)
async def test_decide_abc_malformed_or_error_becomes_no_bet(
    tmp_path,
    response: dict[str, object] | None,
    error: Exception | None,
    reason_prefix: str,
) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        llm = FakeLLM(response, error)
        async with db.session_factory() as session:
            brief = await build_brief(
                session,
                _settings(),
                run_id,
                match_id,
                FakeStriker(_fetch(_side("HOM"), _side("AWY"))),
            )
            summary = await decide_abc(
                session, _settings(), run_id, llm, briefs=[brief]
            )
            await session.commit()
        rows = await _c_decisions(db)
        assert summary.llm_calls == 1
        assert summary.rejected == 1
        assert rows[0].action == "no_bet"
        assert rows[0].stake is None
        assert rows[0].reason.startswith(reason_prefix)
    finally:
        await db.dispose()


async def test_decide_abc_with_no_a_bet_writes_no_c_decision(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path, had_payload=None)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        llm = FakeLLM({"decision": "approve", "confidence": 0.9, "reason": "ok"})
        async with db.session_factory() as session:
            summary = await decide_abc(session, _settings(), run_id, llm)
            await session.commit()
        assert summary.candidates == 0
        assert summary.briefs == 0
        assert llm.calls == []
        assert await _c_decisions(db) == []
    finally:
        await db.dispose()


async def test_place_agent_bets_routes_variants_to_their_own_agent(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        settings = _settings()
        run_id = await _risk_run(db, settings)
        llm = FakeLLM(
            {"decision": "approve", "confidence": 0.9, "reason": "lineups complete"}
        )
        async with db.session_factory() as session:
            brief = await build_brief(
                session,
                settings,
                run_id,
                match_id,
                FakeStriker(_fetch(_side("HOM"), _side("AWY"))),
            )
            await decide_abc(session, settings, run_id, llm, briefs=[brief])
            await session.commit()

        async with db.session_factory() as session:
            assert await place_agent_bets(session, settings, run_id, "a_only") == 1
            assert await place_agent_bets(session, settings, run_id, "abc") == 1
            assert await place_agent_bets(session, settings, run_id, "abc") == 0
            await session.commit()
            bets = (
                await session.execute(select(AgentBet).order_by(AgentBet.id))
            ).scalars().all()
            assert [(bet.variant, bet.outcome) for bet in bets] == [
                ("a_only", "H"),
                ("abc", "H"),
            ]
            assert (
                await session.execute(select(func.count()).select_from(LedgerBet))
            ).scalar_one() == 0
            assert (
                await session.execute(select(func.count()).select_from(ShadowLedgerBet))
            ).scalar_one() == 0
    finally:
        await db.dispose()


async def test_place_abc_skips_risk_bet_when_c_rejected(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        settings = _settings()
        run_id = await _risk_run(db, settings)
        llm = FakeLLM(
            {"decision": "reject", "confidence": 0.7, "reason": "rotation risk"}
        )
        async with db.session_factory() as session:
            brief = await build_brief(
                session,
                settings,
                run_id,
                match_id,
                FakeStriker(_fetch(_side("HOM"), _side("AWY"))),
            )
            await decide_abc(session, settings, run_id, llm, briefs=[brief])
            await session.commit()
        async with db.session_factory() as session:
            assert await place_agent_bets(session, settings, run_id, "a_only") == 1
            assert await place_agent_bets(session, settings, run_id, "abc") == 0
            await session.commit()
        async with db.session_factory() as session:
            variants = (
                await session.execute(select(AgentBet.variant))
            ).scalars().all()
        assert variants == ["a_only"]
    finally:
        await db.dispose()


async def test_agent_abc_update_settles_builds_and_places_then_tracks_job(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        settings = _settings()
        striker = FakeStriker(_fetch(_side("HOM"), _side("AWY")))
        llm = FakeLLM(
            {"decision": "approve", "confidence": 0.9, "reason": "lineups complete"}
        )
        first = await agent_abc_update(
            db.session_factory, settings, striker_client=striker, llm_client=llm
        )
        assert first.matches_considered == 1
        assert first.candidates == 1
        assert first.briefs == 1
        assert first.approved == 1
        assert first.bets_placed == 1
        assert first.bets_settled == 0
        assert len(striker.calls) == 1
        assert len(llm.calls) == 1

        second = await agent_abc_update(
            db.session_factory, settings, striker_client=striker, llm_client=llm
        )
        assert second.bets_placed == 0
        assert second.bets_settled == 1
        assert second.run_id != first.run_id

        async with db.session_factory() as session:
            runs = (
                await session.execute(
                    select(IngestionRun).where(IngestionRun.job == AGENT_ABC_JOB_ID)
                )
            ).scalars().all()
            briefs = (
                await session.execute(select(func.count()).select_from(AnalystBrief))
            ).scalar_one()
            bets = (
                await session.execute(select(AgentBet))
            ).scalars().all()
            assert (
                await session.execute(select(func.count()).select_from(LedgerBet))
            ).scalar_one() == 0
            assert (
                await session.execute(select(func.count()).select_from(ShadowLedgerBet))
            ).scalar_one() == 0
        assert len(runs) == 2
        assert {run.status for run in runs} == {"success"}
        assert briefs == 2
        assert len(bets) == 1
        assert bets[0].variant == "abc"
        assert bets[0].status == "won"
    finally:
        await db.dispose()


async def test_agent_briefs_api_filters_and_order(tmp_path) -> None:
    db, match_id, version_id = await _seed_world(tmp_path)
    try:
        await _add_prediction(db, match_id, version_id)
        run_id = await _risk_run(db, _settings())
        async with db.session_factory() as session:
            await build_brief(
                session,
                _settings(),
                run_id,
                match_id,
                FakeStriker(_fetch(_side("HOM"), _side("AWY"))),
            )
            session.add(
                AnalystBrief(
                    run_id="older-run",
                    match_id=match_id,
                    source="striker",
                    captured_at=datetime(2026, 1, 1, tzinfo=UTC),
                    facts={"lineups_available": False},
                    uncertainties=[],
                    missing=["lineups"],
                    trust_score=0.0,
                    raw_snapshot={},
                )
            )
            await session.commit()

        client = await _client(db)
        try:
            rows = (await client.get("/agent/briefs")).json()
            assert len(rows) == 2
            assert rows[0]["run_id"] == run_id
            assert rows[0]["facts"]["home_starters"] == 11
            assert rows[0]["trust_score"] == pytest.approx(1.0)
            assert rows[0]["missing"] == []
            by_run = (await client.get("/agent/briefs", params={"run_id": run_id})).json()
            assert len(by_run) == 1
            by_match = (
                await client.get("/agent/briefs", params={"match_id": match_id})
            ).json()
            assert len(by_match) == 2
            assert (
                await client.get("/agent/briefs", params={"match_id": 999})
            ).json() == []
            assert len((await client.get("/agent/briefs", params={"limit": 1})).json()) == 1
            assert (await client.get("/agent/briefs", params={"limit": 0})).status_code == 422
        finally:
            await client.aclose()
    finally:
        await db.dispose()


def test_cli_agent_abc_smoke(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = asyncio.run(make_db(tmp_path))
    try:
        monkeypatch.setattr("app.cli.Database", lambda _url: db)
        monkeypatch.setattr("app.cli.get_settings", lambda: _settings())
        main(["agent-abc"])
        out = capsys.readouterr().out
        assert "agent-abc complete: run_id=" in out
        assert "briefs=0 decisions=0" in out
        assert "bets_placed=0 bets_settled=0" in out

        async def _runs() -> list[IngestionRun]:
            async with db.session_factory() as session:
                return (
                    await session.execute(
                        select(IngestionRun).where(IngestionRun.job == AGENT_ABC_JOB_ID)
                    )
                ).scalars().all()

        runs = asyncio.run(_runs())
        assert len(runs) == 1
        assert runs[0].status == "success"
    finally:
        asyncio.run(db.dispose())


async def test_llm_client_contract_and_redaction() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"decision": "approve", "confidence": 0.8, "reason": "ok"}
                            )
                        }
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AgentLLMClient(_settings(), http_client=http_client)
    try:
        data = await client.complete("hello", system="system", session_id="sess-1")
    finally:
        await http_client.aclose()

    headers = seen["headers"]
    payload = seen["payload"]
    assert isinstance(headers, dict) and isinstance(payload, dict)
    assert headers["authorization"] == "Bearer sk-llm"
    assert headers["x-opencode-session"] == "sess-1"
    assert headers["user-agent"] == "football-pred-agent/1.0"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] <= 500
    assert data["decision"] == "approve"
    redacted = redacted_headers({"Authorization": "Bearer sk-llm", "Accept": "json"})
    assert redacted["Authorization"] == "***"
    assert "sk-llm" not in json.dumps(redacted)


async def test_llm_client_errors_never_include_the_key() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    )
    client = AgentLLMClient(_settings(), http_client=http_client)
    try:
        with pytest.raises(AgentLLMError) as excinfo:
            await client.complete("hello")
    finally:
        await http_client.aclose()
    assert "sk-llm" not in str(excinfo.value)
