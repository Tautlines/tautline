import subprocess


def _git_repo(path):
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    return path


def _answer_interview(path):
    text = path.read_text(encoding="utf-8")
    text = text.replace("BOOTSTRAP REQUIRED", "project-specific bootstrap answer")
    path.write_text(text, encoding="utf-8")


def test_init_on_unmanaged_repo_writes_interview_and_prints_questions(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "new-product")

    res = run_cli("init", "--target", str(repo))

    assert res.returncode == 0, res.stderr
    assert (repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md").exists()
    assert "## Questions for the human operator" in res.stdout
    assert "backlog" in res.stdout.lower()
    assert "production" in res.stdout.lower()
    assert "preflight" in res.stdout.lower()
    assert "after answering, run: tautline init --target . --continue" in res.stdout


def test_init_reuses_existing_interview_without_overwriting_answers(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "existing-interview")
    interview = repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md"
    first = run_cli("init", "--target", str(repo))
    assert first.returncode == 0, first.stderr
    interview.write_text("partial human answers\n", encoding="utf-8")

    res = run_cli("init", "--target", str(repo))

    assert res.returncode == 0, res.stderr
    assert "interview_existing:" in res.stdout
    assert interview.read_text(encoding="utf-8") == "partial human answers\n"


def test_init_on_managed_repo_is_noop(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "managed-product")
    (repo / ".minervit-ai-delivery.json").write_text("{}\n", encoding="utf-8")
    (repo / ".ai-work").mkdir()
    (repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md").write_text("stale interview\n", encoding="utf-8")

    res = run_cli("init", "--target", str(repo))

    assert res.returncode == 0, res.stderr
    assert "already managed; run: tautline lane-start --target ." in res.stdout


def test_init_continue_on_managed_repo_is_noop(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "managed-product")
    (repo / ".minervit-ai-delivery.json").write_text('{"project":"Managed"}\n', encoding="utf-8")
    (repo / ".ai-work").mkdir()
    (repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md").write_text("stale interview\n", encoding="utf-8")

    res = run_cli("init", "--target", str(repo), "--continue")

    assert res.returncode == 0, res.stderr
    assert "already managed; run: tautline lane-start --target ." in res.stdout
    assert (repo / ".minervit-ai-delivery.json").read_text(encoding="utf-8") == '{"project":"Managed"}\n'
    assert not (repo / ".minervit" / "adapter.json").exists()


def test_init_continue_refuses_existing_source_adapter_without_generated_contract(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "partial-product")
    (repo / ".minervit").mkdir()
    (repo / ".minervit" / "adapter.json").write_text('{"project":"Partial"}\n', encoding="utf-8")
    first = run_cli("init", "--target", str(repo))
    assert first.returncode == 0, first.stderr
    _answer_interview(repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md")

    res = run_cli("init", "--target", str(repo), "--continue")

    assert res.returncode == 1
    assert "init_error: source adapter already exists" in res.stderr
    assert (repo / ".minervit" / "adapter.json").read_text(encoding="utf-8") == '{"project":"Partial"}\n'


def test_init_continue_refuses_to_overwrite_existing_instruction_files(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "existing-instructions")
    first = run_cli("init", "--target", str(repo))
    assert first.returncode == 0, first.stderr
    _answer_interview(repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md")
    (repo / "AGENTS.md").write_text("hand-authored instructions\n", encoding="utf-8")

    res = run_cli("init", "--target", str(repo), "--continue")

    assert res.returncode == 1
    assert "init_error: generated instruction file already exists" in res.stderr
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "hand-authored instructions\n"
    assert not (repo / ".minervit" / "adapter.json").exists()


def test_init_continue_with_answered_interview_renders_and_starts(run_cli, tmp_path):
    repo = _git_repo(tmp_path / "answered-product")
    first = run_cli("init", "--target", str(repo))
    assert first.returncode == 0, first.stderr
    _answer_interview(repo / ".ai-work" / "ADAPTER_BOOTSTRAP_INTERVIEW.md")

    res = run_cli("init", "--target", str(repo), "--continue")

    assert res.returncode == 0, res.stderr
    for name in ("CLAUDE.md", "AGENTS.md", ".tautline.json", ".tautline/adapter.json"):
        assert (repo / name).exists()
    assert "onboarded: yes" in res.stdout
    assert "generated: CLAUDE.md" in res.stdout
