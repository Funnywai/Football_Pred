from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
from selectolax.lexbor import LexborHTMLParser

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)


@dataclass(frozen=True)
class NewsItem:
    source_name: str
    title: str
    link: str
    published_at: datetime | None
    summary: str


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _plain_text(html: str) -> str:
    if not html:
        return ""
    return LexborHTMLParser(html).text(separator=" ", strip=True)


def _published_at(entry: object, index: int) -> datetime | None:
    parsed_time = getattr(entry, "published_parsed", None)
    if parsed_time is None:
        return None
    try:
        return datetime(*parsed_time[:6], tzinfo=UTC)
    except (TypeError, ValueError) as exc:
        raise AdapterSchemaError(
            f"invalid published time for feed item {index}"
        ) from exc


class RssNewsAdapter(BaseAdapter):
    name = "rss"
    tos_risk = "low"
    schema_version = "rss-v1"

    def __init__(
        self,
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(
            client=client,
            limiter=limiter if limiter is not None else MinIntervalRateLimiter(900.0),
        )

    def fetch_feed(self, feed_url: str, source_name: str) -> FetchResult:
        return self._get_text(feed_url)

    @staticmethod
    def parse_feed(text: str, source_name: str) -> list[NewsItem]:
        if not isinstance(text, str):
            raise AdapterSchemaError(
                f"feed payload must be text, got {type(text).__name__}"
            )
        if not text.strip():
            raise AdapterSchemaError("feed body is empty")
        parsed = feedparser.parse(text)
        entries = parsed.get("entries", [])
        if not entries and not parsed.get("version"):
            raise AdapterSchemaError(
                "response is not a recognized RSS/Atom feed"
            )
        rows: list[NewsItem] = []
        for index, entry in enumerate(entries):
            rows.append(
                NewsItem(
                    source_name=source_name,
                    title=_clean_text(getattr(entry, "title", "")),
                    link=_clean_text(getattr(entry, "link", "")),
                    published_at=_published_at(entry, index),
                    summary=_plain_text(_clean_text(getattr(entry, "summary", ""))),
                )
            )
        return rows
