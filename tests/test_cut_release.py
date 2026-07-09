"""prod-distribution-1/3 (productization): cut-release builds the release boundary — a SHA256
checksums manifest of the distributed artifacts + the signed-tag command — without mutating git refs
by default, so an immutable, verifiable release artifact exists (composes with the auto-update trust
gate / pinned-tag policy).
"""


def test_cut_release_dry_run_lists_checksums_without_writing(run_cli, tmp_path):
    res = run_cli("cut-release", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "cut_release_version:" in res.stdout
    assert "cut_release_tag:" in res.stdout
    # five artifacts, each a 64-hex sha256
    import re

    shas = re.findall(r"^  ([0-9a-f]{64})  (\S+)$", res.stdout, re.MULTILINE)
    assert len(shas) >= 5
    assert any(p == "bin/tautline" for _, p in shas)
    # Extracted package modules are distributed implementation and must stay
    # inside the immutable release boundary alongside the bin entrypoint.
    assert any(p == "src/minervit_methodology/__init__.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/adapter.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/chat.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/deploy.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/gitutil.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/ghutil.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/guards.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/names.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/paths.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/profiles.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/releases.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/telemetry.py" for _, p in shas)
    assert any(p == "src/minervit_methodology/util.py" for _, p in shas)
    assert any(p == "methodology/policy-phrases.json" for _, p in shas)
    assert "cut_release_dry_run: no files written" in res.stdout


def test_cut_release_dry_run_writes_nothing_and_creates_no_tag(run_cli):
    # --dry-run must not write the checksum manifest or create a git tag (no repo mutation).
    res = run_cli("cut-release", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "no files written, no tag created" in res.stdout
    assert "cut_release_written:" not in res.stdout
    assert "cut_release_tagged:" not in res.stdout
