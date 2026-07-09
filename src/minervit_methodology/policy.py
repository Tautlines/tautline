"""Policy projection helpers for the Minervit methodology CLI."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping


def policy_phrase_constants(constants: Mapping[str, object]) -> dict[str, list[str]]:
    """Return the authored guard phrase constants from a module global mapping."""
    excluded = {"RELEASE_ARTIFACT_PATHS"}
    out: dict[str, list[str]] = {}
    for name, value in sorted(constants.items()):
        if name in excluded or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            continue
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            out[name] = list(value)
    return out


def render_policy_phrases_json(constants: Mapping[str, object]) -> str:
    return json.dumps(policy_phrase_constants(constants), indent=2, sort_keys=True) + "\n"


def render_policy_phrases_reference(constants: Mapping[str, object]) -> str:
    data = policy_phrase_constants(constants)
    total = sum(len(v) for v in data.values())
    lines = [
        "# Guard Phrase Vocabulary (GENERATED — do not edit by hand)",
        "",
        f"Generated from the CLI guard constants via `minervit-methodology dump-policy-phrases --write` "
        f"({len(data)} lists, {total} phrases). This is the human-readable projection of "
        "`methodology/policy-phrases.json`; both derive from one CLI source. Edit the CLI "
        "constants, then regenerate.",
        "",
    ]
    for name in sorted(data):
        lines.append(f"## {name} ({len(data[name])})")
        lines.extend(f"- `{phrase}`" for phrase in data[name])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
