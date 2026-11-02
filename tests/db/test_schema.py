from sqlalchemy import Engine, UniqueConstraint, inspect

from packages.db.base import Base
from packages.db.models import (
    Availability,
    BankrollAccount,
    BankrollReservation,
    CalibrationMetric,
    Competition,
    DecisionLog,
    Lineup,
    MarketLine,
    Match,
    ModelPrediction,
    ModelVersion,
    NewsSignal,
    OddsSnapshot,
    PaperBet,
    Player,
    RawPayload,
    Settlement,
    SourceFetchRun,
    StrategyVersion,
    Team,
    WeightSnapshot,
)

PHASE1_TABLES = {
    "competitions",
    "teams",
    "players",
    "matches",
    "lineups",
    "availability",
    "odds_snapshots",
    "market_lines",
    "paper_bets",
    "settlements",
    "raw_payloads",
    "source_fetch_runs",
    "bankroll_accounts",
    "bankroll_reservations",
    "news_signals",
}


def test_phase1_tables_exist(engine):
    assert PHASE1_TABLES <= set(inspect(engine).get_table_names())


def test_match_keeps_regulation_and_final_scores_separate():
    columns = {column.name for column in Match.__table__.columns}
    assert {
        "home_goals_90",
        "away_goals_90",
        "home_goals_final",
        "away_goals_final",
    } <= columns


def test_provenance_columns_exist():
    raw_columns = {column.name for column in RawPayload.__table__.columns}
    assert {"source_name", "source_url", "fetched_at", "schema_version", "payload_hash"} <= raw_columns
    settlement_columns = {column.name for column in Settlement.__table__.columns}
    assert {"hk_result_ref", "provisional", "source"} <= settlement_columns


def test_paper_bet_has_three_layer_idempotency_keys():
    assert PaperBet.__table__.c.bet_intent_key.unique is True
    assert PaperBet.__table__.c.analysis_run_key.index is True
    assert PaperBet.__table__.c.decision_slot_key.index is True
    assert "decision_at" in {column.name for column in PaperBet.__table__.columns}


def test_odds_snapshot_and_market_line_links():
    assert OddsSnapshot.__table__.c.match_id.foreign_keys
    assert MarketLine.__table__.c.snapshot_id.foreign_keys
    assert Competition.__table__.c.code.unique is True
    assert Team.__table__.c.slug.unique is True
    assert Player.__table__.c.fotmob_id.unique is True


def test_v21_temporal_fields_present():
    assert {"event_time", "first_seen_at", "result_available_at"} <= {
        column.name for column in Match.__table__.columns
    }
    assert {"result_availability_basis", "result_evidence_grade"} <= {
        column.name for column in Match.__table__.columns
    }
    assert {"available_at", "availability_basis", "evidence_grade"} <= {
        column.name for column in Lineup.__table__.columns
    }
    assert {"available_at", "availability_basis", "evidence_grade"} <= {
        column.name for column in Availability.__table__.columns
    }
    assert {"available_at", "availability_basis"} <= {
        column.name for column in MarketLine.__table__.columns
    }
    assert {"published_at", "first_seen_at", "available_at", "availability_basis"} <= {
        column.name for column in NewsSignal.__table__.columns
    }
    assert {"available_at", "availability_basis", "evidence_grade"} <= {
        column.name for column in NewsSignal.__table__.columns
    }


def test_source_verification_fields_present():
    assert {
        "source_status",
        "verification_date",
        "schema_scope",
        "field_scope",
        "test_evidence_ref",
        "licensing_check",
    } <= {column.name for column in SourceFetchRun.__table__.columns}


def test_bankroll_tables_have_required_columns():
    assert {"bankroll_balance", "reserved_stake"} <= {
        column.name for column in BankrollAccount.__table__.columns
    }
    assert {"bet_intent_key", "amount", "status"} <= {
        column.name for column in BankrollReservation.__table__.columns
    }
    assert BankrollReservation.__table__.c.bet_intent_key.unique is True


def test_model_predictions_table_and_constraints(engine: Engine):
    assert "model_predictions" in set(inspect(engine).get_table_names())
    assert "model_predictions" in Base.metadata.tables

    table = Base.metadata.tables["model_predictions"]
    assert table is ModelPrediction.__table__
    assert table.c.match_id.foreign_keys

    unique_column_sets = {
        frozenset(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert frozenset(
        {"analysis_run_key", "market", "line_key", "outcome"}
    ) in unique_column_sets

    assert {
        "score_distribution",
        "return_distribution",
        "decision_at",
        "model_version",
        "analysis_run_key",
    } <= {column.name for column in table.columns}

    index_column_sets = {
        frozenset(index.columns.keys()) for index in table.indexes
    }
    assert frozenset({"match_id", "decision_at"}) in index_column_sets


def test_calibration_and_versioning_tables(engine: Engine):
    tables = {"model_versions", "strategy_versions", "weight_snapshots", "calibration_metrics"}
    assert tables <= set(inspect(engine).get_table_names())
    assert tables <= set(Base.metadata.tables)

    model_version = Base.metadata.tables["model_versions"]
    assert model_version is ModelVersion.__table__
    assert model_version.c.version.unique is True
    assert {
        "version",
        "family",
        "params",
        "training_window",
        "validation_metrics",
        "status",
    } <= {column.name for column in model_version.columns}
    assert {
        "version",
        "model_version",
        "policy_params",
        "status",
    } <= {column.name for column in StrategyVersion.__table__.columns}
    assert StrategyVersion.__table__.c.version.unique is True

    weight_snapshot = WeightSnapshot.__table__
    assert weight_snapshot.c.strategy_version.index is True
    assert {
        "strategy_version",
        "weights",
        "reason",
        "evaluation_period",
    } <= {column.name for column in weight_snapshot.columns}

    calibration = CalibrationMetric.__table__
    assert calibration.c.model_version.index is True
    assert calibration.c.strategy_version.index is True
    assert {
        "model_version",
        "strategy_version",
        "competition",
        "market",
        "time_block",
        "sample_count",
        "brier",
        "log_loss",
        "roi",
        "clv",
        "calibration",
    } <= {column.name for column in calibration.columns}

    unique_column_sets = {
        frozenset(constraint.columns.keys())
        for constraint in calibration.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert frozenset(
        {"model_version", "strategy_version", "competition", "market", "time_block"}
    ) in unique_column_sets


def test_decision_logs_table_and_constraints(engine: Engine):
    assert "decision_logs" in set(inspect(engine).get_table_names())
    assert "decision_logs" in Base.metadata.tables

    table = Base.metadata.tables["decision_logs"]
    assert table is DecisionLog.__table__
    assert table.c.decision_slot_key.unique is True
    assert table.c.match_id.index is True
    assert {
        "match_id",
        "decision_slot_key",
        "snapshot_id",
        "decision_at",
        "status",
        "reason",
        "model_version",
        "prediction_count",
        "paper_bet_id",
    } <= {column.name for column in table.columns}

    foreign_key_targets = {
        column.name: {
            (element.target_fullname, element.ondelete)
            for element in column.foreign_keys
        }
        for column in table.columns
    }
    assert ("matches.id", "CASCADE") in foreign_key_targets["match_id"]
    assert ("odds_snapshots.id", "SET NULL") in foreign_key_targets["snapshot_id"]
    assert ("paper_bets.id", "SET NULL") in foreign_key_targets["paper_bet_id"]
