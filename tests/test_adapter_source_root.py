"""prod-onboarding-1 (productization): an operator can keep the SOURCE adapter OUT of the framework
repo by designating a trusted adapter root via MINERVIT_METHODOLOGY_ADAPTER_ROOT (a private
minervit-adapters repo, or the adopter's own repo). Adapters under that root are accepted as
canonical source adapters; everything else (ad-hoc/lane-local JSON) is still rejected.
"""

import argparse
import json
import shutil
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


# --- the $schema an adapter carries must outlive the tree that wrote it ------------------------
#
# Adapters written OUTSIDE the target repo get a relative `$schema` pointing at the framework's
# adapter-schema.json. Resolved against REPO_ROOT that is fine on a dev checkout -- but under
# snapshot execution REPO_ROOT is `<store>/<sha12>`, an immutable export that prune COLLECTS. The
# adapter is durable; the tree it was written from is not. Anchor the path on the canonical
# checkout, which is the one methodology tree that persists across every release.


def _schema_probe(cli, tmp_path, monkeypatch):
    """Run init-project-adapter as if executing from a snapshot, writing outside the target repo."""
    canonical = tmp_path / "canonical"
    (canonical / "methodology").mkdir(parents=True)
    (canonical / "methodology" / "adapter-schema.json").write_text("{}", encoding="utf-8")
    snapshot = tmp_path / "store" / "abc123abc123"
    (snapshot / "methodology").mkdir(parents=True)
    (snapshot / "methodology" / "adapter-schema.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cli, "REPO_ROOT", snapshot)
    monkeypatch.setattr(cli, "canonical_methodology_repo", lambda: canonical)

    target = tmp_path / "product"
    target.mkdir()
    output = tmp_path / "private-adapters" / "product.json"  # not repo-local: the relpath branch
    assert cli.init_project_adapter(
        argparse.Namespace(
            target=target,
            project_name="Product",
            output=output,
            overwrite=False,
            repo="acme/product",
        )
    ) == 0
    return canonical, snapshot, output


def test_init_project_adapter_schema_does_not_point_into_the_snapshot_store(
    cli, tmp_path, monkeypatch
):
    canonical, snapshot, output = _schema_probe(cli, tmp_path, monkeypatch)

    schema = json.loads(output.read_text(encoding="utf-8"))["$schema"]
    assert str(snapshot) not in schema, schema
    assert "abc123abc123" not in schema, schema

    # It resolves to the canonical checkout's schema -- and keeps resolving after prune collects
    # the snapshot this adapter was written from.
    resolved = (output.parent / schema).resolve()
    assert resolved == (canonical / "methodology" / "adapter-schema.json").resolve()
    shutil.rmtree(snapshot)
    assert resolved.is_file(), "the $schema dangles once the snapshot is pruned"
