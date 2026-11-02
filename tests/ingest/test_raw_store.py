from dataclasses import replace
from typing import cast

import pytest

from packages.adapters.base import FetchResult, hash_text
from packages.domain.enums import FetchRunStatus
from packages.ingest.raw_store import (
    finish_fetch_run,
    persist_raw_payload,
    start_fetch_run,
)
from packages.shared.time import utc_now


def _result(payload: object) -> FetchResult:
    raw_text = str(payload)
    return FetchResult(
        source_name="test-source",
        source_url="https://example.test/data",
        fetched_at=utc_now(),
        http_status=200,
        schema_version="test-v1",
        payload=payload,
        payload_hash=hash_text(raw_text),
        raw_text=raw_text,
    )


def test_persist_raw_payload_keeps_provenance_and_json_body(session):
    result = _result({"hello": "world"})
    row = persist_raw_payload(
        session,
        result,
        schema_version="v1",
        run_id="run-1",
    )
    session.flush()
    assert row.source_name == "test-source"
    assert row.source_url == "https://example.test/data"
    assert row.schema_version == "v1"
    assert row.payload_hash == result.payload_hash
    assert row.body == {"hello": "world"}
    assert row.run_id == "run-1"
    assert row.http_status == 200


def test_persist_text_payload_wraps_text(session):
    result = _result("csv,text")
    row = persist_raw_payload(session, result, schema_version="csv-v1")
    session.flush()
    assert row.body == {"text": "csv,text"}
    assert row.run_id is None


def test_persist_list_payload_wraps_value(session):
    result = _result([1, 2, 3])
    row = persist_raw_payload(session, result, schema_version="v1")
    session.flush()
    assert row.body == {"value": [1, 2, 3]}


def test_persist_raw_payload_copies_payload(session):
    payload = {"hello": "world"}
    result = _result(payload)
    row = persist_raw_payload(session, result, schema_version="v1")
    payload["hello"] = "mutated"
    assert row.body == {"hello": "world"}


def test_persist_raw_payload_rejects_blank_schema_version(session):
    with pytest.raises(ValueError):
        persist_raw_payload(session, _result({}), schema_version="   ")


def test_persist_raw_payload_rejects_blank_run_id(session):
    with pytest.raises(ValueError):
        persist_raw_payload(session, _result({}), schema_version="v1", run_id="")


def test_persist_raw_payload_rejects_blank_source(session):
    result = replace(_result({}), source_name="   ")
    with pytest.raises(ValueError):
        persist_raw_payload(session, result, schema_version="v1")


def test_persist_raw_payload_rejects_hash_mismatch(session):
    result = _result({"hello": "world"})
    tampered = replace(result, payload_hash="0" * 64)
    with pytest.raises(ValueError):
        persist_raw_payload(session, tampered, schema_version="v1")


def test_start_and_finish_fetch_run_records_progress(session):
    run = start_fetch_run(
        session,
        source_name="hkjc",
        run_id="run-1",
        params={"market": "HAD"},
    )
    assert run.status == FetchRunStatus.RUNNING
    assert run.request_count == 0
    assert run.error_count == 0
    assert run.params == {"market": "HAD"}
    assert run.finished_at is None

    finished = finish_fetch_run(
        session,
        run,
        status=FetchRunStatus.FAILED,
        request_count=4,
        error_count=2,
        error_summary="two failures",
    )
    assert finished is run
    assert finished.status == FetchRunStatus.FAILED
    assert finished.request_count == 4
    assert finished.error_count == 2
    assert finished.error_summary == "two failures"
    assert finished.finished_at is not None


def test_finish_fetch_run_rejects_negative_counts(session):
    run = start_fetch_run(session, source_name="hkjc", run_id="run-1")
    with pytest.raises(ValueError):
        finish_fetch_run(
            session,
            run,
            status=FetchRunStatus.FAILED,
            request_count=-1,
            error_count=0,
        )
    assert run.status == FetchRunStatus.RUNNING


def test_finish_fetch_run_rejects_unknown_status(session):
    run = start_fetch_run(session, source_name="hkjc", run_id="run-1")
    bad_status = cast(object, "unknown")
    with pytest.raises(ValueError):
        finish_fetch_run(
            session,
            run,
            status=cast(FetchRunStatus, bad_status),
            request_count=0,
            error_count=0,
        )
    assert run.status == FetchRunStatus.RUNNING
