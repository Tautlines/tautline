"""fleet-lease verb: claim/renew/release/takeover with enforcement-aware overlap."""

import io
import json
import subprocess
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

from test_fleet_state import _git, _init_repo

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ADAPTER = REPO_ROOT / "tests" / "fixtures" / "generated-adapter-example-saas.json"


def _fleet_repo(tmp_path, *, enforcement="block"):
    repo = tmp_path / "repo"
    _init_repo(repo)
    adapter = json.loads(FIXTURE_ADAPTER.read_text(encoding="utf-8"))
    adapter["fleet"] = {"enforcement": enforcement}
    (repo / ".tautline.json").write_text(json.dumps(adapter), encoding="utf-8")
    return repo


def _worktree(repo, tmp_path, name):
    wt = tmp_path / name
    _git(repo, "worktree", "add", "-q", str(wt), "-b", name)
    # The adapter marker is untracked in the main worktree; every lane needs its own copy.
    (wt / ".tautline.json").write_text(
        (repo / ".tautline.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return wt


def _cleanup_wt(repo, wt):
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
        check=False, capture_output=True,
    )


def _leases(repo):
    return sorted((repo / ".git" / "tautline-fleet" / "leases").glob("*.json"))


def test_claim_writes_lease_and_reports(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    res = run_cli(
        "fleet-lease", "claim", "--target", str(repo), "--globs", "src/**,docs/a.md"
    )
    assert res.returncode == 0, res.stderr
    assert "fleet_lease: claimed" in res.stdout
    leases = _leases(repo)
    assert len(leases) == 1
    lease = json.loads(leases[0].read_text(encoding="utf-8"))
    assert lease["globs"] == ["src/**", "docs/a.md"]
    assert lease["schema"] == "tautline-fleet-lease/v1"
    assert lease["ttl_minutes"] == 240


def test_overlapping_claim_blocked_under_block_enforcement(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        first = run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        assert first.returncode == 0
        second = run_cli(
            "fleet-lease", "claim", "--target", str(wt), "--globs", "src/pkg/**"
        )
        assert second.returncode != 0
        assert "fleet_lease_conflict:" in second.stdout
        # The instruction must be runnable AS PRINTED: --target (the claim may be
        # driven from another cwd) and --operator-note (the conflicting lease is
        # live and foreign, so both escape paths are operator-owned).
        assert "fleet_lease_instruction:" in second.stdout
        assert second.stdout.count("--operator-note") == 2
        assert f"--target {wt}" in second.stdout
        assert len(_leases(repo)) == 1
    finally:
        _cleanup_wt(repo, wt)


def test_overlapping_claim_allowed_and_logged_under_observe(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path, enforcement="observe")
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        second = run_cli(
            "fleet-lease", "claim", "--target", str(wt), "--globs", "src/pkg/**"
        )
        assert second.returncode == 0
        assert "fleet_lease_conflict:" in second.stdout  # warned, not blocked
        log = (repo / ".git" / "tautline-fleet" / "fleet.log").read_text(encoding="utf-8")
        assert "lease_conflict_observed" in log
        assert len(_leases(repo)) == 2
    finally:
        _cleanup_wt(repo, wt)


def test_renew_and_release_default_to_own_leases(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
    renewed = run_cli("fleet-lease", "renew", "--target", str(repo))
    assert renewed.returncode == 0 and "fleet_lease: renewed" in renewed.stdout
    released = run_cli("fleet-lease", "release", "--target", str(repo))
    assert released.returncode == 0 and "fleet_lease: released" in released.stdout
    assert _leases(repo) == []


def test_release_foreign_requires_operator_note(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        lease_id = json.loads(_leases(repo)[0].read_text(encoding="utf-8"))["lease_id"]
        refused = run_cli(
            "fleet-lease", "release", "--target", str(wt), "--lease", lease_id
        )
        assert refused.returncode != 0
        allowed = run_cli(
            "fleet-lease", "release", "--target", str(wt), "--lease", lease_id,
            "--operator-note", "operator: lane-a abandoned",
        )
        assert allowed.returncode == 0
    finally:
        _cleanup_wt(repo, wt)


def test_concurrent_overlapping_claims_only_one_wins(run_cli, tmp_path):
    # The race the flock exists for. Real agent lanes are separate PROCESSES, so
    # the race must be exercised with subprocesses -- same-process lock semantics
    # (thread reentrancy) prove nothing about the deployed topology. Parallel
    # Popen launches don't force the interleaving every run, but the invariant
    # (exactly one winner, exactly one lease) must hold under ANY interleaving.
    import os
    import sys as _sys

    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        cli_path = str(REPO_ROOT / "bin" / "tautline")
        home = tmp_path / "race-home"
        home.mkdir()
        env = {"PATH": os.environ["PATH"], "HOME": str(home)}

        def launch(tree):
            return subprocess.Popen(
                [_sys.executable, cli_path, "fleet-lease", "claim",
                 "--target", str(tree), "--globs", "src/**"],
                env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        procs = [launch(repo), launch(wt)]
        codes = sorted(p.wait(timeout=60) for p in procs)
        assert codes == [0, 1], [p.communicate() for p in procs]
        assert len(_leases(repo)) == 1
    finally:
        _cleanup_wt(repo, wt)


def test_fleet_claim_enters_the_lock(cli, monkeypatch, tmp_path):
    # Deterministic companion to the race test: prove the claim path actually
    # enters the claims-lock critical section (the race test can't force the
    # interleaving), and that a REAL kernel lock was taken on this POSIX host.
    repo = tmp_path / "solo"
    _init_repo(repo)
    entered = []
    real_lock = cli.fleet_claims_lock

    @contextmanager
    def recording_lock(state):
        entered.append(str(state / "claims.lock"))
        with real_lock(state) as locked:
            entered.append(f"locked={locked}")
            yield locked

    monkeypatch.setattr(cli, "fleet_claims_lock", recording_lock)
    code, lines = cli.fleet_claim({"fleet": {}}, repo, ["src/**"], None, None, "")
    assert code == 0
    assert any(name.endswith("claims.lock") for name in entered)
    assert "locked=True" in entered, "POSIX host must get a real lock, not best-effort"
    assert not any("advisory locking unavailable" in line for line in lines)


def test_fleet_claim_warns_when_locking_degrades(cli, monkeypatch, tmp_path):
    # The OSError path advisory_flock swallows: flock present but failing. The
    # claim must still succeed AND must say it was not serialized.
    repo = tmp_path / "degraded"
    _init_repo(repo)

    @contextmanager
    def unlocked(state):
        state.mkdir(parents=True, exist_ok=True)
        yield False

    monkeypatch.setattr(cli, "fleet_claims_lock", unlocked)
    code, lines = cli.fleet_claim({"fleet": {}}, repo, ["src/**"], None, None, "")
    assert code == 0
    assert any("advisory locking unavailable" in line for line in lines)
    log_path = cli.fleet_state_dir(repo) / "fleet.log"
    assert "lease_claim_unserialized" in log_path.read_text(encoding="utf-8")


def test_takeover_overlap_refusal_follows_enforcement(run_cli, tmp_path):
    # Under observe, a fresh claim for overlapping globs is allowed, so takeover
    # must not be stricter than claim for the same globs.
    repo = _fleet_repo(tmp_path, enforcement="observe")
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        stale_path = _leases(repo)[0]
        stale = json.loads(stale_path.read_text(encoding="utf-8"))
        stale["renewed_at"] = "2020-01-01T00:00:00+00:00"
        stale["claimed_at"] = "2020-01-01T00:00:00+00:00"
        stale_path.write_text(json.dumps(stale), encoding="utf-8")
        # A second, LIVE lease overlapping the stale one (allowed under observe).
        run_cli("fleet-lease", "claim", "--target", str(wt), "--globs", "src/pkg/**")
        taken = run_cli(
            "fleet-lease", "takeover", "--target", str(repo),
            "--lease", stale["lease_id"], "--note", "reclaim stale",
        )
        assert taken.returncode == 0, taken.stderr
        assert "fleet_lease: takeover" in taken.stdout
        assert "fleet_lease_conflict:" in taken.stdout  # observed, not refused
    finally:
        _cleanup_wt(repo, wt)


def test_takeover_stale_free_live_gated(run_cli, tmp_path):
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        lease_path = _leases(repo)[0]
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        # Live takeover without an operator note refuses.
        refused = run_cli(
            "fleet-lease", "takeover", "--target", str(wt),
            "--lease", lease["lease_id"], "--note", "I want it",
        )
        assert refused.returncode != 0
        # Stale takeover is free: age the lease out, then retake.
        lease["renewed_at"] = "2020-01-01T00:00:00+00:00"
        lease["claimed_at"] = "2020-01-01T00:00:00+00:00"
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        taken = run_cli(
            "fleet-lease", "takeover", "--target", str(wt),
            "--lease", lease["lease_id"], "--note", "stale lane-a",
        )
        assert taken.returncode == 0, taken.stderr
        assert "fleet_lease: takeover" in taken.stdout
        remaining = json.loads(_leases(repo)[0].read_text(encoding="utf-8"))
        assert Path(remaining["worktree_path"]).resolve() == wt.resolve()
    finally:
        _cleanup_wt(repo, wt)


def test_takeover_publishes_replacement_before_deleting_original(cli, tmp_path, monkeypatch):
    """The ordering IS the safety property. The guard scans lock-free, so a takeover
    that deleted first would expose a window in which no lease covers the globs and a
    foreign edit sails through. Proven deterministically at the seam rather than by
    hoping a race interleaves."""
    import argparse

    from test_fleet_state import _lease

    repo = _fleet_repo(tmp_path)
    original = _lease(
        cli, lease_id="feed01", worktree=str(tmp_path / "other"), globs=("src/**",)
    )
    original["renewed_at"] = "2020-01-01T00:00:00+00:00"  # stale: no operator note
    original["claimed_at"] = "2020-01-01T00:00:00+00:00"
    cli.write_fleet_lease(repo, original)

    order = []
    real_write, real_unlink = cli.write_fleet_lease, Path.unlink

    def spy_write(target, lease):
        order.append("write")
        return real_write(target, lease)

    def spy_unlink(self, missing_ok=False):
        if self.suffix == ".json" and self.parent.name == "leases":
            order.append("unlink")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(cli, "write_fleet_lease", spy_write)
    monkeypatch.setattr(Path, "unlink", spy_unlink)
    cli.fleet_lease_command(argparse.Namespace(
        action="takeover", target=repo, globs=None, ttl_minutes=None,
        note="reclaim", goal=None, lease="feed01", operator_note=None,
    ))
    assert order == ["write", "unlink"], (
        f"takeover must publish the replacement before removing the original; saw {order}"
    )


def test_claim_conflict_escape_uses_the_adapter_root(run_cli, tmp_path):
    """_fleet_load_context accepts --target <worktree>/subdir (a supported
    monorepo/subproject layout), but find_adapter_root only walks UP -- so a
    worktree-root --target in the printed escape finds no marker and exits 1."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    app = repo / "app"
    app.mkdir()
    adapter = json.loads(FIXTURE_ADAPTER.read_text(encoding="utf-8"))
    adapter["fleet"] = {"enforcement": "block"}
    (app / ".tautline.json").write_text(json.dumps(adapter), encoding="utf-8")
    wt = tmp_path / "lane-b"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "lane-b")
    (wt / "app").mkdir(parents=True, exist_ok=True)
    (wt / "app" / ".tautline.json").write_text(
        (app / ".tautline.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    try:
        first = run_cli("fleet-lease", "claim", "--target", str(app), "--globs", "app/src/**")
        assert first.returncode == 0, first.stderr
        second = run_cli(
            "fleet-lease", "claim", "--target", str(wt / "app"), "--globs", "app/src/pkg/**"
        )
        assert second.returncode != 0
        assert "fleet_lease_instruction:" in second.stdout
        # The escape must name the ADAPTER root (…/app), not the worktree root.
        assert f"--target {wt / 'app'}" in second.stdout
        assert f"--target {wt} " not in second.stdout
    finally:
        _cleanup_wt(repo, wt)


def test_every_mutation_path_warns_when_locking_degrades(cli, monkeypatch, tmp_path):
    """A mutation that reports success while the serialization it depends on did NOT
    hold is a silent lie: concurrent claims/takeovers can leave duplicate overlapping
    leases. claim already warned; renew, release and takeover ignored the flag."""
    import argparse

    from test_fleet_state import _lease

    repo = _fleet_repo(tmp_path)

    @contextmanager
    def unlocked(state):
        state.mkdir(parents=True, exist_ok=True)
        yield False

    monkeypatch.setattr(cli, "fleet_claims_lock", unlocked)

    def _run(action, **kw):
        ns = argparse.Namespace(
            action=action, target=repo, globs=kw.get("globs"), ttl_minutes=None,
            note=kw.get("note"), goal=None, lease=kw.get("lease"),
            operator_note=kw.get("operator_note"),
        )
        out = io.StringIO()
        with redirect_stdout(out):
            cli.fleet_lease_command(ns)
        return out.getvalue()

    assert "advisory locking unavailable" in _run("claim", globs="src/**")
    assert "advisory locking unavailable" in _run("renew")

    # takeover needs a foreign lease to take.
    foreign = _lease(cli, lease_id="0fee01", worktree=str(tmp_path / "other"),
                     globs=("docs/**",))
    foreign["renewed_at"] = "2020-01-01T00:00:00+00:00"
    foreign["claimed_at"] = "2020-01-01T00:00:00+00:00"
    cli.write_fleet_lease(repo, foreign)
    assert "advisory locking unavailable" in _run(
        "takeover", lease="0fee01", note="reclaim"
    )
    assert "advisory locking unavailable" in _run("release")

    log = (cli.fleet_state_dir(repo) / "fleet.log").read_text(encoding="utf-8")
    assert "lease_mutation_unserialized" in log


def test_stale_renew_cannot_revive_into_a_mutual_deadlock(run_cli, tmp_path):
    """A lane parked past its TTL returns and runs `renew`. While it was lapsed,
    another lane legitimately claimed its globs (claim ignores stale records).
    Blindly refreshing renewed_at would yield TWO live overlapping leases and both
    lanes would block each other -- a mutual deadlock, strictly worse than the
    missed-block direction everything else here fails toward."""
    repo = _fleet_repo(tmp_path)
    wt = _worktree(repo, tmp_path, "lane-b")
    try:
        run_cli("fleet-lease", "claim", "--target", str(repo), "--globs", "src/**")
        # Age lane A's lease out.
        lease_path = _leases(repo)[0]
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        lease["renewed_at"] = "2020-01-01T00:00:00+00:00"
        lease["claimed_at"] = "2020-01-01T00:00:00+00:00"
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        # Lane B legitimately claims the now-free globs.
        taken = run_cli("fleet-lease", "claim", "--target", str(wt), "--globs", "src/**")
        assert taken.returncode == 0, taken.stdout + taken.stderr
        # Lane A returns and renews: must be refused, not silently revived.
        revived = run_cli("fleet-lease", "renew", "--target", str(repo))
        assert revived.returncode != 0, revived.stdout
        assert "fleet_lease_conflict:" in revived.stdout
        assert "fleet_lease_instruction:" in revived.stdout
        # Exactly one lease is still LIVE, so neither lane is deadlocked. The
        # aged-out record keeps its 2020 stamp; a successful revive would have
        # rewritten it to now.
        records = [json.loads(f.read_text(encoding="utf-8")) for f in _leases(repo)]
        live_ids = [r["lease_id"] for r in records if not r["renewed_at"].startswith("2020")]
        assert len(live_ids) == 1, records
    finally:
        _cleanup_wt(repo, wt)
