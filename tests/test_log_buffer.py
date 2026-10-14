import logging

from app import log_buffer


def _root_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, log_buffer.RingBufferHandler)
    ]


def test_install_is_idempotent():
    log_buffer.install("INFO")
    log_buffer.install("INFO")
    assert len(_root_handlers()) == 1


def test_install_attaches_to_uvicorn_loggers():
    log_buffer.install("INFO")
    for name in ("uvicorn.access", "uvicorn.error"):
        handlers = logging.getLogger(name).handlers
        assert any(isinstance(handler, log_buffer.RingBufferHandler) for handler in handlers)


def test_snapshot_is_newest_first_with_expected_fields():
    log_buffer.install("DEBUG")
    logger = logging.getLogger("tests.log_buffer")
    logger.setLevel(logging.DEBUG)
    logger.info("buffer-first")
    logger.error("buffer-second")
    entries = log_buffer.snapshot(10, None)
    assert entries[0]["message"] == "buffer-second"
    assert entries[0]["level"] == "ERROR"
    assert entries[0]["logger"] == "tests.log_buffer"
    assert entries[0]["time"].endswith("+00:00")
    assert set(entries[0]) == {"time", "level", "logger", "message"}
    assert entries[1]["message"] == "buffer-first"


def test_snapshot_filters_by_min_level():
    log_buffer.install("DEBUG")
    logger = logging.getLogger("tests.log_buffer")
    logger.setLevel(logging.DEBUG)
    logger.info("filter-info")
    logger.error("filter-error")
    messages = [entry["message"] for entry in log_buffer.snapshot(500, logging.ERROR)]
    assert "filter-error" in messages
    assert "filter-info" not in messages


def test_snapshot_clamps_limit():
    log_buffer.install("DEBUG")
    logger = logging.getLogger("tests.log_buffer")
    logger.setLevel(logging.DEBUG)
    logger.info("clamp-marker")
    assert len(log_buffer.snapshot(9999, None)) <= log_buffer.MAX_RECORDS
    assert len(log_buffer.snapshot(0, None)) == 1


def _emit_access(path: str, status: int = 200) -> None:
    """Emit a uvicorn.access record with the same logger name and args shape uvicorn uses."""
    logger = logging.getLogger("uvicorn.access")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:54321",
        "GET",
        path,
        "1.1",
        status,
    )


def _access_message(path: str, status: int = 200) -> str:
    return f'127.0.0.1:54321 - "GET {path} HTTP/1.1" {status}'


def _messages() -> list[str]:
    return [entry["message"] for entry in log_buffer.snapshot(500, None)]


def test_access_record_for_health_is_not_stored():
    log_buffer.install("DEBUG")
    _emit_access("/health")
    assert _access_message("/health") not in _messages()


def test_access_record_for_ops_path_is_not_stored():
    log_buffer.install("DEBUG")
    _emit_access("/ops/logs?limit=5")
    assert _access_message("/ops/logs?limit=5") not in _messages()


def test_access_record_for_other_path_is_stored():
    log_buffer.install("DEBUG")
    _emit_access("/matches?limit=5")
    assert _access_message("/matches?limit=5") in _messages()


def test_application_log_record_is_stored():
    log_buffer.install("DEBUG")
    logger = logging.getLogger("app.something")
    logger.setLevel(logging.INFO)
    logger.info("app-log-marker")
    assert "app-log-marker" in _messages()


def test_malformed_access_record_is_stored_and_emit_does_not_raise():
    log_buffer.install("DEBUG")
    logger = logging.getLogger("uvicorn.access")
    logger.setLevel(logging.INFO)
    record = logger.makeRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        "malformed-access %s",
        ("marker",),
        None,
    )
    handler = next(
        item for item in logger.handlers if isinstance(item, log_buffer.RingBufferHandler)
    )
    handler.emit(record)
    assert "malformed-access marker" in _messages()
