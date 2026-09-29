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


# --- baseline strict-vs-fail-on-drift characterization pins -----------------------------------
# Each pin below states, for one representative gate, whether it blocks under --strict alone
# and/or --fail-on-drift alone. These booleans were true on the pre-0.8.9 baseline (proven via
# `git stash` -- see task-089-T1-report.md) and remain true after the classification rework;
# only the *numeric* debt exit code (1 -> 2 under bare --fail-on-drift) is new.


# --- report block: the maintainer_mode line (0.9.17 maintainer standdown, T3) -----------------
