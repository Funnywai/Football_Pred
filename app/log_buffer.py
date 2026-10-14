"""Bounded in-memory log ring buffer backing ``GET /ops/logs``.

The buffer is per-process and lost on restart; the durable log remains
``docker compose logs app``. ``install`` is idempotent so repeated ``create_app``
calls (as in tests) never double-record.
"""

import logging
import threading
from collections import deque
from datetime import UTC, datetime

MAX_RECORDS = 500

_records: deque[dict[str, str]] = deque(maxlen=MAX_RECORDS)
_lock = threading.Lock()


class RingBufferHandler(logging.Handler):
    """Append every record that reaches this handler to the module ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            with _lock:
                _records.append(entry)
        except Exception:  # noqa: BLE001  (a logging handler must never raise; stdlib StreamHandler does the same)
            self.handleError(record)


def install(level: str) -> None:
    """Attach the ring buffer handler to the root and uvicorn loggers.

    Uvicorn sets ``propagate=False`` on its own loggers, so the handler is attached
    explicitly to ``uvicorn.access`` and ``uvicorn.error`` as well. Idempotent: a
    second call only updates the level of the already-attached handler.
    """
    root = logging.getLogger()
    handler = next(
        (item for item in root.handlers if isinstance(item, RingBufferHandler)), None
    )
    if handler is None:
        handler = RingBufferHandler()
        root.addHandler(handler)
        logging.getLogger("uvicorn.access").addHandler(handler)
        logging.getLogger("uvicorn.error").addHandler(handler)
    handler.setLevel(level.upper())


def _levelno(levelname: str) -> int:
    return logging.getLevelNamesMapping().get(levelname, logging.NOTSET)


def snapshot(limit: int, min_level: int | None) -> list[dict[str, str]]:
    """Return up to ``limit`` buffered records, newest first, optionally filtered."""
    clamped = max(1, min(limit, MAX_RECORDS))
    with _lock:
        records = list(_records)
    if min_level is not None:
        records = [entry for entry in records if _levelno(entry["level"]) >= min_level]
    return list(reversed(records))[:clamped]
