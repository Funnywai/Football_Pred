from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.base import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    json_type,
)


class LlmEvidencePacket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_evidence_packets"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "stage",
            "packet_hash",
            name="uq_llm_evidence_packets_match_stage_hash",
        ),
        Index("ix_llm_evidence_packets_match_id", "match_id"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    packet: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)


class LlmAgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_agent_runs"
    __table_args__ = (
        Index("ix_llm_agent_runs_match_id_created_at", "match_id", "created_at"),
        Index("ix_llm_agent_runs_packet_id", "packet_id"),
    )

    packet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_evidence_packets.id", ondelete="CASCADE"), nullable=False
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class LlmAgentOutput(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_agent_outputs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_llm_agent_outputs_run_id"),
        Index("ix_llm_agent_outputs_match_id", "match_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    probabilities: Mapped[dict[str, str]] = mapped_column(json_type(), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    data_quality: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    abstain: Mapped[bool] = mapped_column(Boolean, nullable=False)
    output: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)


class LlmEnsemblePrediction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_ensemble_predictions"
    __table_args__ = (
        Index("ix_llm_ensemble_predictions_match_id_created_at", "match_id", "created_at"),
        Index("ix_llm_ensemble_predictions_packet_id", "packet_id"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    packet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_evidence_packets.id", ondelete="CASCADE"), nullable=False
    )
    probabilities: Mapped[dict[str, str]] = mapped_column(json_type(), nullable=False)
    weights: Mapped[dict[str, str]] = mapped_column(json_type(), nullable=False)
    active_agents: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    red_team: Mapped[dict[str, object] | None] = mapped_column(json_type())
    judge: Mapped[dict[str, object] | None] = mapped_column(json_type())
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class LlmResearchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_research_runs"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "stage",
            "evidence_hash",
            "model_version",
            name="uq_llm_research_runs_match_stage_evidence_model",
        ),
        Index("ix_llm_research_runs_match_id_created_at", "match_id", "created_at"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    report: Mapped[dict[str, object] | None] = mapped_column(json_type())
    probabilities: Mapped[dict[str, str] | None] = mapped_column(json_type())
    recommended_side: Mapped[str | None] = mapped_column(String(8))
    recommended_stake_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    abstain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk: Mapped[dict[str, object] | None] = mapped_column(json_type())
    raw_response: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class LlmResearchFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_research_findings"
    __table_args__ = (
        UniqueConstraint("run_id", "agent_id", name="uq_llm_research_findings_run_agent"),
        Index("ix_llm_research_findings_run_id", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_research_runs.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    findings: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(), default=list, nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    direction: Mapped[str | None] = mapped_column(String(16))
    evidence_refs: Mapped[list[str]] = mapped_column(json_type(), default=list, nullable=False)
    uncertainties: Mapped[list[str]] = mapped_column(json_type(), default=list, nullable=False)
    abstain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
