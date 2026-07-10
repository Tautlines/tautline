import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def _rev_exists(ref: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    ).returncode == 0


def _evidence_only(path: str) -> bool:
    return path.startswith("docs/backlog/session-journals/") or path.startswith(
        "docs/backlog/methodology-regressions/"
    )


def _project_adapter_config_only(path: str) -> bool:
    path_obj = Path(path)
    return (
        len(path_obj.parts) == 3
        and path_obj.parts[0] == "adapters"
        and path_obj.parts[1] == "projects"
        and path_obj.suffix == ".json"
        and not path_obj.name.startswith(".")
    )


def _version_bump_exempt(path: str) -> bool:
    return _evidence_only(path) or _project_adapter_config_only(path)


def _changed_paths_against_base(base: str) -> set[str]:
    changed = set(filter(None, _git("diff", "--name-only", f"{base}...HEAD").splitlines()))
    for args in (
        ("diff", "--name-only", "HEAD"),
        ("diff", "--cached", "--name-only", "HEAD"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        changed.update(filter(None, _git(*args).splitlines()))
    return changed


def _release_contract_base_ref() -> str | None:
    explicit = os.environ.get("MINERVIT_VALIDATE_BASE_REF", "").strip()
    if explicit:
        if _rev_exists(explicit):
            return explicit
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            pytest.fail(f"CI cannot validate VERSION bump enforcement: {explicit!r} is not available")
        return None
    github_base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base:
        candidate = f"origin/{github_base}"
        if _rev_exists(candidate):
            return candidate
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            pytest.fail(f"CI cannot validate VERSION bump enforcement: {candidate!r} is not available")
    if _rev_exists("origin/main"):
        return "origin/main"
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        pytest.fail("CI cannot validate VERSION bump enforcement: no base ref found")
    return None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("adapters/projects/example-saas.json", True),
        ("adapters/projects/.draft.json", False),
        ("adapters/projects/nested/example.json", False),
        ("adapters/templates/example.json", False),
        ("methodology/adapter-schema.json", False),
        ("docs/backlog/session-journals/2026-07-04.md", True),
        ("docs/backlog/methodology-regressions/rca.md", True),
        ("docs/backlog/methodology-backlog.md", False),
    ],
)
def test_version_bump_exemption_classifies_only_adapter_config_and_evidence(path: str, expected: bool):
    assert _version_bump_exempt(path) is expected


def test_release_contract_base_ref_prefers_explicit_env(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.setenv("MINERVIT_VALIDATE_BASE_REF", "origin/experimental")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/experimental")

    assert _release_contract_base_ref() == "origin/experimental"


def test_release_contract_base_ref_fails_ci_when_explicit_base_is_missing(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.setenv("MINERVIT_VALIDATE_BASE_REF", "origin/missing")
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/main")

    with pytest.raises(pytest.fail.Exception, match="origin/missing"):
        _release_contract_base_ref()


def test_release_contract_base_ref_does_not_fallback_when_explicit_base_is_missing_locally(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.setenv("MINERVIT_VALIDATE_BASE_REF", "origin/missing")
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/main")

    assert _release_contract_base_ref() is None


def test_release_contract_base_ref_uses_github_base_when_available(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.delenv("MINERVIT_VALIDATE_BASE_REF", raising=False)
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/experimental")

    assert _release_contract_base_ref() == "origin/experimental"


def test_release_contract_base_ref_fails_ci_when_github_base_is_missing(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.delenv("MINERVIT_VALIDATE_BASE_REF", raising=False)
    monkeypatch.setenv("GITHUB_BASE_REF", "experimental")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(module, "_rev_exists", lambda _ref: False)

    with pytest.raises(pytest.fail.Exception, match="origin/experimental"):
        _release_contract_base_ref()


def test_release_contract_base_ref_falls_back_to_main_for_local_checkouts(monkeypatch):
    module = sys.modules[__name__]
    monkeypatch.delenv("MINERVIT_VALIDATE_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "_rev_exists", lambda ref: ref == "origin/main")

    assert _release_contract_base_ref() == "origin/main"


def test_python_ci_fetches_base_ref_for_release_change_contract():
    workflow = (ROOT / ".github" / "workflows" / "ci-python.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow


def test_framework_changes_require_version_bump_when_base_ref_is_available():
    base = _release_contract_base_ref()
    if base is None:
        pytest.skip("no base ref available for local VERSION bump enforcement")

    changed = _changed_paths_against_base(base)
    framework_changes = sorted(path for path in changed if path and not _version_bump_exempt(path))
    version_changed = "VERSION" in changed

    assert not framework_changes or version_changed, (
        "framework changes require VERSION bump; changed files:\n"
        + "\n".join(f"- {path}" for path in framework_changes)
    )
