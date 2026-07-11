"""T1 (0.9.0 sanitized instrumentation): `instrumentation_record_errors(record) -> list[str]` in
bin/tautline is the ONE authority for instrumentation-record validity. `methodology/
instrumentation-schema.json` is GENERATED from the same in-code field rules via `dump-
instrumentation-schema --write|--check`, so the schema and the validator cannot drift by
construction. This module is the shared adversarial fixture corpus: every attack fixture is
asserted rejected by BOTH the in-code validator and (shape-wise) the generated schema artifact
loaded straight off disk, and a static walk of that artifact asserts additionalProperties:false at
every object level and that every string-typed property is const/enum/pattern constrained (i.e.
the schema itself has no freeform string capacity).

The operator-approved v1 event vocabulary (T0, sha256 fe966b2a...) is transcribed verbatim below
and pinned against the CLI constant so an unreviewed enum edit fails the gate.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTATION_SCHEMA_FILE = ROOT / "methodology" / "instrumentation-schema.json"

# Transcribed verbatim from docs/superpowers/plans/.plan-reviews/2026-07-10-sanitized-
# instrumentation-telemetry-v4-t0-vocabulary-approval.json (sha256 fe966b2a...), the operator-
# approved v1 vocabulary. Order matters for the hash preimage, so this list is deliberately not
# re-sorted.
OPERATOR_APPROVED_VOCABULARY = (
    "startup",
    "preflight",
    "planning_review_gate",
    "plan_review_round",
    "plan_review_clean",
    "plan_review_blocked",
    "implementation_review_round",
    "implementation_review_clean",
    "implementation_review_blocked",
    "gate_block",
    "autonomy_stop",
    "human_question",
    "blocker_declared",
    "blocker_cleared",
    "rca",
    "continuity_written",
    "context_rotation",
    "goal_transition",
    "milestone_transition",
    "pr_opened",
    "pr_queue_merge",
    "pr_merged",
    "ci_wait",
    "merge_queue_wait",
    "task_started",
    "task_completed",
    "session_end",
)


def _valid_record() -> dict:
    return {
        "schema": "tautline-instrumentation/v1",
        "emitted_at": "2026-07-10T12:00:00+00:00",
        "lane_id": "9f2c4a1b0e7d5c3a",
        "plugin_version": "0.9.0",
        "window_seconds": 5400,
        "window_gap": False,
        "end_seq": 12,
        "events": [
            {"code": "plan_review_round", "count": 3, "total_seconds": 1820.5, "round": 3},
            {"code": "gate_block", "count": 1},
            {"code": "context_rotation", "count": 1, "ordinal": 2},
        ],
    }


def _gap_record() -> dict:
    record = _valid_record()
    record["window_gap"] = True
    record["window_seconds"] = 0
    record["events"] = []
    return record


def _with(base: dict, path: tuple, value: object) -> dict:
    """Deep-set a single field on a fresh copy of `base`, addressed by a key/index path."""
    record = copy.deepcopy(base)
    node = record
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return record


def _without(base: dict, key: str) -> dict:
    record = copy.deepcopy(base)
    del record[key]
    return record


# A "product-looking" freeform string -- exactly the kind of narrative the schema must never be
# able to carry (operator acceptance bar: adversarial injection tests attack EVERY field).
FREEFORM = "shipped the auth refactor to prod for project acme-widgets, see PR #482"

ATTACK_FIXTURES: list[tuple[str, object]] = [
    ("record_is_a_list", ["not", "a", "record"]),
    ("record_is_a_string", "definitely not a record"),
    ("unknown_top_level_key", _with(_valid_record(), ("notes",), FREEFORM)),
    ("unknown_event_key", _with(_valid_record(), ("events", 0, "detail"), FREEFORM)),
    ("out_of_enum_code", _with(_valid_record(), ("events", 0, "code"), "shipped_to_prod")),
    ("freeform_schema_field", _with(_valid_record(), ("schema",), FREEFORM)),
    ("freeform_emitted_at", _with(_valid_record(), ("emitted_at",), FREEFORM)),
    ("freeform_lane_id", _with(_valid_record(), ("lane_id",), FREEFORM)),
    ("freeform_plugin_version", _with(_valid_record(), ("plugin_version",), FREEFORM)),
    ("freeform_window_seconds", _with(_valid_record(), ("window_seconds",), FREEFORM)),
    ("freeform_window_gap", _with(_valid_record(), ("window_gap",), FREEFORM)),
    ("freeform_end_seq", _with(_valid_record(), ("end_seq",), FREEFORM)),
    ("freeform_event_code", _with(_valid_record(), ("events", 0, "code"), FREEFORM)),
    ("freeform_event_count", _with(_valid_record(), ("events", 0, "count"), FREEFORM)),
    ("freeform_event_total_seconds", _with(_valid_record(), ("events", 0, "total_seconds"), FREEFORM)),
    ("freeform_event_round", _with(_valid_record(), ("events", 0, "round"), FREEFORM)),
    ("freeform_event_ordinal", _with(_valid_record(), ("events", 2, "ordinal"), FREEFORM)),
    ("zero_count", _with(_valid_record(), ("events", 0, "count"), 0)),
    ("negative_count", _with(_valid_record(), ("events", 0, "count"), -1)),
    ("negative_window_seconds", _with(_valid_record(), ("window_seconds",), -1)),
    ("negative_end_seq", _with(_valid_record(), ("end_seq",), -1)),
    ("negative_ordinal", _with(_valid_record(), ("events", 2, "ordinal"), -1)),
    ("negative_round", _with(_valid_record(), ("events", 0, "round"), -1)),
    ("lane_id_too_short", _with(_valid_record(), ("lane_id",), "abc123")),
    ("lane_id_too_long", _with(_valid_record(), ("lane_id",), "9f2c4a1b0e7d5c3a00")),
    ("lane_id_uppercase", _with(_valid_record(), ("lane_id",), "9F2C4A1B0E7D5C3A")),
    ("lane_id_non_hex", _with(_valid_record(), ("lane_id",), "9f2c4a1b0e7d5c3g")),
    ("timestamp_missing_timezone", _with(_valid_record(), ("emitted_at",), "2026-07-10T12:00:00")),
    ("timestamp_wrong_format", _with(_valid_record(), ("emitted_at",), "07/10/2026 12:00:00")),
    ("timestamp_non_utc_offset", _with(_valid_record(), ("emitted_at",), "2026-07-10T12:00:00+01:00")),
    ("timestamp_space_separator", _with(_valid_record(), ("emitted_at",), "2026-07-10 12:00:00+00:00")),
    ("version_missing_patch", _with(_valid_record(), ("plugin_version",), "0.9")),
    ("version_leading_v", _with(_valid_record(), ("plugin_version",), "v0.9.0")),
    ("version_prerelease_suffix", _with(_valid_record(), ("plugin_version",), "0.9.0-beta")),
    ("wrong_schema_version_v2", _with(_valid_record(), ("schema",), "tautline-instrumentation/v2")),
    (
        "forged_empty_non_gap_record",
        _with(_valid_record(), ("events",), []),
    ),
    ("missing_events_key", _without(_valid_record(), "events")),
    ("missing_lane_id_key", _without(_valid_record(), "lane_id")),
    ("missing_schema_key", _without(_valid_record(), "schema")),
]


def test_valid_record_passes_validator_and_schema_artifact(cli):
    schema = json.loads(INSTRUMENTATION_SCHEMA_FILE.read_text(encoding="utf-8"))
    assert cli.instrumentation_record_errors(_valid_record()) == []
    assert cli.schema_validation_errors(_valid_record(), schema) == []


def test_gap_record_with_empty_events_is_valid(cli):
    schema = json.loads(INSTRUMENTATION_SCHEMA_FILE.read_text(encoding="utf-8"))
    assert cli.instrumentation_record_errors(_gap_record()) == []
    assert cli.schema_validation_errors(_gap_record(), schema) == []


def test_attack_corpus_rejected_by_validator(cli):
    failures = []
    for name, record in ATTACK_FIXTURES:
        errors = cli.instrumentation_record_errors(record)
        if not errors:
            failures.append(name)
    assert failures == [], f"attack fixtures accepted by instrumentation_record_errors: {failures}"


def test_attack_corpus_rejected_by_generated_schema_artifact(cli):
    """Shape-wise: the same corpus must also be rejected by the PERSISTED schema file (not just
    the in-code dict), so a serialization/round-trip bug can't quietly widen the artifact."""
    schema = json.loads(INSTRUMENTATION_SCHEMA_FILE.read_text(encoding="utf-8"))
    failures = []
    for name, record in ATTACK_FIXTURES:
        errors = cli.schema_validation_errors(record, schema)
        if not errors:
            failures.append(name)
    assert failures == [], f"attack fixtures accepted by the generated schema artifact: {failures}"


def _walk_object_schemas(schema: object):
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        yield schema
    for prop_schema in (schema.get("properties") or {}).values():
        yield from _walk_object_schemas(prop_schema)
    items_schema = schema.get("items")
    if isinstance(items_schema, dict):
        yield from _walk_object_schemas(items_schema)


def _walk_string_properties(schema: object):
    if not isinstance(schema, dict):
        return
    for name, prop_schema in (schema.get("properties") or {}).items():
        if isinstance(prop_schema, dict) and prop_schema.get("type") == "string":
            yield name, prop_schema
        yield from _walk_string_properties(prop_schema)
    items_schema = schema.get("items")
    if isinstance(items_schema, dict):
        yield from _walk_string_properties(items_schema)


def test_schema_additional_properties_false_at_every_object_level():
    schema = json.loads(INSTRUMENTATION_SCHEMA_FILE.read_text(encoding="utf-8"))
    object_nodes = list(_walk_object_schemas(schema))
    # root record object + event item object, at minimum
    assert len(object_nodes) >= 2
    non_closed = [node for node in object_nodes if node.get("additionalProperties") is not False]
    assert non_closed == [], f"object schema nodes without additionalProperties:false: {non_closed}"


def test_schema_every_string_property_is_const_enum_or_pattern_constrained():
    schema = json.loads(INSTRUMENTATION_SCHEMA_FILE.read_text(encoding="utf-8"))
    string_props = list(_walk_string_properties(schema))
    names = [name for name, _ in string_props]
    # schema, emitted_at, lane_id, plugin_version, events[].code -- the design's exhaustive list
    # of string-typed fields.
    assert set(names) == {"schema", "emitted_at", "lane_id", "plugin_version", "code"}
    unconstrained = [
        name
        for name, prop_schema in string_props
        if not ({"const", "enum", "pattern"} & prop_schema.keys())
    ]
    assert unconstrained == [], f"freeform (unconstrained) string properties: {unconstrained}"


def test_event_code_enum_matches_instrumentation_event_codes_tuple(cli):
    schema = json.loads(INSTRUMENTATION_SCHEMA_FILE.read_text(encoding="utf-8"))
    enum = schema["properties"]["events"]["items"]["properties"]["code"]["enum"]
    assert enum == list(cli.INSTRUMENTATION_EVENT_CODES)


def test_instrumentation_event_codes_is_a_tuple(cli):
    # Constant gotcha: an UPPER_CASE list-of-str constant auto-enters the policy-phrases SSOT and
    # breaks test_policy_phrases_ssot.py. The event vocabulary must be a tuple.
    assert isinstance(cli.INSTRUMENTATION_EVENT_CODES, tuple)
    assert "INSTRUMENTATION_EVENT_CODES" not in cli.policy_phrase_constants()


def test_instrumentation_event_codes_matches_operator_approved_vocabulary(cli):
    assert cli.INSTRUMENTATION_EVENT_CODES == OPERATOR_APPROVED_VOCABULARY


def test_instrumentation_schema_file_is_fresh():
    res = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "tautline"), "dump-instrumentation-schema", "--check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert res.returncode == 0, (
        "stale methodology/instrumentation-schema.json; run "
        f"bin/tautline dump-instrumentation-schema --write\n{res.stdout}{res.stderr}"
    )


def test_dump_instrumentation_schema_check_passes(run_cli):
    res = run_cli("dump-instrumentation-schema", "--check")
    assert res.returncode == 0, res.stderr
    assert "ok" in res.stdout


def test_dump_instrumentation_schema_write_round_trips(run_cli, tmp_path):
    output = tmp_path / "instrumentation-schema.json"
    written = run_cli("dump-instrumentation-schema", "--write", "--output", str(output))
    assert written.returncode == 0, written.stderr
    assert output.exists()
    checked = run_cli("dump-instrumentation-schema", "--check", "--output", str(output))
    assert checked.returncode == 0, checked.stderr


def test_dump_instrumentation_schema_is_classified_internal_in_public_contract(cli):
    manifest = cli.public_contract_manifest_data()
    commands = {item["name"]: item for item in manifest["commands"]}
    assert "dump-instrumentation-schema" in commands
    assert commands["dump-instrumentation-schema"]["status"] == "internal"
