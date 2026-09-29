"""`doctor` and `red-green-check`: on-demand, always-exit-0 diagnostics for a working tree.

Neither verb ever gates or blocks. `doctor` runs four advisory checks and reports each as OK,
FINDING, or UNKNOWN(reason) -- never a fake OK. A check that cannot run (no `gh`, no remote, no
upstream, an unreadable log) says UNKNOWN and why, rather than silently passing. This codebase has
already paid for the alternative once: a control whose failure mode is silent success is worse than
no control at all (the "controls that report success while doing nothing" lesson -- see also
lean.slim_command's "how a control comes to report success while doing nothing"). `red-green-check`
salvages the pre-demolition mutation-discrimination proof (2c5b9a2c8) as a pure report: it always
exits 0 too, and it always restores the file it mutated.

Both are leaves: this module never imports `cli` (cli.py imports every leaf, never the reverse, or
the two would cycle). `cli.py` wires two thin wrapper functions (`doctor`, `red_green_check`) that
call into `doctor_command` / `red_green_check_command` below.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tautline_methodology import gitutil
from tautline_methodology.util import flatten_printable, parse_duration_seconds

OK = "OK"
FINDING = "FINDING"
UNKNOWN = "UNKNOWN"

DEFAULT_STALE_AFTER = "10m"
DEFAULT_SKIP_LINT_BASE = "origin/main"
_SUBPROCESS_TIMEOUT_SECONDS = 10


def _safe(text: object, limit: int = 160) -> str:
    """Anything that could carry bytes this process did not author (a subprocess's stderr, a `gh`
    JSON field, an operator-supplied path) is flattened before it reaches a terminal -- same
    primitive and posture as `backlog._safe`."""
    return flatten_printable(text, limit)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # OK | FINDING | UNKNOWN
    detail: str = ""

    def render(self) -> str:
        detail = f" -- {self.detail}" if self.detail else ""
        return f"{self.name}: {self.status}{detail}"


def _safe_check(name: str, fn: Callable[..., CheckResult], *args: object, **kwargs: object) -> CheckResult:
    """Run one check, converting an unexpected exception into an honest UNKNOWN instead of taking
    the whole `doctor` run down with it -- a crash that skips every check after it is the same
    failure mode as a fake OK: the report goes quiet exactly when something is wrong."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - intentionally broad; see docstring above
        return CheckResult(name, UNKNOWN, f"internal error: {_safe(exc, 160)}")


def _run(command: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> tuple[int, str, str]:
    """Local subprocess helper. A missing binary or a timeout is a RESULT (127 / 124), never an
    uncaught exception -- every check above needs to turn that into UNKNOWN, not a traceback."""
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return 124, stdout, stderr or f"command timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ---------------------------------------------------------------------------
# a. branch-liveness
# ---------------------------------------------------------------------------


def _target_integration_branch(target: Path) -> str | None:
    """Advisory-grade read of the target's own integration branch: lean-1 `integrationBranch`,
    else 1.x `laneStatus.integrationBranch` falling back to `latestCode.base` (the same order the
    renderer resolves it). None when unreadable or undeclared -- callers fall back, never fail,
    matching `_default_skip_lint_base`'s posture. ValueError covers both JSONDecodeError and a
    byte-corrupt file's UnicodeDecodeError."""
    try:
        data = json.loads((Path(target) / _LANE_ADAPTER_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    candidates = [data.get("integrationBranch")]
    lane_status = data.get("laneStatus")
    if isinstance(lane_status, dict):
        candidates.append(lane_status.get("integrationBranch"))
    latest = data.get("latestCode")
    if isinstance(latest, dict):
        candidates.append(latest.get("base"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def check_branch_liveness(
    target: Path, *, gh_binary: str = "gh", timeout: float = _SUBPROCESS_TIMEOUT_SECONDS
) -> CheckResult:
    """Is the current branch's PR merged or closed? If so, whoever is working on it is working on a
    dead branch. Honest about everything it cannot determine: no git repo, no `gh`, no configured
    remote, and a detached HEAD are all UNKNOWN, never OK-by-default."""
    name = "branch-liveness"
    if not gitutil.target_is_git_worktree(target):
        return CheckResult(name, UNKNOWN, f"{target} is not a git repository")
    if shutil.which(gh_binary) is None:
        return CheckResult(name, UNKNOWN, "gh CLI not installed")
    if gitutil.infer_repo_slug(target) == "<owner>/<repo>":
        return CheckResult(name, UNKNOWN, "no git remote configured")
    branch = gitutil.current_branch_name(target)
    if not branch:
        return CheckResult(name, UNKNOWN, "could not determine the current branch (detached HEAD?)")
    if branch == _target_integration_branch(target):
        # An integration branch is routinely the HEAD of merged release/promotion PRs, so "its
        # PR is merged" is business as usual there, not a dead lane -- without this the check
        # reports a FINDING on every integration-branch session forever, and a control that
        # cries wolf on every session reports nothing.
        return CheckResult(
            name, OK, f"'{_safe(branch, 80)}' is the integration branch; PR liveness does not apply"
        )
    code, out, err = _run(
        [gh_binary, "pr", "list", "--head", branch, "--state", "all", "--json", "number,state,url", "--limit", "1"],
        cwd=target,
        timeout=timeout,
    )
    if code != 0:
        return CheckResult(name, UNKNOWN, f"gh pr list failed: {_safe(err or out, 160)}")
    try:
        prs = json.loads(out or "[]")
    except json.JSONDecodeError:
        return CheckResult(name, UNKNOWN, "gh returned unparsable output")
    if not isinstance(prs, list) or not prs:
        return CheckResult(name, OK, f"no PR found for branch '{_safe(branch, 80)}'")
    pr = prs[0] if isinstance(prs[0], dict) else {}
    state = pr.get("state")
    number = pr.get("number")
    if state in ("MERGED", "CLOSED"):
        return CheckResult(name, FINDING, f"you are working on a dead branch -- PR #{number} is {state}")
    if state == "OPEN":
        return CheckResult(name, OK, f"PR #{number} is OPEN")
    return CheckResult(name, UNKNOWN, f"unexpected PR state from gh: {_safe(state, 40)}")


# ---------------------------------------------------------------------------
# b. framework-staleness
# ---------------------------------------------------------------------------


def _default_framework_repo() -> Path:
    """The checkout containing this file. `cli.doctor()` passes the fuller
    `canonical_methodology_repo()` resolution (pin files, snapshot manifests, env overrides) for the
    real CLI path; this is the fallback for a caller that uses `doctor_command` directly, since this
    module never imports `cli` (a leaf importing its own importer would cycle)."""
    return Path(__file__).resolve().parents[2]


def check_framework_staleness(
    framework_repo: Path | None, *, timeout: float = _SUBPROCESS_TIMEOUT_SECONDS
) -> CheckResult:
    """The framework checkout vs its own origin. Read-only: a `git ls-remote` (no `fetch`, no local
    mutation), so an on-demand `doctor` run never leaves a side effect in someone's checkout. When
    origin has moved but the new commits are not locally fetchable, this says UNKNOWN rather than
    guessing a count -- a wrong "behind by N" would be exactly the kind of report a reader trusts and
    a `git fetch` would then prove false."""
    name = "framework-staleness"
    if framework_repo is None:
        return CheckResult(name, UNKNOWN, "framework checkout not resolved")
    repo = Path(framework_repo)
    if not (repo / ".git").exists():
        return CheckResult(name, UNKNOWN, f"{repo} is not a git checkout (snapshot or packaged install?)")
    upstream = gitutil.git_branch_upstream(repo)
    if not upstream or "/" not in upstream:
        return CheckResult(name, UNKNOWN, "no upstream tracking branch configured")
    remote, _, branch = upstream.partition("/")
    code, local_head, _ = _run(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=timeout)
    local_head = local_head.strip()
    if code != 0 or not local_head:
        return CheckResult(name, UNKNOWN, "could not read local HEAD")
    code, remote_out, remote_err = _run(
        ["git", "-C", str(repo), "ls-remote", remote, f"refs/heads/{branch}"], timeout=timeout
    )
    if code != 0 or not remote_out.strip():
        return CheckResult(
            name, UNKNOWN, f"could not reach {_safe(remote, 40)}: {_safe(remote_err or remote_out, 120)}"
        )
    remote_sha = remote_out.split()[0]
    if remote_sha == local_head:
        return CheckResult(name, OK, f"up to date with {upstream}")
    code, _, _ = _run(["git", "-C", str(repo), "cat-file", "-e", f"{remote_sha}^{{commit}}"], timeout=timeout)
    if code != 0:
        return CheckResult(
            name,
            UNKNOWN,
            f"{upstream} has moved and the new commits are not fetched locally; run git fetch for an "
            "exact count",
        )
    code, count_out, _ = _run(["git", "-C", str(repo), "rev-list", "--count", f"HEAD..{remote_sha}"], timeout=timeout)
    if code != 0 or not count_out.strip().isdigit():
        return CheckResult(name, UNKNOWN, "could not count commits behind")
    behind = int(count_out.strip())
    if behind == 0:
        return CheckResult(name, OK, f"not behind {upstream} (local may be ahead or diverged)")
    return CheckResult(name, FINDING, f"the framework checkout at {repo} is behind {upstream} by {behind} commit(s)")


# ---------------------------------------------------------------------------
# c. skip-lint
# ---------------------------------------------------------------------------

# Cross-language skip/xfail/quarantine markers, salvaged from the pre-demolition
# `FLAKY_QUARANTINE_MARKERS` gate (2c5b9a2c8, cli.py) -- MINUS that gate's "t.skip(" entry. Matching
# here is a plain substring (see `_skip_lint_diff_findings`), and "t.skip(" substring-matches any
# `<word ending in t>.skip(` -- `element.skip(`, `client.skip(`, `pagination.skip(` (a common
# pagination/cursor method, e.g. MongoDB, RxJS) are all real, non-test code that would false-positive.
# The old gate carried the same risk; dropped here rather than promoted to a word-boundary regex,
# since every remaining marker is unambiguous on its own (a dotted namespace prefix, an "@"
# decorator, or a whole distinctive token like "xit(") and a single ambiguous entry isn't worth a
# second matching mechanism just for AVA's `t.skip(` idiom.
SKIP_LINT_MARKERS: tuple[str, ...] = (
    "@flaky",
    "@pytest.mark.flaky",
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    "@pytest.mark.skipif",
    "@unittest.skip",
    "pytest.skip(",
    "pytest.xfail(",
    "describe.skip(",
    "it.skip(",
    "test.skip(",
    "xit(",
    "xdescribe(",
    "@disabled",
    "@ignore",
    "#[ignore]",
)


def _skip_lint_diff_findings(diff_text: str, markers: tuple[str, ...] = SKIP_LINT_MARKERS) -> list[str]:
    """New skip/xfail/quarantine markers a diff ADDS, one finding per added line that introduces
    one. Simplified from the pre-demolition `flaky_quarantine_diff_issues` (core/runtime.py @
    2c5b9a2c8): this drops the owner/due-annotation requirement, the marker ratchet, and the
    enforcement config -- this check only reports, it never blocks."""
    lowered = [m.lower() for m in markers]
    findings: list[str] = []
    current_file = "?"
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            current_file = "/dev/null" if path == "/dev/null" else re.sub(r"^b/", "", path).strip().strip('"')
        elif raw.startswith("+") and not raw.startswith("+++"):
            line = raw[1:]
            low = line.lower()
            hit = next((markers[i] for i, m in enumerate(lowered) if m in low), None)
            if hit is not None:
                findings.append(f"{current_file}: new '{hit}' marker: {_safe(line.strip(), 100)}")
    return findings


# Mirrors cli.py's own LANE_ADAPTER_FILE. Read directly (never through cli's adapter-loading
# machinery, which validates and can raise) because a wrong or missing adapter here should only
# ever cost a less-useful DEFAULT, never a crash -- `--base` always overrides it regardless.
_LANE_ADAPTER_FILENAME = ".tautline.json"


def _default_skip_lint_base(target: Path) -> str:
    """Best-effort default diff base: `<remote>/<base>` from this target's own `.tautline.json`
    (`latestCode.remote` / `latestCode.base`) when readable, else `origin/main`. A repo whose
    integration branch is not `main` (this one included -- `origin/main` sits far behind
    `origin/experimental`) would otherwise default to a diff against a nearly-unrelated history and
    report a wall of unrelated findings. Advisory-grade only: any failure to read or parse the
    adapter falls back silently, since a wrong default here just makes the report less useful, never
    wrong in a way `--base` can't fix."""
    try:
        raw = (Path(target) / _LANE_ADAPTER_FILENAME).read_text(encoding="utf-8")
        data = json.loads(raw)
        lean_branch = data.get("integrationBranch") if isinstance(data, dict) else None
        if isinstance(lean_branch, str) and lean_branch.strip():
            # lean-1: the base is `integrationBranch` and the remote concept is fixed to origin.
            return f"origin/{lean_branch.strip()}"
        latest = data.get("latestCode") if isinstance(data, dict) else None
        if isinstance(latest, dict):
            remote = str(latest.get("remote") or "origin").strip() or "origin"
            base = str(latest.get("base") or "main").strip() or "main"
            return f"{remote}/{base}"
    except (OSError, ValueError, AttributeError, TypeError):
        # ValueError covers JSONDecodeError and a byte-corrupt file's UnicodeDecodeError; this
        # helper runs outside _safe_check, so anything escaping here kills the whole doctor run.
        pass
    return DEFAULT_SKIP_LINT_BASE


def _load_skip_lint_diff(target: Path, base: str, diff_file: Path | None) -> tuple[str | None, str | None]:
    """(diff_text, error). Exactly one is None. `diff_text` may legitimately be an empty string (no
    changes); `error` is set only when a diff could not be obtained at all.

    Only the three-dot form (`base...HEAD`, i.e. "what changed since this branch diverged from
    base") is ever used. An earlier version fell back to a plain two-dot `git diff base` whenever
    three-dot failed -- but that is a DIFFERENT, unrelated comparison (tip vs tip, not
    merge-base vs tip): on a shallow or disjoint-history checkout, three-dot fails with "no merge
    base" while two-dot SILENTLY SUCCEEDS, comparing the two tips directly and reporting nearly the
    entire unrelated history as "added by this branch" -- a wrong FINDING, and a confidently wrong
    one. Reporting UNKNOWN here is the honest answer."""
    if diff_file is not None:
        path = Path(diff_file)
        if not path.exists():
            return None, f"--diff-file {path} not found"
        try:
            return path.read_text(encoding="utf-8", errors="replace"), None
        except OSError as exc:
            return None, f"could not read --diff-file {path}: {_safe(exc, 120)}"
    code, out = gitutil.run_git_status(target, ["diff", f"{base}...HEAD"])
    if code == 0:
        return out, None
    # Distinguish "no merge base" (base resolves fine, but shares no history with HEAD -- shallow
    # or disjoint clone) from every other failure (base doesn't resolve at all, git itself is
    # broken, etc.), so the message never blames "fetch deeper history" on a plain typo'd ref.
    ref_code, _ = gitutil.run_git_status(target, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    if ref_code == 0:
        merge_base_code, _ = gitutil.run_git_status(target, ["merge-base", base, "HEAD"])
        if merge_base_code != 0:
            return None, f"no merge base with {base}; fetch deeper history"
    return None, f"could not diff against {base} (is it fetched? try --diff-file)"


def check_skip_lint(
    target: Path,
    base: str = DEFAULT_SKIP_LINT_BASE,
    *,
    diff_file: Path | None = None,
    diff_text: str | None = None,
) -> CheckResult:
    """New skip/xfail/quarantine markers introduced by the diff vs `base` -- silently disabled
    coverage that a green test run would not show. Report-only: unlike the pre-demolition gate this
    is salvaged from, nothing here can fail a build. `diff_text` is an injection seam for tests and
    is used verbatim when given (bypassing both `--diff-file` and git)."""
    name = "skip-lint"
    error = None
    if diff_text is None:
        diff_text, error = _load_skip_lint_diff(target, base, diff_file)
    if error is not None:
        return CheckResult(name, UNKNOWN, error)
    findings = _skip_lint_diff_findings(diff_text or "")
    if not findings:
        return CheckResult(name, OK, f"no new skip/xfail/quarantine markers vs {base}")
    shown = findings[:8]
    more = f" (+{len(findings) - 8} more)" if len(findings) > 8 else ""
    return CheckResult(name, FINDING, "silently disabled coverage -- " + "; ".join(shown) + more)


# ---------------------------------------------------------------------------
# d. monitor-liveness
# ---------------------------------------------------------------------------


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else -- still alive
    except OSError:
        return False
    return True


def check_monitor_liveness(
    spec: str,
    *,
    stale_after_seconds: int = 600,
    now: float | None = None,
    pid_alive: Callable[[int], bool] | None = None,
) -> CheckResult:
    """A generic PID+logfile liveness primitive, only run when the caller opts in with `--watch` --
    no assumptions about what the process is or what its log looks like, so there is no dead receipt
    format to maintain. Alive plus a log that is still moving is the entire contract."""
    name = f"monitor-liveness ({_safe(spec, 80)})"
    pid_text, sep, log_text = spec.partition(":")
    log_text = log_text.strip()
    if not sep or not log_text:
        return CheckResult(name, UNKNOWN, "expected PID:LOGPATH")
    try:
        pid = int(pid_text.strip())
    except ValueError:
        return CheckResult(name, UNKNOWN, f"'{_safe(pid_text, 40)}' is not a PID")
    alive = (pid_alive or _pid_is_alive)(pid)
    if not alive:
        return CheckResult(name, FINDING, f"pid {pid} is not running")
    log_path = Path(log_text)
    try:
        mtime = log_path.stat().st_mtime
    except OSError:
        return CheckResult(name, FINDING, f"log path does not exist: {log_path}")
    age = (time.time() if now is None else now) - mtime
    if age > stale_after_seconds:
        return CheckResult(
            name, FINDING, f"pid {pid} alive but log stale for {int(age)}s (> {stale_after_seconds}s): {log_path}"
        )
    return CheckResult(name, OK, f"pid {pid} alive, log fresh ({int(age)}s old)")


# ---------------------------------------------------------------------------
# doctor: orchestration
# ---------------------------------------------------------------------------


def _summary_line(results: list[CheckResult]) -> str:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    parts = ", ".join(f"{counts[status]} {status.lower()}" for status in (FINDING, UNKNOWN, OK) if counts.get(status))
    plural = "" if len(results) == 1 else "s"
    return f"doctor: {len(results)} check{plural} -- {parts}" if parts else "doctor: 0 checks"


def doctor_command(args: argparse.Namespace, *, framework_repo: Path | None = None) -> int:
    """Run all four advisory checks and print one line per check, always exiting 0: a finding here
    is reported, never enforced. See the module docstring for why UNKNOWN beats a guessed OK."""
    target = Path(getattr(args, "target", None) or ".")
    base = getattr(args, "base", None) or _default_skip_lint_base(target)
    diff_file = getattr(args, "diff_file", None)
    repo = framework_repo if framework_repo is not None else _default_framework_repo()

    results = [
        _safe_check("branch-liveness", check_branch_liveness, target),
        _safe_check("framework-staleness", check_framework_staleness, repo),
        _safe_check("skip-lint", check_skip_lint, target, base, diff_file=Path(diff_file) if diff_file else None),
    ]

    stale_after_raw = getattr(args, "stale_after", None) or DEFAULT_STALE_AFTER
    stale_after_seconds: int | None
    try:
        stale_after_seconds = parse_duration_seconds(stale_after_raw)
        stale_after_error: str | None = None
    except SystemExit as exc:
        stale_after_seconds = None
        stale_after_error = str(exc)

    for spec in getattr(args, "watch", None) or []:
        check_name = f"monitor-liveness ({_safe(spec, 80)})"
        if stale_after_seconds is None:
            results.append(CheckResult(check_name, UNKNOWN, f"--stale-after: {stale_after_error}"))
            continue
        results.append(_safe_check(check_name, check_monitor_liveness, spec, stale_after_seconds=stale_after_seconds))

    print(_summary_line(results))
    for result in results:
        print(result.render())
    return 0


# ---------------------------------------------------------------------------
# red-green-check
# ---------------------------------------------------------------------------

# Single-symbol mutations for the red-green discrimination proof, salvaged verbatim from the
# pre-demolition MUTATION_RULES (2c5b9a2c8, cli.py).
MUTATION_RULES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("return True -> return False", re.compile(r"\breturn True\b"), "return False"),
    ("return False -> return True", re.compile(r"\breturn False\b"), "return True"),
    ("== -> !=", re.compile(r"=="), "!="),
    ("!= -> ==", re.compile(r"!="), "=="),
    ("and -> or", re.compile(r"\band\b"), "or"),
    ("or -> and", re.compile(r"\bor\b"), "and"),
    ("< -> >=", re.compile(r"<(?![=<])"), ">="),
    ("> -> <=", re.compile(r"(?<![->=])>(?![=>])"), "<="),
)


def generate_mutations(source: str) -> list[tuple[str, str]]:
    """Single-symbol mutations of one source file: for each rule, mutate the FIRST occurrence on a
    non-comment line. Returns (label, mutated_source) in rule order; the caller tries them in turn
    until one is killed (tests discriminate) or one survives (tests are a no-op). Salvaged verbatim
    from the pre-demolition rec #8 handler (2c5b9a2c8, cli.py)."""
    lines = source.splitlines(keepends=True)
    mutants: list[tuple[str, str]] = []
    for label, pattern, repl in MUTATION_RULES:
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                new_line = pattern.sub(repl, line, count=1)
                if new_line != line:
                    mutants.append((label, "".join(lines[:i] + [new_line] + lines[i + 1 :])))
                    break
    return mutants


# A genuine test-assertion failure (a real kill), NOT a tooling/lint/type/import failure. Salvaged
# verbatim (2c5b9a2c8, cli.py).
MUTATION_ASSERTION_FAIL = re.compile(
    r"AssertionError|\bassert\b|\b\d+ failed\b|\bFAILED\b|\bexpect\(|\bto (?:equal|be|throw|contain|match|have)\b|✗|✕",
    re.IGNORECASE,
)


def mutation_outcome(exit_code: int, output: str) -> str:
    """Classify a mutated test run: 'survived' (exit 0 -> tests are a no-op), 'killed' (a genuine
    test-assertion failure caught the mutation), 'timeout' (the command hit `--timeout` -- neither a
    confirmed kill nor a confirmed survival, so it must never be scored as either), or 'error'
    (non-zero with no assertion evidence -- a tooling/lint/type/import failure, not a valid kill).
    Salvaged from the pre-demolition rec #8 handler (2c5b9a2c8, cli.py); the 'timeout' case is new
    (see `_run`'s 124 sentinel) -- the old handler had no `--timeout` and none of this."""
    if exit_code == 124:
        return "timeout"
    if exit_code == 0:
        return "survived"
    if MUTATION_ASSERTION_FAIL.search(output):
        return "killed"
    return "error"


DEFAULT_RED_GREEN_TIMEOUT_SECONDS = 600


def _backup_path(file: Path) -> Path:
    return file.with_name(file.name + ".red-green-check.orig")


def red_green_check_command(args: argparse.Namespace) -> int:
    """Mutate one symbol of `--file`, run `--test-command`, and report killed/survived/inconclusive
    -- always exiting 0; the report is the product, nothing here blocks a build. COPY-guarded: an
    on-disk backup is written before the first mutation and removed only once the original is
    confirmed restored, so even a crash that skips the `finally` restore below (the interpreter
    killed outright, not merely an exception) leaves a recoverable copy next to the mutated file
    instead of a silently corrupted one.

    A pre-existing backup REFUSES the run rather than being read or overwritten. A run killed
    mid-mutation leaves file=mutated, backup=true-original; a naive re-run would read the MUTATED
    file as "original", write that over the true-original backup, then delete it on its own clean
    exit -- destroying the only recoverable copy. Refusing is the only choice that cannot lose data;
    every other option was tried and each one could zero out the true original.
    """
    target = Path(getattr(args, "target", None) or ".")
    file = Path(args.file)
    timeout_seconds = getattr(args, "timeout", None) or DEFAULT_RED_GREEN_TIMEOUT_SECONDS
    if not file.exists():
        print(f"red_green: file not found: {file}")
        return 0
    backup = _backup_path(file)
    if backup.exists():
        print(
            f"red_green: a previous run left {backup}; the file may be mutated -- restore from the "
            "backup before re-running; nothing was touched"
        )
        return 0
    try:
        original = file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"red_green: could not read {file}: {_safe(exc, 160)}")
        return 0
    mutants = generate_mutations(original)
    if not mutants:
        print(f"red_green: no applicable single-symbol mutation in {file}; skipping (not a failure)")
        return 0
    base_code, _, _ = _run(["bash", "-c", args.test_command], cwd=target, timeout=timeout_seconds)
    if base_code != 0:
        if base_code == 124:
            print(f"red_green: baseline test command timed out (> --timeout {timeout_seconds}s); skipping")
        else:
            print("red_green: baseline test command is not green; skipping (cannot measure discrimination)")
        return 0

    try:
        backup.write_text(original, encoding="utf-8")
    except OSError as exc:
        print(f"red_green: could not write backup copy {backup}: {_safe(exc, 160)}; not mutating {file}")
        return 0

    try:
        try:
            any_timeout = False
            for label, mutated in mutants:
                file.write_text(mutated, encoding="utf-8")
                code, out, err = _run(["bash", "-c", args.test_command], cwd=target, timeout=timeout_seconds)
                outcome = mutation_outcome(code, f"{out}\n{err}")
                print(f"red_green_mutation: {label} -> {outcome}")
                if outcome == "killed":
                    print(f"red_green: pass (tests discriminate; killed mutant '{label}')")
                    return 0
                if outcome == "survived":
                    print(
                        f"red_green_issue: mutation '{label}' in {file} SURVIVED the test command -- the "
                        "tests do not prove this code works (they would pass even if it broke). Add a "
                        "discriminating assertion."
                    )
                    return 0
                if outcome == "timeout":
                    any_timeout = True
                # 'error' or 'timeout': neither a kill nor a survival; try the next mutation.
            if any_timeout:
                print(
                    f"red_green: inconclusive (timeout: the test command exceeded --timeout "
                    f"{timeout_seconds}s on at least one mutation); skipping"
                )
            else:
                print(
                    "red_green: inconclusive (no mutation produced a test-assertion failure; tooling/loading "
                    "errors only); skipping"
                )
            return 0
        finally:
            file.write_text(original, encoding="utf-8")
            backup.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - always-exit-0 contract; see docstring above
        print(
            f"red_green: internal error during the mutation run: {_safe(exc, 160)}. If {file} was not "
            f"restored, the pre-mutation copy is at {backup}."
        )
        return 0
