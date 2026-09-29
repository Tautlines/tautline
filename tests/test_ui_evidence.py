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
