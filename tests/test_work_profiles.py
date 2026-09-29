import json
import subprocess
from pathlib import Path



REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _prepare_rendered_repo(run_cli, tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "checkout", "-B", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    res = run_cli("render-adapters", "--project", str(EXAMPLE), "--target", str(root), "--write")
    assert res.returncode == 0, res.stderr
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "render adapter")
    _git(root, "checkout", "-qb", "feature/docs")
    return root


def _write_profile(root: Path, profile: str) -> None:
    path = root / ".ai-work" / "WORK_PROFILE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "minervit-work-profile/v1", "profile": profile}) + "\n",
        encoding="utf-8",
    )


def _commit_file(root: Path, rel: str, content: bytes | str = "content\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-qm", f"add {rel}")


def _generated_adapter_path(root: Path) -> Path:
    return root / ".tautline.json"


def _read_generated_adapter(root: Path) -> dict:
    return json.loads(_generated_adapter_path(root).read_text(encoding="utf-8"))


def _write_generated_adapter(root: Path, data: dict) -> None:
    _generated_adapter_path(root).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_default_rendered_adapter_omits_pre_push_base_for_rollback_compatibility(run_cli, tmp_path):
    root = _prepare_rendered_repo(run_cli, tmp_path)

    data = _read_generated_adapter(root)

    assert "prePushBase" not in data["workProfiles"]
