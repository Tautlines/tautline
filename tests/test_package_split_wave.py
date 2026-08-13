"""Package-split waves (roadmap #11): A2 recipe proof (events/usage + core leaves) and W1
(guards & review machinery: response_guard + iteration_review families).

For every def/constant carved into the ``tautline_methodology`` package across these waves, this
suite asserts the recipe invariants the sibling waves plan inherits:

- (a) it is importable from its real package submodule;
- (b) it still resolves as an attribute of the bin CLI module loaded under the package name
      (the eager alias re-export) and IS the same object the package defines -- so ``cli.<name>``
      reach and ``set_defaults(func=...)`` references survive the move;
- (c) no ``def <name>(`` / ``class <name>(`` DEFINITION remains in ``bin/tautline`` (the alias
      ASSIGNMENT legitimately remains and is exempt);
- (d) the loading-order Assumption holds: bin loaded UNDER THE PACKAGE NAME (as the ``cli``
      fixture and a fresh child interpreter both do, with ``SRC_ROOT`` on ``sys.path``) imports the
      real submodules, and script-mode execution via ``run_cli`` performs the same eager imports at
      startup -- both load modes agree with the in-process behavior.

The moved helpers are also exercised in-process so their bodies are hit under coverage (the run_cli
subprocess is not coverage-collected; see the plan's coverage Assumption).
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from functools import lru_cache
from importlib import import_module
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
CLI_PATH = REPO_ROOT / "bin" / "tautline"
# Post the flip (roadmap #11): bin/tautline is a thin shim; the CLI engine body (every handler,
# dispatch_command, main(), and the eager wave aliases) lives here.
CLI_ENGINE_PATH = SRC_ROOT / "tautline_methodology" / "cli.py"

# The explicit moved-name manifest for this wave. name -> the dotted package module it moved into.
MOVED_DEFS = {
    "event_jsonl_read_paths": "tautline_methodology.core.paths",
    "event_boundary_family": "tautline_methodology.core.policy",
    "event_record_id": "tautline_methodology.events",
    "event_base_name": "tautline_methodology.events",
    "event_family_enabled": "tautline_methodology.events",
    "event_is_terminal_for": "tautline_methodology.events",
    "audit_event_records": "tautline_methodology.events",
    "usage_record_key": "tautline_methodology.usage",
    "usage_tokens": "tautline_methodology.usage",
    "usage_nonnegative_int": "tautline_methodology.usage",
    "usage_float_or_none": "tautline_methodology.usage",
    "usage_report_key": "tautline_methodology.usage",
}
MOVED_CONSTANTS = {
    "EVENT_LOG_SCHEMA": "tautline_methodology.core.policy",
    "EVENT_START_SUFFIX": "tautline_methodology.core.policy",
    "EVENT_REQUIRED_BOUNDARY_FAMILIES": "tautline_methodology.core.policy",
    "EVENT_TERMINAL_SUFFIXES": "tautline_methodology.core.policy",
}
ALL_MOVED = {**MOVED_DEFS, **MOVED_CONSTANTS}


# --- Wave W1 (roadmap #11): response_guard + iteration_review families -------------------------
# The guards/review-machinery carve. The response-guard detection leaves (pure text scanners over
# an assistant response) + their marker constants moved to ``tautline_methodology.response_guard``
# (importing the scan primitives from ``.guards``); the iteration-review record/validation/render
# leaves + three customer-copy/approval constants moved to
# ``tautline_methodology.iteration_review``. The stateful verb handlers stay in bin/tautline (they
# reach lane/adapter/goal state) and wire the moved helpers through the eager bin aliases. Merged
# into the manifests above so the four recipe invariants (package-importable, cli-fixture reachable
# and identity-equal, no def remains in bin, alias assignment remains) are asserted over every W1
# name too. Module paths are factored out of the literals so no manifest line runs long.
_W1_RG = "tautline_methodology.response_guard"
_W1_IR = "tautline_methodology.iteration_review"
W1_MOVED_DEFS = {
    **{name: _W1_RG for name in (
        "hook_decision",
        "hook_additional_context",
        "response_is_rca_shaped",
        "response_has_forbidden_opt_in",
        "response_has_anthropomorphic_capacity_deferral",
        "response_looks_like_human_discussion_framing",
        "response_has_status_report_as_stop",
        "response_is_terminal_stop_context",
        "response_has_terminal_continuity_omission",
        "response_has_wrong_merge_queue_signal",
        "response_has_unverified_monitor_alive_claim",
        "response_has_rotation_action_or_fallback",
        "response_has_host_fallback_rotation",
        "response_has_context_rotation_stop",
        "response_percent_is_progress",
        "response_context_percent_values",
        "response_context_percent_is_estimated",
        "response_context_percent_is_host_sourced",
        "response_has_affirmative_stop_or_defer",
        "response_has_unmeasured_context_deferral",
        "response_has_defer_mandatory_work_without_rotation",
        "response_asks_to_keep_going",
        "_response_context_stop_anchor_positions",
        "response_has_unprovenanced_context_stop",
        "response_has_iteration_review_media_deferral",
        "response_has_boundary_summary_marker",
        "response_looks_like_boundary_event",
        "response_boundary_summary_errors",
        "response_non_whitespace_len",
        "response_is_terse_no_information",
        "response_looks_like_autonomous_yield",
        "response_autonomous_yield_fields",
        "response_has_transient_external_marker",
        "response_has_transient_external_yield_without_armed_retry",
        "response_has_provider_outage_stop_without_recovery",
        "response_has_flaky_rationalization_stop",
        "response_has_recovery_cancellation",
        "response_has_specific_anchor",
        "response_autonomous_yield_schema_errors",
        "response_has_blocked_pr_yield_without_context",
        "flatten_hook_text",
        "response_guard_has_live_goal_session",
        "response_guard_should_evaluate_stop",
        "response_guard_has_documented_rotation_exit",
        "guard_check_call",
    )},
    **{name: _W1_IR for name in (
        "iteration_review_config",
        "iteration_review_renderer_ignored_names",
        "iteration_review_required_string",
        "iteration_review_optional_string",
        "iteration_review_validate_string_list",
        "iteration_review_customer_copy_check",
        "iteration_review_customer_link_check",
        "iteration_review_validate_customer_copy",
        "validate_iteration_review_record",
        "iteration_review_hosting_base_url",
        "iteration_review_url_is_hosted",
        "iteration_review_media_references",
        "iteration_review_output_contract_issues",
        "iteration_review_required_outputs_satisfied",
        "iteration_review_operator_approval_ok",
        "iteration_review_builtin_music_credit",
        "iteration_review_apply_media_defaults",
        "iteration_review_poster_lines",
        "iteration_review_generated_poster_data_uri",
        "iteration_review_default_page_path",
        "iteration_review_public_url",
        "iteration_review_marker_unreasoned_repeats",
        "iteration_review_delivery_marker_matches",
        "iteration_review_chat_payload",
        "iteration_review_after_merge_workflow_yaml",
    )},
}
W1_MOVED_CONSTANTS = {
    **{name: _W1_RG for name in (
        "RESPONSE_GUARD_PASSIVE_MONITOR_PHRASES",
        "RESPONSE_GUARD_AUTONOMOUS_YIELD_MARKERS",
        "RESPONSE_GUARD_MONITOR_ALIVE_CLAIM_MARKERS",
        "RESPONSE_GUARD_MONITOR_FRESHNESS_EVIDENCE_MARKERS",
        "RESPONSE_GUARD_FORWARD_MOTION_MARKERS",
        "RESPONSE_GUARD_STATUS_REPORT_NEXT_ACTION_MARKERS",
        "RESPONSE_GUARD_TERMINAL_STOP_MARKERS",
        "RESPONSE_GUARD_CONTINUITY_EVIDENCE_MARKERS",
        "RESPONSE_GUARD_SESSION_JOURNAL_EVIDENCE_MARKERS",
        "RESPONSE_GUARD_OPT_IN_DIRECT_PHRASES",
        "RESPONSE_GUARD_ANTHROPOMORPHIC_DEFERRAL_MARKERS",
        "RESPONSE_GUARD_ANTHROPOMORPHIC_CAPACITY_RE",
        "RESPONSE_GUARD_DECISION_MENU_CONTEXT_MARKERS",
        "RESPONSE_GUARD_PLAN_CAP_CONTEXT_MARKERS",
        "RESPONSE_GUARD_WRONG_MERGE_QUEUE_SIGNAL_MARKERS",
        "RESPONSE_GUARD_WRONG_MERGE_QUEUE_CONTEXT_MARKERS",
        "RESPONSE_GUARD_WRONG_MERGE_QUEUE_ACTIVE_CONTEXT_MARKERS",
        "RESPONSE_GUARD_WRONG_MERGE_QUEUE_POLICY_MARKERS",
        "RESPONSE_GUARD_OPT_IN_ACTION_VERBS",
        "RESPONSE_GUARD_DISCUSSION_FORBIDDEN_ACTION_VERBS",
        "RESPONSE_GUARD_LIVE_GOAL_SESSION_MARKERS",
        "RESPONSE_GUARD_ASSISTANT_DISCUSSION_FRAMING_MARKERS",
        "RESPONSE_GUARD_DISCUSSION_YIELD_MARKERS",
        "RESPONSE_GUARD_CONTEXT_PRESSURE_MARKERS",
        "RESPONSE_GUARD_CONTEXT_STOP_MARKERS",
        "RESPONSE_GUARD_CONTEXT_SOFT_THRESHOLD_PERCENT",
        "RESPONSE_GUARD_CONTEXT_PRESSURE_WORD_MARKERS",
        "RESPONSE_GUARD_CONTEXT_PERCENT_ANCHORS",
        "RESPONSE_GUARD_CONTEXT_DEFERRAL_MARKERS",
        "RESPONSE_GUARD_CONTEXT_UNMEASURED_ESCAPE_MARKERS",
        "RESPONSE_GUARD_CONTEXT_PERCENT_ESTIMATE_MARKERS",
        "RESPONSE_GUARD_CONTEXT_PERCENT_HOST_SOURCE_MARKERS",
        "RESPONSE_GUARD_CONTEXT_RESUME_MARKERS",
        "RESPONSE_GUARD_CONTEXT_DEFER_TO_LATER_MARKERS",
        "RESPONSE_GUARD_MEDIA_DEFERRAL_MARKERS",
        "RESPONSE_GUARD_ITERATION_REVIEW_MEDIA_CONTEXT_MARKERS",
        "RESPONSE_GUARD_CONTEXT_HUMAN_PROMPT_MARKERS",
        "RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_MARKERS",
        "RESPONSE_GUARD_CONTEXT_ROTATION_FALLBACK_MARKERS",
        "RESPONSE_GUARD_CONTEXT_NEGATIVE_ACTION_MARKERS",
        "RESPONSE_GUARD_CONTEXT_ROTATION_ACTION_RE",
        "RESPONSE_GUARD_AFFIRMATIVE_IMMEDIATE_NEGATOR_RE",
        "RESPONSE_GUARD_CONTEXT_HOST_NEGATOR_RE",
        "RESPONSE_GUARD_AFFIRMATIVE_PHRASE_NEGATOR_RE",
        "RESPONSE_GUARD_ASKS_TO_KEEP_GOING_RE",
        "BOUNDARY_SUMMARY_RECOGNIZED_HEADINGS",
        "RESPONSE_GUARD_BOUNDARY_EVENT_MARKERS",
        "RESPONSE_GUARD_TRANSIENT_EXTERNAL_MARKERS",
        "RESPONSE_GUARD_TRANSIENT_EXTERNAL_STATUS_RE",
        "RESPONSE_GUARD_PROVIDER_OUTAGE_STOP_MARKERS",
        "RESPONSE_GUARD_ARMED_RETRY_MARKERS",
        "RESPONSE_GUARD_RECOVERY_CANCELLATION_MARKERS",
        "RESPONSE_GUARD_FLAKY_DISMISSAL_MARKERS",
        "RESPONSE_GUARD_FLAKE_HANDLING_MARKERS",
    )},
    **{name: _W1_IR for name in (
        "ITERATION_REVIEW_CUSTOMER_FIELD_LIMITS",
        "ITERATION_REVIEW_CUSTOMER_JARGON_PATTERNS",
        "ITERATION_REVIEW_OPERATOR_APPROVAL_TOKEN",
    )},
}
MOVED_DEFS.update(W1_MOVED_DEFS)
MOVED_CONSTANTS.update(W1_MOVED_CONSTANTS)
ALL_MOVED = {**MOVED_DEFS, **MOVED_CONSTANTS}


# --- Wave W2 (roadmap #11): goal + milestone + backlog work-tracking families -------------------
# The work-tracking carve. Only the closure-clean leaves move: goal-plan parsers + goal-run ledger
# record/percent/integrity helpers + GitHub-Projects goal-tracker field/value/item accessors to
# ``tautline_methodology.goal``; the milestone-update config accessor + milestone-run ledger
# helpers to ``tautline_methodology.milestone``; the backlog-item business-lead scanners (+ heading
# constants) and stakeholder-question config/marker/parse helpers to
# ``tautline_methodology.backlog`` (each module imports only stdlib -- no cross-family imports, so
# the three modules cannot form an
# import cycle). Every stateful verb handler (goal_start/goal_advance/goal_tracker_status,
# milestone_start/milestone_advance/publish_milestone_update, backlog_provider_*/backlog_board_*/
# stakeholder_question_ask/status) STAYS in bin/tautline -- their closures reach lane/adapter/goal-
# run/board state (lane_project, load_project, run_git, goal_tracker_config, configured_path,
# adapter_marker_path, ...) so they are on the recorded deferred list, wired to the moved helpers
# through the eager bin aliases. Merged into the manifests above so the four recipe invariants are
# asserted over every W2 name too.
_W2_GOAL = "tautline_methodology.goal"
_W2_MILESTONE = "tautline_methodology.milestone"
_W2_BACKLOG = "tautline_methodology.backlog"
W2_MOVED_DEFS = {
    **{name: _W2_GOAL for name in (
        "goal_plan_bullets",
        "goal_operator_dependency_entries",
        "goal_dependency_matches_milestone",
        "goal_dependencies_for_milestone",
        "goal_instruction_with_dependencies",
        "goal_plan_is_multi_session",
        "goal_milestones_from_plan",
        "goal_plan_title",
        "goal_percent_complete",
        "goal_next_action_record",
        "goal_status_from_action",
        "goal_run_integrity_issues",
        "goal_tracker_allowed_statuses",
        "goal_tracker_value_text",
        "goal_tracker_item_title",
        "goal_tracker_item_url",
        "goal_tracker_item_content_url",
        "goal_tracker_item_body",
        "goal_tracker_item_id",
        "goal_tracker_item_matches",
        "goal_tracker_priority_rank",
        "goal_tracker_field_options",
        "goal_tracker_option_by_name",
        "goal_tracker_next_sort_key",
        "goal_tracker_project_guidance_body",
        "goal_tracker_subtask_ref",
        "goal_tracker_primary_status",
        "goal_tracker_print_sync_result",
        "goal_tracker_done_evidence_for_transition",
        "goal_tracker_status_matches",
        "ui_evidence_screenshot_entries",
        "ui_evidence_path_for_entry",
    )},
    **{name: _W2_MILESTONE for name in (
        "milestone_update_config",
        "milestone_status_from_action",
        "milestone_run_integrity_issues",
        "milestone_percent_complete",
        "milestone_next_action_record",
    )},
    **{name: _W2_BACKLOG for name in (
        "backlog_provider_completion_unit",
        "backlog_provider_done_evidence_comment",
        "_backlog_lead_section",
        "_backlog_lead_section_content",
        "_backlog_lead_content_ok",
        "backlog_item_missing_business_lead",
        "stakeholder_questions_config",
        "stakeholder_questions_status_summary",
        "stakeholder_login_from_mention",
        "stakeholder_question_marker",
        "stakeholder_question_parse_markers",
        "stakeholder_question_answer_is_substantive",
    )},
}
W2_MOVED_CONSTANTS = {
    "GOAL_TERMINAL_STATUSES": _W2_GOAL,
    "MILESTONE_TERMINAL_STATUSES": _W2_MILESTONE,
    "BACKLOG_LEAD_WHAT_HEADINGS": _W2_BACKLOG,
    "BACKLOG_LEAD_WHY_HEADINGS": _W2_BACKLOG,
    "BACKLOG_LEAD_MIN_CHARS": _W2_BACKLOG,
    "STAKEHOLDER_QUESTION_MARKER": _W2_BACKLOG,
    "STAKEHOLDER_QUESTION_ATTR_RE": _W2_BACKLOG,
}
MOVED_DEFS.update(W2_MOVED_DEFS)
MOVED_CONSTANTS.update(W2_MOVED_CONSTANTS)
ALL_MOVED = {**MOVED_DEFS, **MOVED_CONSTANTS}


# --- Wave W3 (roadmap #11): publish + adapters + release + install delivery families -------------
# The delivery/publication carve. Only the closure-clean leaves move: the adapter/bootstrap
# questionnaire builder + question bank, bootstrap answer-slot parsing, rendered-adapter
# provenance-stamp extraction/equivalence, the fail-closed init command string, canonical
# adapter-JSON serialization, and adapter test-command detection to ``tautline_methodology.adapters``
# ; the registry-package MIT license text, the registry-JSON HTTP fetch, the release-notes leak-term
# scan, the public-mirror export overlay, and annotated-tag commit peeling to
# ``tautline_methodology.release``. The ``publish`` and ``install`` families have NO closure-clean
# defs -- every publish_*/install_* handler reaches monolith state (run_git, run_command,
# lane_project, chat_module, deploy_module, canonical_*, post_google_chat_webhook, ...) -- so both
# are FULLY DEFERRED with no module this wave. Every stateful render/init/bootstrap and release verb
# handler (render_adapter, init_methodology_project, adapter_drift, cut_release, registry_package,
# release_tail, release_migration_report, ...) STAYS in bin/tautline, wired to the moved leaves
# through the eager bin aliases. Merged into the manifests above so the four recipe invariants are
# asserted over every W3 name too.
_W3_ADAPTERS = "tautline_methodology.adapters"
_W3_RELEASE = "tautline_methodology.release"
W3_MOVED_DEFS = {
    **{name: _W3_ADAPTERS for name in (
        "adapter_bootstrap_questionnaire",
        "bootstrap_slot_values",
        "adapter_provenance_stamps",
        "adapter_stamp_equivalent_content",
        "init_fail_closed_command",
        "adapter_json_text",
        "adapter_command_is_configured",
        "adapter_test_command_tokens",
        "adapter_test_run_command_tokens",
    )},
    **{name: _W3_RELEASE for name in (
        "registry_package_license",
        "release_http_json",
        "release_tail_leaks",
        "release_tail_overlay",
        "release_tail_tag_commit",
    )},
}
W3_MOVED_CONSTANTS = {
    "BOOTSTRAP_REQUIRED_PREFIX": _W3_ADAPTERS,
    "ADAPTER_BOOTSTRAP_QUESTIONS": _W3_ADAPTERS,
    "ADAPTER_PROVENANCE_STAMP_KEYS": _W3_ADAPTERS,
    "RELEASE_TAIL_LEAK_TERMS": _W3_RELEASE,
}
MOVED_DEFS.update(W3_MOVED_DEFS)
MOVED_CONSTANTS.update(W3_MOVED_CONSTANTS)
ALL_MOVED = {**MOVED_DEFS, **MOVED_CONSTANTS}


# --- Wave W4 (roadmap #11): lane + context ROOT families ----------------------------------------
# The lane/context carve -- the MOST shared-state-heavy families in the CLI. Only genuinely
# closure-clean leaves move: the deterministic lane slot/index derivation, the lane env-file path,
# the lane session-state path, the lane-coordination config accessor + the coordination
# contract/board markdown templates, and the lane-start debt-preflight write wrapper (+ the
# LANE_SESSION_FILE constant) to ``tautline_methodology.lane``; the pure context-rotation decision
# core to ``tautline_methodology.context`` (each module imports only stdlib -- no cross-family
# import, so lane and context cannot form a cycle). Every stateful lane/context verb handler stays
# in bin/tautline -- lane_start/lane_run/lane_project/ensure_lane_state/work_loop and all the
# lane_coordination_* verbs, context_bootstrap/context_status/context_rotation_check/
# context_rotation_heartbeat_hook -- their closures reach monolith state (REPO_ROOT, run_git,
# load_project, lane_project, ensure_lane_state, goal_run_path, slugify, configured_path,
# adapter_marker_path, plugin_version, ...), so they are on the recorded deferred list, wired to the
# moved leaves through the eager bin aliases. Merged into the manifests above so the four recipe
# invariants are asserted over every W4 name too.
_W4_LANE = "tautline_methodology.lane"
_W4_CONTEXT = "tautline_methodology.context"
W4_MOVED_DEFS = {
    **{name: _W4_LANE for name in (
        "lane_slot",
        "lane_env_path",
        "lane_session_path",
        "lane_coordination_config",
        "lane_coordination_contract_template",
        "lane_coordination_board_template",
        "_lane_start_hook_write",
    )},
    "context_rotation_decision": _W4_CONTEXT,
}
W4_MOVED_CONSTANTS = {
    "LANE_SESSION_FILE": _W4_LANE,
}
MOVED_DEFS.update(W4_MOVED_DEFS)
MOVED_CONSTANTS.update(W4_MOVED_CONSTANTS)
ALL_MOVED = {**MOVED_DEFS, **MOVED_CONSTANTS}


@pytest.mark.parametrize("name, module_path", sorted(MOVED_DEFS.items()))
def test_moved_def_importable_from_package(name, module_path):
    module = import_module(module_path)
    assert callable(getattr(module, name)), f"{name} is not an importable def in {module_path}"


@pytest.mark.parametrize("name, module_path", sorted(MOVED_CONSTANTS.items()))
def test_moved_constant_importable_from_package(name, module_path):
    module = import_module(module_path)
    assert hasattr(module, name), f"{name} is not importable from {module_path}"


@pytest.mark.parametrize("name, module_path", sorted(ALL_MOVED.items()))
def test_moved_name_reachable_as_cli_attribute(cli, name, module_path):
    # The eager bin alias re-exports the SAME object the package defines, so attribute reach and
    # set_defaults(func=...) references keep resolving after the carve.
    assert getattr(cli, name) is getattr(import_module(module_path), name)


def _module_file(module_path: str) -> Path:
    """Filesystem path of a dotted ``tautline_methodology`` module."""
    return SRC_ROOT / (module_path.replace(".", "/") + ".py")


@lru_cache(maxsize=None)
def _source(path: Path) -> str:
    """Cached file read. The CLI engine is 2.6MB and several parametrized suites below want it
    once per PARAMETER; without the cache that is hundreds of re-reads."""
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _defined_names(path: Path) -> frozenset[str]:
    """Every def/class name ANYWHERE in ``path``, nested definitions included.

    Cached because the alias pin below is parametrized over ~300 moved names and each case used to
    re-parse the whole 2.6MB CLI engine -- ~300 full AST parses at ~0.75s each, which made this
    file 431.8s, over a fifth of the entire suite's measured test time. The parse is identical for
    every parameter, so it belongs outside the parameter loop.
    """
    return frozenset(
        node.name
        for node in ast.walk(ast.parse(_source(path)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )


@lru_cache(maxsize=None)
def _top_level_defs(path: Path) -> dict[str, str]:
    """name -> 'def'|'class' for every top-level FunctionDef/ClassDef in ``path``.

    Only ``tree.body`` (the module scope) is inspected, so a nested helper -- including the
    shim's fallback ``main`` inside its ModuleNotFoundError handler -- is not a top-level def.
    """
    tree = ast.parse(_source(path))
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = "def"
        elif isinstance(node, ast.ClassDef):
            out[node.name] = "class"
    return out


def _package_source_files() -> list[Path]:
    """Every package .py plus the bin shim -- the full surface a name could be defined on."""
    return [CLI_PATH, *sorted(SRC_ROOT.glob("tautline_methodology/**/*.py"))]


@pytest.mark.parametrize("name", sorted(ALL_MOVED))
def test_moved_name_is_alias_not_def_in_cli_engine(name):
    """Post-flip successor of the wave "no def remains in bin" pin. The moved name is now an
    eager alias ASSIGNMENT in the CLI engine module (cli.py) -- never a def/class there -- which
    is what keeps ``cli.<name>`` reach and every ``set_defaults(func=...)`` reference resolving.
    (bin/tautline is a shim and holds neither the def nor the alias -- pinned separately below.)"""
    assert name not in _defined_names(CLI_ENGINE_PATH), (
        f"{name} is DEFINED in cli.py; a moved name must be an eager alias "
        "ASSIGNMENT, not a def/class definition"
    )
    assert re.search(rf"(?m)^{re.escape(name)} = ", _source(CLI_ENGINE_PATH)), (
        f"{name} eager alias assignment is missing from cli.py"
    )


@pytest.mark.parametrize("name, module_path", sorted(MOVED_DEFS.items()))
def test_moved_def_has_single_owner_across_all_files(name, module_path):
    """Hardened cross-file single-owner pin (deferred W4 P3): a moved def is a top-level def in
    EXACTLY its recorded owning module and is NOT a top-level def/class anywhere else (cli.py
    carries it only as an eager alias ASSIGN, the bin shim not at all). Derived from actual
    module contents, so an accidental duplicate definition in a second module reddens this."""
    owner = _module_file(module_path)
    assert _top_level_defs(owner).get(name) in {"def", "class"}, (
        f"{name} is not a top-level def in its owning module {module_path}"
    )
    duplicates = [
        f for f in _package_source_files()
        if f != owner and name in _top_level_defs(f)
    ]
    assert not duplicates, (
        f"{name} is ALSO a top-level def in {[str(d) for d in duplicates]}; a moved name "
        "must have a single owning module"
    )


def test_spike_loading_order_in_process_and_subprocess_agree(cli, tmp_path):
    """The T3 Step-1 spike, updated for the flip: the CLI engine module resolves the real
    ``core.paths`` submodule. Prove it in-process (the ``cli`` fixture, now
    ``tautline_methodology.cli``) AND in a fresh child interpreter that imports
    ``tautline_methodology.cli`` cleanly with SRC_ROOT on sys.path -- the two must agree (the
    loading-order Assumption the waves plan inherits, now that the engine is a real submodule)."""
    base = tmp_path / "events.jsonl"
    base.write_text("live\n", encoding="utf-8")
    (tmp_path / "events.jsonl.1").write_text("r1\n", encoding="utf-8")
    (tmp_path / "events.jsonl.2").write_text("r2\n", encoding="utf-8")

    in_process = [p.name for p in cli.event_jsonl_read_paths(base, 2)]
    assert in_process == ["events.jsonl.2", "events.jsonl.1", "events.jsonl"]

    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(SRC_ROOT)!r})\n"
        "from tautline_methodology import cli as mod\n"
        f"paths = mod.event_jsonl_read_paths(Path({str(base)!r}), 2)\n"
        "print(json.dumps([p.name for p in paths]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == in_process


def test_cli_loads_in_script_mode_via_run_cli(run_cli):
    """The counterpart load mode: ``bin/tautline`` executed AS A SCRIPT (``__main__``) via run_cli
    performs the same eager package imports at startup. A clean ``version --no-remote`` proves the
    real ``core``/``events``/``usage`` submodules imported in script mode too (a missing package
    would fail loud with the standalone-copy message before any verb ran)."""
    res = run_cli("version", "--no-remote")
    assert res.returncode == 0, res.stderr
    assert "standalone copy of" not in res.stderr
    assert "ModuleNotFoundError" not in res.stderr


def test_moved_helpers_behave_in_process(cli, tmp_path):
    """Exercise every moved helper in-process (coverage-collected) at representative inputs, to
    prove behavior neutrality of the verbatim carve and to hit the moved bodies under coverage."""
    # core.paths spike
    base = tmp_path / "e.jsonl"
    base.write_text("x\n", encoding="utf-8")
    (tmp_path / "e.jsonl.1").write_text("y\n", encoding="utf-8")
    assert [p.name for p in cli.event_jsonl_read_paths(base, 1)] == ["e.jsonl.1", "e.jsonl"]

    # core.policy decision core + constants
    assert cli.event_boundary_family("startup") == "startup"
    assert cli.event_boundary_family("preflight_ci") == "preflight"
    assert cli.event_boundary_family("something", "block") == "blocker"
    assert cli.event_boundary_family("nothing_notable") is None
    assert cli.EVENT_LOG_SCHEMA == "minervit-repo-event/v1"
    assert "startup" in cli.EVENT_REQUIRED_BOUNDARY_FAMILIES
    assert cli.EVENT_START_SUFFIX == "_started"
    assert "_passed" in cli.EVENT_TERMINAL_SUFFIXES

    # events helpers
    assert cli.event_record_id({"a": 1}) == cli.event_record_id({"a": 1})
    assert len(cli.event_record_id({"a": 1})) == 16
    assert cli.event_base_name("goal_started") == "goal"
    assert cli.event_base_name("goal_start") == "goal"
    assert cli.event_family_enabled(None, None) is True
    assert cli.event_family_enabled({"startup"}, "startup") is True
    assert cli.event_family_enabled({"startup"}, "preflight") is False
    assert cli.event_is_terminal_for("goal", "goal_passed") is True
    assert cli.event_is_terminal_for("goal", "goal_running") is False
    assert cli.audit_event_records([]) == []
    bad = cli.audit_event_records([{"schema": "wrong", "event": "startup", "next": "go"}])
    assert any("invalid schema" in issue for issue in bad)

    # usage helpers
    assert cli.usage_record_key({"dedupe_key": "K"}) == "K"
    assert len(cli.usage_record_key({"provider": "anthropic", "model": "opus"})) == 64
    assert cli.usage_tokens({"tokens": {"input": 3, "output": 4}})["input"] == 3
    assert cli.usage_tokens({"tokens": "not-a-dict"})["total"] == 0
    assert cli.usage_nonnegative_int("5", "input") == 5
    with pytest.raises(SystemExit):
        cli.usage_nonnegative_int("-1", "input")
    assert cli.usage_float_or_none(None, "cost") is None
    assert cli.usage_float_or_none("1.5", "cost") == 1.5
    with pytest.raises(SystemExit):
        cli.usage_float_or_none("-1", "cost")
    assert cli.usage_report_key({"project": "acme"}, "product") == "acme"
    assert cli.usage_report_key({"ts": "2026-07-21T09:00"}, "day") == "2026-07-21"
    assert cli.usage_report_key({"model": "opus"}, "model") == "opus"


def test_w1_moved_helpers_behave_in_process(cli):
    """Wave W1: exercise representative response_guard + iteration_review leaves in-process
    (coverage-collected) to prove verbatim-carve behavior neutrality and hit the moved bodies."""
    # response_guard pure scanners + the guard-check driver
    assert cli.response_non_whitespace_len("  ab ") == 2
    assert cli.flatten_hook_text("hello") == "hello"
    assert "a" in cli.flatten_hook_text(["a", ["b", "c"]])
    assert cli.guard_check_call("lbl", lambda _a: 0, None) == 0
    assert cli.guard_check_call("lbl", lambda _a: 1, None) == 1
    assert isinstance(cli.response_is_rca_shaped("Root cause of the failure"), bool)
    # marker constants moved with the scanners (incl. the derived WORD_MARKERS)
    assert isinstance(cli.RESPONSE_GUARD_PASSIVE_MONITOR_PHRASES, list)
    assert isinstance(cli.RESPONSE_GUARD_CONTEXT_PRESSURE_WORD_MARKERS, list)
    # iteration_review validators / render leaves
    errs: list[str] = []
    cli.iteration_review_required_string({"x": "value"}, "x", errs)
    assert errs == []
    assert cli.validate_iteration_review_record("not-a-dict") == ["GoalReview must be a JSON object"]
    assert cli.iteration_review_operator_approval_ok(
        argparse.Namespace(operator_approval_token=cli.ITERATION_REVIEW_OPERATOR_APPROVAL_TOKEN)
    )
    assert cli.iteration_review_default_page_path(Path("/t/x.review.json")).suffix == ".html"


def test_w1_owning_module_monkeypatch_seam_is_observed(cli, monkeypatch):
    """Monkeypatch-seam migration proof (plan T1): once a moved function's globals live in its
    OWNING package module, a moved caller resolves its helpers THERE -- so patching the owning
    module path is what the caller observes, and patching the ``cli`` alias no longer reaches the
    moved caller's internal call. The sibling waves repoint their seams to the owning module for
    exactly this reason. (No existing test patches a W1-moved name, so none needed repointing this
    wave; this asserts the mechanism the sibling waves depend on.)"""
    rg = import_module("tautline_methodology.response_guard")
    ir = import_module("tautline_methodology.iteration_review")

    # response_guard_should_evaluate_stop() calls response_guard_has_live_goal_session() by its
    # module-global name; patching it on the OWNING module is observed by the moved caller.
    monkeypatch.setattr(rg, "response_guard_has_live_goal_session", lambda *a, **k: True)
    assert cli.response_guard_should_evaluate_stop({}, "", "") is True
    monkeypatch.setattr(rg, "response_guard_has_live_goal_session", lambda *a, **k: False)
    assert cli.response_guard_should_evaluate_stop({}, "", "") is False

    # ...and the bin alias (cli.<name>) is NOT the seam: rebinding it does not reach the moved
    # caller, which resolves the helper via the owning module's globals.
    monkeypatch.setattr(cli, "response_guard_has_live_goal_session", lambda *a, **k: True)
    assert cli.response_guard_should_evaluate_stop({}, "", "") is False

    # iteration_review_validate_customer_copy() dispatches to iteration_review_customer_copy_check()
    # by module-global name -- the owning-module patch is observed.
    seen: list[str] = []
    monkeypatch.setattr(ir, "iteration_review_customer_copy_check",
                        lambda field, value, errors, **k: seen.append(field))
    cli.iteration_review_validate_customer_copy({"product": "x", "why": "y"}, [])
    assert "product" in seen


def test_w2_moved_helpers_behave_in_process(cli):
    """Wave W2: exercise representative goal / milestone / backlog leaves in-process
    (coverage-collected) to prove verbatim-carve behavior neutrality and hit the moved bodies."""
    # goal ledger record/percent/integrity leaves + terminal-status constant
    assert cli.GOAL_TERMINAL_STATUSES == {"complete", "deferred"}
    assert cli.goal_percent_complete({"milestones": []}) == 0
    assert cli.goal_percent_complete(
        {"milestones": [{"status": "complete"}, {"status": "active"}]}
    ) == 50
    assert cli.goal_status_from_action({"type": "goal_complete"}) == "complete"
    assert cli.goal_status_from_action({"type": "true_blocker"}) == "blocked"
    assert cli.goal_status_from_action({"type": "start"}, "complete") == "complete"
    assert cli.goal_run_integrity_issues({"milestones": [], "status": "active"}) == []
    assert any(
        "validationProof" in issue
        for issue in cli.goal_run_integrity_issues({"milestones": [], "status": "complete"})
    )
    # goal-tracker field/value/item accessors
    assert cli.goal_tracker_value_text({"name": " Ready "}) == "Ready"
    assert cli.goal_tracker_value_text([{"name": "a"}, {"name": "b"}]) == "a, b"
    assert cli.goal_tracker_item_title({"title": "T"}) == "T"
    assert cli.goal_tracker_item_title({}) == "Untitled GitHub Project item"
    assert cli.goal_tracker_priority_rank("P1") == 1
    assert cli.goal_tracker_priority_rank("critical") == 0
    assert cli.goal_tracker_priority_rank("") == 999
    assert cli.goal_tracker_status_matches("Done", ["done", "closed"]) is True
    assert cli.goal_tracker_next_sort_key("board", 0, 0, 3.0, 7) == (3.0, 7)
    assert cli.goal_tracker_next_sort_key("priority", 1, 10, 0.0, 7) == (1, 10, 7)
    assert cli.goal_tracker_allowed_statuses(
        {"readyStatuses": ["r"], "activeStatuses": ["a"],
         "doneStatuses": ["d"], "blockedStatuses": ["b"]}
    ) == ["r", "a", "d", "b"]

    # milestone ledger leaves + terminal-status constant
    assert "merged" in cli.MILESTONE_TERMINAL_STATUSES
    assert cli.milestone_update_config({"milestoneUpdate": {"k": 1}}) == {"k": 1}
    assert cli.milestone_status_from_action({"type": "milestone_complete"}) == "complete"
    assert cli.milestone_status_from_action({"type": "true_blocker"}) == "blocked"
    assert cli.milestone_percent_complete({"items": []}) == 0
    assert cli.milestone_percent_complete(
        {"items": [{"status": "merged"}, {"status": "active"}]}
    ) == 50

    # backlog business-lead scanners + heading constants
    assert cli.BACKLOG_LEAD_MIN_CHARS == 24
    assert "what this delivers" in cli.BACKLOG_LEAD_WHAT_HEADINGS
    good_body = (
        "## What this delivers\nA concrete new capability that customers can use today.\n"
        "## Why it matters\nIt removes a recurring manual step teams complain about often.\n"
    )
    assert cli.backlog_item_missing_business_lead(good_body) == ""
    assert "business justification" in cli.backlog_item_missing_business_lead("no headings here")
    assert cli.backlog_provider_completion_unit(
        {"backlogProvider": {"enabled": True, "completionUnit": "provider-item"}}
    ) == "provider-item"
    assert cli.backlog_provider_completion_unit({}) == "goal"

    # stakeholder-question marker round-trip + substantive-answer gate
    assert cli.stakeholder_login_from_mention(" @Alice ") == "alice"
    marker = cli.stakeholder_question_marker({"id": "q1", "status": "open"})
    assert cli.STAKEHOLDER_QUESTION_MARKER in marker
    parsed = cli.stakeholder_question_parse_markers(marker)
    assert parsed and parsed[0]["id"] == "q1"
    assert cli.stakeholder_question_answer_is_substantive(
        "This is a detailed and substantive answer to the stakeholder question."
    ) is True
    assert cli.stakeholder_question_answer_is_substantive("ok") is False


def test_w2_owning_module_monkeypatch_seam_is_observed(cli, monkeypatch):
    """Monkeypatch-seam migration proof (plan T2): a moved caller resolves its helpers in its
    OWNING package module, so patching the owning-module path is what the caller observes; patching
    the ``cli`` alias no longer reaches the moved caller's internal call. (No existing test patches
    a W2-moved name, so none needed repointing this wave; this asserts the mechanism.)"""
    goal = import_module("tautline_methodology.goal")
    backlog = import_module("tautline_methodology.backlog")

    # goal_tracker_item_title() calls goal_tracker_value_text() by its module-global name; patching
    # it on the OWNING module is observed by the moved caller.
    monkeypatch.setattr(goal, "goal_tracker_value_text", lambda value: "PATCHED")
    assert cli.goal_tracker_item_title({"title": "real"}) == "PATCHED"
    # ...and the bin alias (cli.<name>) is NOT the seam: rebinding it does not reach the moved
    # caller, which resolves the helper via the owning module's globals.
    monkeypatch.setattr(cli, "goal_tracker_value_text", lambda value: "ALIAS")
    assert cli.goal_tracker_item_title({"title": "real"}) == "PATCHED"

    # backlog_item_missing_business_lead() dispatches to _backlog_lead_section() by module-global
    # name -- the owning-module patch is observed.
    monkeypatch.setattr(backlog, "_backlog_lead_section", lambda text, headings: None)
    assert "business justification" in cli.backlog_item_missing_business_lead("anything")


def test_w3_moved_helpers_behave_in_process(cli):
    """Wave W3: exercise representative adapters / release leaves in-process (coverage-collected)
    to prove verbatim-carve behavior neutrality and hit the moved bodies."""
    # adapters: bootstrap questionnaire builder + question bank constant
    assert cli.ADAPTER_BOOTSTRAP_QUESTIONS[0][0] == "Product And Deployment"
    interview = cli.adapter_bootstrap_questionnaire("Acme", "acme/acme", include_answer_slots=True)
    assert interview.startswith("# Project Adapter Bootstrap Interview")
    assert "Project: Acme" in interview and "Repository: acme/acme" in interview
    assert "Answer: BOOTSTRAP REQUIRED" in interview  # include_answer_slots wiring
    # bootstrap answer-slot parsing
    assert cli.bootstrap_slot_values("Answer: foo\nAnswer: bar\n", "Answer") == ["foo", "bar"]
    # provenance-stamp extraction + equivalence normalization + stamp-key constant
    assert cli.ADAPTER_PROVENANCE_STAMP_KEYS == ("methodologyCommit", "pluginVersion")
    stamped = '{"_generated": {"methodologyCommit": "abc", "pluginVersion": "1.2.3"}}'
    assert cli.adapter_provenance_stamps(stamped) == {
        "methodologyCommit": "abc", "pluginVersion": "1.2.3"
    }
    assert cli.adapter_provenance_stamps("not json") is None
    assert cli.adapter_provenance_stamps("[]") is None
    # a stamp-only difference normalizes equal; a real content difference does not
    fresh = '{"_generated": {"methodologyCommit": "NEW", "pluginVersion": "9"}, "x": 1}'
    on_disk = '{"_generated": {"methodologyCommit": "OLD", "pluginVersion": "9"}, "x": 1}'
    assert cli.adapter_provenance_stamps(cli.adapter_stamp_equivalent_content(fresh, on_disk)) == \
        cli.adapter_provenance_stamps(on_disk)
    # fail-closed init command + canonical adapter-JSON serialization
    assert cli.init_fail_closed_command("mainStatus").startswith("echo 'minervit init:")
    assert cli.adapter_json_text({"b": 1, "a": 2}) == '{\n  "a": 2,\n  "b": 1\n}\n'
    # adapter test-command detection + BOOTSTRAP_REQUIRED_PREFIX constant
    assert cli.BOOTSTRAP_REQUIRED_PREFIX == "BOOTSTRAP REQUIRED"
    assert cli.adapter_command_is_configured("pnpm test") is True
    assert cli.adapter_command_is_configured("") is False
    assert cli.adapter_command_is_configured("BOOTSTRAP REQUIRED: set it") is False
    cfg = {"commands": {"fullPreflight": "make test", "testEnvironment": "pnpm install"}}
    assert cli.adapter_test_command_tokens(cfg) == ["make test", "pnpm install"]
    assert cli.adapter_test_run_command_tokens(cfg) == ["make test"]

    # release: MIT license text + leak-term scan + leak-term constant
    assert cli.registry_package_license().startswith("MIT License")
    assert "METH-FU" in cli.RELEASE_TAIL_LEAK_TERMS
    assert cli.release_tail_leaks("mentions docs/backlog/ and /Users/x but clean otherwise") == \
        ["/Users/", "docs/backlog/"]
    assert cli.release_tail_leaks("nothing sensitive here") == []
    # annotated-tag commit peeling (peeled ^{} entry wins over the tag object)
    out = "objsha\trefs/tags/v1.0\ncommitsha\trefs/tags/v1.0^{}\n"
    assert cli.release_tail_tag_commit(out, "v1.0") == "commitsha"
    assert cli.release_tail_tag_commit("lightsha\trefs/tags/v2.0\n", "v2.0") == "lightsha"


def test_w3_bin_caller_monkeypatch_seam_is_observed(cli, monkeypatch):
    """Monkeypatch-seam migration proof (plan T3), the MOVED-HELPER / BIN-CALLER case (the inverse
    of the W1/W2 owning-module case). ``release_http_json`` moved to the package, but its callers
    (``registry_latest_version``/``registry_has_version``) are release-machinery that STAYS in
    bin/tautline. A bin caller resolves ``release_http_json`` through bin's module globals -- which
    is the eager alias -- so the existing ``monkeypatch.setattr(cli, "release_http_json", ...)``
    seam in tests/test_release_tail.py keeps being observed WITHOUT repointing (verified: no repoint
    was needed this wave). This asserts that contract so a future move of the callers is caught."""
    monkeypatch.setattr(
        cli, "release_http_json", lambda url, timeout=20: {"dist-tags": {"latest": "9.9.9"}}
    )
    assert cli.registry_latest_version("npm") == "9.9.9"
    monkeypatch.setattr(cli, "release_http_json", lambda url, timeout=20: None)
    assert cli.registry_latest_version("npm") == "absent"
    assert cli.registry_has_version("npm", "1.0.0") is False


def test_w4_moved_helpers_behave_in_process(cli, tmp_path, capsys):
    """Wave W4: exercise the moved lane / context leaves in-process (coverage-collected) to prove
    verbatim-carve behavior neutrality and hit the moved bodies."""
    # lane: deterministic slot derivation + session-file constant
    assert cli.LANE_SESSION_FILE == "lane-session.json"
    assert cli.lane_slot(Path("/x/lane-2")) == 1        # "lane-2" -> index 1 (slot = n - 1)
    assert cli.lane_slot(Path("/x/lane_5")) == 4
    assert cli.lane_slot(Path("/x/myrepo")) >= 50       # no lane number -> hashed slot >= 50
    # lane env-file path + session-state path (session path folds in LANE_SESSION_FILE)
    data = {
        "localResourceIsolation": {"envFile": ".lane.env"},
        "laneState": {"runsDir": ".ai-runs"},
    }
    assert cli.lane_env_path(data, Path("/repo")) == Path("/repo/.lane.env")
    assert cli.lane_session_path(data, Path("/repo")) == Path("/repo/.ai-runs/lane-session.json")
    # lane-coordination config accessor + contract/board templates
    assert cli.lane_coordination_config({"laneCoordination": {"strict": True}}) == {"strict": True}
    contract = cli.lane_coordination_contract_template({}, Path("/repo"))
    assert contract.startswith("# Cross-Lane Coordination Contract")
    board = cli.lane_coordination_board_template({}, Path("/repo"))
    assert board.startswith("# Cross-Lane Lane Board") and "lane-status:start" in board
    # _lane_start_hook_write: success line prints identically; the deferred path swallows a write
    # failure into one warn line; the unflagged path propagates the failure unchanged.
    cli._lane_start_hook_write(
        False, "hook", "Label", "installed hook", lambda: (Path("/p/x"), True)
    )
    assert "Label: already installed hook /p/x" in capsys.readouterr().out
    cli._lane_start_hook_write(
        False, "hook", "Label", "installed hook", lambda: (Path("/p/x"), False)
    )
    assert "Label: installed /p/x" in capsys.readouterr().out

    def _boom():
        raise OSError("disk full")

    cli._lane_start_hook_write(True, "hook", "Label", "installed hook", _boom)
    assert "lane_start_warn: hook - disk full" in capsys.readouterr().out
    with pytest.raises(OSError):
        cli._lane_start_hook_write(False, "hook", "Label", "installed hook", _boom)

    # context: pure rotation decision core -- host vs estimate provenance cap (RCA gate)
    rotation = {"enabled": True, "softPercent": 60, "hardPercent": 85}
    assert cli.context_rotation_decision(rotation, 90, True, "host")["urgency"] == "mandatory"
    capped = cli.context_rotation_decision(rotation, 90, True, "estimate")
    assert capped["urgency"] == "recommended" and capped["capped"] is True
    assert cli.context_rotation_decision(rotation, 40, True, "host")["urgency"] == "none"
    disabled = cli.context_rotation_decision({"enabled": False}, 90, True, "host")
    assert disabled["urgency"] == "disabled"


def test_w4_bin_caller_monkeypatch_seam_is_observed(cli, monkeypatch):
    """Monkeypatch-seam migration proof (plan T4), the MOVED-HELPER / BIN-CALLER case (as in W3).
    ``lane_slot`` moved to ``tautline_methodology.lane``, but its caller ``lane_env_values`` is
    lane-lifecycle machinery whose closure reaches monolith state (slugify/brand_env_pairs) and so
    STAYS in bin/tautline. The bin caller resolves ``lane_slot`` through bin's module globals -- the
    eager alias -- so a ``monkeypatch.setattr(cli, "lane_slot", ...)`` seam is observed by the bin
    caller WITHOUT repointing (no existing test patches a W4-moved name, so none needed repointing
    this wave; this asserts the contract so a future move of the caller is caught)."""
    data = {
        "project": "acme",
        "localResourceIsolation": {
            "envFile": ".lane.env",
            "composeProjectPrefix": "acme",
            "portStride": 10,
            "portVariables": [{"name": "WEB_PORT", "base": 8000}],
            "envTemplates": {},
        },
    }
    monkeypatch.setattr(cli, "lane_slot", lambda target: 7)
    env = cli.lane_env_values(data, Path("/repo/lane-1"))
    assert env["WEB_PORT"] == "8070"  # base 8000 + slot 7 * stride 10 (patched slot flowed)
    assert env["MINERVIT_LANE_SLOT"] == "7"


# --- The flip (roadmap #11): bin/tautline is now a thin shim over tautline_methodology.cli -------
# The wave "what remains in bin" manifest is superseded here. The flip moved the ENTIRE engine body
# (every handler, the ``_register_<family>_<n>`` segment functions, the lazy ``*_module()``
# accessors, ``dispatch_command``, ``main``, ``_MissingFrameworkPackage``, and the eager wave
# aliases) into cli.py. bin/tautline is reduced to a shim: header + sys.path bootstrap + import of
# main() + the ``__main__`` guard (plus a fallback main for the standalone hook fail-open contract).
# These pins guard that end state -- bin holds NO engine def, and cli.py holds the structural
# anchors the flip relocated.

FLIP_ANCHORS = {"main": "def", "dispatch_command": "def", "_MissingFrameworkPackage": "class"}
# Generous ceiling: the shim is ~40 lines (header docstring + bootstrap + import + the fail-open
# fallback main + guard). A regression that let engine code leak back into bin would blow past this.
SHIM_MAX_LINES = 60


def test_bin_is_thin_shim():
    """bin/tautline is a thin executable shim, not the engine: no top-level def/class remains in it
    (the fallback ``main`` lives inside the ModuleNotFoundError handler, not the module body), it
    imports ``main`` from the package engine, and it keeps the ``__main__`` guard. Small by line
    count so engine code cannot silently creep back in."""
    source = _source(CLI_PATH)
    bin_defs = _top_level_defs(CLI_PATH)
    assert bin_defs == {}, (
        f"bin/tautline still holds top-level defs/classes {sorted(bin_defs)}; it must be a shim "
        "with no engine code (the fallback main is nested in the import-failure handler)"
    )
    assert "from tautline_methodology.cli import main" in source, (
        "the shim must import main() from the package engine module"
    )
    assert re.search(r'(?m)^if __name__ == "__main__":', source), "the shim lost its __main__ guard"
    assert len(source.splitlines()) <= SHIM_MAX_LINES, (
        f"bin/tautline grew to {len(source.splitlines())} lines (> {SHIM_MAX_LINES}); it must "
        "stay a thin shim"
    )


def test_no_moved_name_is_defined_in_bin_after_flip():
    """Trivially true now that bin is a shim, but pinned so a regression that reintroduced engine
    code into bin (redefining a moved name there) reddens: no moved name is a def/class in bin."""
    bin_defs = _top_level_defs(CLI_PATH)
    still_defined = sorted(name for name in ALL_MOVED if name in bin_defs)
    assert not still_defined, f"moved names must not be (re)defined in the shim: {still_defined}"


def test_cli_engine_holds_flip_anchors():
    """The relocation target: the CLI engine module (cli.py) holds the structural anchors the flip
    moved out of bin verbatim -- ``main``/``dispatch_command`` as defs, ``_MissingFrameworkPackage``
    as a class -- plus the ``_register_<family>_<n>`` segment functions (the dispatch surface) and
    the lazy ``*_module()`` accessors (the package bootstrap bridges)."""
    engine_defs = _top_level_defs(CLI_ENGINE_PATH)
    miscategorized = sorted(a for a, kind in FLIP_ANCHORS.items() if engine_defs.get(a) != kind)
    assert not miscategorized, f"flip anchors missing/miscategorized in cli.py: {miscategorized}"

    registrars = sorted(n for n in engine_defs if n.startswith("_register_"))
    accessors = sorted(n for n in engine_defs if n.endswith("_module") and engine_defs[n] == "def")
    assert registrars, "no _register_<family>_<n> segment functions in cli.py (dispatch lost?)"
    assert accessors, "no lazy *_module() accessors in cli.py (bootstrap bridges lost?)"

    # No moved name is DEFINED in cli.py -- it carries them only as eager alias assignments.
    moved_but_defined = sorted(name for name in ALL_MOVED if name in engine_defs)
    assert not moved_but_defined, f"cli.py must alias, not define: {moved_but_defined}"
    print(
        f"\nflip: bin shim top-level defs=0; cli.py engine defs/classes={len(engine_defs)} "
        f"(anchors={len(FLIP_ANCHORS)}, registrars={len(registrars)}, accessors={len(accessors)}); "
        f"moved-across-waves={len(ALL_MOVED)} (all eager alias assignments in cli.py)"
    )
