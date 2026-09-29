"""The adapter switch must actually connect agents in independent Git clones."""
import json
import subprocess

import pytest

from tautline_methodology import work


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clones(tmp_path):
    remote = tmp_path / "shared.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    result = []
    for name in ("alice", "bob"):
        root = tmp_path / name
        subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
        git(root, "config", "user.name", name)
        git(root, "config", "user.email", name + "@example.invalid")
        if not result:
            (root / "README.md").write_text("project\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "seed")
            git(root, "push", "origin", "main")
        cfg = {"schemaVersion": "lean-1", "project": {"name": "test"}, "commands": {"test": "true"}, "integrationBranch": "main", "backlog": {"provider": "local"}, "workCoordination": {"backend": "git", "timeoutSeconds": 2}}
        (root / ".tautline.json").write_text(json.dumps(cfg))
        result.append(root)
    return *result, remote


def run(cli, target, *args):
    return cli.main(["work", *args, "--target", str(target)])


def test_adapter_switch_shares_intent_and_completion_between_independent_clones(cli, clones, capsys):
    alice, bob, remote = clones
    assert run(cli, alice, "declare", "Implement login", "--lane", "builder", "--path", "src/auth") == 0
    capsys.readouterr()
    assert run(cli, bob, "status", "--json") == 0
    state = json.loads(capsys.readouterr().out)
    assert any(record.get("goal") == "Implement login" for record in state["records"])
    assert state["sync"]["state"] == "fresh"
    assert run(cli, bob, "declare", "Update auth client", "--lane", "builder", "--path", "src/auth/client.py") == 0
    capsys.readouterr()
    assert run(cli, alice, "sync", "--json", "--lane", "builder") == 0
    state = json.loads(capsys.readouterr().out)
    assert len(state["records"]) == 2
    assert len(state["overlaps"]) == 1
    assert len(set(state["overlaps"][0]["lanes"])) == 2
    assert run(cli, alice, "finish", "--lane", "builder") == 0
    capsys.readouterr()
    assert run(cli, bob, "sync", "--all", "--json", "--lane", "builder") == 0
    state = json.loads(capsys.readouterr().out)
    assert next(r for r in state["records"] if r["goal"] == "Implement login")["state"] == "COMPLETED"
    assert not state["overlaps"]
    assert git(alice, "branch", "--show-current") == git(bob, "branch", "--show-current") == "main"
    assert git(remote, "rev-parse", "main") == git(alice, "rev-parse", "HEAD")


def test_offline_declaration_is_local_success_and_pending_not_false_idle(cli, clones, capsys):
    alice, bob, remote = clones
    git(alice, "remote", "set-url", "origin", str(remote / "missing"))
    assert run(cli, alice, "declare", "Offline work", "--path", "src") == 0
    capsys.readouterr()
    assert run(cli, alice, "status", "--no-sync", "--json") == 0
    state = json.loads(capsys.readouterr().out)
    assert state["records"][0]["goal"] == "Offline work"
    assert state["sync"]["pending"] is True
    assert state["sync"]["state"] in {"offline", "pending", "unknown"}
    git(alice, "remote", "set-url", "origin", str(remote))
    assert run(cli, alice, "sync") == 0
    capsys.readouterr()
    assert run(cli, bob, "sync", "--json") == 0
    state = json.loads(capsys.readouterr().out)
    assert any(r.get("goal") == "Offline work" for r in state["records"])


def test_local_mode_never_invokes_shared_transport(cli, clones, monkeypatch, capsys):
    alice, _, _ = clones
    cfg = json.loads((alice / ".tautline.json").read_text())
    cfg["workCoordination"] = True
    (alice / ".tautline.json").write_text(json.dumps(cfg))
    from tautline_methodology import work_git
    monkeypatch.setattr(work_git, "sync", lambda *a, **kw: pytest.fail("local work made a shared sync call"))
    assert run(cli, alice, "declare", "Local work") == 0
    assert run(cli, alice, "status") == 0
    assert "local, advisory" in capsys.readouterr().out


def test_startup_and_work_pickup_read_shared_peers(cli, clones, capsys):
    alice, bob, _ = clones
    assert run(cli, alice, "declare", "Remote peer", "--path", "src") == 0
    capsys.readouterr()
    assert cli.main(["lane-status", "--hook", "--target", str(bob)]) == 0
    assert "Remote peer" in capsys.readouterr().out
    assert cli.main(["backlog", "add", "New work", "--target", str(bob)]) == 0
    capsys.readouterr()
    assert cli.main(["backlog", "take", "--target", str(bob)]) == 0
    assert "Remote peer" in capsys.readouterr().err


def test_corrupt_own_record_overrides_its_cached_remote_copy(cli, clones, capsys):
    alice, _, _ = clones
    assert run(cli, alice, "declare", "Previously valid", "--lane", "builder") == 0
    state = work.snapshot(alice, refresh=False)
    from pathlib import Path
    (Path(state["store"]) / "builder.json").write_text("{")
    state = work.snapshot(alice, refresh=False)
    matching = [r for r in state["records"] if r["lane"] == "builder"]
    assert len(matching) == 1 and matching[0]["state"] == "UNKNOWN"


def test_never_synced_view_cannot_imply_nobody_else_is_working():
    rendered = "\n".join(work.render({"backend": "git", "lane": "local", "records": [], "overlaps": [], "sync": {"state": "cached", "lastSuccess": None}}))
    assert "never" in rendered and "does not mean nobody" in rendered


@pytest.mark.parametrize("broken", [[], "scalar", 7, None])
def test_corrupt_clone_identity_is_advisory_after_saving_local_work(cli, clones, capsys, broken):
    alice, _, _ = clones
    identity = alice / ".git/tautline/work-git/identity.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps(broken))
    assert run(cli, alice, "declare", "Saved even with corrupt identity") == 0
    capsys.readouterr()
    assert run(cli, alice, "status", "--json") == 0
    state = json.loads(capsys.readouterr().out)
    assert state["records"][0]["goal"] == "Saved even with corrupt identity"
    assert state["sync"]["state"] in {"unknown", "offline"}


def test_delayed_status_preserves_another_local_agents_newer_publication(cli, clones, capsys, monkeypatch):
    from tautline_methodology import work_git
    alice, bob, _ = clones
    assert run(cli, alice, "declare", "Old goal", "--lane", "builder") == 0
    original = work_git._locations
    raced = False
    def locations(target, config):
        nonlocal raced
        if target == alice and not raced:
            raced = True
            assert run(cli, alice, "update", "--goal", "New goal", "--lane", "builder") == 0
        return original(target, config)
    monkeypatch.setattr(work_git, "_locations", locations)
    local = work.snapshot(alice, "builder", force=True)
    assert next(r for r in local["records"] if r["lane"] == "builder")["goal"] == "New goal"
    remote = work.snapshot(bob, force=True)
    assert next(r for r in remote["records"] if r["lane"] == "builder")["goal"] == "New goal"
