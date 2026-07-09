def test_find_adapter_root_prefers_tautline(cli, tmp_path):
    (tmp_path / ".tautline.json").write_text("{}")
    assert cli.find_adapter_root(tmp_path) == tmp_path


def test_find_adapter_root_falls_back_to_legacy(cli, tmp_path):
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}")
    assert cli.find_adapter_root(tmp_path) == tmp_path


def test_write_target_is_tautline(cli):
    assert cli.LANE_ADAPTER_FILE == ".tautline.json"
    assert cli.LEGACY_LANE_ADAPTER_FILE == ".minervit-ai-delivery.json"


def test_source_adapter_write_target_is_tautline_dir(cli):
    assert cli.REPO_LOCAL_ADAPTER_FILE == ".tautline/adapter.json"
    assert cli.LEGACY_REPO_LOCAL_ADAPTER_FILE == ".minervit/adapter.json"


def test_repo_local_source_adapter_path_falls_back_to_legacy(cli, tmp_path):
    legacy = tmp_path / ".minervit" / "adapter.json"
    legacy.parent.mkdir()
    legacy.write_text("{}")
    assert cli.repo_local_source_adapter_path(tmp_path) == legacy


def test_repo_local_source_adapter_path_prefers_canonical(cli, tmp_path):
    canonical = tmp_path / ".tautline" / "adapter.json"
    canonical.parent.mkdir()
    canonical.write_text("{}")
    legacy = tmp_path / ".minervit" / "adapter.json"
    legacy.parent.mkdir()
    legacy.write_text("{}")
    assert cli.repo_local_source_adapter_path(tmp_path) == canonical


def test_adapter_marker_path_prefers_canonical(cli, tmp_path):
    (tmp_path / ".tautline.json").write_text("{}")
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}")
    assert cli.adapter_marker_path(tmp_path) == tmp_path / ".tautline.json"


def test_adapter_marker_path_falls_back_to_legacy(cli, tmp_path):
    (tmp_path / ".minervit-ai-delivery.json").write_text("{}")
    assert cli.adapter_marker_path(tmp_path) == tmp_path / ".minervit-ai-delivery.json"


def test_legacy_source_adapter_stays_trusted_when_both_files_exist(cli, tmp_path):
    # Split-brain edge: a repo with BOTH .tautline/adapter.json and .minervit/adapter.json
    # whose marker recorded the legacy path must keep trusting the legacy file.
    canonical = tmp_path / ".tautline" / "adapter.json"
    canonical.parent.mkdir()
    canonical.write_text("{}")
    legacy = tmp_path / ".minervit" / "adapter.json"
    legacy.parent.mkdir()
    legacy.write_text("{}")
    assert cli.is_repo_local_source_adapter(canonical, tmp_path)
    assert cli.is_repo_local_source_adapter(legacy, tmp_path)


def test_explicit_legacy_render_records_legacy_source(cli, run_cli, tmp_path):
    # Codex R2 P2: with BOTH source files present, an explicit --project
    # .minervit/adapter.json render must record (and hash) the legacy file,
    # not silently relabel it as the canonical path.
    import hashlib
    import json
    import shutil
    import subprocess
    target = tmp_path / "dual-source"
    target.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.email", "t@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin", "git@github.com:example-org/example-saas.git"], check=True)
    (target / "README.md").write_text("# F\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "add", "."], check=True)
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "init"], check=True)
    example = cli.REPO_ROOT / "adapters" / "projects" / "example-saas.json"
    legacy = target / ".minervit" / "adapter.json"
    legacy.parent.mkdir()
    shutil.copy2(example, legacy)
    canonical = target / ".tautline" / "adapter.json"
    canonical.parent.mkdir()
    data = json.loads(example.read_text(encoding="utf-8"))
    data["project"] = "Different Canonical"
    canonical.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rendered = run_cli("render-adapters", "--project", str(legacy), "--target", str(target), "--write", "--json-only")
    assert rendered.returncode == 0, rendered.stderr
    marker = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert marker["_generated"]["sourceAdapter"] == ".minervit/adapter.json"
    assert marker["_generated"]["sourceAdapterSha256"] == hashlib.sha256(legacy.read_bytes()).hexdigest()
