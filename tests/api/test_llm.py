from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app
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
        assert payload["competitions"] == ["UCL"]
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
