"""item 37 W1: `tautline test-run` and the `tautline-test-run/v1` record.

Every Tautline control that appears to cover tests validates a DECLARATION about tests, never an
EXECUTION: `ci_test_gate` reports `has_tests=true (adapter declares a preflight/test command)`, and
`finalize-implementation-review` takes its verdict as a self-reported argument. This module pins
the first control that cannot be satisfied by assertion -- the record is a by-product of running a
command, and its report hash plus tree digest make it tamper-evident.

Every fixture builds its own git repo under `tmp_path`. None of these tests may touch the real
checkout: the item-30 lesson is that a test coupling to ambient lane state fails on exactly the
lanes the framework tells builders to create.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tautline_methodology import test_evidence


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "lane"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("build/\n*.pyc\n", encoding="utf-8")
    (repo / "src.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init")
    return repo


# --- tree digest: .gitignore is the ignore authority ------------------------------------------


def test_tree_digest_changes_when_tracked_file_changes(tmp_path):
    repo = _repo(tmp_path)
    before = test_evidence.non_ignored_tree_digest(repo)
    (repo / "src.py").write_text("value = 2\n", encoding="utf-8")
    assert test_evidence.non_ignored_tree_digest(repo) != before


def test_tree_digest_changes_when_untracked_non_ignored_file_added(tmp_path):
    """The currency property depends on this: a new, never-committed test file must move the
    digest, or 'I ran the suite' survives adding a test the run never collected."""
    repo = _repo(tmp_path)
    before = test_evidence.non_ignored_tree_digest(repo)
    (repo / "test_new.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    assert test_evidence.non_ignored_tree_digest(repo) != before


def test_tree_digest_unchanged_by_gitignored_artifact(tmp_path):
    """Build artifacts must not churn the digest, or currency is unusable in a real lane."""
    repo = _repo(tmp_path)
    before = test_evidence.non_ignored_tree_digest(repo)
    (repo / "build").mkdir()
    (repo / "build" / "artifact.bin").write_text("x" * 100, encoding="utf-8")
    (repo / "stale.pyc").write_text("junk", encoding="utf-8")
    assert test_evidence.non_ignored_tree_digest(repo) == before


def test_tree_digest_does_not_dirty_the_real_index(tmp_path):
    """The digest uses a temporary index. If it staged into the lane's own index, every currency
    check would leave the operator's `git status` rewritten."""
    repo = _repo(tmp_path)
    (repo / "unstaged.py").write_text("x = 1\n", encoding="utf-8")
    test_evidence.non_ignored_tree_digest(repo)
    assert _git(repo, "status", "--porcelain") == "?? unstaged.py"


# --- report parsing --------------------------------------------------------------------------


def test_junit_xml_counts_parse_collected_passed_failed_skipped_errors(tmp_path):
    report = tmp_path / "j.xml"
    report.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite name="pytest" errors="1" failures="2" skipped="3" tests="10">'
        "</testsuite></testsuites>\n",
        encoding="utf-8",
    )
    counts = test_evidence.parse_junit_xml_counts(report)
    assert counts["collected"] == 10
    assert counts["failed"] == 2
    assert counts["errors"] == 1
    assert counts["skipped"] == 3
    assert counts["passed"] == 10 - 2 - 1 - 3


def test_pytest_json_counts_parse_collected_passed_failed_skipped_errors(tmp_path):
    report = tmp_path / "r.json"
    report.write_text(
        json.dumps(
            {"summary": {"collected": 10, "passed": 4, "failed": 2, "error": 1, "skipped": 3}}
        ),
        encoding="utf-8",
    )
    counts = test_evidence.parse_pytest_json_counts(report)
    assert counts["collected"] == 10
    assert counts["passed"] == 4
    assert counts["failed"] == 2
    assert counts["errors"] == 1
    assert counts["skipped"] == 3


def test_unparseable_report_raises_test_report_unparseable(tmp_path):
    report = tmp_path / "j.xml"
    report.write_text("not xml at all", encoding="utf-8")
    with pytest.raises(test_evidence.TestReportUnparseable):
        test_evidence.parse_junit_xml_counts(report)


# --- the record: written only by executing something, and tamper-evident ----------------------


def _write_run(repo: Path, *, command: str, report: Path | None = None,
               report_format: str | None = None, label: str = "full-preflight") -> Path:
    """Run `command` through the wrapper the way the verb does, returning the record path."""
    return test_evidence.run_and_record(
        repo,
        command=command,
        command_source="explicit-flag",
        report_path=report,
        report_format=report_format,
        label=label,
    )[0]


def test_test_run_writes_record_with_exit_code_and_junit_counts(tmp_path):
    repo = _repo(tmp_path)
    report = repo / "junit.xml"
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"1\" tests=\"5\"></testsuite></testsuites>' > junit.xml"
    )
    record_path = _write_run(repo, command=command, report=report, report_format="junit-xml")
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert record["schema"] == test_evidence.TEST_RUN_SCHEMA
    assert record["exitCode"] == 0
    assert record["counts"]["collected"] == 5
    assert record["counts"]["passed"] == 4
    assert record["counts"]["source"] == "junit-xml"
    assert record["git"]["digestMethod"] == test_evidence.TREE_DIGEST_METHOD


def test_test_run_failed_suite_still_writes_record_and_exits_nonzero(tmp_path):
    """A red suite must still leave evidence -- otherwise the only provable runs are green ones,
    and 'no record' becomes indistinguishable from 'never ran'."""
    repo = _repo(tmp_path)
    record_path, exit_code = test_evidence.run_and_record(
        repo, command="exit 3", command_source="explicit-flag",
        report_path=None, report_format=None, label="full-preflight",
    )
    assert exit_code == 3
    assert json.loads(record_path.read_text(encoding="utf-8"))["exitCode"] == 3


def test_no_declared_report_yields_exit_code_only_with_counts_warning_and_no_zero_claims(tmp_path):
    """Zero is a claim. A record that knows nothing must say so rather than write zeros."""
    repo = _repo(tmp_path)
    record = json.loads(_write_run(repo, command="true").read_text(encoding="utf-8"))
    assert record["counts"]["source"] == "exit-code-only"
    for absent in ("collected", "passed", "failed", "errors", "skipped"):
        assert absent not in record["counts"], f"{absent} must be absent, not zero"
    assert "countsWarning" in record


def test_record_timestamps_and_filename_have_sub_second_precision(tmp_path):
    repo = _repo(tmp_path)
    first = _write_run(repo, command="true")
    second = _write_run(repo, command="true")
    assert first != second, "two runs in the same second must not collide on a filename"
    record = json.loads(first.read_text(encoding="utf-8"))
    assert "." in record["startedAt"] and record["startedAt"].endswith("Z")


def test_record_git_block_is_pre_run_snapshot_when_suite_mutates_tree(tmp_path):
    """A writer that recomputed the digest at write time would record the POST-run tree -- the one
    the suite itself mutated -- and then classify that record 'current' against a tree the suite
    never actually tested."""
    repo = _repo(tmp_path)
    pre = test_evidence.non_ignored_tree_digest(repo)
    record = json.loads(
        _write_run(repo, command="echo mutated >> src.py").read_text(encoding="utf-8")
    )
    assert record["git"]["treeDigest"] == pre
    assert record["postRunTreeDiffers"] is True


def test_declared_report_missing_or_unparseable_is_explicit_error_not_silent_pass(tmp_path):
    repo = _repo(tmp_path)
    record_path, exit_code = test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=repo / "absent.xml", report_format="junit-xml", label="full-preflight",
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "reportError" in record
    assert record["counts"]["source"] == "exit-code-only"
    assert exit_code != 0, "a green command with a broken declared report must not exit 0"


def test_red_runner_exit_code_survives_report_error(tmp_path):
    """The runner's own exit code is never masked by a synthesized report-error code."""
    repo = _repo(tmp_path)
    _record, exit_code = test_evidence.run_and_record(
        repo, command="exit 2", command_source="explicit-flag",
        report_path=repo / "absent.xml", report_format="junit-xml", label="full-preflight",
    )
    assert exit_code == 2


def test_report_copy_survives_stable_path_overwrite(tmp_path):
    """Copy-on-record: a later run overwriting the stable report path must not invalidate an
    older record, and no runner has to learn a wrapper-provided path."""
    repo = _repo(tmp_path)
    emit = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"%s\"></testsuite></testsuites>' > junit.xml"
    )
    first = _write_run(repo, command=emit % "5", report=repo / "junit.xml",
                       report_format="junit-xml")
    first_record = json.loads(first.read_text(encoding="utf-8"))
    _write_run(repo, command=emit % "9", report=repo / "junit.xml", report_format="junit-xml")

    copy = repo / first_record["report"]["path"]
    assert copy.exists(), "the record must point at its own copy, not the stable path"
    assert test_evidence.sha256_file(copy) == first_record["report"]["sha256"]
    assert first_record["counts"]["collected"] == 5


def test_report_stamped_just_before_the_run_start_reading_is_still_this_run_s(tmp_path):
    """The staleness floor must absorb clock granularity, or fast runners lose every green run.

    A file's mtime comes from the kernel's coarse-grained clock, refreshed once per timer tick,
    while the run-start reading comes from the fine-grained one. A report written immediately
    after the run starts can therefore carry an mtime BEFORE that reading -- 188 of 200 trials on
    the self-hosted arm64 runner, which turned every green suite into `predates this run` plus a
    synthesised exit code 1. Filesystems with 1s or 2s timestamp granularity truncate further
    still. The command here writes the report and then back-dates it inside that window, so the
    tolerance is pinned rather than left to whichever kernel happens to run the suite.
    """
    repo = _repo(tmp_path)
    report = repo / "junit.xml"
    backdate = (
        f"{sys.executable} -c \"import os,time;t=time.time()-0.5;os.utime('junit.xml',(t,t))\""
    )
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"5\"></testsuite></testsuites>' > junit.xml && " + backdate
    )
    record_path, exit_code = test_evidence.run_and_record(
        repo, command=command, command_source="explicit-flag",
        report_path=report, report_format="junit-xml", label="full-preflight",
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "reportError" not in record, record.get("reportError")
    assert record["counts"]["collected"] == 5
    assert exit_code == 0


def test_a_run_that_writes_no_report_cannot_inherit_the_previous_run_s(tmp_path):
    """A command that exits 0 without writing its declared report must never read as green.

    The stable report path is reused across runs, so the previous run's file is sitting right
    there. Timestamps alone cannot referee this: the mtime floor has to carry slack for clock
    skew, and back-to-back runs land inside any slack worth having. So the declared report is
    removed BEFORE the command runs -- absence afterwards is the proof, in place exactly as in
    fresh mode -- and the second run here must report the missing report rather than re-hash the
    first run's counts.
    """
    repo = _repo(tmp_path)
    emit = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"5\"></testsuite></testsuites>' > junit.xml"
    )
    first = _write_run(repo, command=emit, report=repo / "junit.xml", report_format="junit-xml")
    assert json.loads(first.read_text(encoding="utf-8"))["counts"]["collected"] == 5

    record_path, exit_code = test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=repo / "junit.xml", report_format="junit-xml", label="full-preflight",
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "does not exist after the run" in record.get("reportError", "")
    assert "collected" not in record["counts"]
    assert exit_code != 0

    first_copy = repo / json.loads(first.read_text(encoding="utf-8"))["report"]["path"]
    assert first_copy.exists(), "clearing the stable path must not touch the recorded copy"


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root ignores the directory permissions this test relies on")
def test_a_report_that_cannot_be_cleared_before_the_run_is_an_error_not_a_shrug(tmp_path):
    """Failing to clear the old report must be said out loud, not absorbed by the mtime floor.

    Clearing the declared path is what proves a report belongs to the run, and the floor behind
    it carries seconds of slack for clock skew -- so if the clear fails and the command then
    writes nothing, the previous run's report sits inside that slack and would be re-hashed as
    this run's. Swallowing the error would reopen the exact hole the clearing step closes, so it
    is recorded and the run cannot exit 0.
    """
    repo = _repo(tmp_path)
    holder = repo / "reports"
    holder.mkdir()
    report = holder / "junit.xml"
    report.write_text(
        '<testsuites><testsuite name="p" errors="0" failures="0" skipped="0" tests="5">'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    holder.chmod(0o500)  # readable and traversable, but nothing inside can be removed
    try:
        record_path, exit_code = test_evidence.run_and_record(
            repo, command="true", command_source="explicit-flag",
            report_path=report, report_format="junit-xml", label="full-preflight",
        )
    finally:
        holder.chmod(0o700)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "could not be cleared before the run" in record.get("reportError", "")
    assert "collected" not in record["counts"]
    assert exit_code != 0


def test_report_older_than_run_start_is_explicit_error(tmp_path):
    """A pre-existing report the run never wrote is refused, not re-hashed as if it were fresh."""
    repo = _repo(tmp_path)
    stale = repo / "junit.xml"
    stale.write_text(
        '<testsuites><testsuite name="p" errors="0" failures="0" skipped="0" tests="1">'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    os.utime(stale, (1_000_000, 1_000_000))
    record_path, exit_code = test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=stale, report_format="junit-xml", label="full-preflight",
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "reportError" in record
    assert exit_code != 0


# --- classification: what a reader is allowed to conclude --------------------------------------


def test_classify_states_missing_invalid_stale_red_current(tmp_path):
    repo = _repo(tmp_path)
    assert test_evidence.classify_test_run_evidence(repo)[0] == "missing"

    _write_run(repo, command="true")
    assert test_evidence.classify_test_run_evidence(repo)[0] == "current"

    # A tree that moved after the run is no longer covered by it. This is the property that kills
    # "I ran them" as a defence.
    (repo / "src.py").write_text("value = 99\n", encoding="utf-8")
    assert test_evidence.classify_test_run_evidence(repo)[0] == "stale"

    _write_run(repo, command="exit 1")
    assert test_evidence.classify_test_run_evidence(repo)[0] == "red"


def test_record_with_mismatched_report_sha256_classifies_invalid(tmp_path):
    """Tamper evidence: editing the counts in a recorded report must not survive reading."""
    repo = _repo(tmp_path)
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"5\"></testsuite></testsuites>' > junit.xml"
    )
    record_path = _write_run(repo, command=command, report=repo / "junit.xml",
                             report_format="junit-xml")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    (repo / record["report"]["path"]).write_text("tampered", encoding="utf-8")

    state, _ = test_evidence.classify_test_run_evidence(repo)
    assert state == "invalid"


def test_declared_report_failure_never_classifies_current(tmp_path):
    """A green run whose declared report was missing must not read as `current` -- that would
    silently accept the exact failure this feature exists to prevent."""
    repo = _repo(tmp_path)
    test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=repo / "absent.xml", report_format="junit-xml", label="full-preflight",
    )
    assert test_evidence.classify_test_run_evidence(repo)[0] == "invalid"


def test_no_report_declared_green_run_still_classifies_current(tmp_path):
    """The exit-code-only lane is legitimate and must not be punished for declaring no report."""
    repo = _repo(tmp_path)
    _write_run(repo, command="true")
    assert test_evidence.classify_test_run_evidence(repo)[0] == "current"


@pytest.mark.parametrize("breakage", ["malformed-json", "not-a-git-repo", "missing-report-copy"])
def test_classify_never_raises_on_corrupt_record_unreadable_dir_or_git_error(tmp_path, breakage):
    """W2 prints this at startup boundaries, so it must never raise. Every failure mode is a
    value (`unavailable`), never an exception."""
    repo = _repo(tmp_path)
    if breakage == "malformed-json":
        _write_run(repo, command="true")
        record = sorted(test_evidence.test_run_dir(repo).glob("*-test-run.json"))[-1]
        record.write_text("{not json", encoding="utf-8")
        state, _ = test_evidence.classify_test_run_evidence(repo)
        assert state in {"unavailable", "invalid"}
    elif breakage == "not-a-git-repo":
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / test_evidence.TEST_RUN_DIR).mkdir(parents=True)
        state, _ = test_evidence.classify_test_run_evidence(plain)
        assert state in {"unavailable", "missing"}
    else:
        command = (
            "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
            "skipped=\"0\" tests=\"1\"></testsuite></testsuites>' > junit.xml"
        )
        record_path = _write_run(repo, command=command, report=repo / "junit.xml",
                                 report_format="junit-xml")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        (repo / record["report"]["path"]).unlink()
        state, _ = test_evidence.classify_test_run_evidence(repo)
        assert state == "invalid"


def test_seeded_failing_fixture_suite_produces_red_record(tmp_path):
    """The gate self-proof: prove the whole pipeline can go red, not merely that it goes green.
    A gate never observed failing is not known to be a gate."""
    repo = _repo(tmp_path)
    (repo / "test_seeded.py").write_text(
        "def test_deliberately_failing():\n    assert False, 'seeded'\n", encoding="utf-8"
    )
    record_path, exit_code = test_evidence.run_and_record(
        repo,
        command=f"{sys.executable} -m pytest test_seeded.py -q --junitxml=junit.xml || true; "
                "test -f junit.xml && grep -q 'failures=\"1\"' junit.xml && exit 1",
        command_source="explicit-flag",
        report_path=repo / "junit.xml", report_format="junit-xml", label="seeded-red",
    )
    assert exit_code != 0, "the seeded failure must reach the caller"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["exitCode"] != 0
    assert record["counts"]["failed"] == 1
    assert test_evidence.classify_test_run_evidence(repo)[0] == "red"


# --- adapter wiring: the verb's resolution and the registry partition --------------------------


def test_test_evidence_config_reads_and_rejects(tmp_path):
    from tautline_methodology import cli

    assert cli.test_evidence_config({})["report"] is None
    good = {"testEvidence": {"report": {"path": "j.xml", "format": "junit-xml"}}}
    assert cli.test_evidence_config(good)["report"] == {"path": "j.xml", "format": "junit-xml"}

    for bad in (
        {"testEvidence": "nope"},
        {"testEvidence": {"report": "nope"}},
        {"testEvidence": {"report": {"path": "", "format": "junit-xml"}}},
        {"testEvidence": {"report": {"path": "j.xml", "format": "tap"}}},
    ):
        with pytest.raises(SystemExit):
            cli.test_evidence_config(bad)


def test_test_run_is_startup_remediation_blocked():
    """Running a full suite is project work, not a remediation action. The registry-partition
    test fails any subcommand in neither tuple, so this placement must be explicit."""
    from tautline_methodology import cli

    assert "test-run" in cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS
    assert "test-run" not in cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS


def test_test_run_refuses_when_no_command_configured_and_names_both_remedies():
    """RCA-control-6 standard: a refusal enumerates every supported path forward, not one."""
    from tautline_methodology import cli

    assert cli.resolve_test_run_command({}, "make test") == ("make test", "--command")
    assert cli.resolve_test_run_command(
        {"commands": {"fullPreflight": "scripts/test.sh"}}, None
    ) == ("scripts/test.sh", "commands.fullPreflight")

    with pytest.raises(SystemExit) as excinfo:
        cli.resolve_test_run_command({}, None)
    message = str(excinfo.value)
    assert "--command" in message
    assert "commands.fullPreflight" in message
    assert "render-adapters" in message, "name the command that makes the adapter key take effect"


# --- stage-2 R1: exclusions and read-only .git -------------------------------------------------


def test_declared_report_path_is_excluded_from_the_digest(tmp_path):
    """A lane declaring the obvious `junit.xml` at the repo root -- NOT gitignored -- must still
    reach `current`. The runner writes that file during the run, so without excluding it the
    post-run tree always differs and no valid config could ever produce current evidence."""
    repo = _repo(tmp_path)
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"3\"></testsuite></testsuites>' > junit.xml"
    )
    _write_run(repo, command=command, report=repo / "junit.xml", report_format="junit-xml")
    assert test_evidence.classify_test_run_evidence(repo)[0] == "current"


def test_classify_reapplies_the_exclusions_the_record_declares(tmp_path):
    """A record measured with one exclusion set must be compared with THAT set. Comparing against
    today's defaults measures two different things and reports drift that never happened."""
    repo = _repo(tmp_path)
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"1\"></testsuite></testsuites>' > junit.xml"
    )
    record_path = _write_run(repo, command=command, report=repo / "junit.xml",
                             report_format="junit-xml")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "junit.xml" in record["git"]["excludedPaths"]
    assert test_evidence.TEST_RUN_DIR in record["git"]["excludedPaths"]


def _object_files(objects: Path) -> set[Path]:
    """Object files under `.git/objects`, excluding git's transient `*.lock` files.

    `maintenance.lock` (and gc's siblings) are written and removed on git's OWN schedule by
    background auto-maintenance, so snapshotting them makes the comparison depend on timing
    rather than on what the digest wrote. That is a latent flake at any concurrency and a
    reliable one under parallel test execution, where many workers drive git at once.
    """
    return {
        path.relative_to(objects)
        for path in objects.rglob("*")
        if path.is_file() and path.suffix != ".lock"
    }


def test_digest_writes_nothing_into_the_lane_git_directory(tmp_path):
    """`git add -A` writes blobs into .git/objects even with a redirected index. On a read-only
    checkout -- managed sandboxes, read-only CI -- that raises BEFORE test-run can run the suite
    or record anything, so the objects must go somewhere else too."""
    repo = _repo(tmp_path)
    objects = repo / ".git" / "objects"
    before = _object_files(objects)

    (repo / "brand_new_file.py").write_text("y = 2\n", encoding="utf-8")
    test_evidence.non_ignored_tree_digest(repo)

    # ADDED objects are the property under test; git may legitimately remove or repack its own
    # files meanwhile, so assert on the additions rather than on set equality.
    added = _object_files(objects) - before
    assert added == set(), (
        f"the digest must not add objects to the lane's own .git: {sorted(added)}"
    )


def test_digest_still_sees_content_through_the_alternate_object_store(tmp_path):
    """Redirecting objects must not blind the digest: it still has to notice real changes."""
    repo = _repo(tmp_path)
    before = test_evidence.non_ignored_tree_digest(repo)
    (repo / "src.py").write_text("value = 42\n", encoding="utf-8")
    assert test_evidence.non_ignored_tree_digest(repo) != before


# --- stage-2 R2: counts must not be authorable by assertion ------------------------------------


def test_fabricated_counts_in_the_record_classify_invalid(tmp_path):
    """Hash-matching the report proves the REPORT was not edited; it says nothing about the
    record's own `counts` block. Without re-parsing, a reader surfaces whatever numbers someone
    typed -- counts authorable by assertion, which is the exact substitution this feature removes.
    """
    repo = _repo(tmp_path)
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"3\"></testsuite></testsuites>' > junit.xml"
    )
    record_path = _write_run(repo, command=command, report=repo / "junit.xml",
                             report_format="junit-xml")
    assert test_evidence.classify_test_run_evidence(repo)[0] == "current"

    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["counts"]["collected"] = 9999
    record["counts"]["passed"] = 9999
    record_path.write_text(json.dumps(record), encoding="utf-8")

    assert test_evidence.classify_test_run_evidence(repo)[0] == "invalid"


def test_untampered_report_backed_record_still_classifies_current(tmp_path):
    """The re-parse must not make honest records fragile."""
    repo = _repo(tmp_path)
    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"1\" failures=\"2\" "
        "skipped=\"3\" tests=\"10\"></testsuite></testsuites>' > junit.xml"
    )
    _write_run(repo, command=command, report=repo / "junit.xml", report_format="junit-xml")
    state, record = test_evidence.classify_test_run_evidence(repo)
    assert state == "current"
    assert record["counts"]["collected"] == 10
    assert record["counts"]["passed"] == 4


def test_adapter_format_defaults_even_when_the_path_is_overridden():
    """`--report <alt>` on a lane declaring a format must not fail: this flag's help promises the
    adapter value as the default, and a refusal contradicting its own help is the RCA-control-6
    defect in miniature."""
    from tautline_methodology import cli

    data = {"testEvidence": {"report": {"path": "declared.xml", "format": "junit-xml"}}}
    cfg = cli.test_evidence_config(data)
    assert cfg["report"]["format"] == "junit-xml"
    assert cfg["report"]["path"] == "declared.xml"


def test_corrupt_report_copy_with_matching_hash_classifies_invalid_without_raising(tmp_path):
    """A hand-edited or corrupted evidence directory can hold a non-UTF-8 report copy whose hash
    still matches. UnicodeDecodeError is a ValueError, not an OSError, so it escaped the parser's
    handler and propagated out of classify -- breaking the never-raise contract lane-start relies
    on. Classification must be deterministic even for a copy we cannot decode.
    """
    repo = _repo(tmp_path)
    command = (
        "printf '{\"summary\":{\"collected\":2,\"passed\":2,\"failed\":0,\"error\":0,"
        "\"skipped\":0}}' > r.json"
    )
    record_path = _write_run(repo, command=command, report=repo / "r.json",
                             report_format="pytest-json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    copy = repo / record["report"]["path"]
    copy.write_bytes(b"\xff\xfe\x00not utf-8 at all")
    record["report"]["sha256"] = test_evidence.sha256_file(copy)
    record_path.write_text(json.dumps(record), encoding="utf-8")

    assert test_evidence.classify_test_run_evidence(repo)[0] == "invalid"


def test_parsers_convert_decode_failures_into_test_report_unparseable(tmp_path):
    """Fixed at the source too, not only behind classify's backstop: an undecodable report is
    unparseable, which is exactly what TestReportUnparseable means."""
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(test_evidence.TestReportUnparseable):
        test_evidence.parse_pytest_json_counts(bad)

    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(test_evidence.TestReportUnparseable):
        test_evidence.parse_junit_xml_counts(bad_xml)


# --- fresh checkout: the mode that reproduces CI's checkout state ------------------------------
#
# Backlog item 45 (2026-07-29-fresh-checkout-test-mode). A test that read gitignored evidence under
# `.ai-runs/plan-review/` passed EIGHT local suite runs and reddened all three CI jobs. Every one of
# those local runs was structurally incapable of catching it, because they all ran against a tree
# carrying local untracked evidence. These tests pin the property that makes the mode worth having:
# the gate sees exactly what a fresh clone sees, and it refuses rather than quietly running weaker.


def test_fresh_checkout_hides_gitignored_runtime_state_from_the_gate(tmp_path):
    """The defect class itself: a command that reads a gitignored file passes in place and fails
    fresh."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("build/\n*.pyc\n.ai-runs/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "ignore .ai-runs")
    (repo / ".ai-runs" / "plan-review").mkdir(parents=True)
    (repo / ".ai-runs" / "plan-review" / "log.md").write_text("local only\n", encoding="utf-8")

    command = "test -f .ai-runs/plan-review/log.md"
    in_place = test_evidence.run_and_record(
        repo, command=command, command_source="explicit-flag",
        report_path=None, report_format=None, label="in-place",
    )
    assert in_place[1] == 0, "the evidence is present locally, so an in-place run passes"

    fresh_record_path, fresh_exit = test_evidence.run_and_record(
        repo, command=command, command_source="explicit-flag",
        report_path=None, report_format=None, label="fresh", fresh_checkout=True,
    )
    assert fresh_exit != 0, "a fresh checkout must not see gitignored runtime state"
    record = json.loads(fresh_record_path.read_text(encoding="utf-8"))
    assert record["freshCheckout"]["method"] == test_evidence.FRESH_CHECKOUT_METHOD
    assert test_evidence.record_is_fresh_checkout(record) is True


def test_fresh_checkout_carries_uncommitted_and_untracked_work(tmp_path):
    """It must test what you are about to push, not just HEAD: a working-tree edit and a new
    untracked-but-not-ignored test file are both things a fresh clone gets once you commit."""
    repo = _repo(tmp_path)
    (repo / "src.py").write_text("value = 99\n", encoding="utf-8")
    (repo / "new_test.py").write_text("marker\n", encoding="utf-8")

    record_path, exit_code = test_evidence.run_and_record(
        repo,
        command="grep -q 'value = 99' src.py && test -f new_test.py",
        command_source="explicit-flag",
        report_path=None,
        report_format=None,
        label="fresh",
        fresh_checkout=True,
    )
    assert exit_code == 0
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["freshCheckout"]["appliedWorkingTreeDiff"] is True
    assert record["freshCheckout"]["copiedUntracked"] == 1


def test_fresh_checkout_leaves_the_real_tree_and_worktree_list_untouched(tmp_path):
    """A gate that can mangle the operator's checkout is not a gate anybody runs twice."""
    repo = _repo(tmp_path)
    (repo / "dirty.py").write_text("x = 1\n", encoding="utf-8")
    # Baseline AFTER a plain run, so the records directory every run creates is already accounted
    # for and the comparison is about what the fresh mode did, not about `.ai-runs/` existing.
    _write_run(repo, command="true")
    before_status = _git(repo, "status", "--porcelain")
    before_worktrees = _git(repo, "worktree", "list")

    test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=None, report_format=None, label="fresh", fresh_checkout=True,
    )

    assert _git(repo, "status", "--porcelain") == before_status
    assert _git(repo, "worktree", "list") == before_worktrees


def test_fresh_checkout_reads_the_report_the_fresh_run_actually_wrote(tmp_path):
    """The report lives in the throwaway tree. Hashing the project copy instead would silently
    vouch for whatever an earlier in-place run left behind."""
    repo = _repo(tmp_path)
    report = repo / "junit.xml"
    stale = (
        '<testsuites><testsuite name="stale" errors="0" failures="0" skipped="0" '
        'tests="1"></testsuite></testsuites>'
    )
    report.write_text(stale, encoding="utf-8")

    command = (
        "printf '<testsuites><testsuite name=\"p\" errors=\"0\" failures=\"0\" "
        "skipped=\"0\" tests=\"7\"></testsuite></testsuites>' > junit.xml"
    )
    record_path, exit_code = test_evidence.run_and_record(
        repo, command=command, command_source="explicit-flag",
        report_path=report, report_format="junit-xml", label="fresh", fresh_checkout=True,
    )
    assert exit_code == 0
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "reportError" not in record
    assert record["counts"]["collected"] == 7, "counts came from the fresh run, not the stale copy"
    assert report.read_text(encoding="utf-8") == stale, "the project copy was never overwritten"


def test_fresh_checkout_rejects_a_committed_report_the_command_never_wrote(tmp_path):
    """Codex R1 P2. Checking out a worktree stamps every file with the current time, so a report
    COMMITTED to the repo would sail past the mtime guard and let `true` record counts it never
    produced. The fresh tree's copy is deleted before the command runs."""
    repo = _repo(tmp_path)
    report = repo / "junit.xml"
    report.write_text(
        '<testsuites><testsuite name="committed" errors="0" failures="0" skipped="0" '
        'tests="3"></testsuite></testsuites>',
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "commit a junit report")

    record_path, exit_code = test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=report, report_format="junit-xml", label="fresh", fresh_checkout=True,
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert exit_code != 0, "a green command that wrote no report must not read as a clean run"
    assert "does not exist after the run" in record["reportError"]
    assert record["counts"]["source"] == test_evidence.COUNTS_SOURCE_EXIT_CODE_ONLY
    assert test_evidence.classify_test_run_evidence(repo)[0] == "invalid"


def test_fresh_checkout_record_still_describes_the_real_tree(tmp_path):
    """The digest measures exactly the files a fresh checkout contains, so a fresh record must
    classify `current` against the real project."""
    repo = _repo(tmp_path)
    record_path, _ = test_evidence.run_and_record(
        repo, command="true", command_source="explicit-flag",
        report_path=None, report_format=None, label="fresh", fresh_checkout=True,
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["git"]["treeDigest"] == test_evidence.non_ignored_tree_digest(
        repo, record["git"]["excludedPaths"]
    )
    assert test_evidence.classify_test_run_evidence(repo)[0] == "current"


def test_fresh_checkout_carry_paths_symlink_out_of_tree_dependencies(tmp_path):
    """Without this the mode is unusable: a fresh worktree has no .venv/ and no node_modules/, both
    gitignored, both installed out-of-tree by CI."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("build/\n*.pyc\nvendor/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "ignore vendor")
    (repo / "vendor" / "bin").mkdir(parents=True)
    (repo / "vendor" / "bin" / "tool").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    record_path, exit_code = test_evidence.run_and_record(
        repo, command="test -f vendor/bin/tool", command_source="explicit-flag",
        report_path=None, report_format=None, label="fresh",
        fresh_checkout=True, carry_paths=["vendor"],
    )
    assert exit_code == 0
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["freshCheckout"]["carriedPaths"] == ["vendor"]


def test_carried_dependencies_stay_invisible_to_git_inside_the_fresh_tree(tmp_path):
    """Regression. Carrying a directory as ONE symlink made it visible to git: a `.gitignore` entry
    written `vendor/` matches directories only, and a symlink is not a directory, so the carried
    path showed up as an untracked file and changed the very tree this mode holds fixed."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("build/\n*.pyc\nvendor/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "ignore vendor")
    (repo / "vendor").mkdir()
    (repo / "vendor" / "lib.txt").write_text("dependency\n", encoding="utf-8")

    # The command runs INSIDE the throwaway tree, so its own `git status` is the assertion: the
    # carried dependency must be there, and git must still see a clean tree.
    record_path, exit_code = test_evidence.run_and_record(
        repo,
        command='test -f vendor/lib.txt && test -z "$(git status --porcelain)"',
        command_source="explicit-flag",
        report_path=None,
        report_format=None,
        label="fresh",
        fresh_checkout=True,
        carry_paths=["vendor"],
    )
    assert exit_code == 0, "the carried dependency leaked into git's view of the fresh tree"
    assert json.loads(record_path.read_text(encoding="utf-8"))["freshCheckout"]["carriedPaths"] == [
        "vendor"
    ]


def test_two_fresh_checkouts_of_one_repo_can_overlap(tmp_path):
    """A worktree's directory BASENAME is its id under `.git/worktrees/`, so a fixed name would
    make the second concurrent fresh run fail with 'already exists'."""
    repo = _repo(tmp_path)
    with test_evidence.fresh_checkout_tree(repo) as first:
        with test_evidence.fresh_checkout_tree(repo) as second:
            assert first.root != second.root
            assert (first.root / "src.py").exists()
            assert (second.root / "src.py").exists()
    assert _git(repo, "worktree", "list").count("\n") == 0, "both worktrees were cleaned up"


def test_fresh_checkout_refuses_to_carry_a_path_git_does_not_ignore(tmp_path):
    """carryPaths is for out-of-tree dependencies. Carrying something a real clone WOULD have puts
    a file in the fresh tree that CI has no reason to hold, which is this defect class inverted."""
    repo = _repo(tmp_path)
    (repo / "scratch").mkdir()
    (repo / "scratch" / "note.txt").write_text("untracked but not ignored\n", encoding="utf-8")
    with pytest.raises(test_evidence.FreshCheckoutUnavailable):
        test_evidence.run_and_record(
            repo, command="true", command_source="explicit-flag",
            report_path=None, report_format=None, label="fresh",
            fresh_checkout=True, carry_paths=["scratch"],
        )


def test_fresh_checkout_refuses_to_carry_tracked_content(tmp_path):
    """Symlinking tracked content back to the working copy would reintroduce exactly the
    divergence the mode removes, so it fails closed instead."""
    repo = _repo(tmp_path)
    with pytest.raises(test_evidence.FreshCheckoutUnavailable):
        test_evidence.run_and_record(
            repo, command="true", command_source="explicit-flag",
            report_path=None, report_format=None, label="fresh",
            fresh_checkout=True, carry_paths=["src.py"],
        )


@pytest.mark.parametrize("carry", ["/etc", "../escape"])
def test_fresh_checkout_refuses_carry_paths_outside_the_project(tmp_path, carry):
    repo = _repo(tmp_path)
    with pytest.raises(test_evidence.FreshCheckoutUnavailable):
        test_evidence.run_and_record(
            repo, command="true", command_source="explicit-flag",
            report_path=None, report_format=None, label="fresh",
            fresh_checkout=True, carry_paths=[carry],
        )


def test_fresh_checkout_refuses_rather_than_running_in_place(tmp_path):
    """No silent downgrade. A fresh-checkout run that cannot be set up must raise, never hand back
    an in-place green under the stronger label."""
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    _git(unborn, "init", "-q", "-b", "main")
    (unborn / "src.py").write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(test_evidence.FreshCheckoutUnavailable):
        test_evidence.run_and_record(
            unborn, command="true", command_source="explicit-flag",
            report_path=None, report_format=None, label="fresh", fresh_checkout=True,
        )
    assert not list((unborn / test_evidence.TEST_RUN_DIR).glob("*-test-run.json")), (
        "a refused fresh run must not leave a record claiming anything ran"
    )


def test_in_place_records_carry_no_fresh_checkout_claim(tmp_path):
    repo = _repo(tmp_path)
    record_path = _write_run(repo, command="true")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert "freshCheckout" not in record
    assert test_evidence.record_is_fresh_checkout(record) is False


# --- adapter knob + the pre-push surface -------------------------------------------------------


def test_fresh_checkout_config_defaults_off_and_rejects_malformed(tmp_path):
    """Absent-stays-absent: an adopter whose suite needs an undeclared gitignored dependency tree
    must not have the mode turned on under them."""
    from tautline_methodology import cli

    assert cli.test_evidence_config({})["freshCheckout"] == {"default": False, "carryPaths": []}
    assert cli.test_evidence_config({"testEvidence": {}})["freshCheckout"]["default"] is False

    on = {"testEvidence": {"freshCheckout": {"default": True, "carryPaths": [" .venv "]}}}
    assert cli.test_evidence_config(on)["freshCheckout"] == {
        "default": True,
        "carryPaths": [".venv"],
    }

    for bad in (
        {"testEvidence": {"freshCheckout": "yes"}},
        {"testEvidence": {"freshCheckout": {"default": "yes"}}},
        {"testEvidence": {"freshCheckout": {"carryPaths": ".venv"}}},
        {"testEvidence": {"freshCheckout": {"carryPaths": [""]}}},
    ):
        with pytest.raises(SystemExit):
            cli.test_evidence_config(bad)


def test_framework_adapter_opts_into_fresh_checkout():
    """Tautline's own gate is where this defect was produced; dogfooding it is the point."""
    from tautline_methodology import cli

    adapter = json.loads(
        (Path(__file__).resolve().parents[1] / ".tautline" / "adapter.json").read_text(
            encoding="utf-8"
        )
    )
    fresh = cli.test_evidence_config(adapter)["freshCheckout"]
    assert fresh["default"] is True
    assert ".venv" in fresh["carryPaths"]


def test_prepush_evidence_line_reports_the_mode_and_names_the_configured_remedy(tmp_path):
    """`current` is not the whole answer at a push boundary: an in-place green in a lane that
    defaults to fresh is exactly the evidence that let a red commit through."""
    from tautline_methodology import cli

    repo = _repo(tmp_path)
    _write_run(repo, command="true")

    lines = cli.test_run_evidence_lines(repo, {})
    assert any("freshCheckout=no" in line for line in lines)
    assert not any(line.startswith("test_run_evidence_next:") for line in lines)

    fresh_lane = {"testEvidence": {"freshCheckout": {"default": True}}}
    lines = cli.test_run_evidence_lines(repo, fresh_lane)
    remedy = [line for line in lines if line.startswith("test_run_evidence_next:")]
    assert remedy and "--fresh-checkout" in remedy[0]


def test_prepush_evidence_remedy_names_fresh_checkout_when_there_is_no_record(tmp_path):
    """The remedy must be the command the lane actually wants run, or the operator produces
    evidence the next boundary tells them to redo."""
    from tautline_methodology import cli

    repo = _repo(tmp_path)
    fresh_lane = {"testEvidence": {"freshCheckout": {"default": True}}}
    lines = cli.test_run_evidence_lines(repo, fresh_lane)
    assert lines[0].startswith("test_run_evidence: missing")
    assert "tautline test-run --fresh-checkout --target ." in lines[-1]


def test_evidence_line_never_raises_on_a_malformed_fresh_checkout_knob(tmp_path):
    """A report-only boundary printer must degrade to a missing remedy, never to a broken
    lane-start."""
    from tautline_methodology import cli

    repo = _repo(tmp_path)
    lines = cli.test_run_evidence_lines(repo, {"testEvidence": {"freshCheckout": "nope"}})
    assert lines[0].startswith("test_run_evidence: missing")
