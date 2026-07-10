import hashlib
import json

import pytest


PLAN = """# Goal 9

## GitHub Project Source

- provider: github-projects
- owner: acme
- project_number: 2
- project_item_url: https://github.com/acme/widgets/issues/42
- status: Ready
"""


def _data(**overrides):
    data = {
        "repo": "acme/widgets",
        "uiEvidence": {
            "enabled": True,
            "enforcement": "block",
            "tool": "playwright",
            "evidenceDir": ".ai-runs/ui-evidence",
            "manifestGlob": "*.json",
            "captureCommand": "npx playwright test",
            "requiredEvents": ["milestone-complete", "goal-complete"],
            "issueComments": {
                "enabled": True,
                "provider": "github-issues",
                "triggerEvents": ["milestone-complete", "goal-complete"],
                "required": True,
            },
        },
    }
    data.update(overrides)
    return data


def _run():
    return {
        "goalId": "goal-9",
        "sourceGoal": "plan.md",
        "milestones": [{"index": 1, "title": "M1", "status": "complete"}],
    }


def _seed_plan(tmp_path):
    (tmp_path / "plan.md").write_text(PLAN, encoding="utf-8")


def _manifest(cli, tmp_path, *, status="captured", reason="", url="https://cdn.example.test/home.png"):
    evidence_dir = tmp_path / ".ai-runs" / "ui-evidence"
    evidence_dir.mkdir(parents=True)
    shot = evidence_dir / "home.png"
    shot.write_bytes(b"fake screenshot bytes")
    sha = hashlib.sha256(shot.read_bytes()).hexdigest()
    manifest = {
        "schema": cli.UI_EVIDENCE_SCHEMA,
        "status": status,
        "summary": "Home screen renders the new flow",
        "command": "npx playwright test",
        "targetUrl": "http://127.0.0.1:3000",
    }
    if status == "not_applicable":
        manifest["notApplicableReason"] = reason
    else:
        manifest["screenshots"] = [
            {
                "label": "home desktop",
                "path": ".ai-runs/ui-evidence/home.png",
                "url": url,
                "route": "/",
                "viewport": "desktop",
                "sha256": sha,
            }
        ]
    path = evidence_dir / "home.ui-evidence.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_normalize_ui_evidence_defaults_off_and_rejects_bad_values(cli):
    assert cli.normalize_ui_evidence({})["enabled"] is False
    cfg = cli.normalize_ui_evidence(
        {
            "uiEvidence": {
                "enabled": True,
                "requiredEvents": ["work-item-complete"],
                "issueComments": {"enabled": True, "triggerEvents": ["work-item-complete"]},
            }
        }
    )
    assert cfg["requiredEvents"] == ["work-item-complete"]
    assert cfg["issueComments"]["triggerEvents"] == ["work-item-complete"]
    with pytest.raises(SystemExit):
        cli.normalize_ui_evidence({"uiEvidence": {"enabled": "yes"}})
    with pytest.raises(SystemExit):
        cli.normalize_ui_evidence({"uiEvidence": {"tool": "selenium"}})
    with pytest.raises(SystemExit):
        cli.normalize_ui_evidence({"uiEvidence": {"issueComments": {"provider": "jira"}}})


def test_block_event_requires_manifest(cli, tmp_path):
    blocker, path, manifest = cli.ui_evidence_completion_blocker(_data(), tmp_path, "milestone-complete")
    assert blocker and "ui evidence required" in blocker
    assert path is None
    assert manifest is None


def test_valid_captured_manifest_satisfies_blocker(cli, tmp_path):
    _manifest(cli, tmp_path)
    blocker, path, manifest = cli.ui_evidence_completion_blocker(_data(), tmp_path, "goal-complete")
    assert blocker is None
    assert path and path.name == "home.ui-evidence.json"
    assert manifest["summary"] == "Home screen renders the new flow"


def test_not_applicable_manifest_requires_concrete_reason(cli, tmp_path):
    path, manifest = _manifest(cli, tmp_path, status="not_applicable", reason="No rendered UI surface changed in this migration.")
    assert cli.ui_evidence_manifest_errors(manifest, path, tmp_path) == []

    bad = dict(manifest)
    bad["notApplicableReason"] = "n/a"
    assert any("concrete notApplicableReason" in issue for issue in cli.ui_evidence_manifest_errors(bad, path, tmp_path))


def test_issue_comment_posts_manifest_summary(cli, tmp_path, monkeypatch):
    _seed_plan(tmp_path)
    path, manifest = _manifest(cli, tmp_path)
    calls = []

    def fake_run_command(command, cwd=None, timeout=None):
        calls.append(command)
        assert command[1:3] == ["issue", "comment"]
        return 0, "", ""

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    out, ok = cli.sync_goal_issue_ui_evidence(_data(), tmp_path, _run(), "goal-complete", path, manifest)
    assert ok is True
    assert out and "ui_evidence_comment_synced: issue #42" in out[0]
    body = calls[0][calls[0].index("--body") + 1]
    assert "## UI Evidence Proof" in body
    assert "Home screen renders the new flow" in body
    assert "https://cdn.example.test/home.png" in body
    assert "sha256=" in body


def test_work_item_issue_comment_posts_directly(cli, tmp_path, monkeypatch):
    path, manifest = _manifest(cli, tmp_path)
    data = _data()
    data["uiEvidence"]["requiredEvents"] = ["work-item-complete"]
    data["uiEvidence"]["issueComments"]["triggerEvents"] = ["work-item-complete"]
    calls = []

    def fake_run_command(command, cwd=None, timeout=None):
        calls.append(command)
        return 0, "", ""

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    out, ok = cli.sync_ui_evidence_to_issue(
        data,
        tmp_path,
        "42",
        "work-item-complete",
        path,
        manifest,
        context_label="Work item",
        context_value="#42",
    )
    assert ok is True
    assert out and "ui_evidence_comment_synced: issue #42" in out[0]
    body = calls[0][calls[0].index("--body") + 1]
    assert "- Work item: `#42`" in body
    assert "- Event: `work-item-complete`" in body


def test_required_issue_comment_failure_is_not_ok(cli, tmp_path, monkeypatch):
    _seed_plan(tmp_path)
    path, manifest = _manifest(cli, tmp_path)

    def fake_run_command(command, cwd=None, timeout=None):
        return 1, "", "HTTP 403"

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    out, ok = cli.sync_goal_issue_ui_evidence(_data(), tmp_path, _run(), "goal-complete", path, manifest)
    assert ok is False
    assert out and "HTTP 403" in out[0]
