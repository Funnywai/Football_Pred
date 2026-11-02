from __future__ import annotations

from redis import Redis
from rq import Queue, Worker

from packages.shared.config import get_settings

QUEUE_NAME = "football"


def build_queue() -> Queue:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    return Queue(QUEUE_NAME, connection=connection)


def main() -> None:
    Worker([build_queue()]).work()


if __name__ == "__main__":
    main()
