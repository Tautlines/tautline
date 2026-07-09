"""Adapter schema helper primitives for the Minervit methodology CLI."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path


_ADAPTER_SCHEMA_CACHE: dict[Path, dict] = {}
DEFAULT_RENDER_BUDGET = {"maxGeneratedBytes": 31000, "minGeneratedBytes": 15000, "enforcement": "warn"}


def adapter_schema(schema_path: Path) -> dict | None:
    """Load and cache the adapter JSON Schema.

    Returns None if it is unavailable/unreadable. Schema validation is a
    fail-loud typo/contract check layered on top of the CLI's semantic checks;
    if the schema itself cannot be read, callers keep running those deeper
    checks rather than wedging every adapter load.
    """
    schema_path = schema_path.resolve()
    if schema_path not in _ADAPTER_SCHEMA_CACHE:
        try:
            with schema_path.open("r", encoding="utf-8") as f:
                _ADAPTER_SCHEMA_CACHE[schema_path] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _ADAPTER_SCHEMA_CACHE[schema_path] = {}
    return _ADAPTER_SCHEMA_CACHE[schema_path] or None


def schema_type_matches(value: object, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return True


def schema_validation_errors(instance: object, schema: dict, path: str = "(root)") -> list[str]:
    """Stdlib-only JSON-Schema subset validator.

    Supports the keywords the adapter schema uses: type, properties, required,
    additionalProperties, enum, const, items, minItems, minLength, pattern,
    minimum, maximum, oneOf, allOf, if/then/else.
    """
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    declared_type = schema.get("type")
    if declared_type is not None:
        candidates = declared_type if isinstance(declared_type, list) else [declared_type]
        if not any(schema_type_matches(instance, t) for t in candidates):
            errors.append(f"{path}: expected type {declared_type}, got {type(instance).__name__}")
            return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, instance) is None:
            errors.append(f"{path}: does not match pattern {pattern!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: less than minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: greater than maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: has fewer than minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, element in enumerate(instance):
                errors.extend(schema_validation_errors(element, item_schema, f"{path}[{index}]"))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for required_key in schema.get("required", []):
            if required_key not in instance:
                errors.append(f"{path}: missing required property '{required_key}'")
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                errors.extend(schema_validation_errors(value, properties[key], f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: unknown property '{key}' (not allowed by the adapter schema)")
            elif isinstance(additional, dict):
                errors.extend(schema_validation_errors(value, additional, f"{path}.{key}"))

    for sub_schema in schema.get("allOf", []):
        errors.extend(schema_validation_errors(instance, sub_schema, path))
    if "oneOf" in schema:
        matched = sum(1 for sub in schema["oneOf"] if not schema_validation_errors(instance, sub, path))
        if matched != 1:
            errors.append(f"{path}: must match exactly one schema in oneOf (matched {matched})")
    if "if" in schema:
        condition_failed = bool(schema_validation_errors(instance, schema["if"], path))
        branch = schema.get("else") if condition_failed else schema.get("then")
        if isinstance(branch, dict):
            errors.extend(schema_validation_errors(instance, branch, path))

    return errors


def project_json_decode_error(path: Path, exc: json.JSONDecodeError, *, lane_adapter_file: str | tuple[str, ...]) -> str:
    details = f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raw = ""
    hints = []
    if any(marker in raw for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        hints.append("unresolved Git conflict markers are present")
    lane_adapter_names = (lane_adapter_file,) if isinstance(lane_adapter_file, str) else lane_adapter_file
    if path.name in lane_adapter_names:
        hints.append(
            "This is a generated lane adapter. Re-render it from the canonical project adapter instead of hand-editing it: "
            "minervit-methodology render-adapters --project <methodology_repo>/adapters/projects/<project>.json "
            "--target <lane> --write --json-only"
        )
    else:
        hints.append("Fix the project adapter JSON before running lane startup or status commands.")
    return details + "\n" + "\n".join(f"hint: {hint}" for hint in hints)


def validate_adapter_schema(data: dict, path: Path, schema_path: Path) -> None:
    schema = adapter_schema(schema_path)
    if schema is None:
        return
    errors = schema_validation_errors(data, schema)
    if errors:
        shown = "\n  - ".join(errors[:12])
        more = "" if len(errors) <= 12 else f"\n  ... and {len(errors) - 12} more"
        raise SystemExit(
            f"Project adapter {path} does not match the adapter schema "
            f"({schema_path.name}):\n  - {shown}{more}"
        )


def render_budget_for(data: dict) -> dict:
    budget = dict(DEFAULT_RENDER_BUDGET)
    configured = data.get("renderBudget")
    if isinstance(configured, dict):
        for key in ("maxGeneratedBytes", "minGeneratedBytes", "enforcement"):
            if key in configured:
                budget[key] = configured[key]
    return budget


def render_budget_errors(data: dict, expected: dict, *, generated_markdown_files: set[str]) -> list[str]:
    """Validate adapter-tunable generated-file size budgets."""
    budget = render_budget_for(data)
    errors: list[str] = []
    for rel, content in expected.items():
        if posixpath.basename(rel) not in generated_markdown_files:
            continue
        size = len(content.encode("utf-8"))
        if size > budget["maxGeneratedBytes"]:
            errors.append(f"{rel} is {size} bytes, over renderBudget.maxGeneratedBytes {budget['maxGeneratedBytes']}")
        elif size < budget["minGeneratedBytes"]:
            errors.append(f"{rel} is {size} bytes, under renderBudget.minGeneratedBytes {budget['minGeneratedBytes']}")
    return errors
