from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.db.base import Base
from packages.db.models import (
    Competition,
    LlmEvidencePacket,
    LlmResearchFinding,
    LlmResearchRun,
    MarketLine,
    Match,
    OddsSnapshot,
    PaperBet,
    Team,
)
from packages.domain.enums import MarketType, MatchStatus, Side, SnapshotKind
from packages.llm.providers import MockProvider
from packages.llm.research import ROLE_AGENTS
from packages.llm.research_assistant import run_llm_research_assistant

D = Decimal
NOW = datetime.now(UTC)
KICKOFF = NOW + timedelta(minutes=30)


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session):
    competition = Competition(
        code="UCL",
        name="Champions League",
        country="Europe",
        is_cup=True,
        football_data_code="CL",
    )
    home = Team(slug="research-home", name="Home", short_name="HOM", country="England")
    away = Team(slug="research-away", name="Away", short_name="AWY", country="Spain")
    session.add_all([competition, home, away])
    session.flush()
    match = Match(
        competition_id=competition.id,
        season="2026/27",
        kickoff_at=KICKOFF,
        first_seen_at=NOW - timedelta(hours=2),
        home_team_id=home.id,
        away_team_id=away.id,
        status=MatchStatus.SCHEDULED,
        source_match_ids={},
        coverage_flags=[],
    )
    session.add(match)
    session.flush()
    snapshot = OddsSnapshot(
        match_id=match.id,
        market=MarketType.HAD,
        snapshot_kind=SnapshotKind.T30M,
        snapshot_at=NOW,
        query_version="test",
        payload_hash="research-hash",
        run_id="research-run",
    )
    session.add(snapshot)
    session.flush()
    for index, (side, price) in enumerate(
        ((Side.H, "2.50"), (Side.D, "3.20"), (Side.A, "4.00"))
    ):
        session.add(
            MarketLine(
                snapshot_id=snapshot.id,
                odds_type=MarketType.HAD,
                condition_raw="0.0",
                line_index=index,
                side=side,
                odds_decimal=D(price),
                pool_status="SELLINGSTARTED",
                line_status="AVAILABLE",
                is_main=True,
                offer_early_settlement=False,
            )
        )
    session.commit()
    return match, snapshot


def _finding(agent_id: str, ref: str) -> str:
    return json.dumps(
        {
            "agent_id": agent_id,
            "summary": f"{agent_id} summary",
            "key_findings": ["finding"],
            "confidence": 0.7,
            "direction": "H",
            "evidence_refs": [ref],
            "uncertainties": [],
            "abstain": False,
            "abstain_reason": None,
        }
    )


def test_assistant_runs_roles_then_main_agent_and_places_paper_bet():
    engine, session = _session()
    try:
        match, _snapshot = _seed(session)
        refs = [f"match:{match.id}"]
        responses = [
            _finding(agent_id, refs[0]) for agent_id, _name, _scope in ROLE_AGENTS
        ]
        responses.append(
            json.dumps(
                {
                    "report": {
                        "summary": "Home has the better setup.",
                        "key_findings": ["form and market align"],
                        "market_view": "home price is fair",
                        "risks": ["small sample"],
                        "reasoning": "home edge",
                    },
                    "probabilities": {"H": 0.5, "D": 0.3, "A": 0.2},
                    "recommended_side": "H",
                    "recommended_stake_pct": 0.01,
                    "confidence": 0.7,
                    "evidence_refs": refs,
                    "abstain": False,
                    "abstain_reason": None,
                }
            )
        )
        provider = MockProvider(responses)

        result = run_llm_research_assistant(
            session,
            match.id,
            provider=provider,
            max_workers=1,
        )

        assert result["status"] == "bet"
        assert result["recommended_side"] == "H"
        assert result["probabilities"] == {"H": "0.5", "D": "0.3", "A": "0.2"}
        assert result["paper_bet_id"] is not None
        assert session.scalar(select(LlmResearchRun)) is not None
        assert session.scalar(select(LlmEvidencePacket)) is not None
        assert len(session.scalars(select(LlmResearchFinding)).all()) == len(ROLE_AGENTS)
        assert session.scalar(select(PaperBet)) is not None
        assert len(provider.calls) == len(ROLE_AGENTS) + 1
    finally:
        session.close()
        engine.dispose()


def _abstain_finding(agent_id: str, ref: str) -> str:
    return json.dumps(
        {
            "agent_id": agent_id,
            "summary": f"{agent_id} abstains",
            "key_findings": [],
            "confidence": 0.2,
            "direction": "abstain",
            "evidence_refs": [ref],
            "uncertainties": ["missing data"],
            "abstain": True,
            "abstain_reason": "source data missing",
        }
    )


def test_assistant_reaches_main_agent_with_two_active_findings():
    engine, session = _session()
    try:
        match, _snapshot = _seed(session)
        refs = [f"match:{match.id}"]
        responses = []
        for index, (agent_id, _name, _scope) in enumerate(ROLE_AGENTS):
            if index < 2:
                responses.append(_finding(agent_id, refs[0]))
            else:
                responses.append(_abstain_finding(agent_id, refs[0]))
        responses.append(
            json.dumps(
                {
                    "report": {
                        "summary": "limited but usable evidence",
                        "key_findings": ["market and form agree"],
                        "market_view": "fair price",
                        "risks": ["thin data"],
                        "reasoning": "two active agents",
                    },
                    "probabilities": {"H": 0.45, "D": 0.30, "A": 0.25},
                    "recommended_side": "H",
                    "recommended_stake_pct": 0.01,
                    "confidence": 0.55,
                    "evidence_refs": refs,
                    "abstain": False,
                    "abstain_reason": None,
                }
            )
        )
        provider = MockProvider(responses)

        result = run_llm_research_assistant(
            session,
            match.id,
            provider=provider,
            max_workers=1,
        )

        assert result["status"] in {"bet", "no_bet"}
        assert result["status"] != "abstained"
        assert len(provider.calls) == len(ROLE_AGENTS) + 1
    finally:
        session.close()
        engine.dispose()


def test_assistant_retries_main_agent_once_after_schema_violation():
    engine, session = _session()
    try:
        match, _snapshot = _seed(session)
        refs = [f"match:{match.id}"]
        responses = [
            _finding(agent_id, refs[0]) for agent_id, _name, _scope in ROLE_AGENTS
        ]
        responses.append(
            json.dumps(
                {
                    "report": {
                        "summary": "missing required decision fields",
                        "key_findings": [],
                        "market_view": "fair",
                        "risks": [],
                        "reasoning": "incomplete",
                    },
                    "probabilities": {"H": 0.5, "D": 0.3, "A": 0.2},
                }
            )
        )
        responses.append(
            json.dumps(
                {
                    "report": {
                        "summary": "retry produced a complete decision",
                        "key_findings": [],
                        "market_view": "fair",
                        "risks": [],
                        "reasoning": "complete",
                    },
                    "probabilities": {"H": 0.5, "D": 0.3, "A": 0.2},
                    "recommended_side": "H",
                    "recommended_stake_pct": 0.01,
                    "confidence": 0.7,
                    "evidence_refs": refs,
                    "abstain": False,
                    "abstain_reason": None,
                }
            )
        )
        provider = MockProvider(responses)

        result = run_llm_research_assistant(
            session,
            match.id,
            provider=provider,
            max_workers=1,
        )

        assert result["status"] in {"bet", "no_bet"}
        assert len(provider.calls) == len(ROLE_AGENTS) + 2
        assert "FAILED VALIDATION" in provider.calls[-1][1]
    finally:
        session.close()
        engine.dispose()
