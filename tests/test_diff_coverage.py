"""Quality rec #7 Part 2: diff-scoped coverage gate.

Whole-repo `fail_under` (rec #7 Part 1) is a coarse backstop -- a large untested module barely moves
the aggregate, so new code can ship unexercised with the repo gate green (FM1). The `diff-coverage-check`
subcommand measures only the NEW lines a change adds (git diff) against a coverage report and fails when
their coverage is below coverageFloor.newCodeMinPct, blocking only when enforcement is block.
"""

import argparse
import json

import pytest

SAMPLE_DIFF = """diff --git a/src/foo.py b/src/foo.py
index abc..def 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,0 +11,2 @@
+    new_line_eleven
+    new_line_twelve
@@ -20,1 +22,1 @@
-    old_twenty_two
+    changed_twenty_two
"""

NEW_FILE_DIFF = """diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,3 @@
+line_one
+line_two
+line_three
"""


def _ns(**kw):
    base = dict(project=None, target=None, base=None, report=None, min_pct=None, diff_file=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_parse_diff_added_lines(cli):
    added = cli.parse_diff_added_lines(SAMPLE_DIFF)
    assert added == {"src/foo.py": {11, 12, 22}}


def test_parse_diff_added_lines_new_file(cli):
    assert cli.parse_diff_added_lines(NEW_FILE_DIFF) == {"src/new.py": {1, 2, 3}}


def test_parse_coverage_json_lines(cli):
    report = {"files": {"src/foo.py": {"executed_lines": [11, 22], "missing_lines": [12]}}}
    assert cli.parse_coverage_json_lines(report) == {"src/foo.py": {11, 22}}


def test_parse_lcov_lines(cli):
    lcov = "SF:src/foo.js\nDA:11,1\nDA:12,0\nDA:22,3\nend_of_record\n"
    assert cli.parse_lcov_lines(lcov) == {"src/foo.js": {11, 22}}


def test_diff_coverage_findings_below_floor(cli):
    added = {"src/foo.py": {11, 12, 22}}
    executed = {"src/foo.py": {11, 22}}
    f = cli.diff_coverage_findings(added, executed, 80)
    assert f["total_new_lines"] == 3
    assert f["covered_new_lines"] == 2
    assert f["below_floor"] is True
    assert f["files"][0]["uncovered"] == [12]


def test_new_untested_file_absent_from_report_is_zero_pct(cli):
    # A new module that never appears in the coverage report must be treated as 0% -- not silently
    # passed for "not appearing." This is the precise greenfield fail-open the gate closes.
    f = cli.diff_coverage_findings({"src/new.py": {1, 2, 3}}, {}, 80)
    assert f["pct"] == 0.0 and f["below_floor"] is True


def test_non_source_files_do_not_count(cli):
    f = cli.diff_coverage_findings({"README.md": {1, 2}, "docs/x.json": {3}}, {}, 80)
    assert f["total_new_lines"] == 0 and f["below_floor"] is False and f["pct"] == 100.0


def test_fully_covered_passes(cli):
    f = cli.diff_coverage_findings({"a.py": {1, 2}}, {"a.py": {1, 2, 3}}, 100)
    assert f["below_floor"] is False and f["pct"] == 100.0


def test_coverage_path_suffix_match(cli):
    # diff path is repo-relative; coverage report key may be absolute/prefixed.
    f = cli.diff_coverage_findings({"src/a.py": {1}}, {"/build/src/a.py": {1}}, 100)
    assert f["below_floor"] is False


def test_normalize_coverage_floor(cli):
    with pytest.raises(SystemExit):
        cli.normalize_coverage_floor({"coverageFloor": {"enforcement": "loud"}})
    with pytest.raises(SystemExit):
        cli.normalize_coverage_floor({"coverageFloor": {"newCodeMinPct": 150}})
    with pytest.raises(SystemExit):
        cli.normalize_coverage_floor({"coverageFloor": {"newCodeMinPct": "x"}})
    cfg = cli.normalize_coverage_floor({})
    assert cfg["enforcement"] == "warn" and cfg["newCodeMinPct"] == 80
    assert cfg["coverageReport"] == "coverage.json" and cfg["diffBase"] == "origin/main"


def test_handler_warn_mode_reports_but_does_not_block(cli, tmp_path, capsys):
    diff = tmp_path / "d.diff"
    diff.write_text(SAMPLE_DIFF)
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"files": {"src/foo.py": {"executed_lines": [11]}}}))
    rc = cli.diff_coverage_check(_ns(target=tmp_path, diff_file=diff, report=report, min_pct=80))
    out = capsys.readouterr().out
    assert rc == 0  # warn default never blocks
    assert "status=below_floor" in out


def test_handler_block_mode_fails_below_floor(cli, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_COVERAGE_FLOOR", {**cli.DEFAULT_COVERAGE_FLOOR, "enforcement": "block"})
    diff = tmp_path / "d.diff"
    diff.write_text(SAMPLE_DIFF)
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"files": {"src/foo.py": {"executed_lines": [11]}}}))
    rc = cli.diff_coverage_check(_ns(target=tmp_path, diff_file=diff, report=report, min_pct=80))
    assert rc == 1


def test_handler_block_mode_passes_when_covered(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_COVERAGE_FLOOR", {**cli.DEFAULT_COVERAGE_FLOOR, "enforcement": "block"})
    diff = tmp_path / "d.diff"
    diff.write_text(SAMPLE_DIFF)
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"files": {"src/foo.py": {"executed_lines": [11, 12, 22]}}}))
    rc = cli.diff_coverage_check(_ns(target=tmp_path, diff_file=diff, report=report, min_pct=80))
    assert rc == 0


def test_handler_missing_report_blocks_in_block_mode(cli, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_COVERAGE_FLOOR", {**cli.DEFAULT_COVERAGE_FLOOR, "enforcement": "block"})
    diff = tmp_path / "d.diff"
    diff.write_text(SAMPLE_DIFF)
    rc = cli.diff_coverage_check(_ns(target=tmp_path, diff_file=diff, report=tmp_path / "nope.json", min_pct=80))
    assert rc == 1
    assert "not found" in capsys.readouterr().out


def test_missing_diff_file_skips_not_crashes(cli, tmp_path, capsys):
    # P2 fix: a --diff-file path that does not exist must skip cleanly, not raise FileNotFoundError.
    rc = cli.diff_coverage_check(_ns(target=tmp_path, diff_file=tmp_path / "nope.diff", report=tmp_path / "c.json"))
    assert rc == 0
    assert "not found" in capsys.readouterr().out


def test_corrupt_coverage_report_treated_as_missing(cli, tmp_path, capsys, monkeypatch):
    # P2 fix: a truncated/corrupt coverage report must not crash with a JSONDecodeError traceback.
    monkeypatch.setattr(cli, "DEFAULT_COVERAGE_FLOOR", {**cli.DEFAULT_COVERAGE_FLOOR, "enforcement": "block"})
    diff = tmp_path / "d.diff"
    diff.write_text(SAMPLE_DIFF)
    report = tmp_path / "coverage.json"
    report.write_text('{"files": {"src/foo.py": {"executed_lines": [1')  # truncated
    rc = cli.diff_coverage_check(_ns(target=tmp_path, diff_file=diff, report=report, min_pct=80))
    assert rc == 1  # corrupt == cannot prove coverage -> block in block mode
    assert "unreadable" in capsys.readouterr().out
