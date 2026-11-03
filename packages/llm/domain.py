from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Literal, NoReturn, Self, override

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PROBABILITY_TOLERANCE = Decimal("0.001")


class InvalidPredictionError(ValueError):
    """Raised when an agent output violates the HAD probability contract."""


def _raise_domain_error(error: ValidationError) -> NoReturn:
    """Re-raise a wrapped InvalidPredictionError, otherwise propagate the ValidationError."""
    for details in error.errors():
        cause = (details.get("ctx") or {}).get("error")
        if isinstance(cause, InvalidPredictionError):
            raise cause from error
    raise error


class Outcome(StrEnum):
    H = "H"
    D = "D"
    A = "A"


class Stage(StrEnum):
    T24H = "T-24h"
    T3H = "T-3h"
    T30M = "T-30m"


class AgentPrediction(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    match_id: str
    stage: Stage
    as_of: datetime
    probabilities: dict[Literal["H", "D", "A"], Decimal]
    confidence: Decimal = Field(ge=0, le=1)
    data_quality: Decimal = Field(ge=0, le=1)
    key_factors: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    abstain: bool = False
    abstain_reason: str | None = None

    @classmethod
    @override
    def model_validate(
        cls,
        obj: object,
        *,
        strict: bool | None = None,
        extra: Literal["allow", "ignore", "forbid"] | None = None,
        from_attributes: bool | None = None,
        context: object | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        try:
            return super().model_validate(
                obj,
                strict=strict,
                extra=extra,
                from_attributes=from_attributes,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            _raise_domain_error(error)

    @classmethod
    @override
    def model_validate_json(
        cls,
        json_data: str | bytes | bytearray,
        *,
        strict: bool | None = None,
        extra: Literal["allow", "ignore", "forbid"] | None = None,
        context: object | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        try:
            return super().model_validate_json(
                json_data,
                strict=strict,
                extra=extra,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        except ValidationError as error:
            _raise_domain_error(error)

    @field_validator("agent_id", "match_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("as_of")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("as_of must be timezone-aware UTC")
        return value

    @field_validator("probabilities")
    @classmethod
    def validate_probability_values(
        cls, value: dict[Literal["H", "D", "A"], Decimal]
    ) -> dict[Literal["H", "D", "A"], Decimal]:
        for outcome, probability in value.items():
            if probability < 0 or probability > 1:
                raise ValueError(f"probability for {outcome} must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_probabilities(self) -> AgentPrediction:
        keys = set(self.probabilities)
        if keys != {outcome.value for outcome in Outcome}:
            raise InvalidPredictionError("probabilities must contain H, D and A")
        total = sum(self.probabilities.values(), Decimal(0))
        if abs(total - Decimal(1)) > PROBABILITY_TOLERANCE:
            raise InvalidPredictionError("probabilities must sum to 1")
        if self.abstain and not (self.abstain_reason or "").strip():
            raise InvalidPredictionError("abstain_reason is required when abstain is true")
        return self
