"""T3 (0.9.0 sanitized instrumentation): producer-coverage gate.

Because "drop unknown local event names" could otherwise silently discard real telemetry forever,
this test statically scans `bin/tautline` (via `ast`, never substring matching, mirroring
tests/test_guard_coverage_gate.py's approach) for every event name passed to a real
`write_event(...)`/`try_write_event(...)` call site, plus the adapter's
`requiredBoundaryEvents` boundary-event list, and asserts every one of those names is either
classified into a v1 code (`instrumentation_event_map()`,
`INSTRUMENTATION_PAIRED_LIFECYCLE_PRODUCERS`, or `INSTRUMENTATION_FINALIZE_VERDICT_PRODUCERS`) or
explicitly listed in `INSTRUMENTATION_IGNORED_EVENTS` with a reason. A newly added producer that is
neither classified nor ignored fails this gate -- proven by feeding the same scanner a synthetic
snippet containing a brand new `try_write_event` call (test at the bottom).

The public `log-event` command's runtime `--event` value is a stable, deliberately unconstrained
adopter-local surface (see bin/tautline's `log_event`); this gate covers only the FIXED producer
names bin/tautline itself emits, never runtime-supplied strings.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "bin" / "tautline"


def _resolve_event_arg(node: ast.AST, dynamic_expansions: dict) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _resolve_event_arg(node.body, dynamic_expansions) | _resolve_event_arg(node.orelse, dynamic_expansions)
    if isinstance(node, ast.Attribute) and node.attr == "event" and isinstance(node.value, ast.Name) and node.value.id == "args":
        # `event=args.event`: the public `log-event` command's RUNTIME passthrough (bin/tautline's
        # log_event()). Deliberately unconstrained per the design -- contributes no name to classify.
        return set()
    if isinstance(node, ast.JoinedStr):
        if (
            len(node.values) == 2
            and isinstance(node.values[0], ast.Constant)
            and isinstance(node.values[0].value, str)
            and isinstance(node.values[1], ast.FormattedValue)
            and node.values[0].value in dynamic_expansions
        ):
            return set(dynamic_expansions[node.values[0].value])
    raise AssertionError(f"producer-coverage scanner cannot resolve event= expression: {ast.dump(node)}")


def scan_emitted_event_names(source: str, dynamic_expansions: dict | None = None) -> set[str]:
    """Every literal (or registry-resolvable dynamic) `event=` value passed to a `write_event(...)`
    or `try_write_event(...)` call in `source`. Uses `ast` so a call site can never be missed by a
    superficial text/comment match, and raises loudly (fail-closed) on any `event=` expression shape
    it does not recognize, rather than silently skipping it."""
    dynamic_expansions = dynamic_expansions or {}
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name = func.id if isinstance(func, ast.Name) else None
        if func_name not in {"try_write_event", "write_event"}:
            continue
        event_kwarg = next((kw for kw in node.keywords if kw.arg == "event"), None)
        if event_kwarg is None:
            continue
        names |= _resolve_event_arg(event_kwarg.value, dynamic_expansions)
    return names


def _classified_names(cli) -> set[str]:
    classified = set(cli.instrumentation_event_map())
    for start, finished, failed, _code in cli.INSTRUMENTATION_PAIRED_LIFECYCLE_PRODUCERS:
        classified |= {start, finished, failed}
    for finalize_name, _clean, _blocked in cli.INSTRUMENTATION_FINALIZE_VERDICT_PRODUCERS:
        classified.add(finalize_name)
    return classified


def test_producer_coverage_every_emitted_event_name_is_classified_or_ignored(cli):
    source = SOURCE_PATH.read_text(encoding="utf-8")
    dynamic_expansions = {
        "goal_advance_": {f"goal_advance_{choice.replace('-', '_')}" for choice in cli.GOAL_ADVANCE_EVENTS},
        "milestone_advance_": {f"milestone_advance_{choice.replace('-', '_')}" for choice in cli.MILESTONE_ADVANCE_EVENTS},
    }
    scanned = scan_emitted_event_names(source, dynamic_expansions)
    boundary_list = set(cli.DEFAULT_OBSERVABILITY_EVENTS["requiredBoundaryEvents"])
    all_names = scanned | boundary_list

    classified = _classified_names(cli)
    ignored = set(cli.INSTRUMENTATION_IGNORED_EVENTS)

    unclassified = sorted(all_names - classified - ignored)
    assert not unclassified, (
        "emitted event names (or requiredBoundaryEvents entries) not classified into "
        f"instrumentation_event_map()/PAIRED/FINALIZE and not in INSTRUMENTATION_IGNORED_EVENTS: {unclassified}"
    )


def test_classified_and_ignored_tables_do_not_overlap(cli):
    classified = _classified_names(cli)
    ignored = set(cli.INSTRUMENTATION_IGNORED_EVENTS)
    assert not (classified & ignored), classified & ignored


def test_every_ignored_event_has_a_non_blank_reason(cli):
    for name, reason in cli.INSTRUMENTATION_IGNORED_EVENTS.items():
        assert isinstance(reason, str) and reason.strip(), f"{name} has no reason recorded"


def test_every_instrumentation_event_code_is_reachable_from_some_producer(cli):
    """No code in the frozen v1 enum may be orphaned -- every code must be the target of at least
    one simple mapping, paired-lifecycle reducer, or finalize-verdict reducer entry."""
    reachable_codes = set(cli.instrumentation_event_map().values())
    for *_names, code in cli.INSTRUMENTATION_PAIRED_LIFECYCLE_PRODUCERS:
        reachable_codes.add(code)
    for _name, clean_code, blocked_code in cli.INSTRUMENTATION_FINALIZE_VERDICT_PRODUCERS:
        reachable_codes.add(clean_code)
        reachable_codes.add(blocked_code)
    missing = sorted(set(cli.INSTRUMENTATION_EVENT_CODES) - reachable_codes)
    assert not missing, f"instrumentation codes with no producer mapping to them: {missing}"


def test_producer_coverage_gate_fails_on_a_newly_added_unclassified_event(cli):
    """Negative fixture: a brand new `try_write_event` call site with an unclassified name must be
    caught by the same diff-against-classified-and-ignored logic the real gate above uses."""
    hostile_source = (
        "def try_write_event(data, target, **kwargs):\n"
        "    pass\n"
        "\n"
        "\n"
        "def some_new_producer(data, target):\n"
        "    try_write_event(\n"
        "        data,\n"
        "        target,\n"
        "        event=\"brand_new_unclassified_event\",\n"
        "        severity=\"info\",\n"
        "        plain=\"x\",\n"
        "        next_action=\"y\",\n"
        "    )\n"
    )
    scanned = scan_emitted_event_names(hostile_source)
    classified = _classified_names(cli)
    ignored = set(cli.INSTRUMENTATION_IGNORED_EVENTS)
    unclassified = scanned - classified - ignored
    assert unclassified == {"brand_new_unclassified_event"}, (
        "the negative fixture must reproduce exactly one unclassified producer name until it is "
        f"explicitly mapped or ignored, got: {unclassified}"
    )


def test_scanner_resolves_the_real_dynamic_goal_and_milestone_advance_call_sites(cli):
    """Sanity check that the scanner's dynamic-expansion registry actually matches the real
    f-string shape used at the goal-advance/milestone-advance try_write_event call sites (if a
    future refactor changes that shape, this fails loudly instead of the coverage test silently
    scanning zero names for those two producers)."""
    source = SOURCE_PATH.read_text(encoding="utf-8")
    dynamic_expansions = {
        "goal_advance_": {f"goal_advance_{choice.replace('-', '_')}" for choice in cli.GOAL_ADVANCE_EVENTS},
        "milestone_advance_": {f"milestone_advance_{choice.replace('-', '_')}" for choice in cli.MILESTONE_ADVANCE_EVENTS},
    }
    scanned = scan_emitted_event_names(source, dynamic_expansions)
    assert any(name.startswith("goal_advance_") for name in scanned)
    assert any(name.startswith("milestone_advance_") for name in scanned)
