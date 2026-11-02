from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from packages.adapters.base import (
    AdapterHTTPError,
    AdapterSchemaError,
    MinIntervalRateLimiter,
    hash_text,
)
from packages.adapters.open_meteo import OpenMeteoAdapter
from packages.adapters.rss_news import RssNewsAdapter

RSS_TEXT = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Football</title>
    <item>
      <title>Team news</title>
      <link>https://example.test/a</link>
      <pubDate>Sat, 15 Aug 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>Hello <b>world</b></p>]]></description>
    </item>
    <item>
      <title>Second item</title>
      <link>https://example.test/b</link>
      <description>Plain text</description>
    </item>
  </channel>
</rss>
"""

WEATHER_PAYLOAD = {
    "hourly": {
        "time": [
            "2026-08-15T12:00",
            "2026-08-15T13:00",
            "2026-08-15T14:00",
        ],
        "temperature_2m": [21.5, 22.0, 22.5],
        "precipitation": [0.0, 0.2, 0.0],
        "wind_speed_10m": [10.0, 12.0, 8.0],
    }
}

NO_LIMIT = MinIntervalRateLimiter(0.0)


def _weather_payload() -> dict:
    return deepcopy(WEATHER_PAYLOAD)


def _feed_with(item_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Football</title>'
        f"{item_xml}"
        "</channel></rss>"
    )


def test_parse_rss_strips_html_and_reads_published_time():
    items = RssNewsAdapter.parse_feed(RSS_TEXT, "BBC")
    assert len(items) == 2
    assert items[0].title == "Team news"
    assert items[0].summary == "Hello world"
    assert items[0].published_at == datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    assert items[1].published_at is None
    assert items[1].source_name == "BBC"


def test_parse_rss_keeps_links_and_source_urls():
    items = RssNewsAdapter.parse_feed(RSS_TEXT, "BBC")

    assert items[0].link == "https://example.test/a"
    assert items[1].link == "https://example.test/b"
    assert items[1].summary == "Plain text"


def test_parse_rss_normalizes_published_offset_to_utc():
    text = _feed_with(
        "<item><title>Offset</title><link>https://example.test/c</link>"
        "<pubDate>Sat, 15 Aug 2026 12:00:00 +0200</pubDate></item>"
    )

    items = RssNewsAdapter.parse_feed(text, "BBC")

    assert items[0].published_at == datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


def test_parse_rss_allows_items_without_published_time_or_summary():
    text = _feed_with("<item><link>https://example.test/d</link></item>")

    items = RssNewsAdapter.parse_feed(text, "BBC")

    assert len(items) == 1
    assert items[0].published_at is None
    assert items[0].title == ""
    assert items[0].summary == ""


def test_parse_rss_allows_empty_well_formed_feed():
    text = '<rss version="2.0"><channel><title>Football</title></channel></rss>'

    assert RssNewsAdapter.parse_feed(text, "BBC") == []


def test_parse_rss_rejects_non_feed_body():
    with pytest.raises(AdapterSchemaError, match="RSS/Atom"):
        RssNewsAdapter.parse_feed("<html><body>blocked</body></html>", "BBC")


def test_parse_rss_rejects_empty_body():
    with pytest.raises(AdapterSchemaError, match="empty"):
        RssNewsAdapter.parse_feed("   ", "BBC")


def test_news_adapter_metadata():
    assert RssNewsAdapter.name == "rss"
    assert RssNewsAdapter.schema_version == "rss-v1"


@respx.mock
def test_fetch_feed_records_provenance():
    url = "https://feeds.example.test/football.xml"
    route = respx.get(url).mock(return_value=httpx.Response(200, text=RSS_TEXT))

    with RssNewsAdapter(limiter=NO_LIMIT) as adapter:
        result = adapter.fetch_feed(url, "BBC")

    assert route.called
    assert result.source_name == "rss"
    assert result.source_url == url
    assert result.http_status == 200
    assert result.schema_version == "rss-v1"
    assert result.raw_text == RSS_TEXT
    assert result.payload_hash == hash_text(RSS_TEXT)


@respx.mock
def test_fetch_feed_500_raises_http_error():
    url = "https://feeds.example.test/football.xml"
    respx.get(url).mock(return_value=httpx.Response(500))

    with (
        RssNewsAdapter(limiter=NO_LIMIT) as adapter,
        pytest.raises(AdapterHTTPError, match="returned 500"),
    ):
        adapter.fetch_feed(url, "BBC")


def test_parse_weather_hourly_returns_decimal_points():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)
    assert len(points) == 3
    assert points[0].time_utc == datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    assert points[0].temperature_c == Decimal("21.5")
    assert points[1].precipitation_mm == Decimal("0.2")


def test_parse_weather_hourly_keeps_wind_as_decimal():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)

    assert points[2].wind_speed_kmh == Decimal("8.0")
    assert points[0].temperature_c == Decimal("21.5")
    assert isinstance(points[0].precipitation_mm, Decimal)


def test_parse_weather_allows_absent_hourly_block():
    assert OpenMeteoAdapter.parse_hourly({}) == []


def test_parse_weather_rejects_non_object_payload():
    with pytest.raises(AdapterSchemaError, match="payload must be an object"):
        OpenMeteoAdapter.parse_hourly(["not-a-payload"])


def test_parse_weather_rejects_non_object_hourly_block():
    with pytest.raises(AdapterSchemaError, match="hourly must be an object"):
        OpenMeteoAdapter.parse_hourly({"hourly": "not-an-object"})


def test_parse_weather_rejects_mismatched_array_lengths():
    payload = _weather_payload()
    payload["hourly"]["precipitation"] = [0.0, 0.2]

    with pytest.raises(AdapterSchemaError, match="different lengths"):
        OpenMeteoAdapter.parse_hourly(payload)


def test_parse_weather_rejects_missing_timestamp():
    payload = _weather_payload()
    payload["hourly"]["time"][1] = None

    with pytest.raises(AdapterSchemaError, match="timestamp"):
        OpenMeteoAdapter.parse_hourly(payload)


def test_parse_weather_rejects_malformed_timestamp():
    payload = _weather_payload()
    payload["hourly"]["time"][0] = "not-a-timestamp"

    with pytest.raises(AdapterSchemaError, match="timestamp"):
        OpenMeteoAdapter.parse_hourly(payload)


def test_parse_weather_rejects_non_numeric_temperature():
    payload = _weather_payload()
    payload["hourly"]["temperature_2m"][0] = "abc"

    with pytest.raises(AdapterSchemaError, match="temperature_2m"):
        OpenMeteoAdapter.parse_hourly(payload)


def test_parse_weather_rejects_non_finite_temperature():
    payload = _weather_payload()
    payload["hourly"]["temperature_2m"][0] = "NaN"

    with pytest.raises(AdapterSchemaError, match="temperature_2m"):
        OpenMeteoAdapter.parse_hourly(payload)


def test_weather_adapter_metadata():
    assert OpenMeteoAdapter.name == "open-meteo"
    assert OpenMeteoAdapter.schema_version == "v1"


@respx.mock
def test_fetch_hourly_sends_utc_request_and_records_provenance():
    url = "https://api.open-meteo.com/v1/forecast"
    route = respx.get(url).mock(return_value=httpx.Response(200, json=WEATHER_PAYLOAD))

    with OpenMeteoAdapter(limiter=NO_LIMIT) as adapter:
        result = adapter.fetch_hourly(51.5, -0.1, date(2026, 8, 15), date(2026, 8, 15))

    assert route.called
    request = route.calls[0].request
    assert request.url.params["latitude"] == "51.5"
    assert request.url.params["longitude"] == "-0.1"
    assert request.url.params["timezone"] == "UTC"
    assert request.url.params["start_date"] == "2026-08-15"
    assert request.url.params["end_date"] == "2026-08-15"
    assert request.url.params["hourly"] == (
        "temperature_2m,precipitation,wind_speed_10m"
    )
    assert result.source_name == "open-meteo"
    assert result.schema_version == "v1"
    assert result.http_status == 200
    assert result.payload_hash == hash_text(result.raw_text)


def test_nearest_weather_point_uses_kickoff_window():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)
    summary = OpenMeteoAdapter.nearest_to_kickoff(
        points,
        datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
    )
    assert summary is not None
    assert summary.delta_hours == 0.0
    assert summary.point.temperature_c == Decimal("22.5")
    missing = OpenMeteoAdapter.nearest_to_kickoff(
        points,
        datetime(2026, 8, 16, 14, 0, tzinfo=UTC),
    )
    assert missing is None


def test_nearest_weather_point_accepts_nearby_hour():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)

    summary = OpenMeteoAdapter.nearest_to_kickoff(
        points,
        datetime(2026, 8, 15, 12, 30, tzinfo=UTC),
    )

    assert summary is not None
    assert summary.delta_hours == 0.5
    assert summary.point.temperature_c == Decimal("21.5")


def test_nearest_weather_point_treats_naive_kickoff_as_utc():
    points = OpenMeteoAdapter.parse_hourly(WEATHER_PAYLOAD)

    summary = OpenMeteoAdapter.nearest_to_kickoff(points, datetime(2026, 8, 15, 14, 0))

    assert summary is not None
    assert summary.delta_hours == 0.0


def test_nearest_weather_point_returns_none_for_no_points():
    assert (
        OpenMeteoAdapter.nearest_to_kickoff(
            [],
            datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
        )
        is None
    )
