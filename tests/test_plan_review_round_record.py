"""Item 108 WS1: the durable per-round plan-review record, WRITE PATH ONLY.

Every reviewer invocation appends exactly one committed, append-only record under
``<planning_source_root>/.plan-reviews/rounds/<manifest-identity>/`` -- the foundation the
single mutable manifest could never be. WS1 is dual-write: nothing here changes what any
existing budget reader answers, and every pre-existing test passes unmodified.

Scope note (108-R4-P2-2): the correction WRITER ships here and is covered here; the
correction's SPEND EFFECT (raise-only application, `test_a_correction_record_raises_spend_and
_never_lowers_it`) belongs to WS2's record-backed reader and is deliberately absent from this
file.
"""

import json
import os
import re
import shutil
import time
from pathlib import Path

from tautline_methodology import plan_round_record

from test_plan_review_cli import (
    PLAN_REL,
    SOURCE_ROOT,
    _manifest_path,
    _prepare_target,
    _run_cli,
    _stdout_path,
    _write_plan,
    _write_review_script,
)
from test_plan_review_convergence import CLEAN, NOTE, _blocked, _mutate_plan, _run_round

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = (REPO_ROOT / "src" / "tautline_methodology" / "cli.py").read_text(encoding="utf-8")

ROUND_SCHEMA = "tautline-plan-review-round/v1"


def _rounds_dir(target: Path) -> Path:
    return target / SOURCE_ROOT / ".plan-reviews" / "rounds" / "test-plan"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline(rounds: Path) -> dict:
    return _load(rounds / "000-baseline.json")


def _appended(rounds: Path) -> list[Path]:
    return sorted(path for path in rounds.glob("*.json") if path.name != "000-baseline.json")


def _of_kind(rounds: Path, kind: str) -> list[tuple[Path, dict]]:
    records = []
    for path in _appended(rounds):
        data = _load(path)
        if data.get("kind") == kind:
            records.append((path, data))
    return records


def _finalize(home, adapter_root, target, adapter, log_path, review_round, *verdict_args):
    return _run_cli(
        "finalize-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        str(log_path),
        "--round",
        review_round,
        "--model",
        "codex-test",
        *verdict_args,
        home=home,
        adapter_root=adapter_root,
    )


def test_every_reviewer_invocation_appends_one_committed_round_record(tmp_path):
    """T1.1: one invocation, one record -- fields straight from the run it describes."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr

    rounds = _rounds_dir(target)
    invocations = _of_kind(rounds, "reviewer-invocation")
    assert len(invocations) == 1
    assert len(_appended(rounds)) == 1

    meta = _load(_stdout_path(r1.stdout, "plan_review_run_meta"))
    record = invocations[0][1]
    assert record["schema"] == ROUND_SCHEMA
    assert record["charged"] is True
    assert record["wrapper_exit_code"] == 0
    assert record["source"] == "run"
    assert record["nonce"] == meta["log_frame_nonce"]
    assert record["log_sha256"] == meta["log_sha256"]
    assert record["plan_path"] == PLAN_REL.as_posix()
    assert record["plan_identity"] == "test-plan"
    assert record["plan_content_sha256"] == meta["plan_content_sha256"]
    assert record["declared_round"] == "R1"
    assert record["reviewer"] == "codex"
    assert record["reviewer_model"] == "codex-test"

    r2 = _run_round(home, adapter_root, target, adapter, "R2")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert len(_of_kind(rounds, "reviewer-invocation")) == 2


def test_a_failed_wrapper_run_appends_an_uncharged_record(tmp_path):
    """T1.1: failures are audit facts -- recorded, never charged."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    _write_review_script(
        target, "printf '## Findings\\nwrapper died before reviewing\\n'\nexit 3\n"
    )

    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 3, r1.stdout + r1.stderr

    invocations = _of_kind(_rounds_dir(target), "reviewer-invocation")
    assert len(invocations) == 1
    record = invocations[0][1]
    assert record["wrapper_exit_code"] == 3
    assert record["charged"] is False
    assert record["source"] == "run"


def test_round_records_live_under_the_committed_reviews_root_not_ai_runs(tmp_path):
    """T1.1 / decision DA: records ride the manifests' commit discipline, not the gitignored
    lane-local runs directory that lost the parked lane's 4th P1."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr

    record_path = _stdout_path(r1.stdout, "plan_review_round_record")
    baseline_path = _stdout_path(r1.stdout, "plan_review_round_baseline")
    reviews_root = target / SOURCE_ROOT / ".plan-reviews"
    assert record_path.is_relative_to(reviews_root / "rounds")
    assert baseline_path.is_relative_to(reviews_root / "rounds")
    assert not record_path.is_relative_to(target / ".ai-runs")

    ai_runs = target / ".ai-runs"
    for path in ai_runs.rglob("*.json"):
        assert ROUND_SCHEMA not in path.read_text(encoding="utf-8"), path


def test_round_record_identity_survives_basename_collisions(tmp_path):
    """T1.1: 38 `plan.md`s cannot share a record directory -- the collision-aware manifest
    identity keys the path, never the bare stem."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    rel_a = SOURCE_ROOT / "item-a" / "plan.md"
    rel_b = SOURCE_ROOT / "item-b" / "plan.md"
    _write_plan(target, rel_a, summary="Item A ships its reviewed behavior safely.")
    _write_plan(target, rel_b, summary="Item B ships its reviewed behavior safely.")

    results = {}
    for rel in (rel_a, rel_b):
        run = _run_cli(
            "run-plan-review",
            "--project",
            str(adapter),
            "--target",
            str(target),
            "--plan",
            rel.as_posix(),
            "--round",
            "R1",
            "--model",
            "codex-test",
            home=home,
            adapter_root=adapter_root,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        results[rel] = _stdout_path(run.stdout, "plan_review_round_record")

    dir_a = results[rel_a].parent
    dir_b = results[rel_b].parent
    assert dir_a != dir_b
    for rel, directory in ((rel_a, dir_a), (rel_b, dir_b)):
        assert (directory / "000-baseline.json").is_file()
        record = _load(results[rel])
        assert record["plan_path"] == rel.as_posix()


def test_a_second_baseline_write_is_refused_and_reread(tmp_path):
    """T1.1: the baseline is create-once with O_EXCL semantics; a later writer whose inputs
    changed re-reads the record on disk instead of absorbing new history into it."""
    rounds = tmp_path / "rounds"
    first = plan_round_record.render_baseline(
        plan_identity="member",
        plan_path="member.md",
        prerecord_count=1,
        prerecord_log_sha256s=["aaa"],
    )
    written, created = plan_round_record.write_baseline_once(rounds, first)
    assert created is True
    on_disk = (rounds / "000-baseline.json").read_bytes()

    second = plan_round_record.render_baseline(
        plan_identity="member",
        plan_path="member.md",
        prerecord_count=9,
        prerecord_log_sha256s=["bbb", "ccc"],
    )
    reread, created_again = plan_round_record.write_baseline_once(rounds, second)
    assert created_again is False
    assert reread == written
    assert (rounds / "000-baseline.json").read_bytes() == on_disk

    # The same refusal through the CLI: R2's launch snapshot (which now sees R1's meta) must
    # not rewrite the baseline R1 created empty.
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    assert _run_round(home, adapter_root, target, adapter, "R1").returncode == 0
    baseline_bytes = (_rounds_dir(target) / "000-baseline.json").read_bytes()
    assert _run_round(home, adapter_root, target, adapter, "R2").returncode == 0
    assert (_rounds_dir(target) / "000-baseline.json").read_bytes() == baseline_bytes
    assert _baseline(_rounds_dir(target))["prerecord_log_sha256s"] == []


def test_the_baseline_set_not_timestamps_decides_cutover_membership(tmp_path):
    """T1.1 / R2 P2: clocks differ across worktrees; the enumerated digest set does not.

    A pre-record meta whose mtime is pushed into the FUTURE is still pre-cutover, because it
    is in the baseline's enumerated set -- and the post-cutover run is not, whatever any clock
    says.
    """
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    meta1 = _load(_stdout_path(r1.stdout, "plan_review_run_meta"))

    # Simulate a lane whose history predates the record writer: the metas exist, the records
    # never did. Then make every timestamp lie.
    shutil.rmtree(_rounds_dir(target))
    future = time.time() + 10**6
    for prefix in ("plan_review_run_log", "plan_review_run_meta"):
        os.utime(_stdout_path(r1.stdout, prefix), (future, future))

    r2 = _run_round(home, adapter_root, target, adapter, "R2")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    meta2 = _load(_stdout_path(r2.stdout, "plan_review_run_meta"))

    baseline = _baseline(_rounds_dir(target))
    assert baseline["prerecord_log_sha256s"] == [meta1["log_sha256"]]
    assert baseline["prerecord_count"] == 1
    assert meta2["log_sha256"] not in baseline["prerecord_log_sha256s"]
    invocations = _of_kind(_rounds_dir(target), "reviewer-invocation")
    assert [record["log_sha256"] for _path, record in invocations] == [meta2["log_sha256"]]


def test_the_first_post_cutover_run_is_counted_exactly_once(tmp_path):
    """108-R4-P1-1: the baseline's inputs are snapshotted BEFORE the current run's meta exists,
    so the cutover marker can never absorb the run its own invocation record counts."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    meta1 = _load(_stdout_path(r1.stdout, "plan_review_run_meta"))
    shutil.rmtree(_rounds_dir(target))

    r2 = _run_round(home, adapter_root, target, adapter, "R2")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    meta2 = _load(_stdout_path(r2.stdout, "plan_review_run_meta"))

    baseline = _baseline(_rounds_dir(target))
    # The record contents alone prove single-counting: the current run's digest is OUTSIDE the
    # absorbed set, and its invocation record exists -- one count, from one source.
    assert meta2["log_sha256"] not in baseline["prerecord_log_sha256s"]
    assert baseline["prerecord_log_sha256s"] == [meta1["log_sha256"]]
    assert baseline["prerecord_count"] == 1
    invocations = _of_kind(_rounds_dir(target), "reviewer-invocation")
    assert len(invocations) == 1
    assert invocations[0][1]["log_sha256"] == meta2["log_sha256"]
    assert invocations[0][1]["charged"] is True


def test_finalize_appends_a_classification_record_instead_of_mutating_the_run_record(tmp_path):
    """T1.2: the bind APPENDS; the invocation record stays byte-identical."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    invocation_path = _stdout_path(r1.stdout, "plan_review_round_record")
    invocation_bytes = invocation_path.read_bytes()

    finalize = _finalize(
        home,
        adapter_root,
        target,
        adapter,
        _stdout_path(r1.stdout, "plan_review_run_log"),
        "R1",
        *CLEAN,
    )
    assert finalize.returncode == 0, finalize.stdout + finalize.stderr

    assert invocation_path.read_bytes() == invocation_bytes
    classifications = _of_kind(_rounds_dir(target), "round-classification")
    assert len(classifications) == 1
    record = classifications[0][1]
    invocation = _load(invocation_path)
    assert record["nonce"] == invocation["nonce"]
    assert record["log_sha256"] == invocation["log_sha256"]
    assert record["verdict"] == "clean"
    assert record["unresolved_critical_count"] == 0
    assert record["classified_findings_count"] == 0
    assert "origin" not in record
    manifest = _load(_manifest_path(target))
    assert record["plan_content_sha256"] == manifest["plan_content_sha256"]


def test_a_round_record_is_never_rewritten_by_a_later_round_or_finalize(tmp_path):
    """T1.2, the append-only law: a second round plus its finalize only ever ADDS files."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *CLEAN)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    rounds = _rounds_dir(target)
    before = {path: path.read_bytes() for path in rounds.glob("*.json")}
    assert len(before) == 3  # baseline + invocation + classification

    r2 = _run_round(home, adapter_root, target, adapter, "R2", *CLEAN)
    assert r2.returncode == 0, r2.stdout + r2.stderr

    after = {path: path.read_bytes() for path in rounds.glob("*.json")}
    for path, content in before.items():
        assert after[path] == content, f"{path} was rewritten"
    assert len(after) == len(before) + 2


def test_an_import_against_a_digestless_floor_follows_one_deterministic_rule(tmp_path):
    """108-R4-P1-2: a floor with nothing enumerable can verify nothing, so the import SPENDS --
    a charged `source: imported` invocation record, referenced by an `imported-unverified`
    classification. Never an uncharged classification for an unknown digest."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *CLEAN)
    assert r1.returncode == 0, r1.stdout + r1.stderr

    # Rebuild the fresh-worktree state: the committed manifest remembers the spend, the lane
    # holds no metas, and no records were ever written. The one surviving log arrives as an
    # import from outside the runs directory.
    log_src = _stdout_path(r1.stdout, "plan_review_run_log")
    meta = _load(_stdout_path(r1.stdout, "plan_review_run_meta"))
    import_rel = Path("imported-evidence") / log_src.name
    import_log = target / import_rel
    import_log.parent.mkdir()
    shutil.copy2(log_src, import_log)
    meta["log_path"] = import_rel.as_posix()
    (target / f"{import_rel.as_posix()}.meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.rmtree(target / ".ai-runs" / "plan-review")
    shutil.rmtree(_rounds_dir(target))
    # `record-plan-review` refuses a log older than the plan, and the round that just ran rewrote
    # the plan: `write_plan_review_manifest` upserts Cross-Model Review Evidence back INTO the plan
    # file as its last act. So the plan's mtime is only tens of milliseconds behind this line --
    # measured at 27ms -- and a bare `touch()` was racing that gap on wall-clock alone. Pin the
    # ordering the way the rest of this file already does, so the scenario under test is the
    # digestless floor rather than the runner's clock and timestamp granularity.
    plan_mtime = (target / PLAN_REL).stat().st_mtime
    os.utime(import_log, (plan_mtime + 60, plan_mtime + 60))

    imported = _run_cli(
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--log",
        import_rel.as_posix(),
        "--review-command",
        meta["review_command"],
        "--reviewer",
        "codex",
        "--model",
        "codex-test",
        "--round",
        "R1",
        "--wrapper-exit-code",
        "0",
        *CLEAN,
        home=home,
        adapter_root=adapter_root,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    rounds = _rounds_dir(target)
    baseline = _baseline(rounds)
    assert baseline["prerecord_count"] == 1
    assert baseline["prerecord_log_sha256s"] == []  # the digestless floor

    invocations = _of_kind(rounds, "reviewer-invocation")
    assert len(invocations) == 1
    invocation = invocations[0][1]
    assert invocation["source"] == "imported"
    assert invocation["charged"] is True
    assert invocation["log_sha256"] == meta["log_sha256"]

    classifications = _of_kind(rounds, "round-classification")
    assert len(classifications) == 1
    classification = classifications[0][1]
    assert classification["origin"] == "imported-unverified"
    assert classification["nonce"] == invocation["nonce"]
    assert classification["log_sha256"] == invocation["log_sha256"]


def test_recovery_guidance_names_the_correction_writer_verb(tmp_path):
    """T1.2: evidence-conflict recovery names the sanctioned append -- and the named verb is
    real, writable, and refuses to lower anything."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1", *_blocked(1))
    assert r1.returncode == 0, r1.stdout + r1.stderr

    # Corrupt the manifest's blocker counts so the R3 convergence check cannot read previous
    # evidence -- the exact conflict whose old remedy was "repair the manifest".
    manifest_path = _manifest_path(target)
    manifest = _load(manifest_path)
    manifest["unresolved_critical_count"] = "unreadable"
    manifest["unresolved_p1_count"] = "unreadable"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    _mutate_plan(target, "4. Fix one blocker, breaking the bound hash.\n")
    r3 = _run_round(
        home, adapter_root, target, adapter, "R3", "--exception-note", NOTE, *_blocked(1)
    )
    assert r3.returncode == 2, r3.stdout + r3.stderr
    assert "append a correction record" in r3.stderr
    assert "tautline record-plan-review" in r3.stderr
    assert re.search(r"--correct\b", r3.stderr)
    assert "repair the manifest" not in r3.stderr

    # The verb it names exists and appends.
    correction = _run_cli(
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--correct",
        "baseline",
        "--correction-note",
        "one pre-record round was burned in a parked worktree and never reached this floor",
        "--raise-prerecord-count-to",
        "5",
        home=home,
        adapter_root=adapter_root,
    )
    assert correction.returncode == 0, correction.stdout + correction.stderr
    record = _load(_stdout_path(correction.stdout, "plan_review_round_record"))
    assert record["kind"] == "correction"
    assert record["corrects"] == "baseline"
    assert record["raise_prerecord_count_to"] == 5
    assert record["note"].startswith("one pre-record round")

    # Corrections raise; nothing lowers anything.
    lowering = _run_cli(
        "record-plan-review",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--plan",
        PLAN_REL.as_posix(),
        "--correct",
        "baseline",
        "--correction-note",
        "attempting to lower the recorded floor must be refused by the writer",
        "--raise-prerecord-count-to",
        "0",
        home=home,
        adapter_root=adapter_root,
    )
    assert lowering.returncode == 1
    assert "corrections raise" in lowering.stderr


# --- T1.3: the append-only law in emitted guidance, repository-wide ---------------------------

FORBIDDEN_REMEDY = re.compile(
    r"(?i)\b(overwrit\w*|regenerat\w*|rewrit\w*|re-record\w*|recreat\w*)\b"
    r"[^.;\n]{0,80}?"
    r"\b(round[ -]records?|baseline record|invocation record|correction record|"
    r"review manifests?|plan-review manifests?|review evidence|\.plan-reviews)"
)
# A match preceded by one of these within 32 characters is a PROHIBITION of the remedy, which
# is the law itself speaking, not a violation of it.
NEGATIONS = ("never", "not ", "no ", "n't", "cannot", "instead of", "without", "forbid")

# Deliberately excluded surfaces, each with the reason it is safe (plan T1.3 requires the
# guard to enumerate them).
EXCLUDED_DIRS = {
    "docs/superpowers/plans": (
        "hash-bound historical review artifacts: every plan here binds its manifest to its "
        "exact content, so the sweep must not rewrite history that evidence still references"
    ),
    "docs/superpowers/plans/.plan-reviews": "recorded review evidence, immutable by the law itself",
}
EXCLUDED_FILES = {
    "src/tautline_methodology/plan_reference.py": (
        "its module docstring DESCRIBES the pre-identity collision defect (manifests that "
        "'overwrite each other's review evidence'); it prescribes nothing"
    ),
}
# Excluded EMITTED surfaces that the pattern cannot see but a reviewer will ask about:
# - cli.py's verdict-format recovery says `rm <run_meta_path>` -- that file is a gitignored
#   lane-local run META whose log recorded no verdict, so it attests nothing; it is neither a
#   committed round record nor a manifest.
# - cli.py's round-3 convergence message says "restore the prior review manifest from its
#   original log if it was LOST" -- restoring a lost file overwrites nothing, and the manifest
#   remains a routinely mutable display surface; what the law forbids is
#   recovery-by-manifest-overwrite.


def _swept_files():
    for root, patterns in (
        ("src", ("*.py",)),
        ("methodology", ("*.md",)),
        ("docs", ("*.md",)),
        ("plugins", ("*.md",)),
    ):
        base = REPO_ROOT / root
        for pattern in patterns:
            for path in sorted(base.rglob(pattern)):
                rel = path.relative_to(REPO_ROOT).as_posix()
                if any(rel.startswith(f"{excluded}/") for excluded in EXCLUDED_DIRS):
                    continue
                if rel in EXCLUDED_FILES:
                    continue
                yield rel, path


def test_no_recovery_instruction_prescribes_overwriting_round_records(tmp_path):
    """T1.3: nothing emitted or documented prescribes overwriting/regenerating a round record
    or a manifest as recovery; the sanctioned remedy is the correction append, by name."""
    violations = []
    for rel, path in _swept_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".py"):
            # Join adjacent string literals first: an emitted message wrapped for E501 must be
            # judged as the one line the lane will actually read, or a negation ("never ...")
            # lands on a different source line than the verb it negates.
            text = re.sub(r'"\s*\n\s*f?"', "", text)
        for number, line in enumerate(text.splitlines(), start=1):
            for match in FORBIDDEN_REMEDY.finditer(line):
                prefix = line[max(0, match.start() - 32) : match.start()].lower()
                if any(token in prefix for token in NEGATIONS):
                    continue
                violations.append(f"{rel}:{number}: {line.strip()[:160]}")
    assert violations == [], "\n".join(violations)

    # The exclusion list must not rot: every enumerated surface still exists and the file-level
    # exclusions still contain the text they were excluded for.
    for excluded in EXCLUDED_DIRS:
        assert (REPO_ROOT / excluded).is_dir(), excluded
    for excluded in EXCLUDED_FILES:
        assert (REPO_ROOT / excluded).is_file(), excluded
    assert "overwrite each other's review evidence" in (
        REPO_ROOT / "src/tautline_methodology/plan_reference.py"
    ).read_text(encoding="utf-8")

    # The positive half: the evidence-conflict recovery emitted by cli.py prescribes the
    # correction APPEND (never the dead manifest-overwrite remedy), and the old wording is gone
    # even across argparse-style adjacent string literals.
    condensed = re.sub(r'"\s*\n\s*f?"', "", CLI_SOURCE)
    assert "append a correction record" in condensed
    assert "tautline record-plan-review --target <lane> --plan <plan> --correct" in condensed
    assert "repair the manifest" not in condensed


def test_record_files_are_plain_data_files_not_executables(tmp_path):
    """Codex R1 P2 (this lineage): O_CREAT without an explicit mode inherits 0o777 & ~umask,
    so records landed executable and git would preserve the bit. Every record file must be a
    plain data file."""
    import os as _os
    import stat as _stat

    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr

    rounds = _rounds_dir(target)
    record_files = list(rounds.rglob("*.json"))
    assert record_files, "expected at least a baseline and an invocation record"
    for record in record_files:
        mode = _stat.S_IMODE(_os.stat(record).st_mode)
        assert mode & 0o111 == 0, f"{record.name} is executable: {oct(mode)}"


def test_a_raise_below_a_prior_correction_is_refused(tmp_path):
    """Codex R2 P2 (this lineage): the raise-only check must compare against the CURRENT floor
    -- baseline plus every prior correction -- or correcting to 5 and then 'raising' to 3
    writes a lower correction and the durable record turns ambiguous for the spend reader."""
    home, adapter_root, target, adapter = _prepare_target(tmp_path)
    r1 = _run_round(home, adapter_root, target, adapter, "R1")
    assert r1.returncode == 0, r1.stdout + r1.stderr

    def _correct(to: int):
        return _run_cli(
            "record-plan-review", "--project", str(adapter), "--target", str(target),
            "--plan", PLAN_REL.as_posix(), "--correct", "baseline",
            "--correction-note", "raise-only floor regression fixture",
            "--raise-prerecord-count-to", str(to),
            home=home, adapter_root=adapter_root,
        )

    first = _correct(5)
    assert first.returncode == 0, first.stdout + first.stderr
    lower = _correct(3)
    assert lower.returncode == 1
    assert "current pre-record floor of 5" in lower.stderr
    higher = _correct(6)
    assert higher.returncode == 0, higher.stdout + higher.stderr
