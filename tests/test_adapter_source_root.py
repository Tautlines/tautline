"""prod-onboarding-1 (productization): an operator can keep the SOURCE adapter OUT of the framework
repo by designating a trusted adapter root via MINERVIT_METHODOLOGY_ADAPTER_ROOT (a private
minervit-adapters repo, or the adopter's own repo). Adapters under that root are accepted as
canonical source adapters; everything else (ad-hoc/lane-local JSON) is still rejected.
"""

import hashlib
import json
import subprocess


def test_framework_adapters_dir_is_trusted(cli):
    p = cli.REPO_ROOT / "adapters" / "projects" / "example-saas.json"
    assert cli.source_adapter_requires_bootstrap_evidence(p) is True


def test_arbitrary_path_is_not_trusted(cli, tmp_path):
    p = tmp_path / "rogue" / "adapter.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    assert cli.source_adapter_requires_bootstrap_evidence(p) is False


def test_operator_designated_root_is_trusted(cli, tmp_path, monkeypatch):
    private = tmp_path / "minervit-adapters"
    (private / "adapters" / "projects").mkdir(parents=True)
    adapter = private / "adapters" / "projects" / "acme.json"
    adapter.write_text("{}")
    monkeypatch.setenv("MINERVIT_METHODOLOGY_ADAPTER_ROOT", str(private))
    assert cli.source_adapter_requires_bootstrap_evidence(adapter) is True
    # a sibling outside the designated root is still rejected
    outside = tmp_path / "elsewhere" / "adapter.json"
    outside.parent.mkdir(parents=True)
    outside.write_text("{}")
    assert cli.source_adapter_requires_bootstrap_evidence(outside) is False


def test_trusted_roots_listing(cli, tmp_path, monkeypatch):
    monkeypatch.delenv("MINERVIT_METHODOLOGY_ADAPTER_ROOT", raising=False)
    assert cli.trusted_source_adapter_roots() == [(cli.REPO_ROOT / "adapters/projects").resolve()]
    monkeypatch.setenv("MINERVIT_METHODOLOGY_ADAPTER_ROOT", str(tmp_path))
    roots = cli.trusted_source_adapter_roots()
    assert tmp_path.resolve() in roots and len(roots) == 2


def _init_example_saas_repo(tmp_path):
    remote = tmp_path / "example-org" / "example-saas.git"
    target = tmp_path / "adopter"
    remote.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin", str(remote)], check=True)
    (target / "README.md").write_text("# Example\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(target), "push", "-q", "-u", "origin", "main"], check=True)
    return target


def test_repo_local_adapter_migration_starts_lane_without_rewriting_source_absolute(cli, run_cli, tmp_path):
    target = _init_example_saas_repo(tmp_path)
    source = target / ".tautline" / "adapter.json"

    migrated = run_cli(
        "migrate-adapter",
        str(cli.REPO_ROOT / "adapters/projects/example-saas.json"),
        "--adopter-target",
        str(target),
        "--write",
    )
    assert migrated.returncode == 0, migrated.stderr
    assert source.exists()

    rendered = run_cli(
        "render-adapters",
        "--project",
        str(source),
        "--target",
        str(target),
        "--write",
        "--json-only",
    )
    assert rendered.returncode == 0, rendered.stderr
    generated = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert generated["_generated"]["sourceAdapter"] == ".tautline/adapter.json"
    assert generated["_generated"]["sourceAdapterSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()

    subprocess.run(["git", "-C", str(target), "add", "."], check=True)
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "repo-local adapter"], check=True)
    subprocess.run(["git", "-C", str(target), "push", "-q"], check=True)

    started = run_cli("lane-start", "--target", str(target), "--skip-update")
    assert started.returncode == 0, started.stderr
    combined = started.stdout + started.stderr
    assert "sourceAdapter is missing" not in combined
    assert "sourceAdapter does not point at a trusted source adapter" not in combined
    assert "sourceAdapterSha256 does not match" not in combined

    after_start = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert after_start["_generated"]["sourceAdapter"] == ".tautline/adapter.json"
    assert after_start["_generated"]["sourceAdapterSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_init_project_adapter_defaults_to_repo_local_adapter(cli, run_cli, tmp_path):
    target = tmp_path / "new-adopter"
    target.mkdir()

    initialized = run_cli(
        "init-project-adapter",
        "--target",
        str(target),
        "--project-name",
        "Repo Local Init Probe",
        "--repo",
        "acme/repo-local-init-probe",
    )

    assert initialized.returncode == 0, initialized.stderr
    source = target / ".tautline" / "adapter.json"
    assert source.exists()
    legacy_path = cli.REPO_ROOT / "adapters" / "projects" / "repo-local-init-probe.json"
    assert not legacy_path.exists()
    assert "adapters/projects" not in initialized.stdout
    assert f"--project {source}" in initialized.stdout
    assert f"--target {target}" in initialized.stdout

    data = json.loads(source.read_text(encoding="utf-8"))
    assert data["project"] == "Repo Local Init Probe"
    assert data["repo"] == "acme/repo-local-init-probe"
    assert data["$schema"].startswith("https://")
    assert str(cli.REPO_ROOT) not in source.read_text(encoding="utf-8")
    assert "/Users/" not in source.read_text(encoding="utf-8")
