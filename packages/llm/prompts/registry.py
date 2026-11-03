from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromptRecord:
    name: str
    text: str
    sha256: str


class PromptRegistry:
    def __init__(self, records: dict[str, PromptRecord]) -> None:
        self._records = records

    @classmethod
    def from_directory(cls, directory: Path) -> PromptRegistry:
        if not directory.is_dir():
            raise ValueError(f"prompt directory does not exist: {directory}")
        records: dict[str, PromptRecord] = {}
        for path in sorted(directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                raise ValueError(f"prompt is blank: {path}")
            records[path.stem] = PromptRecord(
                name=path.stem,
                text=text,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        return cls(records)

    def get(self, name: str) -> PromptRecord:
        try:
            return self._records[name]
        except KeyError as exc:
            raise KeyError(f"unknown prompt: {name}") from exc
