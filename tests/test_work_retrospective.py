"""Regressions reproduced from the independent Opus retrospective."""
import json
import time
from pathlib import Path

from tautline_methodology import operator_inbox, work, work_git
import pytest
import test_work_git as git_tests
from test_work_git import config, git, record


@pytest.fixture
def clones(tmp_path):
    return git_tests.clones.__wrapped__(tmp_path)


def test_removed_local_lane_is_removed_from_metadata(clones):
    a, b, remote = clones
    first = work_git.sync(a, config(timeoutSeconds=10), [record()], publish=True)
    result = work_git.sync(a, config(timeoutSeconds=10), [], force=True)
    assert result['sync']['state'] == 'fresh', result
    assert not work_git.sync(b, config(timeoutSeconds=10), [], force=True)['records']
    paths = git(remote, 'ls-tree', '-r', '--name-only', 'tautline/work')
    assert f"records/{first['namespace']}/agent.json" not in paths


def test_enabling_git_does_not_export_retired_local_history(clones):
    a, b, _ = clones
    result = work_git.sync(a, config(timeoutSeconds=10), [record('Private old goal', 'completed')], force=True)
    assert result['sync']['state'] == 'fresh', result
    assert not work_git.sync(b, config(timeoutSeconds=10), [], force=True)['records']


def test_unchanged_records_do_not_each_launch_hash_object(clones, monkeypatch):
    a, _, _ = clones
    records = [dict(record(), lane=f'agent-{i}') for i in range(40)]
    assert work_git.sync(a, config(timeoutSeconds=10), records, publish=True)['sync']['state'] == 'fresh'
    calls = []
    original = work_git._run
    def run(root, args, *rest, **kw):
        calls.append(args)
        return original(root, args, *rest, **kw)
    monkeypatch.setattr(work_git, '_run', run)
    records[0]['goal'] = 'Changed'
    assert work_git.sync(a, config(timeoutSeconds=10), records, publish=True)['sync']['state'] == 'fresh'
    assert sum(args[0] == 'hash-object' for args in calls) <= 1


def test_many_retired_records_do_not_hide_current_local_lane(clones):
    a, _, _ = clones
    ident = work.identity(a)
    store = Path(ident['store'])
    for i in range(300):
        work._write(store, dict(record(status='completed'), lane=f'old-{i}'))
    own = dict(record(), lane=ident['lane'], worktree=ident['worktree'], gitDir=ident['gitDir'], branch=git(a,'branch','--show-current'))
    work._write(store, own)
    state = work._local_snapshot(a)
    assert any(r['lane'] == own['lane'] and r['state'] == 'ACTIVE' for r in state['records'])
    assert not any(r.get('reason') == 'record limit exceeded' for r in state['records'])


def test_unicode_inbox_answer_roundtrips(tmp_path):
    ident = 'a' * 20
    row = {'schema': operator_inbox.SCHEMA, 'id': ident, 'lane_id': 'agent',
           'summary': '😀' * 1000, 'answer': '😀' * 1000,
           'answered_at': '2026-09-29T00:00:00+00:00', 'acknowledged_at': None}
    path = tmp_path / f'{ident}.json'
    operator_inbox._write(path, row)
    assert operator_inbox._read(path) == row


def test_local_and_shared_field_limits_agree():
    item = record('x' * 8001)
    try:
        work._validate(item, item['lane'])
    except work.WorkError:
        return
    raise AssertionError('local goal accepted even though transport rejects it')


def test_task_turnover_does_not_exhaust_shared_lifetime_limit(clones, monkeypatch):
    a, b, remote = clones
    monkeypatch.setattr(work_git, 'MAX_RECORDS', 8)
    monkeypatch.setattr(work_git, 'RETIRED_RECORDS', 2)
    peer = [record('Keep peer active')]
    assert work_git.sync(b, config(timeoutSeconds=10), peer, publish=True)['sync']['state'] == 'fresh'
    history = []
    for i in range(12):
        current = dict(record(f'Task {i}'), lane=f'task-{i}')
        history.append(current)
        state = work_git.sync(a, config(timeoutSeconds=10), history, publish=True)
        assert state['sync']['state'] == 'fresh', state
        current['status'] = 'completed'
        state = work_git.sync(a, config(timeoutSeconds=10), history, publish=True)
        assert state['sync']['state'] == 'fresh', state
    seen = work_git.sync(b, config(timeoutSeconds=10), peer, force=True)
    assert seen['sync']['state'] == 'fresh'
    assert any(r['goal'] == 'Keep peer active' for r in seen['records'])
    assert len(git(remote, 'ls-tree', '-r', '--name-only', 'tautline/work').splitlines()) <= 9


def test_copied_git_directory_gets_new_namespace(clones, tmp_path):
    import shutil
    a, _, _ = clones
    first = work_git.sync(a, config(timeoutSeconds=10), [record()], publish=True)
    copied = tmp_path / 'copied'
    shutil.copytree(a, copied)
    second = work_git.sync(copied, config(timeoutSeconds=10), [record('Copied work')], publish=True)
    assert second['sync']['state'] == 'fresh', second
    assert first['namespace'] != second['namespace']
    assert len(second['records']) == 2


def test_git_ssh_selection_is_preserved(clones, monkeypatch):
    import subprocess
    a, _, _ = clones
    git(a, 'config', 'core.sshCommand', 'ssh -i /example/private-key')
    monkeypatch.delenv('GIT_SSH_COMMAND', raising=False)
    monkeypatch.setenv('GIT_SSH', '/example/custom-ssh')
    original = subprocess.Popen
    seen = []
    def popen(*args, **kw):
        seen.append(kw['env'])
        return original(*args, **kw)
    monkeypatch.setattr(work_git.subprocess, 'Popen', popen)
    work_git._run(a, ['rev-parse', 'HEAD'], time.monotonic() + 5)
    assert 'GIT_SSH_COMMAND' not in seen[0]
    assert seen[0]['GIT_SSH'] == '/example/custom-ssh'


def test_rejected_push_keeps_fetched_peers_current(clones, monkeypatch):
    import subprocess
    a, b, _ = clones
    work_git.sync(b, config(timeoutSeconds=10), [record('Peer')], publish=True)
    original = work_git._run
    pushes = []
    def run(root, args, *rest, **kw):
        if args[0] == 'push':
            pushes.append(args)
            return subprocess.CompletedProcess(args, 1, b'', b'private server diagnostic')
        return original(root, args, *rest, **kw)
    monkeypatch.setattr(work_git, '_run', run)
    state = work_git.sync(a, config(timeoutSeconds=10), [record()], publish=True)
    assert state['sync']['state'] == 'pending', state
    assert state['sync']['lastSuccess'] and state['sync']['pending']
    assert 'publication rejected' in state['sync']['error']
    assert len(pushes) == 1
    assert [r['goal'] for r in state['records']] == ['Peer']


def test_removed_worktree_no_longer_asserts_active_scope_to_peers(clones):
    a, b, _ = clones
    rec = record()
    work_git.sync(a, config(timeoutSeconds=10), [rec], publish=True)
    rec.update(state='STALE', reason='worktree removed or unavailable')
    work_git.sync(a, config(timeoutSeconds=10), [rec], force=True)
    assert not work_git.sync(b, config(timeoutSeconds=10), [], force=True)['records']


def test_old_cached_view_still_warns_about_missing_peers():
    state = {'records': [], 'overlaps': [], 'lane': 'local', 'backend': 'git',
             'sync': {'state': 'cached', 'lastSuccess': time.time() - 7200,
                      'pending': False, 'syncIntervalSeconds': 60}}
    assert 'Remote work may be missing or outdated' in '\n'.join(work.render(state))


def test_legacy_flat_retired_records_do_not_consume_active_quota(clones):
    a, _, _ = clones
    ident = work.identity(a)
    store = Path(ident['store'])
    store.mkdir(parents=True)
    for i in range(300):
        old = dict(record(status='completed'), lane=f'old-{i}')
        (store / f'old-{i}.json').write_text(json.dumps(old))
    own = dict(record(), lane=ident['lane'], worktree=ident['worktree'], gitDir=ident['gitDir'], branch=git(a,'branch','--show-current'))
    work._write(store, own)
    state = work._local_snapshot(a)
    assert any(r['lane'] == own['lane'] and r['state'] == 'ACTIVE' for r in state['records'])
    assert not any(r['state'] == 'UNKNOWN' for r in state['records'])


def test_busy_sync_lock_preserves_offline_state(clones):
    import fcntl
    a, _, remote = clones
    local = [record()]
    work_git.sync(a, config(timeoutSeconds=10), local, publish=True)
    remote.rename(remote.with_name('offline'))
    offline = work_git.sync(a, config(timeoutSeconds=10), local, force=True)
    assert offline['sync']['state'] == 'offline'
    cache, _ = work_git._locations(a, config())
    with (cache / 'sync.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        busy = work_git.sync(a, config(timeoutSeconds=10), local, force=True)
    assert busy['sync']['state'] == 'offline'


def test_reusing_lane_does_not_publish_private_retired_payload(clones):
    a, b, _ = clones
    public = record('Shared task A')
    work_git.sync(a, config(timeoutSeconds=10), [public], publish=True)
    public['status'] = 'completed'
    work_git.sync(a, config(timeoutSeconds=10), [public], publish=True)
    private = record('Private local-only task B', status='completed')
    private['paths'] = ['private-customer-notes']
    work_git.sync(a, config(timeoutSeconds=10), [private], force=True)
    seen = work_git.sync(b, config(timeoutSeconds=10), [], force=True)
    serialized = json.dumps(seen)
    assert 'Private local-only' not in serialized
    assert 'private-customer-notes' not in serialized
    assert all(r['status'] == 'completed' for r in seen['records'])


def test_explicit_shared_finish_can_include_a_new_pr(clones):
    a, b, _ = clones
    rec = record('Shared task')
    work_git.sync(a, config(timeoutSeconds=10), [rec], publish=True)
    rec.update(status='completed', shareRetired=True, pr='https://github.com/example/app/pull/42')
    result = work_git.sync(a, config(timeoutSeconds=10), [rec], publish=True)
    assert result['sync']['state'] == 'fresh'
    seen = work_git.sync(b, config(timeoutSeconds=10), [], force=True)
    assert seen['records'][0]['pr'].endswith('/42')
    assert 'shareRetired' not in seen['records'][0]


def test_unicode_declaration_roundtrips_to_peer(clones):
    a, b, _ = clones
    ident = work.identity(a)
    rec = dict(record('😀' * 1500), lane=ident['lane'], worktree=ident['worktree'], gitDir=ident['gitDir'], branch=git(a,'branch','--show-current'))
    work._write(Path(ident['store']), rec)
    result = work.snapshot(a, cfg={'workCoordination': config(timeoutSeconds=10)}, publish=True)
    assert result['sync']['state'] == 'fresh', result
    peer = work_git.sync(b, config(timeoutSeconds=10), [], force=True)
    assert peer['records'][0]['goal'] == rec['goal']


@pytest.mark.parametrize("action", ["finish", "abandon"])
def test_invalid_adapter_does_not_block_local_retirement(clones, action):
    import argparse
    a, _, _ = clones
    parser = argparse.ArgumentParser()
    work.configure(parser)
    def run(*args):
        return work.command(parser.parse_args([*args, "--target", str(a)]))
    assert run("declare", "Finish local work") == 0
    (a / ".tautline.json").write_text("{invalid")
    assert run(action) == 0
    state = work._local_snapshot(a)
    own = next(r for r in state["records"] if r["lane"] == state["lane"])
    assert own["status"] == ("completed" if action == "finish" else "abandoned")
    assert own["shareRetired"] is False


def test_cleanup_rejection_is_not_unpublished_local_work(clones, monkeypatch):
    a, b, _ = clones
    rows = [dict(record(status="completed"), lane=f"done-{i}", shareRetired=True) for i in range(3)]
    assert work_git.sync(a, config(timeoutSeconds=10), rows, publish=True)["sync"]["state"] == "fresh"
    monkeypatch.setattr(work_git, "RETIRED_RECORDS", 1)
    def unexpected(*args, **kwargs):
        raise AssertionError("cleanup alone must not make a reader publish")
    monkeypatch.setattr(work_git, "_publish", unexpected)
    result = work_git.sync(b, config(timeoutSeconds=10), [], force=True)
    assert result["sync"]["state"] == "fresh", result
    assert result["sync"]["pending"] is False
    assert not result["sync"]["error"]


def test_moved_git_directory_keeps_identity(clones):
    a, _, _ = clones
    before = work_git.sync(a, config(timeoutSeconds=10), [record()], publish=True)
    moved = a.with_name("moved")
    a.rename(moved)
    after = work_git.sync(moved, config(timeoutSeconds=10), [record()], force=True)
    assert after["namespace"] == before["namespace"]
    assert len(after["records"]) == 1


def test_existing_identity_does_not_need_identity_lock(clones):
    import fcntl
    a, _, _ = clones
    cache, namespace = work_git._locations(a, config())
    with (cache.parent / "identity.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        result = work_git.sync(a, config(timeoutSeconds=10), [], force=True)
    assert result["namespace"] == namespace
    assert result["sync"]["state"] == "fresh", result


def test_lane_filename_order_does_not_cause_noop_publication(clones, monkeypatch):
    a, _, _ = clones
    rows = [dict(record(), lane=lane) for lane in ("agent", "agent-1")]
    work_git.sync(a, config(timeoutSeconds=10), rows, publish=True)
    def unexpected(*args, **kwargs):
        raise AssertionError("unchanged declarations should not publish")
    monkeypatch.setattr(work_git, "_publish", unexpected)
    result = work_git.sync(a, config(timeoutSeconds=10), rows, force=True)
    assert result["sync"]["state"] == "fresh"


def test_incomplete_local_inventory_is_unknown_not_offline(clones):
    a, _, _ = clones
    ident = work.identity(a)
    store = Path(ident["store"])
    store.mkdir(parents=True)
    (store / "broken.json").write_text("invalid")
    result = work.snapshot(a, cfg={"workCoordination": config(timeoutSeconds=10)}, force=True)
    assert result["sync"]["state"] == "unknown", result
    assert "local declarations incomplete" in result["sync"]["error"]


def test_clock_rollback_does_not_block_sibling_publication(clones):
    a, b, _ = clones
    ident = work.identity(a)
    for lane in ("future", "current"):
        row = dict(record(lane), lane=lane, worktree=ident["worktree"], gitDir=ident["gitDir"], branch=git(a, "branch", "--show-current"))
        if lane == "future":
            row["updatedAt"] += 30
        work._write(Path(ident["store"]), row)
    result = work.snapshot(a, cfg={"workCoordination": config(timeoutSeconds=10)}, publish=True)
    assert result["sync"]["state"] == "fresh", result
    observed = work_git.sync(b, config(timeoutSeconds=10), [], force=True)
    assert {r["goal"] for r in observed["records"]} == {"future", "current"}
    assert next(r for r in result["records"] if r["lane"] == "future")["state"] == "UNKNOWN"


def test_invalid_utf8_peer_path_preserves_unknown_and_allows_own_update(clones):
    a, b, remote = clones
    rows = [record()]
    first = work_git.sync(a, config(timeoutSeconds=10), rows, publish=True)
    assert first["sync"]["state"] == "fresh"
    git(b, "fetch", "origin", "tautline/work")
    git(b, "checkout", "--detach", "FETCH_HEAD")
    # Git trees allow arbitrary path bytes even on filesystems that reject such names.
    import subprocess
    blob = subprocess.run(["git", "-C", str(b), "hash-object", "-w", "--stdin"],
                          input=b"", capture_output=True, check=True).stdout.strip().decode()
    entry = b"100644 " + blob.encode() + b"\trecords/invalid/peer-\xff.json\0"
    subprocess.run(["git", "-C", str(b), "update-index", "-z", "--index-info"], input=entry, check=True)
    git(b, "commit", "-m", "malformed peer record")
    git(b, "push", "origin", "HEAD:tautline/work")
    rows[0]["goal"] = "Updated own scope"
    result = work_git.sync(a, config(timeoutSeconds=10), rows, publish=True)
    assert result["sync"]["state"] == "unknown", result
    assert not result["sync"]["pending"]
    raw = git(remote, "show", f"tautline/work:records/{first['namespace']}/agent.json")
    assert json.loads(raw)["goal"] == "Updated own scope"


def test_surrogate_text_keeps_json_roundtrip_without_ascii_expanding_emoji(clones, tmp_path):
    a, b, _ = clones
    ident = work.identity(a)
    goal = "escaped byte \udcff " + "😀" * 1500
    row = dict(record(goal), lane=ident["lane"], worktree=ident["worktree"], gitDir=ident["gitDir"], branch=git(a, "branch", "--show-current"))
    work._write(Path(ident["store"]), row)
    result = work.snapshot(a, cfg={"workCoordination": config(timeoutSeconds=10)}, publish=True)
    assert result["sync"]["state"] == "fresh", result
    assert work_git.sync(b, config(timeoutSeconds=10), [], force=True)["records"][0]["goal"] == goal
    answer = {"schema": operator_inbox.SCHEMA, "id": "b" * 20, "lane_id": "agent",
              "summary": "summary", "answer": "answer \udcff", "answered_at": "2026-09-29T00:00:00+00:00", "acknowledged_at": None}
    path = tmp_path / (answer["id"] + ".json")
    operator_inbox._write(path, answer)
    assert operator_inbox._read(path) == answer
