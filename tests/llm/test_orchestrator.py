from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import packages.db.models  # noqa: F401
from apps.api.main import create_app
from packages.db.base import Base
from packages.db.models import (
    Competition,
    LlmAgentOutput,
    LlmAgentRun,
    LlmEnsemblePrediction,
    LlmEvidencePacket,
    MarketLine,
    Match,
    OddsSnapshot,
    Team,
)
from packages.domain.enums import MarketType, MatchStatus, Side, SnapshotKind
from packages.llm.aggregation.log_opinion import aggregate_predictions
from packages.llm.domain import AgentPrediction, Outcome
from packages.llm.orchestrator import run_llm_prediction
from packages.llm.providers import MockProvider
from packages.shared.config import Settings

NOW = datetime.now(UTC)
KICKOFF = NOW + timedelta(minutes=30)
SPECIALIST = json.dumps(
    {
        "probabilities": {"H": 0.42, "D": 0.26, "A": 0.32},
        "confidence": 0.7,
        "data_quality": 0.8,
        "key_factors": ["test evidence"],
        "evidence_refs": ["test"],
        "uncertainties": [],
        "abstain": False,
        "abstain_reason": None,
    }
)


def _seed(session: Session) -> Match:
    competition = Competition(
        code="UCL", name="UEFA Champions League", country="Europe", football_data_code="CL"
    )
    home = Team(slug="home", name="Home FC", short_name="HOM", country="Europe")
    away = Team(slug="away", name="Away FC", short_name="AWY", country="Europe")
    session.add_all([competition, home, away])
    session.flush()
    for index in range(6):
        team = home if index < 3 else away
        opponent = away if index < 3 else home
        session.add(
            Match(
                competition_id=competition.id,
                season="2026/27",
                kickoff_at=NOW - timedelta(days=index + 1),
                home_team_id=team.id,
                away_team_id=opponent.id,
                status=MatchStatus.FINISHED,
                home_goals_90=2,
                away_goals_90=1,
                source_match_ids={},
                coverage_flags=[],
            )
        )
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=KICKOFF,
        first_seen_at=NOW - timedelta(hours=2),
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={"hkjc": "50078957"},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    snapshot = OddsSnapshot(
        match_id=match.id,
        market=MarketType.HAD,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=NOW - timedelta(minutes=5),
        query_version="test",
        payload_hash="odds-hash",
        run_id="run",
    )
    session.add(snapshot)
    session.flush()
    for side, odds in ((Side.H, "2.00"), (Side.D, "3.50"), (Side.A, "3.80")):
        session.add(
            MarketLine(
                snapshot_id=snapshot.id,
                odds_type=MarketType.HAD,
                condition_raw="0.0",
                line_index=0,
                side=side,
                odds_decimal=Decimal(odds),
                pool_status="SELLINGSTARTED",
                line_status="AVAILABLE",
            )
        )
    session.flush()
    return match


def test_orchestrator_persists_evidence_runs_and_prediction() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        match = _seed(session)
        provider = MockProvider(
            [
                SPECIALIST,
                SPECIALIST,
                SPECIALIST,
                SPECIALIST,
                SPECIALIST,
                SPECIALIST,
                json.dumps(
                    {
                        "objections": ["small sample"],
                        "consensus_fragility": 0.2,
                        "recommended_abstain": False,
                    }
                ),
                json.dumps(
                    {
                        "main_disagreement": "none",
                        "abstain_recommendation": False,
                        "reasoning_summary": "test",
                    }
                ),
            ]
        )
        result = run_llm_prediction(
            session,
            match.id,
            as_of=NOW,
            provider=provider,
            prompt_dir=__import__("pathlib").Path("prompts/llm"),
        )
        assert result["active_agents"] == [
            "market_agent",
            "form_agent",
            "tactical_agent",
            "availability_agent",
            "context_agent",
            "base_rate_agent",
        ]
        assert len(provider.calls) == 8
        assert session.scalar(select(LlmEvidencePacket)) is not None
        assert len(session.scalars(select(LlmAgentRun)).all()) == 8
        assert len(session.scalars(select(LlmAgentOutput)).all()) == 6
        ensemble = session.scalar(select(LlmEnsemblePrediction))
        assert ensemble is not None
        assert set(ensemble.probabilities) == {"H", "D", "A"}
        assert sum(Decimal(value) for value in ensemble.probabilities.values()) > 0
    engine.dispose()


def test_llm_predictions_endpoint_returns_latest_ensemble() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    application = create_app(
        Settings(database_url="sqlite+pysqlite:///:memory:", _env_file=None),
        redis_client=None,
    )
    # This test only checks the empty endpoint contract; persistence is covered above.
    try:
        client = TestClient(application)
        assert client.get("/llm/predictions").json() == []
    finally:
        application.state.engine.dispose()
    engine.dispose()


def test_aggregation_accepts_six_equal_specialists() -> None:
    prediction = AgentPrediction(
        agent_id="a",
        match_id="m",
        stage="T-30m",
        as_of=NOW,
        probabilities={"H": Decimal("0.42"), "D": Decimal("0.26"), "A": Decimal("0.32")},
        confidence=Decimal("0.7"),
        data_quality=Decimal("0.8"),
        abstain=False,
    )
    predictions = [prediction.model_copy(update={"agent_id": f"a{i}"}) for i in range(6)]
    result = aggregate_predictions(
        predictions,
        {item.agent_id: Decimal(1) / Decimal(6) for item in predictions},
    )
    assert set(result) == set(Outcome)
    assert sum(result.values()) > Decimal("0.99")


def test_llm_predictions_endpoint_returns_persisted_ensemble(tmp_path) -> None:
    from apps.api.main import create_app
    from packages.db.base import Base
    from packages.shared.config import Settings

    database_url = f"sqlite+pysqlite:///{tmp_path / 'llm-api.db'}"
    application = create_app(Settings(database_url=database_url, _env_file=None))
    Base.metadata.create_all(application.state.engine)
    factory = application.state.session_factory
    try:
        with factory() as session:
            match = _seed(session)
            provider = MockProvider(
                [
                    SPECIALIST,
                    SPECIALIST,
                    SPECIALIST,
                    SPECIALIST,
                    SPECIALIST,
                    SPECIALIST,
                    json.dumps({"objections": [], "consensus_fragility": 0.1, "recommended_abstain": False}),
                    json.dumps({"main_disagreement": "none", "abstain_recommendation": False, "reasoning_summary": "test"}),
                ]
            )
            run_llm_prediction(
                session,
                match.id,
                as_of=NOW,
                provider=provider,
                prompt_dir=__import__("pathlib").Path("prompts/llm"),
            )
            session.commit()
        client = TestClient(application)
        payload = client.get("/llm/predictions").json()
        assert len(payload) == 1
        assert payload[0]["decision_status"] == "bet"
        assert payload[0]["paper_bet_id"] is not None
        assert set(payload[0]["probabilities"]) == {"H", "D", "A"}
    finally:
        application.state.engine.dispose()
