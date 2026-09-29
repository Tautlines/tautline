"""`scripts/check_pr_backlog_ref.py`: the deterministic PR<->backlog reference stamp check.

Subprocess-tested exactly as CI invokes it -- same pattern as `tests/test_evidence_artifacts.py`
against `.github/scripts/emit_evidence.py`. This is a standalone script, not a package module, so
importing it and calling `main()` in-process would exercise a different code path (module import
order, `sys.path` mutation) than the one CI actually runs.

The grammar TABLE itself (`backlog.REFERENCE_GRAMMAR`) is tested in `tests/test_backlog_providers.py`,
beside the provider seam it is discovery-complete against. This file is about the SCRIPT: the
pull_request/push gate, the config-key opt-in, and reading the event payload.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_pr_backlog_ref.py"

LEAN_BASE = {
    "schemaVersion": "lean-1",
    "project": {"name": "Demo", "repo": "acme/demo"},
    "integrationBranch": "main",
    "commands": {"test": "scripts/test.sh"},
}


def _write_config(root: Path, backlog_block: dict | None) -> None:
    cfg = dict(LEAN_BASE)
    if backlog_block is not None:
        cfg["backlog"] = backlog_block
    root.mkdir(parents=True, exist_ok=True)
    (root / ".tautline.json").write_text(json.dumps(cfg), encoding="utf-8")


def _run(
    tmp_path: Path,
    backlog_block: dict | None,
    *,
    title: str = "",
    body: str = "",
    event_name: str | None = "pull_request",
    set_event_path: bool = True,
    event_payload: object = None,
    raw_event_text: str | None = None,
    event_path_override: Path | None = None,
    root: Path | None = None,
) -> subprocess.CompletedProcess:
    project_root = root if root is not None else (tmp_path / "repo")
    if root is None:
        _write_config(project_root, backlog_block)

    env = dict(os.environ)
    if event_name is None:
        env.pop("GITHUB_EVENT_NAME", None)
    else:
        env["GITHUB_EVENT_NAME"] = event_name

    if event_path_override is not None:
        env["GITHUB_EVENT_PATH"] = str(event_path_override)
    elif set_event_path:
        event_path = tmp_path / "event.json"
        if raw_event_text is not None:
            event_path.write_text(raw_event_text, encoding="utf-8")
        else:
            payload = event_payload if event_payload is not None else {
                "pull_request": {"title": title, "body": body}
            }
            event_path.write_text(json.dumps(payload), encoding="utf-8")
        env["GITHUB_EVENT_PATH"] = str(event_path)
    else:
        env.pop("GITHUB_EVENT_PATH", None)

    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(project_root)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


# ================================================================================================
# the opt-in gate: no backlog key, or not a pull_request event, is a silent pass
# ================================================================================================


def test_no_backlog_key_skips_with_exit_0(tmp_path):
    result = _run(tmp_path, None, title="feat: widgets", body="no reference here")
    assert result.returncode == 0, result.stderr
    assert "skipped (no backlog configured)" in result.stdout


def test_no_adapter_file_at_all_skips(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    result = _run(tmp_path, None, root=empty_root)
    assert result.returncode == 0, result.stderr
    assert "skipped (no backlog configured)" in result.stdout


def test_non_pull_request_event_skips_without_reading_the_event_path(tmp_path):
    """`set_event_path=False` doubles as an ordering assertion: if the event-name check ever
    moved after the event-path read, this would blow up with a SystemExit instead of skipping
    cleanly."""
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        event_name="push",
        set_event_path=False,
    )
    assert result.returncode == 0, result.stderr
    assert "skipped (not a pull_request event" in result.stdout


def test_unknown_provider_skips_rather_than_blocking(tmp_path):
    result = _run(tmp_path, {"provider": "carrierpigeon"}, title="feat: widgets", body="")
    assert result.returncode == 0, result.stderr
    assert "skipped (unknown backlog provider 'carrierpigeon'" in result.stdout


# ================================================================================================
# github
# ================================================================================================


def test_github_generic_stamp_in_body_passes(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        title="feat: widgets",
        body="Implements the thing.\n\nBacklog: #42\n",
    )
    assert result.returncode == 0, result.stderr
    assert "OK (backlog provider: github)" in result.stdout


def test_github_closing_keyword_passes(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        title="feat: widgets",
        body="Implements the thing.\n\nCloses #42\n",
    )
    assert result.returncode == 0, result.stderr


def test_github_stamp_in_title_alone_is_enough(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        title="feat: widgets (Backlog: #42)",
        body="",
    )
    assert result.returncode == 0, result.stderr


def test_github_no_reference_fails_and_names_only_githubs_form(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        title="feat: widgets",
        body="no reference anywhere in here",
    )
    assert result.returncode == 1
    assert "FAILED" in result.stderr
    assert "Backlog: <id>" in result.stderr, "the exact generic line must be shown"
    assert "closing keyword" in result.stderr
    # only the CONFIGURED provider's form -- never a cross-provider list (operator directive)
    assert "Jira" not in result.stderr
    assert "slug" not in result.stderr


# ================================================================================================
# jira
# ================================================================================================


def test_jira_bare_key_in_title_passes(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "jira", "site": "https://team.atlassian.net", "project": "PROJ"},
        title="fix(PROJ-12): tighten validation",
        body="",
    )
    assert result.returncode == 0, result.stderr
    assert "OK (backlog provider: jira)" in result.stdout


def test_jira_generic_stamp_passes(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "jira", "site": "https://team.atlassian.net", "project": "PROJ"},
        title="fix: tighten validation",
        body="Backlog: PROJ-12\n",
    )
    assert result.returncode == 0, result.stderr


def test_jira_rejects_a_github_only_closing_keyword(tmp_path):
    """A GitHub closing keyword is not this provider's grammar -- the check must not accept a
    form that means nothing to the board this project actually uses."""
    result = _run(
        tmp_path,
        {"provider": "jira", "site": "https://team.atlassian.net", "project": "PROJ"},
        title="fix: tighten validation",
        body="Closes #42\n",
    )
    assert result.returncode == 1
    assert "FAILED" in result.stderr


def test_jira_no_reference_fails_and_names_only_jiras_form(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "jira", "site": "https://team.atlassian.net", "project": "PROJ"},
        title="fix: tighten validation",
        body="no reference at all",
    )
    assert result.returncode == 1
    assert "Jira issue key" in result.stderr
    assert "closing keyword" not in result.stderr, "github's form must not leak into jira's message"


# ================================================================================================
# local
# ================================================================================================


def test_local_generic_stamp_passes(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "local"},
        title="fix: tighten validation",
        body="Backlog: 2026-08-31-tighten-validation\n",
    )
    assert result.returncode == 0, result.stderr


def test_local_no_backlog_provider_key_defaults_to_local_grammar(tmp_path):
    """`backlog: {}` (the key is present, but names no provider) is still an opt-in -- and
    defaults to the local provider's grammar, the same default `describe_config` uses."""
    result = _run(
        tmp_path,
        {},
        title="fix: tighten validation",
        body="Backlog: 2026-08-31-tighten-validation\n",
    )
    assert result.returncode == 0, result.stderr
    assert "OK (backlog provider: local)" in result.stdout


def test_local_no_reference_fails(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "local"},
        title="fix: tighten validation",
        body="no reference at all",
    )
    assert result.returncode == 1
    assert "queue-item slug" in result.stderr


# ================================================================================================
# environment / event-payload errors -- these are tooling failures, not "no backlog configured"
# ================================================================================================


def test_missing_github_event_path_on_a_pull_request_event_is_a_clear_error(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        set_event_path=False,
    )
    assert result.returncode != 0
    assert "GITHUB_EVENT_PATH" in result.stderr


def test_event_payload_without_a_pull_request_object_is_a_clear_error(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        event_payload={"action": "synchronize"},
    )
    assert result.returncode != 0
    assert "pull_request" in result.stderr


def test_malformed_event_json_is_a_clear_error_not_a_traceback(tmp_path):
    """Review P3: the read-and-parse of GITHUB_EVENT_PATH must fail as cleanly as the two checks
    beside it (missing path; payload with no `pull_request` object), not with a bare
    JSONDecodeError traceback."""
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        raw_event_text="{not valid json",
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "could not read or parse the event payload" in result.stderr
    assert "JSONDecodeError" in result.stderr


def test_a_nonexistent_event_path_is_a_clear_error_not_a_traceback(tmp_path):
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        event_path_override=tmp_path / "does-not-exist.json",
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "could not read or parse the event payload" in result.stderr
    assert "FileNotFoundError" in result.stderr


def test_a_non_dict_event_payload_is_a_clear_error(tmp_path):
    """The top-level JSON value can syntax-check as valid JSON while still not being an object
    (a bare list, a bare string) -- `.get("pull_request")` on that must not raise AttributeError."""
    result = _run(
        tmp_path,
        {"provider": "github", "repo": "acme/demo"},
        event_payload=["just", "an", "array"],
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "pull_request" in result.stderr
