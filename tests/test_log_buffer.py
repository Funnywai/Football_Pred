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
