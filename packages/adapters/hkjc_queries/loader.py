from pathlib import Path

from packages.adapters.base import AdapterSchemaError

QUERY_FILES = {
    "HAD": "had.graphql",
    "HDC": "hdc.graphql",
    "HIL": "hil.graphql",
    "matchResults": "match_results.graphql",
}

_GRAPHQL_PREFIXES = ("query", "mutation", "fragment")


class HkjcQueryMissingError(AdapterSchemaError):
    pass


def load_query(queries_dir: Path, key: str) -> str:
    filename = QUERY_FILES.get(key)
    if filename is None:
        raise KeyError(f"unknown HKJC query key {key}")
    path = Path(queries_dir) / filename
    if not path.is_file():
        raise HkjcQueryMissingError(f"missing captured query {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise HkjcQueryMissingError(f"empty captured query {path}")
    if not text.startswith(_GRAPHQL_PREFIXES):
        raise HkjcQueryMissingError(f"captured query is not GraphQL: {path}")
    return text
