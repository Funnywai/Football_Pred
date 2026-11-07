from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import packages.db.models  # noqa: F401
from apps.api.main import create_app
from packages.db.base import Base
from packages.db.models import (
    Competition,
    LlmResearchFinding,
    LlmResearchRun,
    Match,
    Team,
)
from packages.domain.enums import MatchStatus
from packages.shared.config import Settings


def test_llm_status_contract(tmp_path):
    settings = Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'llm.db'}")
    application = create_app(settings)
    try:
        client = TestClient(application)
        response = client.get("/llm/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["phase"] == "phase-3"
        assert payload["runtime"]["decision_layer"] == "llm_not_connected"
        assert payload["counts"]["agents"] == 9
        assert payload["counts"]["prompts"] == 9
        assert payload["counts"]["predictions"] == 0
        assert payload["counts"]["paper_bets"] == 0
        assert payload["competitions"] == ["BUNDESLIGA", "EPL", "LALIGA", "LIGUE1", "SERIEA", "UCL"]
        assert payload["next_fixtures"] == []
        assert payload["safety"] == {
            "paper_only": True,
            "real_money": False,
            "llm_may_write_database": False,
            "llm_may_settle": False,
        }
        assert {agent["agent_id"] for agent in payload["agents"]} >= {
            "market_agent",
            "red_team_agent",
            "judge_agent",
            "risk_agent",
        }
        assert {prompt["name"] for prompt in payload["prompts"]} == {
            "system",
            "market_agent",
            "form_agent",
            "tactical_agent",
            "availability_agent",
            "context_agent",
            "base_rate_agent",
            "red_team_agent",
            "judge_agent",
        }
        assert all(prompt["sha256"] for prompt in payload["prompts"])
        assert client.get("/llm/predictions").json() == []
        assert client.get("/llm/bets").json() == []
        assert client.get("/llm/equity").json() == {"initial": None, "points": []}
    finally:
        application.state.engine.dispose()


def test_research_runs_include_match_context_and_analyst_counts(tmp_path):
    settings = Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'llm.db'}")
    application = create_app(settings)
    try:
        Base.metadata.create_all(application.state.engine)
        session = application.state.session_factory()
        try:
            competition = Competition(
                code="EPL",
                name="Premier League",
                country="England",
                football_data_code="E0",
            )
            home = Team(
                slug="arsenal", name="Arsenal", short_name="ARS", country="England"
            )
            away = Team(
                slug="chelsea", name="Chelsea", short_name="CHE", country="England"
            )
            session.add_all([competition, home, away])
            session.flush()

            kickoff_at = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
            match = Match(
                competition_id=competition.id,
                season="2026/27",
                kickoff_at=kickoff_at,
                home_team_id=home.id,
                away_team_id=away.id,
                status=MatchStatus.SCHEDULED,
                source_match_ids={},
                coverage_flags=[],
            )
            session.add(match)
            session.flush()

            run = LlmResearchRun(
                match_id=match.id,
                stage="T-24h",
                as_of=kickoff_at - timedelta(hours=24),
                evidence_hash="evidence-hash",
                model_version="deepseek-v4.1-flash",
                prompt_version="research-v1",
                provider="openai_compatible",
                status="completed",
            )
            session.add(run)
            session.flush()
            for index in range(7):
                session.add(
                    LlmResearchFinding(
                        run_id=run.id,
                        agent_id=f"analyst_{index}",
                        summary=f"Summary {index}",
                        findings=[],
                        evidence_refs=[],
                        uncertainties=[],
                        abstain=index >= 5,
                    )
                )
            session.commit()
            run_id = str(run.id)
            match_id = str(match.id)
        finally:
            session.close()

        client = TestClient(application)
        rows = client.get("/llm/research-runs").json()
        assert len(rows) == 1
        row = rows[0]
        assert row["run_id"] == run_id
        assert row["match_id"] == match_id
        assert row["home_team"] == "Arsenal"
        assert row["away_team"] == "Chelsea"
        assert row["competition"] == "EPL"
        kickoff_returned = datetime.fromisoformat(row["kickoff_at"]).replace(tzinfo=None)
        assert kickoff_returned == kickoff_at.replace(tzinfo=None)
        assert row["active_findings"] == 5
        assert row["total_findings"] == 7

        detail = client.get(f"/llm/research-runs/{run_id}").json()
        assert detail["run_id"] == run_id
        assert detail["match_id"] == match_id
        assert detail["home_team"] == "Arsenal"
        assert detail["away_team"] == "Chelsea"
        assert detail["competition"] == "EPL"
        detail_kickoff = datetime.fromisoformat(detail["kickoff_at"]).replace(tzinfo=None)
        assert detail_kickoff == kickoff_at.replace(tzinfo=None)
        assert detail["active_findings"] == 5
        assert detail["total_findings"] == 7
        assert len(detail["findings"]) == 7
    finally:
        application.state.engine.dispose()
