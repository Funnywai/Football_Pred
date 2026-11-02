"""Capture the official HKJC GraphQL query strings once, then store them as fixtures.

HKJC rejects query strings that its own website did not send. Never hand-write
these files: open the official site, visit the markets, and let this script
record the exact request bodies. Re-run it whenever HKJC updates its whitelist.

The live site uses one parameterized ``matchList`` query for HAD, HDC and HIL;
only the ``fbOddsTypes`` variable changes. It is therefore expected (and fine)
for ``had.graphql``, ``hdc.graphql`` and ``hil.graphql`` to hold identical text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET = "https://info.cld.hkjc.com/graphql/base/"
OUT = Path("packages/adapters/hkjc_queries")
MARKET_KEYS = ("HAD", "HDC", "HIL", "matchResults")
FILENAMES = {
    "HAD": "had.graphql",
    "HDC": "hdc.graphql",
    "HIL": "hil.graphql",
    "matchResults": "match_results.graphql",
}
EXPECTED_PREFIX = {
    "HAD": "query matchlist",
    "HDC": "query matchlist",
    "HIL": "query matchlist",
    "matchResults": "query matchresults",
}
_GRAPHQL_PREFIXES = ("query", "mutation", "fragment")


def _identify_operation(decoded: dict[str, object]) -> str | None:
    """Map a captured request to one market key without guessing."""
    operation = str(decoded.get("operationName") or "")
    query = decoded.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    lowered_query = query.lower()
    if operation == "matchResults" or "query matchresults" in lowered_query:
        return "matchResults"

    raw_variables = decoded.get("variables")
    variables = raw_variables if isinstance(raw_variables, dict) else {}
    raw_types = variables.get("fbOddsTypes")
    odds_types = (
        {str(item).upper() for item in raw_types}
        if isinstance(raw_types, list)
        else set()
    )
    if "HAD" in odds_types:
        return "HAD"
    if odds_types & {"HDC", "EDC"}:
        return "HDC"
    if odds_types & {"HIL", "EHL"}:
        return "HIL"
    if operation in MARKET_KEYS:
        return operation

    matches = [key for key in MARKET_KEYS if key.lower() in lowered_query]
    if len(matches) == 1:
        return matches[0]
    return None


def _capture_body(body: str) -> tuple[str | None, str]:
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(decoded, dict):
        return None, ""
    query = decoded.get("query")
    if not isinstance(query, str) or not query.strip().startswith(_GRAPHQL_PREFIXES):
        return None, ""
    return _identify_operation(decoded), query.strip()


def _run_capture() -> dict[str, str]:
    from playwright.sync_api import sync_playwright

    captured: dict[str, str] = {}

    def on_request(request: object) -> None:
        url = getattr(request, "url", "")
        method = getattr(request, "method", "")
        if url != TARGET or method != "POST":
            return
        body = getattr(request, "post_data", None)
        if not body:
            return
        key, query = _capture_body(body)
        if key is not None and key not in captured:
            captured[key] = query

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("request", on_request)
        page.goto("https://bet.hkjc.com/football", wait_until="domcontentloaded")
        input(
            "Open one football match with HAD, HDC and HIL odds, plus a finished "
            "result if available, then press Enter here."
        )
        browser.close()
    return captured


def main() -> int:
    try:
        captured = _run_capture()
    except ModuleNotFoundError:
        print(
            "playwright is not installed. Run `uv sync` (dev group) and "
            "`uv run playwright install chromium` before capturing.",
            file=sys.stderr,
        )
        return 2

    missing = [key for key in MARKET_KEYS if key not in captured]
    if missing:
        print(f"missing capture for: {', '.join(missing)}", file=sys.stderr)
        return 1

    for key in MARKET_KEYS:
        if not captured[key].lower().startswith(EXPECTED_PREFIX[key]):
            print(
                f"captured text for {key} does not start with {EXPECTED_PREFIX[key]!r}; "
                "refusing to write a query that is not the expected official operation.",
                file=sys.stderr,
            )
            return 1

    market_texts = {captured[key] for key in ("HAD", "HDC", "HIL")}
    if len(market_texts) > 1:
        print(
            "note: HAD/HDC/HIL captured different text; storing each capture as-is",
            file=sys.stderr,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    for key in MARKET_KEYS:
        path = OUT / FILENAMES[key]
        path.write_text(captured[key], encoding="utf-8")
        print(f"wrote {path} ({len(captured[key])} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
