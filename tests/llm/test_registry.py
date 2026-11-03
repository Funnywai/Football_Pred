import hashlib
from pathlib import Path

import pytest

from packages.llm.prompts.registry import PromptRecord, PromptRegistry


def test_registry_loads_prompts_with_stable_hashes(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "system.md").write_text("system prompt", encoding="utf-8")
    (prompt_dir / "market_agent.md").write_text("market prompt", encoding="utf-8")

    registry = PromptRegistry.from_directory(prompt_dir)

    record = registry.get("system")
    assert record.name == "system"
    assert record.text == "system prompt"
    assert record.sha256 == hashlib.sha256(b"system prompt").hexdigest()
    assert isinstance(record, PromptRecord)


def test_registry_rejects_missing_prompt(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    registry = PromptRegistry.from_directory(prompt_dir)

    with pytest.raises(KeyError, match="unknown prompt"):
        registry.get("missing")
