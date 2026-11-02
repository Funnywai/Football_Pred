from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from packages.adapters.base import FetchResult, hash_text
from packages.db.models import RawPayload, SourceFetchRun
from packages.domain.enums import FetchRunStatus
from packages.shared.time import utc_now


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def persist_raw_payload(
    session: Session,
    result: FetchResult,
    *,
    schema_version: str,
    run_id: str | None = None,
) -> RawPayload:
    """Store the provider body verbatim with its provenance and hash.

    The payload is deep-copied so later caller mutation cannot rewrite the
    persisted raw record. Raw payloads are never updated by ingestion code.
    """
    _require_text(schema_version, "schema_version")
    _require_text(result.source_name, "source_name")
    _require_text(result.source_url, "source_url")
    _require_text(result.payload_hash, "payload_hash")
    if run_id is not None:
        _require_text(run_id, "run_id")
    if hash_text(result.raw_text) != result.payload_hash:
        raise ValueError("payload_hash does not match raw_text")

    if isinstance(result.payload, dict):
        body = copy.deepcopy(result.payload)
    elif isinstance(result.payload, str):
        body = {"text": result.payload}
    else:
        body = {"value": copy.deepcopy(result.payload)}
    row = RawPayload(
        source_name=result.source_name,
        source_url=result.source_url,
        fetched_at=result.fetched_at,
        schema_version=schema_version,
        payload_hash=result.payload_hash,
        body=body,
        http_status=result.http_status,
        run_id=run_id,
    )
    session.add(row)
    session.flush()
    return row


def start_fetch_run(
    session: Session,
    *,
    source_name: str,
    run_id: str,
    params: dict[str, object] | None = None,
) -> SourceFetchRun:
    _require_text(source_name, "source_name")
    _require_text(run_id, "run_id")
    row = SourceFetchRun(
        source_name=source_name,
        run_id=run_id,
        started_at=utc_now(),
        status=FetchRunStatus.RUNNING,
        params={} if params is None else copy.deepcopy(params),
    )
    session.add(row)
    session.flush()
    return row


def finish_fetch_run(
    session: Session,
    run: SourceFetchRun,
    *,
    status: FetchRunStatus,
    request_count: int,
    error_count: int,
    error_summary: str | None = None,
) -> SourceFetchRun:
    _require_non_negative_int(request_count, "request_count")
    _require_non_negative_int(error_count, "error_count")
    parsed_status = FetchRunStatus(status)
    run.finished_at = utc_now()
    run.status = parsed_status
    run.request_count = request_count
    run.error_count = error_count
    run.error_summary = error_summary
    session.flush()
    return run
