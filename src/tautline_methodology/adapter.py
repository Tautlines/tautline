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


# --- adapter-schema version skew (backlog item 1 Release B) -------------------------------------
#
# THE CONTROL ID THIS MODULE EXPECTS, recorded here because `FAIL_CLOSED_CONTROLS` does not exist
# yet and `fail-closed-remedy-composition` owns it. When that registry lands it should inherit:
#
#   control id: prepush.adapter-schema-skew
#   closed path: tests/test_prepush_schema_skew.py
#                 ::test_unprovable_unknown_key_still_refuses_under_the_hook_signal
#   open path:   tests/test_prepush_schema_skew.py
#                 ::test_lane_adds_a_key_with_the_old_installed_cli_resolvable
#
# LAYERING INVARIANT: this module is a stdlib-only leaf (json, posixpath, re, pathlib) and stays
# one. Nothing here imports from `cli` or `core.runtime` -- so the remedy verbs below are NOT
# cross-checked against STARTUP_REMEDIATION_ALLOWED_COMMANDS here; that check lives in the test,
# which may import both. A reviewer reading a remedy string in a leaf module will ask; this is why.

_ROOT_UNKNOWN_PROPERTY = re.compile(
    r"^\(root\): unknown property '([^']+)' \(not allowed by the adapter schema\)$"
)
_SELF_AUTHORITY_MAX_DEPTH = 6


def unknown_top_level_property_keys(errors: list[str]) -> tuple[str, ...]:
    """The offending root keys, but ONLY when every error is a root-level unknown property.

    Deliberately all-or-nothing. A nested unknown property, a type error, a missing required key --
    any one of them disqualifies the whole list, because the downgrade this feeds is only ever
    sound for "the installed schema does not know this top-level key yet". A list that mixes an
    unknown key with a real validation failure is not version skew; it is a broken adapter, and
    reporting-and-continuing on it would hide the second error behind the first.
    """
    if not errors:
        return ()
    keys: list[str] = []
    for error in errors:
        match = _ROOT_UNKNOWN_PROPERTY.match(error.strip())
        if match is None:
            return ()
        keys.append(match.group(1))
    return tuple(keys)


def self_authoritative_schema_path(adapter_path: Path) -> Path | None:
    """The schema of the framework checkout the adapter lives in, if there is one.

    Walks up at most six levels looking for a directory carrying BOTH
    ``methodology/adapter-schema.json`` and ``src/tautline_methodology/cli.py``. Both, because a
    tree with the engine but no schema is not an authority on a schema it does not have.

    No subprocess, bounded depth, and ``resolve()``-based so a symlink loop cannot spin it.
    """
    try:
        current = adapter_path.resolve().parent
    except OSError:
        return None
    for _ in range(_SELF_AUTHORITY_MAX_DEPTH):
        schema = current / "methodology" / "adapter-schema.json"
        if schema.is_file() and (current / "src" / "tautline_methodology" / "cli.py").is_file():
            return schema
        if current.parent == current:
            break
        current = current.parent
    return None


def _semver_tuple(value: object) -> tuple[int, ...] | None:
    """Parse a plain dotted numeric version. Returns None for anything that is not one."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if not parts or len(parts) > 4:
        return None
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers)


def adapter_schema_skew_classification(
    data: dict,
    path: Path,
    *,
    installed_schema_path: Path,
    installed_version: str,
) -> dict | None:
    """Classify an unknown-top-level-key refusal as provable skew, or decline to.

    Returns None unless one of the two signals below fires, and records which. The `disposition`
    field is the whole point of the return shape: exactly one signal earns a downgrade, and the
    canonical downgrade rule reads that field rather than re-deriving the distinction. One field,
    one reader.

    PROOF `tree-authoritative` -> disposition `downgrade`. The adapter lives inside a framework
    checkout whose own schema is a DIFFERENT file from the installed one, and re-validating against
    that schema is clean. This is the only sound proof, because it is the only one that consults a
    schema which actually declares the key. The tree being pushed accepts its own adapter; the
    installed schema is the stale party.

    SIGNAL `generator-newer` -> disposition `refuse`. The adapter's `_generated.pluginVersion` is
    strictly newer than the installed CLI. This proves the RENDERER was newer and proves NOTHING
    about the key: "declared nowhere in the installed schema" is satisfied by a misspelling exactly
    as it is by a legitimate new key. An earlier draft of this plan made it a downgrade proof, and
    plan review caught that it would have excused a real typo on any machine with a stale install.
    So it refuses -- unchanged behaviour -- and its only effect is that the refusal finally names a
    remedy that works.

    A lagging stamp is evidence of nothing either: a framework lane's `.tautline.json` is
    regenerated by `lane-start` and routinely stamps a version older than its own tree.
    """
    errors = schema_validation_errors(data, adapter_schema(installed_schema_path) or {})
    keys = unknown_top_level_property_keys(errors)
    if not keys:
        return None

    tree_schema_path = self_authoritative_schema_path(path)
    if tree_schema_path is not None and tree_schema_path != installed_schema_path.resolve():
        tree_schema = adapter_schema(tree_schema_path)
        if tree_schema is not None and not schema_validation_errors(data, tree_schema):
            # The authority is named RELATIVE to the lane, never absolutely. A hook report is
            # copied into CI logs and pasted into issues; `authority=/Users/<someone>/...` leaks
            # local filesystem layout for no diagnostic gain, since the only useful fact is WHICH
            # tree answered, and "the checkout N levels up" says that.
            lane_dir = path.resolve().parent
            tree_root = tree_schema_path.parent.parent
            try:
                relative = tree_schema_path.relative_to(lane_dir).as_posix()
            except ValueError:
                relative = f"the enclosing framework checkout's {tree_schema_path.name}"
            # The reinstall command is qualified to THIS checkout, relative to the lane. The
            # tree-authoritative proof means that checkout exists and is current -- it is what
            # accepted the adapter -- so there is no reason to route the reinstall through PATH,
            # where the stale install that produced this report may still win. Relative, not
            # absolute, so a hook log copied into CI does not publish the machine's layout.
            # posixpath.relpath, not Path.relative_to: the adapter is often in a SUBDIRECTORY of
            # the checkout, where the CLI is above it and relative_to raises. Codex caught that the
            # empty fallback then printed a bare `bin/tautline`, which resolves against the lane
            # subdirectory -- a remedy pointing at a path that does not exist. relpath emits the
            # `../` form, which is still relative (nothing absolute reaches a copied log) and
            # actually resolves.
            cli_relative = posixpath.relpath(
                (tree_root / "bin" / "tautline").as_posix(), lane_dir.as_posix()
            )
            return {
                "proof": "tree-authoritative",
                "disposition": "downgrade",
                "keys": keys,
                "installedVersion": installed_version,
                "authority": relative,
                "treeCli": cli_relative,
                "adapterFile": path.name,
            }

    generated = data.get("_generated")
    stamped = generated.get("pluginVersion") if isinstance(generated, dict) else None
    stamped_tuple = _semver_tuple(stamped)
    installed_tuple = _semver_tuple(installed_version)
    have_both = stamped_tuple is not None and installed_tuple is not None
    if have_both and stamped_tuple > installed_tuple:
        return {
            "proof": "generator-newer",
            "disposition": "refuse",
            "keys": keys,
            "installedVersion": installed_version,
            "authority": f"generator {stamped}",
        }
    return None


def adapter_schema_skew_report_lines(classification: dict) -> tuple[str, ...]:
    """The report text, and it says only what is actually known and actually runnable.

    TWO SHAPES, because the two dispositions know different amounts, and neither may name a command
    that cannot run in the state that produced it. That last clause is not obvious and cost three
    review rounds: **every verb this CLI offers loads and validates the lane adapter first.**
    `sync_methodology` calls `lane_project`, so running it from the stale install fails with the
    IDENTICAL schema violation instead of fixing anything. A remedy blocked by the error it exists
    to clear is the defect this whole item was filed against.

    `downgrade` (proof `tree-authoritative`): the lane's own checkout accepts this adapter, so it is
    already current -- there is **nothing to sync**, and naming a sync here would have been both
    useless and circular. The remedy is to rewrite the hook from that checkout and confirm against
    it. Both commands are qualified to it, relative to the lane, so `PATH` cannot route them back to
    the stale install and no absolute path reaches a copied log.

    `refuse` (signal `generator-newer`): there is no authoritative checkout -- that is why it
    refuses -- so no command run through this lane can clear it, and the report says so instead of
    pretending. It names the ambiguity (this CLI cannot tell a new key from a misspelling), names
    the one action that always works if it IS a typo, and says plainly that updating the install has
    to happen outside this lane.
    """
    keys = ", ".join(classification["keys"])
    head = (
        f"adapter_schema_version_skew: unknown top-level key(s) {keys}; "
        f"signal={classification['proof']} disposition={classification['disposition']} "
        f"installed_version={classification['installedVersion']} "
        f"authority={classification['authority']}"
    )
    if classification["disposition"] == "downgrade":
        cli = classification.get("treeCli") or "bin/tautline"
        # The adapter's OWN filename, not a hardcoded one. Legacy lanes are still supported and
        # still use `.minervit-ai-delivery.json`; telling one of those to validate `.tautline.json`
        # points the confirmation step at a file that is not there.
        adapter_file = classification.get("adapterFile") or ".tautline.json"
        return (
            head,
            f"adapter_schema_version_skew_remedy: {cli} install-hooks --target .",
            f"adapter_schema_version_skew_remedy: {cli} validate-adapter --project {adapter_file}",
        )
    return (
        head,
        "adapter_schema_version_skew_hint: the installed CLI is older than the generator that "
        "wrote this adapter. That does NOT establish the key is legitimate -- this CLI cannot "
        "tell a new key from a misspelled one -- so what follows is offered, not promised.",
        "adapter_schema_version_skew_hint: if the key is misspelled, fix the spelling; that always "
        "clears this and needs no tooling.",
        "adapter_schema_version_skew_hint: if the key is correct, this install is too old for it. "
        "Update it from the framework checkout itself -- not through this lane, because every verb "
        "here re-validates this adapter with the same stale schema and fails identically.",
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
