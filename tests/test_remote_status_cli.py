import json
import subprocess
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "generated-adapter-example-saas.json"


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def _git(repo: Path, *args: str) -> None:
    _run(["git", "-C", str(repo), *args])


def _commit(repo: Path, message: str) -> None:
    _git(
        repo,
        "-c",
        "user.email=validate@example.invalid",
        "-c",
        "user.name=validate",
        "commit",
        "-q",
        "-m",
        message,
    )


def _status_fixture(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "status-remote.git"
    source = tmp_path / "status-source"
    clone = tmp_path / "status-clone"

    (source / "backlog").mkdir(parents=True)
    _git(source, "init", "-q", "-b", "main")
    (source / "backlog" / "_index.md").write_text("# Backlog Index\n", encoding="utf-8")
    _git(source, "add", "backlog/_index.md")
    _commit(source, "initial status fixture")

    _run(["git", "init", "--bare", "-q", "-b", "main", str(remote)])
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-q", "-u", "origin", "main")
    _run(["git", "clone", "-q", str(remote), str(clone)])

    with (source / "backlog" / "_index.md").open("a", encoding="utf-8") as fh:
        fh.write("\n- G4C complete\n")
    _git(source, "add", "backlog/_index.md")
    _commit(source, "complete remote status item")
    _git(source, "push", "-q", "origin", "main")
    return source, clone


def _push_deployed_lane(source: Path) -> None:
    _git(source, "switch", "-q", "-c", "second-lane-deployed")
    (source / "app").mkdir()
    (source / "app" / "live.txt").write_text("deployed lane surface\n", encoding="utf-8")
    _git(source, "add", "app/live.txt")
    _commit(source, "second lane deployed surface")
    _git(source, "push", "-q", "origin", "second-lane-deployed")


def _write_latest_code_adapter(target: Path) -> Path:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["project"] = "Latest Code Fixture"
    data["repo"] = "<owner>/<repo>"
    data["bootstrapEvidence"] = {
        "project": "Latest Code Fixture",
        "status": "repo-evident",
        "summary": "Validation fixture for latest-code baseline behavior.",
        "repoEvidence": [
            {"path": "backlog/_index.md", "fact": "fixture backlog index exists"},
            {"path": "LOCAL.md", "fact": "fixture local lane file exists"},
        ],
    }
    data["latestCode"] = {
        "enabled": True,
        "remote": "origin",
        "base": "main",
        "statusFile": ".ai-work/LATEST_CODE_BASELINE.json",
        "maxAgeMinutes": 60,
        "fetchAll": True,
        "includeOpenPrs": False,
        "includeRemoteBranches": True,
        "maxAheadBranches": 20,
        "rule": "Validate fetched base plus ahead remote branches before trusting local lane files.",
    }
    adapter = target / ".minervit" / "adapter.json"
    adapter.parent.mkdir()
    adapter.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adapter


def test_remote_main_status_reports_stale_clean_and_dirty_lane(run_cli, tmp_path):
    _source, clone = _status_fixture(tmp_path)

    res = run_cli("remote-main-status", "--target", str(clone), "--path", "backlog/_index.md")
    assert res.returncode == 0, res.stderr
    assert "remote_main_status: fetched" in res.stdout
    assert "status_source: origin/main" in res.stdout
    assert "local_vs_remote_main: ahead=0 behind=1" in res.stdout
    assert "local_dirty: no" in res.stdout
    assert "remote_main_path: present backlog/_index.md" in res.stdout
    assert "do not trust a stale local lane" in res.stdout

    (clone / "LOCAL.md").write_text("# local stale note\n", encoding="utf-8")
    dirty = run_cli("remote-main-status", "--target", str(clone))
    assert dirty.returncode == 0, dirty.stderr
    assert "local_dirty: yes" in dirty.stdout


def test_latest_code_status_writes_baseline_with_remote_branch_ahead(run_cli, tmp_path):
    source, clone = _status_fixture(tmp_path)
    _push_deployed_lane(source)
    adapter = _write_latest_code_adapter(clone)

    res = run_cli("latest-code-status", "--project", str(adapter), "--target", str(clone), "--write")
    assert res.returncode == 0, res.stderr
    assert "latest_code_baseline_state: wrote" in res.stdout
    assert "latest_code_base_ref: origin/main" in res.stdout
    assert "latest_code_remote_branches_ahead: 1" in res.stdout
    assert "latest_code_remote_branch_ahead: origin/second-lane-deployed ahead=1" in res.stdout
    assert "latest_code_instruction: remote branches are ahead of base" in res.stdout

    baseline = json.loads((clone / ".ai-work" / "LATEST_CODE_BASELINE.json").read_text(encoding="utf-8"))
    assert baseline["schema"] == "minervit-latest-code-baseline/v1"
    assert [branch["ref"] for branch in baseline["remoteBranchesAheadOfBase"]] == ["origin/second-lane-deployed"]
