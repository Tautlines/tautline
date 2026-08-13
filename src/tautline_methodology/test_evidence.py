"""Test-execution evidence: the `tautline-test-run/v1` record (item 37, Release 1).

Every existing Tautline control that appears to cover tests validates a DECLARATION about tests,
never an EXECUTION -- `ci_test_gate` reports `has_tests=true (adapter declares a preflight/test
command)`, and `finalize-implementation-review` takes its verdict as a self-reported argument.
`canonical-rules.md` already says green tests must mean working software; nothing could observe
compliance.

This module produces evidence that is a BY-PRODUCT of running a command rather than a claim about
having run one:

- the record is only ever written by the wrapper that executed something, and it carries that
  command's real exit code;
- `report.sha256` hashes a per-run COPY of the runner's machine-readable report, so counts cannot
  be edited after the fact without detection, and a later run overwriting the stable report path
  cannot invalidate an older record;
- `git.treeDigest` is the non-ignored tree the suite actually ran against, so "I ran the tests"
  stops being a defence once the tree moves.

Pure-ish leaf module: no `cli` import, so it is unit-testable in isolation (the `lane_status.py`
and `plan_authoring.py` precedent). Subprocess and filesystem work live here; the CLI wrapper in
`cli.py` stays thin.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

TEST_RUN_SCHEMA = "tautline-test-run/v1"
TEST_RUN_DIR = ".ai-runs/test-runs"

# How `--fresh-checkout` builds the tree it runs against. Named in the record so a reader can tell
# a fresh run from an in-place one, and so a future change of method is visible rather than silent.
FRESH_CHECKOUT_METHOD = "git-worktree-visible-tree/v1"

# `git write-tree` against a throwaway index after `git add -A`. Named in the record so a future
# change of method is visible to readers rather than silently altering what a digest means.
TREE_DIGEST_METHOD = "git-write-tree-non-ignored/v1"

# Counts provenance. `exit-code-only` is honest about knowing nothing: the record omits the count
# numbers entirely rather than writing zeros, because a zero is a claim.
COUNTS_SOURCE_JUNIT = "junit-xml"
COUNTS_SOURCE_PYTEST_JSON = "pytest-json"
COUNTS_SOURCE_EXIT_CODE_ONLY = "exit-code-only"

REPORT_FORMATS = (COUNTS_SOURCE_JUNIT, COUNTS_SOURCE_PYTEST_JSON)

# Slack on the "the command wrote this report" floor, because the two timestamps being compared do
# not come from the same clock. A file's mtime comes from the kernel's coarse-grained realtime
# clock, refreshed once per timer tick, while the run-start reading comes from the fine-grained
# one -- so a report a fast command writes right after the run starts can carry an mtime BEFORE
# that reading (measured at up to 1ms on a HZ=1000 arm64 kernel, on 188 of 200 trials), and
# filesystems with 1s or 2s timestamp granularity truncate further still. Without the slack, the
# faster the runner the more green suites read as `predates this run` with a synthesised exit code
# 1. What the slack would otherwise concede -- the previous run's report, still at the stable
# path, answering for a second run whose command exited 0 without writing anything -- is closed
# ahead of it rather than by it: `run_and_record` clears the declared report before the command
# runs, so absence afterwards is the proof. A clear that FAILS is reported as its own error
# rather than falling through to this floor, precisely because the slack here is wider than the
# gap between two consecutive runs. So this floor covers clock skew, and nothing else has to.
REPORT_MTIME_TOLERANCE_SECONDS = 2.0


def _util():
    from . import util as module

    return module


class TestReportUnparseable(Exception):
    """A declared machine-readable report exists but cannot be read as its declared format.

    Deliberately an exception, not a silent fallback to exit-code-only: an unparseable report is a
    configuration error the lane must see. Silently degrading would reproduce the provability
    theater this whole feature exists to remove.
    """


def _run_git(target: Path, args: list[str], *, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(target),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


class FreshCheckoutUnavailable(Exception):
    """A fresh-checkout run was asked for and could not be set up.

    Always fatal, never a fallback to an in-place run. A gate that quietly downgrades to the weaker
    mode is worse than one that refuses: the operator reads "the suite passed" and has no way to
    know it passed in the environment that is structurally blind to this defect class.
    """


class FreshCheckout:
    """A throwaway checkout containing exactly what git can see, plus its record summary."""

    __slots__ = ("root", "summary")

    def __init__(self, root: Path, summary: dict) -> None:
        self.root = root
        self.summary = summary


def _git_bytes(target: Path, args: list[str]) -> bytes:
    """Raw stdout from git. Separate from `_run_git` because a binary patch must not be decoded."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(target),
        capture_output=True,
        check=True,
        timeout=300,
    )
    return result.stdout


def _git_or_unavailable(target: Path, args: list[str], why: str) -> str:
    try:
        return _run_git(target, args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        raise FreshCheckoutUnavailable(f"{why}: {str(detail).strip() or exc}") from exc


def _carry_into(source_root: Path, run_root: Path, carry_paths: Sequence[str]) -> list[str]:
    """Link adapter-declared dependency directories into the fresh tree, invisibly to git.

    A fresh worktree has no `.venv/` and no `node_modules/` -- both gitignored, both installed
    out-of-tree by CI. Without them the configured gate cannot even start, so the mode would be
    unusable for exactly the adopters it is meant to protect. Linked rather than copied: a 161MB
    copy per run is not a gate anybody keeps.

    A carried DIRECTORY is recreated as a real directory whose children are symlinks, never as a
    single symlink standing in for the directory. That is not cosmetic. A `.gitignore` entry
    written `.venv/` matches directories only, and a symlink is not a directory -- so the
    single-symlink form makes the carried path show up as an untracked FILE inside the fresh tree,
    changing the very thing this mode exists to hold fixed. Observed, not theorised: it reddened
    three public-release export tests, which walk untracked files and refuse absolute symlinks.
    """
    carried: list[str] = []
    for raw in carry_paths:
        relative = str(raw).strip()
        if not relative:
            continue
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise FreshCheckoutUnavailable(
                f"testEvidence.freshCheckout.carryPaths entry {relative!r} must be a relative path "
                "inside the project"
            )
        source = source_root / candidate
        if not source.exists():
            continue
        destination = run_root / candidate
        if destination.exists() or destination.is_symlink():
            # It is in the fresh tree already, which means git tracks it. Replacing tracked content
            # with a link to the working copy would reintroduce precisely the divergence this mode
            # exists to remove, so refuse instead of quietly doing it.
            raise FreshCheckoutUnavailable(
                f"carryPaths entry {relative!r} is tracked content, not an out-of-tree dependency; "
                "remove it from testEvidence.freshCheckout.carryPaths"
            )
        # Fail closed on a path git does not ignore: carrying it would leave the fresh tree holding
        # something a real clone does not have, which is this whole defect class inverted.
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative],
            cwd=str(source_root),
            capture_output=True,
            check=False,
            timeout=120,
        )
        if ignored.returncode != 0:
            raise FreshCheckoutUnavailable(
                f"carryPaths entry {relative!r} is not gitignored, so a fresh clone would not have "
                "it either; carryPaths is for out-of-tree dependencies like .venv or node_modules"
            )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                destination.mkdir()
                for child in source.iterdir():
                    (destination / child.name).symlink_to(child.resolve())
            else:
                destination.symlink_to(source.resolve())
        except OSError as exc:
            # Symlink creation is not universally available (unprivileged Windows, some sandboxes).
            # Convert rather than let an OSError escape: the caller's contract is that a
            # fresh-checkout run either happens or refuses with a reason, never crashes.
            raise FreshCheckoutUnavailable(
                f"fresh-checkout could not link carryPaths entry {relative!r}: {exc}"
            ) from exc
        carried.append(relative)
    return carried


@contextlib.contextmanager
def fresh_checkout_tree(target: Path, carry_paths: Sequence[str] = ()) -> Iterator[FreshCheckout]:
    """A disposable checkout holding every file git can see and nothing it ignores.

    This is the local reproduction of CI's checkout state. It is built from `HEAD` plus the
    working-tree diff plus untracked-but-not-ignored files -- which is, by construction, the same
    set of files `non_ignored_tree_digest` hashes, so the tree a record describes and the tree the
    suite ran against are the same tree.

    What it deliberately leaves out is the gitignored runtime state (`.ai-runs/`, `.ai-work/`, and
    whatever else `.gitignore` covers). A test that reads that state passes on the authoring
    machine and fails on every fresh clone; eight local suite runs missed one, and all three CI
    jobs caught it.

    The operator's real tree is never touched: a temporary `git worktree` is added outside the
    repo and removed in `finally`.
    """
    _git_or_unavailable(
        target, ["rev-parse", "--verify", "HEAD"], "fresh-checkout needs a commit at HEAD"
    )

    holder = Path(tempfile.mkdtemp(prefix="tautline-fresh-checkout-"))
    # The worktree's directory BASENAME becomes its id under `.git/worktrees/`, so a fixed name
    # like "tree" would collide the moment two fresh runs overlap in one repo. Reuse the holder's
    # unique mkdtemp name.
    run_root = holder / holder.name
    try:
        _git_or_unavailable(
            target,
            ["worktree", "add", "--detach", "--quiet", str(run_root), "HEAD"],
            "fresh-checkout could not create a temporary git worktree",
        )

        # `--binary` so a changed binary fixture survives the round trip; without it `git apply`
        # refuses the patch and the run would silently test HEAD instead of the working tree.
        try:
            diff = _git_bytes(target, ["diff", "--binary", "HEAD"])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            raise FreshCheckoutUnavailable(
                f"fresh-checkout could not read the working-tree diff: {exc}"
            ) from exc
        applied_diff = bool(diff)
        if applied_diff:
            patch = holder / "working-tree.patch"
            patch.write_bytes(diff)
            try:
                subprocess.run(
                    ["git", "apply", "--binary", "--whitespace=nowarn", str(patch)],
                    cwd=str(run_root),
                    capture_output=True,
                    check=True,
                    timeout=300,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
                detail = getattr(exc, "stderr", b"") or b""
                raise FreshCheckoutUnavailable(
                    "fresh-checkout could not apply the working-tree diff: "
                    f"{detail.decode('utf-8', 'replace').strip() or exc}"
                ) from exc

        listing = _git_or_unavailable(
            target,
            ["ls-files", "--others", "--exclude-standard", "-z"],
            "fresh-checkout could not list untracked files",
        )
        copied = 0
        for entry in (item for item in listing.split("\0") if item):
            source = target / entry
            destination = run_root / entry
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    # Recreate the link, do not follow it: a symlink is what a clone would get, and
                    # copying through it would put different content in the fresh tree.
                    destination.symlink_to(os.readlink(source))
                elif source.is_file():
                    shutil.copy2(source, destination)
                else:
                    # Vanished mid-listing, or a socket/fifo. git can see it; there is nothing a
                    # clone would carry.
                    continue
            except OSError as exc:
                raise FreshCheckoutUnavailable(
                    f"fresh-checkout could not copy untracked file {entry!r}: {exc}"
                ) from exc
            copied += 1

        carried = _carry_into(target, run_root, carry_paths)

        yield FreshCheckout(
            run_root,
            {
                "method": FRESH_CHECKOUT_METHOD,
                "appliedWorkingTreeDiff": applied_diff,
                "copiedUntracked": copied,
                "carriedPaths": carried,
            },
        )
    finally:
        # Best-effort teardown in both directions: `worktree remove` unregisters the metadata under
        # `.git/worktrees`, `rmtree` gets the holder, and `prune` mops up if the first one failed.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(run_root)],
            cwd=str(target),
            capture_output=True,
            check=False,
            timeout=120,
        )
        shutil.rmtree(holder, ignore_errors=True)
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(target),
            capture_output=True,
            check=False,
            timeout=120,
        )


def _is_untrustworthy_exclusion(entry: str) -> bool:
    """True when a recorded exclusion is not a plain relative path this module could have written.

    Records declare the exclusions they were measured under and the classifier re-applies THOSE
    rather than today's defaults -- deliberately, so widening the default set never retroactively
    reclassifies an existing record. The cost is that the record names its own comparison basis,
    and the exclusions are handed to `git rm --cached` against a throwaway index.

    So a record that excludes the whole worktree makes its own digest the empty-tree hash, which
    the classifier then recomputes to that identical hash for ANY tree. A hand-written record with
    a copied green report would read `current` on a tree nothing ever ran against.

    This is an ALLOWLIST, and it is deliberately not a list of the bad spellings. The first draft
    enumerated ".", "*", "**" and missed git pathspec magic entirely -- `:(top)`, `:/*`,
    `:(glob)**` all reach the whole tree and none of them look like the forms that were checked.
    Enumerating what git accepts is a losing game; enumerating what this module EMITS is a short,
    closed list. Every exclusion `digest_excluded_paths` produces is a plain relative path, so
    anything else is rejected regardless of what it would have meant.

    Glob METACHARACTERS are not rejected, deliberately. `report[1].xml` is a perfectly legal
    filename, and a lane that configures one would have had its own freshly written record called
    `invalid` -- the writer emitting evidence the classifier then refuses. They are safe to allow
    because `non_ignored_tree_digest` passes every exclusion as an explicit `:(literal)` pathspec,
    so git matches the name rather than the pattern. That is where glob handling belongs: at the
    boundary that would otherwise interpret it, not in a data check that cannot tell a filename
    from an attack.
    """
    cleaned = entry.strip()
    if not cleaned:
        return True
    # Pathspec magic in either form: long `:(top)`/`:(glob)` or short `:/`, `:!`, `:^`.
    if cleaned.startswith(":"):
        return True
    if cleaned.startswith("/") or cleaned.startswith("~"):
        return True
    # Option-shaped. `non_ignored_tree_digest` now passes exclusions after `--`, so this can no
    # longer be parsed as a flag -- but an entry the writer could never have produced still has no
    # business being trusted, and the two defences fail independently.
    if cleaned.startswith("-"):
        return True
    try:
        candidate = Path(cleaned)
    except (ValueError, OSError):
        return True
    if candidate.is_absolute() or ".." in candidate.parts:
        return True
    # "." and "./" normalise to the whole tree.
    return str(candidate) in ("", ".")


def digest_excluded_paths(
    report_path: Path | None, target: Path, extra: Sequence[str] = ()
) -> list[str]:
    """Paths the digest always ignores, whatever `.gitignore` says.

    Some files are evidence ABOUT a run rather than part of the tree that run tested, and
    including any of them makes a record invalidate itself the moment it is written:

    * the record directory itself;
    * the runner's declared report, which the command writes DURING the run; and
    * `extra` -- review-evidence artifacts the surrounding workflow writes AFTER the run.

    The report case is not hypothetical: a lane declaring the obvious `junit.xml` at the repo root
    (not gitignored) could never reach `current` at all -- the pre-run digest is captured before
    the runner writes the report, so the post-run tree always differs. Excluding only the record
    directory left that config permanently `stale`.

    Neither was `extra` (Release 2, Codex R1 P2). The implementation-review LEDGER is tracked, so
    `finalize-implementation-review` writing it made the record that the same finalize had just
    accepted go `stale` one line later -- and the prepush gate shipping in the same release would
    then refuse the push. Two new gates deadlocking each other, costing every lane a second full
    suite run per PR. A ledger edit cannot change what the suite would do, so excluding it is
    semantically right rather than merely convenient; its own integrity is carried by
    `review-evidence-check` and the manifest sha binding, not by this digest.

    Records declare the exclusions they were written under, and `classify_test_run_evidence`
    re-applies THOSE rather than today's, so widening this set never retroactively changes how an
    existing record classifies.
    """
    excluded = [TEST_RUN_DIR]
    if report_path is not None:
        try:
            relative = report_path.resolve().relative_to(target.resolve())
        except (ValueError, OSError):
            excluded.extend(str(entry).strip() for entry in extra if str(entry).strip())
            return excluded
        excluded.append(str(relative))
    excluded.extend(str(entry).strip() for entry in extra if str(entry).strip())
    return excluded


def non_ignored_tree_digest(target: Path, excluded: list[str] | None = None) -> str:
    """Digest of every non-ignored file, tracked or not, minus `excluded`.

    `.gitignore` is the ignore authority, which is what makes this usable in a real lane: build
    artifacts cannot churn the digest, while a brand-new untracked test file DOES move it -- so a
    record cannot stay "current" across adding a test the run never collected.

    Two isolation properties matter as much as the digest itself:

    * the staging uses a TEMPORARY index (`GIT_INDEX_FILE`), so a currency check never rewrites the
      operator's `git status`; and
    * new blobs are written to a TEMPORARY object directory with the real one as an alternate, so
      nothing is written into the lane's `.git` at all. Without that, `git add -A` writes blobs into
      `.git/objects` even with a redirected index, and a read-only checkout (managed sandboxes,
      read-only CI) raises here -- BEFORE `test-run` can execute the suite or record anything.
    """
    excluded = excluded if excluded is not None else [TEST_RUN_DIR]
    with tempfile.TemporaryDirectory() as tmp:
        objects = Path(tmp) / "objects"
        objects.mkdir()
        env = _util().child_env(
            GIT_INDEX_FILE=str(Path(tmp) / "index"),
            GIT_OBJECT_DIRECTORY=str(objects),
            GIT_ALTERNATE_OBJECT_DIRECTORIES=str((target / ".git" / "objects").resolve()),
        )
        _run_git(target, ["add", "-A"], env=env)
        for path in excluded:
            # `--` before the path, always. Recorded exclusions are attacker-influenceable data
            # (the record declares them and the classifier re-applies them), and without the
            # separator an entry like `--bad-option` is parsed as a FLAG. git then exits non-zero,
            # the classifier reports `unavailable`, and `unavailable` fails open by design -- so a
            # malformed record in gitignored .ai-runs/test-runs/ walked straight through the gate
            # it was supposed to be stopped by, in `block` mode. The separator makes that whole
            # class impossible here rather than only where it was noticed; the allowlist in
            # `_is_untrustworthy_exclusion` rejects such entries too, and both are kept because
            # one is a parser boundary and the other is a data contract.
            _run_git(
                target,
                ["rm", "-r", "--cached", "--quiet", "--ignore-unmatch", "--", f":(literal){path}"],
                env=env,
            )
        return _run_git(target, ["write-tree"], env=env)


def git_snapshot(target: Path, excluded: list[str] | None = None) -> dict:
    """The tree identity to record. Callers take this BEFORE running the command.

    `excludedPaths` is recorded so a later reader re-applies the IDENTICAL rule. Without it, a
    classifier computing the digest its own way compares two different measurements and reports
    drift that never happened.
    """
    try:
        commit = _run_git(target, ["rev-parse", "HEAD"])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        commit = ""
    try:
        branch = _run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        branch = ""
    return {
        "commit": commit,
        "branch": branch,
        "treeDigest": non_ignored_tree_digest(target, excluded),
        "digestMethod": TREE_DIGEST_METHOD,
        "excludedPaths": excluded if excluded is not None else [TEST_RUN_DIR],
    }


def _int_attr(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def parse_junit_xml_counts(path: Path) -> dict:
    """Counts from a JUnit XML report, summed across every `<testsuite>`.

    Summed rather than read off the root: pytest emits a `<testsuites>` wrapper, but other runners
    emit a bare `<testsuite>`, and a multi-suite report would otherwise report only its first.
    """
    try:
        root = ET.parse(str(path)).getroot()
    except (ET.ParseError, UnicodeDecodeError, ValueError, OSError) as exc:
        raise TestReportUnparseable(f"{path} is not readable JUnit XML: {exc}") from exc

    suites = list(root.iter("testsuite")) or ([root] if root.tag == "testsuite" else [])
    if not suites:
        raise TestReportUnparseable(f"{path} contains no <testsuite> element")

    collected = sum(_int_attr(s.get("tests")) for s in suites)
    failed = sum(_int_attr(s.get("failures")) for s in suites)
    errors = sum(_int_attr(s.get("errors")) for s in suites)
    skipped = sum(_int_attr(s.get("skipped")) for s in suites)
    return {
        "collected": collected,
        "passed": max(collected - failed - errors - skipped, 0),
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "source": COUNTS_SOURCE_JUNIT,
    }


def parse_pytest_json_counts(path: Path) -> dict:
    """Counts from a pytest-json-report summary block."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as exc:
        # UnicodeDecodeError is a ValueError, NOT an OSError, so a corrupt non-UTF-8 copy used to
        # escape this handler and propagate out through classify -- breaking the never-raise
        # contract that lane-start depends on. A report we cannot decode is unparseable; that is
        # this exception's whole meaning.
        raise TestReportUnparseable(f"{path} is not readable pytest JSON: {exc}") from exc
    summary = data.get("summary")
    if not isinstance(summary, dict):
        raise TestReportUnparseable(f"{path} has no object `summary` block")

    passed = _int_attr(summary.get("passed"))
    failed = _int_attr(summary.get("failed"))
    errors = _int_attr(summary.get("error", summary.get("errors")))
    skipped = _int_attr(summary.get("skipped"))

    # Codex R5 P2. pytest reports four MORE outcomes that `collected` counts and these four buckets
    # do not: xfailed, xpassed, and deselected. Left unmapped, an ordinary green suite using
    # expected-failure markers fails the `passed + failed + errors + skipped == collected` check
    # and classifies `invalid` -- so `block` mode would refuse to finalize or push a project that
    # had done nothing wrong. That check is worth keeping (it is what catches a doctored report), so
    # the fix is to map the outcomes rather than loosen the invariant.
    #
    #   xpassed   -> passed.  It ran and it passed; the xfail marker was simply stale.
    #   xfailed   -> skipped. It ran and did not pass. Deliberately NOT `passed`: an expected
    #                failure is not evidence the code works, and `current-zero-tests` measures
    #                `collected - skipped`, so a suite that is entirely xfail correctly reads as
    #                proving nothing.
    #   deselected-> subtracted from collected. Those tests never ran at all, so counting them in
    #                the denominator would make every -k/-m filtered run look short.
    passed += _int_attr(summary.get("xpassed"))
    skipped += _int_attr(summary.get("xfailed"))
    deselected = _int_attr(summary.get("deselected"))
    collected = _int_attr(summary.get("collected"), passed + failed + errors + skipped) - deselected
    return {
        "collected": collected,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "source": COUNTS_SOURCE_PYTEST_JSON,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_stamp(moment: datetime) -> str:
    """Filename stamp with microseconds.

    Sub-second precision is load-bearing: `now_iso()`'s second resolution already ties ordering in
    the plan-review pending-run list (a recorded defect), and two runs inside one second must not
    collide on a filename or on "newest wins".
    """
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%f") + "Z"


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def test_run_dir(target: Path) -> Path:
    return target / TEST_RUN_DIR


def _copy_report_for_record(
    report_path: Path, records_dir: Path, stamp: str, report_format: str
) -> tuple[Path, str]:
    """Copy the runner's report beside the record and hash THE COPY.

    Copy-on-record is what lets a lane point `testEvidence.report` at a stable path (the runner's
    `--junitxml` target) without a later run silently invalidating an older record: each record
    owns its own immutable copy. It also means no runner has to learn a wrapper-provided path.
    """
    suffix = ".xml" if report_format == COUNTS_SOURCE_JUNIT else ".json"
    copy = records_dir / f"{stamp}-report{suffix}"
    copy.write_bytes(report_path.read_bytes())
    return copy, sha256_file(copy)


def _counts_for(report_path: Path, report_format: str) -> dict:
    if report_format == COUNTS_SOURCE_JUNIT:
        return parse_junit_xml_counts(report_path)
    if report_format == COUNTS_SOURCE_PYTEST_JSON:
        return parse_pytest_json_counts(report_path)
    raise TestReportUnparseable(
        f"unknown report format {report_format!r}; expected one of {', '.join(REPORT_FORMATS)}"
    )


def _rerooted_report(report_path: Path | None, target: Path, run_root: Path) -> Path | None:
    """Where the runner will actually write its report when the run happens elsewhere.

    A declared report path is relative to the project, so in a fresh checkout the runner writes it
    inside the fresh tree. Reading the project copy instead would hash a report from some earlier
    run -- and `report_path predates this run` would be the only symptom.
    """
    if report_path is None or run_root == target:
        return report_path
    try:
        relative = report_path.resolve().relative_to(target.resolve())
    except (ValueError, OSError):
        # Declared outside the project (an absolute scratch path): the runner writes it there
        # whichever tree it runs from.
        return report_path
    return run_root / relative


def run_and_record(
    target: Path,
    *,
    command: str,
    command_source: str,
    report_path: Path | None,
    report_format: str | None,
    label: str,
    fresh_checkout: bool = False,
    carry_paths: Sequence[str] = (),
    digest_excludes: Sequence[str] = (),
) -> tuple[Path, int]:
    """Execute `command` and write the record it produces. Returns (record path, exit code).

    The record is a by-product of the run, never an assertion about one: this function is the only
    writer, and it cannot be reached without a command having actually executed.

    With `fresh_checkout`, the command runs in a throwaway checkout carrying only what git can see
    (see `fresh_checkout_tree`), while the record, the output log and the tree digest still belong
    to the real project. That pairing is deliberate: the digest already measures exactly the
    non-ignored tree, so a fresh run's record describes the tree it really tested.

    Exit-code contract, in both directions:
      * the underlying command's exit code is returned unchanged whenever it is non-zero -- a red
        suite stays red through the wrapper, and a red runner's code is never masked by a
        report-handling problem;
      * a report problem synthesises a non-zero code ONLY when the command itself exited 0, so a
        green run with an unreadable declared report can never read as a clean run.
    """
    records_dir = test_run_dir(target)
    records_dir.mkdir(parents=True, exist_ok=True)

    # The tree that is about to be tested. Recomputing this after the run would record the tree the
    # suite itself mutated, and a later currency check would compare against something never run.
    excluded = digest_excluded_paths(report_path, target, digest_excludes)
    pre_run_git = git_snapshot(target, excluded)
    started = datetime.now(timezone.utc)
    stamp = utc_stamp(started)
    output_log = records_dir / f"{stamp}-output.log"

    report_error: str | None = None
    report_clear_error: str | None = None
    counts: dict | None = None
    report_record: dict | None = None

    with contextlib.ExitStack() as stack:
        run_root = target
        fresh_summary: dict | None = None
        if fresh_checkout:
            fresh = stack.enter_context(fresh_checkout_tree(target, carry_paths))
            run_root = fresh.root
            fresh_summary = fresh.summary

        effective_report = _rerooted_report(report_path, target, run_root)
        if effective_report is not None and effective_report != report_path:
            # In-place runs get this directory for free (the record dir is created above). A runner
            # that writes its report without mkdir must not fail only in fresh mode.
            effective_report.parent.mkdir(parents=True, exist_ok=True)
        if effective_report is not None and report_format is not None:
            # Clear the declared path before the command runs, so ABSENCE afterwards is the proof
            # that it wrote nothing. Timestamps cannot referee this on their own, in either mode:
            # checking out a worktree stamps every file with the current time, so a report
            # committed to the repo would look freshly written; and in place, the stable path
            # still holds the PREVIOUS run's report, whose mtime sits inside whatever slack the
            # floor below must carry for clock skew. Either way a command like `true` could
            # otherwise record counts it never produced. Only a report this function is going to
            # read is removed, and the record store keeps its own copy of every report it ever
            # accepted, so nothing that counts as evidence is thrown away here.
            try:
                effective_report.unlink(missing_ok=True)
            except OSError as exc:
                # A path we cannot clear (read-only mount, permissions) is neither a traceback nor
                # something to shrug at. The floor below cannot cover for it: the floor carries
                # seconds of slack for clock skew, and the report still sitting there is the
                # previous run's, well inside that slack. So the run says it could not establish
                # the report as its own, and cannot exit 0 on it.
                report_clear_error = (
                    f"declared report {report_path} could not be cleared before the run ({exc}); "
                    "a report present afterwards cannot be proven to be this run's"
                )

        # Stream live to the terminal while teeing to the log: a long suite that goes silent for
        # fifteen minutes is the failure mode the background-command rule exists to prevent.
        with output_log.open("w", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                ["bash", "-c", command],
                cwd=str(run_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                log.write(line)
            exit_code = process.wait()

        finished = datetime.now(timezone.utc)

        # Inside the stack on purpose: in fresh mode the report lives in the throwaway tree, so it
        # must be parsed and copied before that tree is removed.
        if effective_report is not None and report_format is not None:
            if report_clear_error is not None:
                report_error = report_clear_error
            elif not effective_report.exists():
                report_error = (
                    f"declared report {report_path} does not exist after the run; "
                    f"expected a {report_format} report written by the command"
                )
            elif (
                effective_report.stat().st_mtime
                < started.timestamp() - REPORT_MTIME_TOLERANCE_SECONDS
            ):
                # Older than the run means the command never wrote it. Re-hashing it would let a
                # months-old report vouch for a run that produced nothing. The tolerance absorbs
                # clock-source and filesystem-granularity skew only (see the constant).
                report_error = (
                    f"declared report {report_path} predates this run; "
                    "the command did not write it"
                )
            else:
                try:
                    counts = _counts_for(effective_report, report_format)
                except TestReportUnparseable as exc:
                    report_error = str(exc)
                else:
                    copy, digest = _copy_report_for_record(
                        effective_report, records_dir, stamp, report_format
                    )
                    report_record = {
                        "path": str(copy.relative_to(target)),
                        "format": report_format,
                        "sha256": digest,
                    }

    record: dict = {
        "schema": TEST_RUN_SCHEMA,
        "label": label,
        "command": command,
        "commandSource": command_source,
        "exitCode": exit_code,
        "startedAt": iso_utc(started),
        "finishedAt": iso_utc(finished),
        "durationSeconds": round((finished - started).total_seconds(), 3),
        "git": pre_run_git,
        "outputLog": str(output_log.relative_to(target)),
    }
    if fresh_summary is not None:
        record["freshCheckout"] = fresh_summary
    if report_record is not None:
        record["report"] = report_record

    post_run_digest = non_ignored_tree_digest(target, excluded)
    if post_run_digest != pre_run_git["treeDigest"]:
        # Not fatal, but worth surfacing: a suite that rewrites non-ignored files makes every
        # later currency comparison ambiguous, and that is a smell in the suite itself.
        record["postRunTreeDiffers"] = True

    if counts is not None:
        record["counts"] = counts
    else:
        # No numbers at all rather than zeros: a zero is a claim, and this record knows nothing.
        record["counts"] = {"source": COUNTS_SOURCE_EXIT_CODE_ONLY}
        record["countsWarning"] = "no machine-readable report declared; counts unknown"

    if report_error is not None:
        record["reportError"] = report_error
        record["countsWarning"] = "declared report could not be used; counts unknown"

    record_path = records_dir / f"{stamp}-test-run.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if exit_code == 0 and report_error is not None:
        return record_path, 1
    return record_path, exit_code


def load_latest_test_run(target: Path) -> dict | None:
    """Newest record by filename stamp, or None. Never raises."""
    try:
        records = sorted(test_run_dir(target).glob("*-test-run.json"))
    except OSError as exc:
        # Codex R3 P2. Swallowing this into None made an unreadable STORE indistinguishable from
        # an empty one, so a permissions or filesystem error classified `missing` and BLOCKED
        # under the default mode. That inverts the standing rule: a control that cannot tell must
        # not stop the lane. Distinguished here so the classifier can report the outage as one.
        return {"__store_unreadable__": f"{TEST_RUN_DIR}: {exc}"}
    if not records:
        return None
    try:
        data = json.loads(records[-1].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        # ValueError covers UnicodeDecodeError, which is NOT an OSError -- the exact trap already
        # documented in parse_pytest_json_counts and missed here. Without it a non-UTF-8 newest
        # record escaped this handler, the classifier's broad catch mapped it to `unavailable`,
        # and `unavailable` fails open -- so dropping a binary file into gitignored
        # .ai-runs/test-runs/ walked through both new gates in `block` mode.
        return {"__unreadable__": str(records[-1])}
    if not isinstance(data, dict):
        return {"__unreadable__": str(records[-1])}
    data["__path__"] = str(records[-1])
    return data


def record_is_fresh_checkout(record: dict | None) -> bool:
    """True when this record was produced by a fresh-checkout run. Never raises.

    Read from the record rather than inferred from today's configuration: whether a run reproduced
    CI's checkout state is a fact about that run, and a lane that turns the mode on afterwards must
    not retroactively make old evidence look like it had been fresh all along.
    """
    fresh = record.get("freshCheckout") if isinstance(record, dict) else None
    return isinstance(fresh, dict) and bool(fresh.get("method"))


def classify_test_run_evidence(target: Path) -> tuple[str, dict | None]:
    """How much a reader may conclude from the newest record.

    States: ``missing`` | ``invalid`` | ``stale`` | ``red`` | ``current`` | ``unavailable``.

    NEVER raises. W2 prints this at startup and prepush boundaries, and a currency reporter that
    can itself explode is worse than no reporter -- that is the 2026-07-22 startup-gate lesson.
    Every failure mode is a value with a reason.

    Order matters. ``invalid`` outranks ``red`` and ``stale`` because an untrustworthy record
    tells you nothing about the suite at all, so it must not be reported as a mere staleness
    problem the operator can dismiss.
    """
    try:
        record = load_latest_test_run(target)
    except Exception:  # noqa: BLE001 - containment is the contract
        return "unavailable", None

    if record is None:
        return "missing", None
    if "__store_unreadable__" in record:
        # The record STORE could not be listed at all -- not a statement about any record's
        # contents, so it is a checker outage and fails open, unlike a record that exists and
        # cannot be parsed (`invalid`, below).
        return "unavailable", None
    if "__unreadable__" in record:
        # Codex R4 P1 + R5 P1. `unavailable` must mean the CHECKER could not run, because that is
        # the only reading under which failing open is safe. A record that EXISTS and cannot be
        # parsed is not an outage -- it is evidence that is present and untrustworthy, which is
        # what `invalid` means. Reported as an outage, it let any corrupt file dropped into
        # gitignored .ai-runs/test-runs/ bypass every gate that reads this.
        return "invalid", record

    if record.get("schema") != TEST_RUN_SCHEMA:
        return "invalid", record

    # A declared report that could not be used means the counts are unknown, whatever the exit
    # code said. Reporting that as `current` would accept precisely the failure this exists to
    # catch: a green-looking run that proved nothing.
    if record.get("reportError"):
        return "invalid", record

    report = record.get("report")
    if isinstance(report, dict):
        declared = report.get("path")
        if not isinstance(declared, str):
            return "invalid", record
        copy = target / declared
        try:
            if not copy.exists() or sha256_file(copy) != report.get("sha256"):
                return "invalid", record
        except OSError:
            # Codex R5 P1, the SAME class as the malformed-record case one branch up -- fixing
            # that one by tag alone left this one open, because there are two ways for evidence to
            # be present-and-unreadable and only one of them sets `__unreadable__`. The report
            # copy is what verifies the counts; unreadable, it verifies nothing.
            return "invalid", record

        # Hash-matching the report proves the REPORT was not edited. It says nothing about the
        # `counts` block in the record, which is a separate field an editor can simply rewrite --
        # so without this the numbers a reader surfaces are authorable by assertion, which is the
        # exact substitution this whole feature exists to prevent. Re-parse the copy and require
        # the record to agree with it.
        recorded_counts = record.get("counts")
        if not isinstance(recorded_counts, dict):
            return "invalid", record
        try:
            parsed = _counts_for(copy, str(report.get("format")))
        except (TestReportUnparseable, OSError):
            return "invalid", record
        except Exception:  # noqa: BLE001 - classify is contractually never-raise
            # Defence in depth: the parsers above are expected to convert their own failures, but
            # this function's contract is absolute and it runs at lane-start. An unreadable copy is
            # `invalid` however it fails to read.
            return "invalid", record
        for field in ("collected", "passed", "failed", "errors", "skipped"):
            if recorded_counts.get(field) != parsed.get(field):
                return "invalid", record

    exit_code = record.get("exitCode")
    if not isinstance(exit_code, int):
        return "invalid", record
    if exit_code != 0:
        return "red", record

    git_block = record.get("git")
    if git_block is not None and not isinstance(git_block, dict):
        # Codex R5 P1. `(record.get("git") or {})` handles a null but not a STRING: `"oops".get`
        # raises AttributeError, the broad catch in evaluate_test_evidence_enforcement converts
        # that to `unavailable`, and `unavailable` fails open by design -- so a hand-edited record
        # with a malformed shape bypassed the gate in `block` mode. A record whose shape is wrong
        # is present-and-untrustworthy, which is exactly what `invalid` means. Same reasoning as
        # R4/R5's unparseable-record fix, one level further in.
        return "invalid", record
    recorded = (git_block or {}).get("treeDigest")
    if not isinstance(recorded, str) or not recorded:
        return "invalid", record
    # Re-apply the exclusions the RECORD declares, not today's defaults: a record written when a
    # different report path was configured must still be compared the way it was measured.
    excluded = (git_block or {}).get("excludedPaths")
    if not isinstance(excluded, list) or not all(isinstance(x, str) for x in excluded):
        excluded = [TEST_RUN_DIR]
    if any(_is_untrustworthy_exclusion(entry) for entry in excluded):
        # Codex R2 P1. Re-applying the record's OWN exclusions is what lets a record stay valid
        # across config changes -- but it also means the record chooses what it is compared
        # against. An entry of "." (or "", "/", "*") excludes the entire worktree, so the digest
        # becomes the empty-tree hash, which this function then recomputes to the SAME value for
        # any tree at all. A hand-written record with a copied green report would be admitted as
        # `current` on a tree that had never been tested, and this is the classifier the push and
        # finalize gates ask.
        #
        # `invalid`, not `stale`: the record is not out of date, it is not a legitimate record.
        return "invalid", record
    try:
        if non_ignored_tree_digest(target, excluded) != recorded:
            return "stale", record
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return "unavailable", record

    return "current", record


# --- Enforcement (item 37, Release 2) ------------------------------------------------------------
#
# Release 1 made test execution produce a tamper-evident receipt. Nothing read it: `red` was
# computed and its only consumer in the entire codebase was a print. This is the layer that makes
# the gates read it.
#
# DEFAULT IS `block`, by operator decision of 2026-07-31, overriding this plan's original `warn`
# default. The reasoning recorded there: a warn default makes the control opt-in, and the failure
# it exists to stop -- "the tests passed" as a sentence someone typed rather than a fact -- is the
# operator's #1 recurring failure. An opt-in control does not fix a recurring failure.
#
# The cost of that choice is that a downstream project advanced into `block` with no record lands
# in `missing`, not `red`. That is why every refusal below prints its remedy: a project blocked
# with no way out teaches its operator `--no-verify`, which is worse than no gate at all.

ENFORCEMENT_MODES = ("off", "warn", "block")
DEFAULT_ENFORCEMENT = "block"

# Dispositions the evaluator returns, kept distinct from the MODE that produced them.
PASS = "pass"
WARN = "warn"
BLOCK = "block"
FAIL_OPEN = "fail-open"


def _remedy_lines(target_arg: str = ".") -> list[str]:
    return [
        f"run the gate and record it:  tautline test-run --target {target_arg}",
        "or, if the suite writes a machine-readable report, declare it so counts parse:",
        "  testEvidence.report {path, format} in the project adapter",
        "or downgrade deliberately, in the SOURCE adapter, with a decision record saying why:",
        "  testEvidence.enforcement: warn   (report only)   /   off   (silent)",
        "  then re-render:  tautline render-adapters --project <adapter.json> "
        f"--target {target_arg} --write",
    ]


def evaluate_test_evidence_enforcement(
    target: Path, mode: str | None = None, target_display: str = "."
) -> tuple[str, str, list[str]]:
    """(condition, disposition, lines) for the newest test-run record under `mode`.

    NEVER raises, for the same reason `classify_test_run_evidence` never does: this runs on the
    prepush path, and a gate that can itself explode is worse than no gate. Every failure mode is
    a value.

    The eight conditions are the six classify states, with `current` split by what the counts can
    actually prove:

      current-parsed          a parsed report, tests collected, tests EXECUTED, counts agree,
                              zero failures/errors IN THE REPORT -- the only admitting state
      current-zero-tests      structurally valid, but collected == 0 or everything was skipped.
                              A suite that ran nothing proves nothing; this is the same bypass
                              class as a fabricated count, reached honestly.
      current-exit-code-only  green process, no declared report. Honest, and not proof of
                              anything about how many tests ran.

    `unavailable` FAILS OPEN. It means the classifier hit an internal error, not that the tests
    are bad, and the 2026-07-22 startup-gate lockout is the standing precedent: a control that
    cannot tell must not stop the lane.
    """
    effective = mode if mode in ENFORCEMENT_MODES else DEFAULT_ENFORCEMENT
    try:
        state, record = classify_test_run_evidence(target)
    except Exception as exc:  # noqa: BLE001 - contractually never-raise
        return (
            "unavailable",
            FAIL_OPEN,
            [f"test_evidence_enforcement: unavailable ({type(exc).__name__}: {exc})"],
        )

    condition = state
    if state == "current":
        condition = _current_condition(record)

    if effective == "off":
        return condition, PASS, []

    if condition == "unavailable":
        # Now genuinely narrow: `classify_test_run_evidence` returns `unavailable` only when the
        # CHECKER could not run -- the record store was unreadable, or git could not resolve the
        # tree. Evidence that is present and unreadable classifies `invalid` and blocks, which is
        # where two separate P1 bypasses lived (R4 and R5). Failing open is safe here precisely
        # because this state no longer says anything about the evidence.
        return condition, FAIL_OPEN, [
            "test_evidence_enforcement: unavailable — the checker itself could not run "
            "(the record store could not be read, or the git tree could not be resolved)",
            "test_evidence_enforcement: failing OPEN; this is a checker error, not a test failure",
        ]

    if condition == "current-parsed":
        return condition, PASS, [f"test_evidence_enforcement: {condition} — admitted"]

    reason = ENFORCEMENT_REASONS.get(condition, "the recorded evidence does not admit")
    if effective == "warn":
        return condition, WARN, [f"test_evidence_enforcement: {condition} — {reason}"]

    return condition, BLOCK, [
        f"test_evidence_enforcement: {condition} — {reason}",
        "test_evidence_enforcement: REFUSED (testEvidence.enforcement=block)",
        *_remedy_lines(target_display),
    ]


ENFORCEMENT_REASONS = {
    "missing": "no test-run record exists, so nothing proves this tree's tests were ever executed",
    "invalid": "the newest record is not trustworthy (schema, tampered report, or counts that "
    "disagree with the report they claim to summarise)",
    "stale": "the newest record was taken against a different tree than the one being shipped",
    # Reached two ways, and the text must be true of BOTH: `classify_test_run_evidence` returns
    # `red` for a non-zero exit, and `_current_condition` returns it for a run that exited ZERO
    # while its report recorded failures (`pytest ... || true`). Naming only the exit code made the
    # second case print something false -- a small instance of exactly the untrue-green this
    # release exists to stop.
    "red": "the newest record is RED — the suite exited non-zero, or its report recorded "
    "failures/errors (the report outranks the exit code)",
    "current-exit-code-only": "the run was green but declared no report, so how many tests ran is "
    "unknown; a green process is not a count",
    "current-zero-tests": "the report is valid and proves NO test executed (zero collected, or "
    "every test skipped). A suite that ran nothing cannot have passed anything",
}


def _current_condition(record: dict | None) -> str:
    """Split `current` by what its counts can actually prove."""
    if not isinstance(record, dict):
        return "current-exit-code-only"
    counts = record.get("counts")
    if not isinstance(counts, dict):
        return "current-exit-code-only"
    source = str(counts.get("source") or "")
    if source not in ("junit-xml", "pytest-json"):
        return "current-exit-code-only"

    # Codex R2 P2 on Release 2, and a bypass of this feature's central guarantee.
    #
    # `classify_test_run_evidence` verifies counts against the hashed report copy ONLY inside
    # `if isinstance(report, dict)`. With no report block there is nothing to verify against -- so
    # a record in gitignored `.ai-runs/` could be hand-edited to claim `source: junit-xml` with
    # plausible green counts, and `block` would admit it. That is precisely the substitution of an
    # ASSERTION for an EXECUTION that this whole item exists to stop, reintroduced by the layer
    # meant to enforce it.
    #
    # `invalid`, not `current-exit-code-only`, because this combination is NOT PRODUCIBLE by the
    # writer: `run_and_record` emits a parsed source only alongside the report it parsed, and
    # records `exit-code-only` otherwise. A record claiming a parse that left no artifact is
    # therefore corrupt or edited, and an untrustworthy record must not be downgraded to a merely
    # weaker-but-honest one.
    if not isinstance(record.get("report"), dict):
        return "invalid"

    collected = _int_attr(counts.get("collected"))
    skipped = _int_attr(counts.get("skipped"))
    failed = _int_attr(counts.get("failed"))
    errors = _int_attr(counts.get("errors"))
    passed = _int_attr(counts.get("passed"))

    if collected <= 0:
        return "current-zero-tests"
    # An all-skipped report proves no execution just as surely as a zero-collected one. Skipped
    # tests are not evidence -- that is this methodology's founding rule, and treating them as
    # evidence is the same bypass wearing a valid report.
    if collected - skipped <= 0:
        return "current-zero-tests"
    if passed + failed + errors + skipped != collected:
        # classify() already rejects this as `invalid` when a report is declared; kept here so the
        # partition is total rather than total-by-assumption.
        return "invalid"
    # The REPORT is the authority, not the exit code: `pytest ... || true` swallows the process
    # status while the report still records the failures.
    if failed > 0 or errors > 0:
        return "red"
    return "current-parsed"
