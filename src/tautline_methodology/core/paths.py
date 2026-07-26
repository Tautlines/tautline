"""Path-resolution leaves shared across CLI command families (events, usage, instrumentation)."""

from __future__ import annotations

from pathlib import Path


def event_jsonl_read_paths(jsonl: Path, retained: int) -> list[Path]:
    paths: list[Path] = []
    for index in range(retained, 0, -1):
        rotated = jsonl.with_name(f"{jsonl.name}.{index}")
        if rotated.exists():
            paths.append(rotated)
    if jsonl.exists():
        paths.append(jsonl)
    return paths
