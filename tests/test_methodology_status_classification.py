"""T1 (0.8.9 startup remediation): failure classification, the three-way exit contract, and the
truthful `methodology_status_blocking` summary line for `methodology-status --fail-on-drift`.

See .superpowers/sdd/task-089-T1-brief.md. Two kinds of test live here:

- Characterization pins (docstring says "baseline pin"): they encode a fact about the PRE-0.8.9
  per-list `return 1` block that must NOT change -- whether a given gate blocks under --strict,
  under --fail-on-drift, or under both. Each pin asserts only baseline-true facts (exact exit
  codes where the value is unchanged, nonzero where only the 1-vs-2 value is new) and was proven
  to PASS against `git stash`'d bin/tautline (the pre-change baseline); see task-089-T1-report.md
  for the stash/verify transcript. They are exempt from red-first.
- New-behavior tests: the debt-vs-integrity exit-code split (1 vs 2) and the
  `methodology_status_blocking` summary line are genuinely new -- the baseline always returned 1
  and printed no summary. Each was verified RED against the same stashed baseline (failing for
  the right reason: exit 1 where 2 is required, summary line absent) and green after the rework.
"""

import inspect
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
SOURCE_REL = "docs/product/backlog/example-saas-v1/specs"
TEMPLATE_REL = "docs/product/backlog/templates/pr-execution-spec.template.md"
REPO_LOCAL_ADAPTER_REL = ".tautline/adapter.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_adapter(target: Path, mutate=None) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for methodology-status classification coverage (T1).",
        "repoEvidence": [
            {"path": ".ai-work/bootstrap-evidence.txt", "fact": "Primary bootstrap evidence exists."},
            {"path": ".ai-work/bootstrap-evidence-2.txt", "fact": "Secondary bootstrap evidence exists."},
        ],
    }
    # Quiet every optional/networked gate by default so each test isolates the gate(s) it cares
    # about; individual tests re-enable exactly the gate under test.
    data["graphify"] = {"enabled": False}
    data["latestCode"] = {"enabled": False}
    data["ciTestGate"] = {"enabled": False}
    data["backlogProvider"] = {"enabled": False}
    data["stakeholderQuestions"] = {"enabled": False}
    data["milestoneUpdate"] = {"enabled": False}
    data["productChat"] = {"enabled": False}
    data["deploymentNotification"] = {"enabled": False}
    behavior_specs = dict(data.get("behaviorSpecs") or {})
    behavior_specs["required"] = False
    behavior_specs["acceptanceHarnesses"] = []
    data["behaviorSpecs"] = behavior_specs
    document_context = dict(data.get("documentContext") or {})
    document_context["ignoredDocPaths"] = [
        *(document_context.get("ignoredDocPaths") or []),
        "docs/product/backlog",
    ]
    data["documentContext"] = document_context
    if mutate:
        mutate(data)
    adapter = target / REPO_LOCAL_ADAPTER_REL
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def _init_target(target: Path) -> None:
    target.mkdir(parents=True)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    evidence = target / ".ai-work"
    evidence.mkdir(parents=True)
    (evidence / "bootstrap-evidence.txt").write_text("bootstrap evidence\n", encoding="utf-8")
    (evidence / "bootstrap-evidence-2.txt").write_text("bootstrap evidence two\n", encoding="utf-8")
    (target / SOURCE_REL).mkdir(parents=True)
    template = target / TEMPLATE_REL
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("# Validation Template\n", encoding="utf-8")


def _lane(tmp_path: Path, run_cli, mutate=None) -> Path:
    """A clean, fully-started lane: adapter rendered (no drift), hooks installed, no debt.
    Returns the target path; callers selectively re-introduce a gate from this clean baseline.
    """
    target = tmp_path / "target"
    _init_target(target)
    adapter = _write_adapter(target, mutate)
    started = run_cli("lane-start", "--project", str(adapter), "--target", str(target), "--skip-update")
    assert started.returncode == 0, started.stdout + started.stderr
    bootstrapped = run_cli("context-bootstrap", "--project", str(adapter), "--target", str(target), "--write")
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    return target


def _status(run_cli, target: Path, *flags: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return run_cli("methodology-status", "--target", str(target), "--no-remote", *flags, cwd=cwd)


def _existing_event_lines(target: Path, run_cli) -> list[str]:
    """The event-log lines that exist BEFORE the command under test runs.

    Asked of the CLI rather than assembled from a path this test builds itself: `event-log-path`
    is the same resolution the writer uses, so a future change of location cannot leave this
    reading a file nothing writes to and silently seeing every run as having appended nothing.
    """
    resolved = run_cli("event-log-path", "--target", str(target), cwd=target)
    if resolved.returncode != 0:
        return []
    for line in resolved.stdout.splitlines():
        if line.startswith("event_jsonl:"):
            path = target / Path(line.split(": ", 1)[1])
            try:
                return path.read_text(encoding="utf-8").strip().splitlines()
            except OSError:
                return []
    return []


def _break_hooks(run_cli, tmp_path: Path) -> None:
    """Wipe the installed Claude hook settings -- an unconditionally-populated DEBT gate
    (hook_failures) that historically only ever blocked under --fail-on-drift, never --strict
    alone (baseline pin, see test_hook_failures_only_blocks_under_fail_on_drift_not_strict)."""
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")


# --- structural / SSOT machinery (pure, no subprocess) ---------------------------------------


def test_gate_tuples_exactly_partition_the_real_gate_condition_set(cli):
    """Partition/completeness: introspects the actual gate_conditions function signature (not a
    hand-typed copy) so an added/renamed gate list fails this test until classified."""
    params = set(inspect.signature(cli.methodology_status_gate_conditions).parameters) - {"args"}
    integrity = set(cli.METHODOLOGY_STATUS_INTEGRITY_GATES)
    debt = set(cli.METHODOLOGY_STATUS_DEBT_GATES)
    assert integrity | debt == params
    assert integrity.isdisjoint(debt)


def test_display_name_map_covers_every_gate_including_synthetic(cli):
    all_names = (
        set(cli.METHODOLOGY_STATUS_INTEGRITY_GATES)
        | set(cli.METHODOLOGY_STATUS_DEBT_GATES)
        | set(cli.METHODOLOGY_STATUS_SYNTHETIC_INTEGRITY_GATES)
    )
    assert all_names == set(cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES)


def test_synthetic_integrity_gates_disjoint_from_list_derived_gates(cli):
    list_derived = set(cli.METHODOLOGY_STATUS_INTEGRITY_GATES) | set(cli.METHODOLOGY_STATUS_DEBT_GATES)
    assert list_derived.isdisjoint(cli.METHODOLOGY_STATUS_SYNTHETIC_INTEGRITY_GATES)
    assert "remediation_marker" in cli.METHODOLOGY_STATUS_SYNTHETIC_INTEGRITY_GATES
    assert cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES["remediation_marker"] == "remediation_marker"


def test_classification_constants_are_tuples_not_lists(cli):
    # SSOT gotcha: UPPER_CASE list-of-str constants auto-enter the policy-phrases collector.
    assert isinstance(cli.METHODOLOGY_STATUS_INTEGRITY_GATES, tuple)
    assert isinstance(cli.METHODOLOGY_STATUS_DEBT_GATES, tuple)
    assert isinstance(cli.METHODOLOGY_STATUS_SYNTHETIC_INTEGRITY_GATES, tuple)


def test_integrity_gates_are_exactly_drift_and_development_environment(cli):
    assert set(cli.METHODOLOGY_STATUS_INTEGRITY_GATES) == {"drift", "development_environment_failures"}


def test_display_names_strip_the_failures_suffix_only(cli):
    names = cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES
    assert names["development_environment_failures"] == "development_environment"
    assert names["lane_coordination_failures"] == "lane_coordination"
    assert names["drift"] == "drift"
    for list_name in (*cli.METHODOLOGY_STATUS_INTEGRITY_GATES, *cli.METHODOLOGY_STATUS_DEBT_GATES):
        assert "_failures" not in names[list_name]


# --- grep-audit: no caller treats the exit code as specifically == 1 -------------------------


def test_no_bin_tautline_code_path_compares_methodology_status_exit_to_1_specifically():
    """Nonzero-means-stop: exit 1 (integrity) and exit 2 (debt) must both be treated as
    'refuse'. A caller that special-cases `== 1` would silently treat a debt-only exit 2 as
    success. Scoped to actual invocation sites (not the methodology_status()/gate_conditions()
    implementation itself, and not unrelated `== 1`/`-eq 1` code for other subprocesses/exit
    codes elsewhere in this ~36k-line file) by windowing around each real call site."""
    import re

    # Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a shim.
    text = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    invocation_markers = ("methodology-status", "methodology_status(args)")
    forbidden = re.compile(r"==\s*1\b|-eq\s+1\b|=\s*[\"']1[\"']")
    window = 5
    checked_any = False
    for index, line in enumerate(lines):
        if not any(marker in line for marker in invocation_markers):
            continue
        if "def methodology_status" in line or "def methodology_status_gate_conditions" in line:
            continue  # the implementation itself, not a caller
        checked_any = True
        start = max(0, index - window)
        end = min(len(lines), index + window + 1)
        surrounding = "\n".join(lines[start:end])
        assert not forbidden.search(surrounding), (
            f"line {index + 1} invokes methodology-status and a nearby line compares its exit "
            f"to 1 specifically (nonzero must mean stop):\n{surrounding}"
        )
    assert checked_any, "no methodology-status invocation sites found -- audit window is stale"


# --- clean / debt-only / integrity-dominates end-to-end behavior -----------------------------


def test_clean_lane_exits_0_with_no_summary_line(tmp_path, run_cli):
    """Baseline pin (also true post-change): a clean lane exits 0 and never prints the
    methodology_status_blocking line."""
    target = _lane(tmp_path, run_cli)
    result = _status(run_cli, target, "--fail-on-drift")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "methodology_status_blocking:" not in result.stdout


def test_debt_only_gate_exits_2_under_bare_fail_on_drift(tmp_path, run_cli):
    """NEW behavior (red-first): on the pre-0.8.9 baseline this exited 1. hook_failures is a
    DEBT gate; with no integrity failure present, bare --fail-on-drift must exit 2."""
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    result = _status(run_cli, target, "--fail-on-drift")
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout.rstrip("\n").endswith("\nmethodology_status_blocking: debt - hook"), result.stdout


def test_adapter_drift_integrity_gate_exits_1_even_with_debt_present(tmp_path, run_cli):
    """Explicit T1 fixture: adapter drift (INTEGRITY) alongside hook debt -- integrity dominates
    the exit code (still 1) and the summary truthfully lists both, integrity first."""
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    lane_json = target / ".tautline.json"
    lane_data = json.loads(lane_json.read_text(encoding="utf-8"))
    lane_data["commands"]["mainStatus"] = "stale local generated adapter command"
    lane_json.write_text(json.dumps(lane_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = _status(run_cli, target, "--fail-on-drift")
    assert result.returncode == 1, result.stdout + result.stderr
    # Exact-line pin (endswith, not substring): a substring match would tolerate extra trailing
    # gates; the design requires exactly these failing gates, integrity first, printed last.
    assert result.stdout.rstrip("\n").endswith("\nmethodology_status_blocking: integrity - drift, hook"), result.stdout


def test_development_environment_integrity_gate_exits_1_even_with_debt_present(tmp_path, run_cli):
    """Explicit T1 fixture: an unsupported development runtime (INTEGRITY) alongside hook debt.

    `lane-start` itself hard-refuses on an unsupported runtime (it cannot start a lane that
    cannot prove anything), so this fixture cannot lane-start directly with the broken adapter.
    Instead: lane-start cleanly, then temporarily overwrite the trusted repo-local adapter's
    developmentEnvironment field in place (the trust check requires the canonical
    `.tautline/adapter.json` path/name -- a copy under another name is rejected) and pass
    --project explicitly, which reads the adapter live rather than through the
    generated-marker sha-pin path. developmentEnvironment is not part of any rendered file, so
    adapter_drift stays clean and only the development_environment gate is newly introduced.
    """
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)

    adapter_path = target / REPO_LOCAL_ADAPTER_REL
    original = adapter_path.read_text(encoding="utf-8")
    data = json.loads(original)
    data["developmentEnvironment"] = {"supportedRuntimes": ["win32"], "windows": {"native": "unspecified"}}
    adapter_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        result = _status(run_cli, target, "--project", str(adapter_path), "--fail-on-drift")
    finally:
        adapter_path.write_text(original, encoding="utf-8")

    # Editing developmentEnvironment on the live source adapter also disagrees with the already
    # -rendered `.tautline.json` snapshot (it mirrors the full normalized config), so adapter
    # drift legitimately fires too -- both are INTEGRITY, listed ahead of the hook DEBT gate.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "methodology_status_blocking: integrity - drift, development_environment, hook" in result.stdout


def test_combined_strict_and_fail_on_drift_debt_only_still_exits_1_never_2(tmp_path, run_cli):
    """Baseline pin: `--strict` semantics preserved EXACTLY -- combined with --fail-on-drift, a
    debt-only failure still exits 1, never 2 (identical result on baseline and post-change; the
    combination is what existing docs/migrations use)."""
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    result = _status(run_cli, target, "--strict", "--fail-on-drift")
    assert result.returncode == 1, result.stdout + result.stderr


def test_strict_failures_also_print_truthful_summary_line(tmp_path, run_cli):
    """NEW behavior (red on baseline): the summary line prints on EVERY nonzero exit, including
    --strict paths, and prints LAST so it is the final word of the command."""
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    result = _status(run_cli, target, "--strict", "--fail-on-drift")
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.rstrip("\n").endswith("methodology_status_blocking: debt - hook"), result.stdout


def test_event_refs_carry_classification_and_gates_on_failure(tmp_path, run_cli):
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)
    # This adapter's event log is a PROJECT-RELATIVE path, so where the command runs from decides
    # which file it appends to. Run from the repository -- the default -- every test in every
    # xdist worker and every local run before this one shares a single log: it already held dozens
    # of `methodology_status_failed` events carrying these exact refs, so selecting one by name
    # would let this pin pass while the command under test wrote nothing at all, and a concurrent
    # worker appending mid-read would make it flake on someone else's event.
    #
    # Both go away by running in the lane, where the log belongs to this test alone. The
    # before/after boundary stays as the second line of defence: it is what makes the assertion
    # about THIS invocation even if the log location changes again (backlog item 46).
    before = _existing_event_lines(target, run_cli)
    result = _status(run_cli, target, "--fail-on-drift", cwd=target)
    assert result.returncode == 2, result.stdout + result.stderr

    events_dir = None
    for line in result.stdout.splitlines():
        if line.startswith("event_log_jsonl:"):
            # Project-relative, and the command ran in the lane -- so it resolves against the lane,
            # not against wherever pytest happens to have been started.
            events_dir = target / Path(line.split(": ", 1)[1])
            break
    assert events_dir is not None, result.stdout
    # Select the event BY NAME, never by position. `lines[-1]` assumed nothing appends after the
    # command under test -- an assumption about ambient state, not about this command, and one that
    # parallel execution falsifies: the pin was observed reading `methodology_status_passed`
    # instead. Now that the merge gate blocks on red checks, a flake like this stops a merge rather
    # than merely annoying someone (backlog item 46).
    lines = events_dir.read_text(encoding="utf-8").strip().splitlines()
    appended = lines[len(before):]
    failures = [
        payload
        for payload in (json.loads(line) for line in appended)
        if payload.get("event") == "methodology_status_failed"
    ]
    assert failures, (
        "no methodology_status_failed event was written by THIS run; "
        f"saw {[json.loads(line).get('event') for line in appended]}"
    )
    payload = failures[-1]
    assert payload["refs"]["classification"] == "debt"
    assert payload["refs"]["gates"] == "hook"


# --- baseline strict-vs-fail-on-drift characterization pins -----------------------------------
# Each pin below states, for one representative gate, whether it blocks under --strict alone
# and/or --fail-on-drift alone. These booleans were true on the pre-0.8.9 baseline (proven via
# `git stash` -- see task-089-T1-report.md) and remain true after the classification rework;
# only the *numeric* debt exit code (1 -> 2 under bare --fail-on-drift) is new.


def test_hook_failures_only_blocks_under_fail_on_drift_not_strict(tmp_path, run_cli):
    """Pattern A (unconditional population, dedicated-return needs fail_on_drift only): baseline
    pin -- hook_failures never blocked under bare --strict, only under --fail-on-drift."""
    target = _lane(tmp_path, run_cli)
    _break_hooks(run_cli, tmp_path)

    unflagged = _status(run_cli, target)
    strict_only = _status(run_cli, target, "--strict")
    fail_on_drift_only = _status(run_cli, target, "--fail-on-drift")

    assert unflagged.returncode == 0, unflagged.stdout + unflagged.stderr
    assert strict_only.returncode == 0, strict_only.stdout + strict_only.stderr
    assert fail_on_drift_only.returncode != 0, fail_on_drift_only.stdout + fail_on_drift_only.stderr


def test_ci_test_gate_failures_blocks_under_either_strict_or_fail_on_drift(tmp_path, run_cli):
    """Pattern B (population is adapter-config-driven, not args-gated; dedicated return checks
    `strict or fail_on_drift`): baseline pin -- ci_test_gate_failures (a DEBT gate) already
    blocked under bare --strict alone, with exit 1 (--strict never returns 2)."""

    def mutate(data: dict) -> None:
        data["ciTestGate"] = {"enabled": True, "enforcement": "block", "requiredWorkflow": "", "expectTests": True}

    target = _lane(tmp_path, run_cli, mutate=mutate)
    (target / "tests").mkdir()

    unflagged = _status(run_cli, target)
    strict_only = _status(run_cli, target, "--strict")
    fail_on_drift_only = _status(run_cli, target, "--fail-on-drift")

    assert unflagged.returncode == 0, unflagged.stdout + unflagged.stderr
    assert strict_only.returncode == 1, strict_only.stdout + strict_only.stderr
    # `!= 0` (not == a value): the gate blocked on the baseline (exit 1) and still blocks
    # post-change (exit 2, debt under bare --fail-on-drift); only the numeric value moved.
    assert fail_on_drift_only.returncode != 0, fail_on_drift_only.stdout + fail_on_drift_only.stderr


def test_drift_only_blocks_under_fail_on_drift_not_strict(tmp_path, run_cli):
    """drift (INTEGRITY) shares Pattern A's return condition (fail_on_drift only, regardless of
    --strict) -- baseline pin, unchanged by the classification rework."""
    target = _lane(tmp_path, run_cli)
    lane_json = target / ".tautline.json"
    lane_data = json.loads(lane_json.read_text(encoding="utf-8"))
    lane_data["commands"]["mainStatus"] = "stale local generated adapter command"
    lane_json.write_text(json.dumps(lane_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    strict_only = _status(run_cli, target, "--strict")
    fail_on_drift_only = _status(run_cli, target, "--fail-on-drift")

    assert strict_only.returncode == 0, strict_only.stdout + strict_only.stderr
    # Exact == 1 is baseline-true AND post-change-true: drift is INTEGRITY, so its exit stays 1.
    assert fail_on_drift_only.returncode == 1, fail_on_drift_only.stdout + fail_on_drift_only.stderr


# --- report block: the maintainer_mode line (0.9.17 maintainer standdown, T3) -----------------


def test_report_block_carries_the_maintainer_mode_line(tmp_path, run_cli):
    """The ONE deliberate off-mode surface change of the maintainer-standdown release: every
    methodology-status report carries the three-state maintainer_mode line, sitting directly
    under methodology_exec_root so diagnosis (status is startup-remediation-ALLOWED) always
    shows whether this machine's update gates are standing down. Off by default; `on` names
    the managed checkout @ commit -- the same contract as the per-launch sync banner."""
    target = _lane(tmp_path, run_cli)

    off = _status(run_cli, target)
    assert off.returncode == 0, off.stdout + off.stderr
    off_lines = off.stdout.splitlines()
    assert "maintainer_mode: off" in off_lines, off.stdout
    exec_root_index = next(
        index for index, line in enumerate(off_lines) if line.startswith("methodology_exec_root: ")
    )
    assert off_lines[exec_root_index + 1] == "maintainer_mode: off", (
        "the maintainer_mode line must sit in the report block next to methodology_exec_root"
    )

    # Armed (key in the hermetic HOME's installed config env file; the repo checkout the tests
    # run from is the manageable canonical checkout): the line flips to `on` and names it.
    config_env = tmp_path / "home" / ".config" / "tautline" / "tautline.env"
    config_env.parent.mkdir(parents=True, exist_ok=True)
    config_env.write_text(
        "export TAUTLINE_METHODOLOGY_MAINTAINER_MODE=1\n"
        "export MINERVIT_METHODOLOGY_MAINTAINER_MODE=1\n",
        encoding="utf-8",
    )
    on = _status(run_cli, target)
    assert on.returncode == 0, on.stdout + on.stderr
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()[:12]
    assert (
        f"maintainer_mode: on - update gates off; running {REPO_ROOT} @ {head}"
        in on.stdout.splitlines()
    ), on.stdout
