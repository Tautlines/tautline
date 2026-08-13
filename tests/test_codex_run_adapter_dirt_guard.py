"""Item 69 / WS2: a review round never silently takes the generated adapters as its subject.

The product-repo wrapper (`review.codexWrapper`) flips to `--uncommitted` on ANY dirty tree. So on
2026-08-03, when an older runtime re-rendered `CLAUDE.md`/`AGENTS.md` under a live session, the
next review round's scope became a diff nobody wrote, and the round's whole budget went with it.

The guard is deliberately narrow, and the shape of that narrowness is what this suite pins:

- **adapter-only dirt refuses** -- there is no real subject matter, so the round is pure waste.
- **mixed dirt warns and proceeds** -- there IS real subject matter; refusing would be worse than
  the noise, but an `--uncommitted` round will still review the adapters, so say so.
- **git that cannot answer says NOTHING.** `run_git` returns the literal string `"unavailable"` on
  any non-zero exit, never `""` and never `None`. An `or ""` here would parse that sentinel as a
  porcelain line, drop `"vailable"` into `other_dirty`, and produce a guard that can never refuse
  (other_dirty is never empty) while warning about dirt on a clean tree. Both halves are pinned.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def review_repo(tmp_path):
    """A git repo with committed generated adapters and a sentinel wrapper.

    The wrapper creates a marker file, so "the wrapper never ran" is an assertion about the
    filesystem rather than about stdout -- a refusal that still executed the wrapper would have
    already burned the round.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    # Render BEFORE `git init`: validate_adapter_repo_matches_target compares the example
    # adapter's declared repo against the target's git remote, and a fresh local repo has none.
    rendered = subprocess.run(
        [
            sys.executable, str(CLI_PATH), "render-adapters",
            "--project", str(EXAMPLE_ADAPTER), "--target", str(repo), "--write",
        ],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "lane@example.test")
    _git(repo, "config", "user.name", "Lane")
    # The adapter declares its repo, and every verb that loads it checks the target's remote
    # against that declaration. Without this the guard under test is never reached.
    _git(repo, "remote", "add", "origin", "https://github.com/example-org/example-saas.git")

    # The wrapper path is the adapter's own `review.codexWrapper`, spelled exactly: `codex-run`
    # only records (and therefore only guards) an invocation that MATCHES it.
    marker = repo / "wrapper-ran.marker"
    wrapper = repo / "scripts" / "codex-review.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    wrapper.chmod(0o755)

    # What a real adopter has. The guard also drops the framework's own scratch on its own, so
    # this is realism rather than a crutch -- see test_framework_scratch_is_not_dirt.
    (repo / ".gitignore").write_text(".ai-work/\n.ai-runs/\n.impl-reviews/\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")

    # A REAL review subject: one commit ahead of the base. Item 75 (RCA 2026-07-28) added the
    # empty-subject refusal, and until then this harness reviewed `main` against `main` -- a
    # zero-byte scope. Every "the wrapper ran" assertion below was therefore passing over a review
    # of nothing, which is precisely the defect that refusal exists to catch. Without this commit
    # the subject refusal fires first and the dirt guard is never reached.
    _git(repo, "switch", "-q", "-c", "feature/dirt-guard")
    (repo / "subject.py").write_text("# the outgoing work this review is about\n", encoding="utf-8")
    _git(repo, "add", "subject.py")
    _git(repo, "commit", "-q", "-m", "real outgoing work")
    return repo, marker, env


def _codex_run(repo: Path, env: dict, *extra: str):
    return subprocess.run(
        [
            sys.executable, str(CLI_PATH), "codex-run", "--target", str(repo),
            "--risk-tier", "T1", "--review-round", "R1", *extra, "--", "./scripts/codex-review.sh",
        ],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120,
    )


def test_adapter_only_dirt_refuses_before_the_wrapper_runs(review_repo):
    repo, marker, env = review_repo
    (repo / "CLAUDE.md").write_text(
        (repo / "CLAUDE.md").read_text(encoding="utf-8") + "\n<!-- injected -->\n",
        encoding="utf-8",
    )

    result = _codex_run(repo, env)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "codex_run_error: adapter_dirt:" in result.stderr
    assert "CLAUDE.md" in result.stderr
    # Both continuations, built from the files that are ACTUALLY dirty (see the legacy-marker
    # test below for why a hard-coded pathspec is a dead end).
    assert "git diff HEAD -- CLAUDE.md" in result.stderr
    assert "git restore --source=HEAD --staged --worktree -- CLAUDE.md" in result.stderr
    assert "--allow-adapter-dirt" in result.stderr
    assert not marker.exists(), "the wrapper ran despite the refusal; the round is already spent"


def test_mixed_dirt_warns_and_proceeds(review_repo):
    repo, _marker, env = review_repo
    (repo / "CLAUDE.md").write_text(
        (repo / "CLAUDE.md").read_text(encoding="utf-8") + "\n<!-- injected -->\n",
        encoding="utf-8",
    )
    (repo / "src.py").write_text("real work\n", encoding="utf-8")

    result = _codex_run(repo, env)

    assert "codex_run_warning: adapter_dirt:" in result.stdout
    assert "CLAUDE.md" in result.stdout
    assert "codex_run_error: adapter_dirt:" not in result.stderr


def test_a_clean_tree_says_nothing(review_repo):
    repo, marker, env = review_repo

    result = _codex_run(repo, env)

    assert "adapter_dirt:" not in result.stdout
    assert "adapter_dirt:" not in result.stderr
    # NON-VACUITY. Asserting only the ABSENCE of a line is satisfied by any earlier refusal, and
    # that is not hypothetical: while item 75's empty-subject guard was landing, this test kept
    # passing over a run that never reached the dirt guard at all, hiding three sibling failures
    # from a naive pass count. "Said nothing" has to mean the run got all the way through.
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists(), "the wrapper never ran, so this test proved nothing about the guard"


def test_the_override_reviews_the_adapters_deliberately(review_repo):
    repo, _marker, env = review_repo
    (repo / "CLAUDE.md").write_text(
        (repo / "CLAUDE.md").read_text(encoding="utf-8") + "\n<!-- injected -->\n",
        encoding="utf-8",
    )

    result = _codex_run(repo, env, "--allow-adapter-dirt")

    assert "codex_run_error: adapter_dirt:" not in result.stderr
    assert "codex_run_warning: adapter_dirt:" in result.stdout
    assert "--allow-adapter-dirt" in result.stdout


def test_git_that_cannot_answer_produces_no_line_at_all(tmp_path):
    """The `"unavailable"` sentinel is a string, not an empty value -- and it is not dirt."""
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")

    not_a_repo = tmp_path / "loose"
    not_a_repo.mkdir()

    assert cli.adapter_only_dirty_files(not_a_repo) is None
    assert cli.codex_run_adapter_dirt_status(not_a_repo, allow=False) is None
    # Explicitly: the sentinel must never be parsed as a porcelain line. `"unavailable"[3:]` is
    # `"vailable"`, which would land in other_dirty and make the refusal unreachable forever.
    porcelain_args = ["status", "--porcelain", "--untracked-files=all"]
    assert cli.run_git(not_a_repo, porcelain_args) == "unavailable"


def test_a_target_below_the_git_root_still_matches(review_repo):
    """Porcelain prints paths relative to the REPO ROOT; the generated set is bare names.

    A bare-name membership test silently never matches for `--target <repo>/sub`, so the guard
    would be dead exactly where a monorepo lane runs it.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, env = review_repo

    sub = repo / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("<!-- GENERATED -->\nsub adapter\n", encoding="utf-8")
    other = repo / "other"
    other.mkdir()
    (other / "CLAUDE.md").write_text("<!-- GENERATED -->\nnot this target\n", encoding="utf-8")

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(sub)

    assert adapter_dirty == ["sub/CLAUDE.md"]
    assert "other/CLAUDE.md" in other_dirty


def test_an_adapter_file_renamed_away_is_still_adapter_dirt(review_repo):
    """Both sides of a rename (plan-review R1 A1).

    `R  CLAUDE.md -> CLAUDE.old` moves the adapter file OUT of the way. The destination is not an
    adapter path, so matching only the destination files it as ordinary dirt -- and the guard goes
    quiet on a change whose subject is the adapter itself.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, env = review_repo

    _git(repo, "mv", "CLAUDE.md", "CLAUDE.old")

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)

    assert any("CLAUDE" in name for name in adapter_dirty), (
        f"an adapter renamed away was classified as ordinary dirt: {adapter_dirty} / {other_dirty}"
    )


def test_quoted_and_untracked_porcelain_shapes_are_parsed(review_repo):
    """Untracked (`?? `), staged (`M `) and quoted paths all reach the same partition."""
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, env = review_repo

    (repo / "a file with spaces.txt").write_text("untracked\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text(
        (repo / "AGENTS.md").read_text(encoding="utf-8") + "\n<!-- injected -->\n",
        encoding="utf-8",
    )
    _git(repo, "add", "AGENTS.md")

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)

    assert adapter_dirty == ["AGENTS.md"]
    assert "a file with spaces.txt" in other_dirty


def test_framework_scratch_is_not_dirt(review_repo):
    """`codex-run` creates its own scratch BEFORE this guard runs.

    Lane state and the review-evidence log land under `.ai-work/` and `.ai-runs/` while the verb
    is starting up. If those counted as `other_dirty`, then on any repo that does not gitignore
    them `other_dirty` would never be empty -- so the adapter-only refusal could never fire, and
    the guard would fail OPEN. Same shape as mis-parsing the `"unavailable"` sentinel, arrived at
    from the opposite direction.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    (repo / ".gitignore").unlink()  # the adopter who never gitignored the framework's scratch
    for scratch in cli.FRAMEWORK_SCRATCH_DIRS:
        directory = repo / scratch
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "state.json").write_text("{}\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text(
        (repo / "CLAUDE.md").read_text(encoding="utf-8") + "\n<!-- injected -->\n",
        encoding="utf-8",
    )

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)

    assert adapter_dirty == ["CLAUDE.md"]
    assert other_dirty == [".gitignore"], (
        f"framework scratch leaked into other_dirty and would fail the guard open: {other_dirty}"
    )
    _message, blocking = cli.codex_run_adapter_dirt_status(repo, allow=False)
    assert blocking is False, "a deleted .gitignore is real dirt; that warns rather than refusing"

    # Restore it to its committed bytes: now the ONLY dirt is the adapter plus framework scratch,
    # and the refusal must fire despite the scratch being untracked and unignored.
    (repo / ".gitignore").write_text(
        ".ai-work/\n.ai-runs/\n.impl-reviews/\n", encoding="utf-8"
    )
    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)
    assert adapter_dirty == ["CLAUDE.md"]
    assert other_dirty == []
    message, blocking = cli.codex_run_adapter_dirt_status(repo, allow=False)
    assert blocking is True
    assert "codex_run_error: adapter_dirt:" in message


def test_a_handwritten_adapter_doc_is_the_lanes_own_work(review_repo):
    """R1 P2. A managed repo may deliberately keep a HAND-WRITTEN CLAUDE.md/AGENTS.md.

    The framework supports that shape on purpose -- `protected_handwritten_markdown` skips those
    files on every render, `render-adapters --json-only` exists for exactly this layout, and this
    repository is itself one of them. Editing such a document is real work. A path-only match would
    classify it as a tool-injected re-render and REFUSE the review of that work: a false refusal on
    the review boundary, which is the one place this guard cannot afford to be wrong.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    handwritten = repo / "CLAUDE.md"
    handwritten.write_text("# Product - Claude Bootstrap\n\nhand-written, never rendered\n", encoding="utf-8")
    assert not cli.is_methodology_generated_markdown(handwritten)

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)

    assert adapter_dirty == [], f"a hand-written adapter doc was called generated: {adapter_dirty}"
    assert "CLAUDE.md" in other_dirty
    assert cli.codex_run_adapter_dirt_status(repo, allow=False) is None, (
        "the review of a hand-written adapter doc was refused or warned about"
    )

    # The JSON lane adapter has no hand-written variant -- it is generated by definition, so the
    # path match still stands for it and the guard still fires.
    lane_json = repo / cli.LANE_ADAPTER_FILE
    lane_json.write_text(lane_json.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    adapter_dirty, _other = cli.adapter_only_dirty_files(repo)
    assert cli.LANE_ADAPTER_FILE in adapter_dirty


def test_a_deleted_generated_adapter_is_still_adapter_dirt(review_repo):
    """R2 P2. A deleted file has no header to read, so ask the COMMITTED version what it was.

    Without this the deletion of a generated `CLAUDE.md` reads as ordinary dirt and the round gets
    no signal at all that its scope includes the adapter -- the guard goes quiet on a change whose
    subject IS the adapter. `--allow-adapter-dirt` remains the escape for a deliberate removal, so
    this is a signal, not a dead end.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    (repo / "CLAUDE.md").unlink()

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)

    assert adapter_dirty == ["CLAUDE.md"], (
        f"a deleted generated adapter was classified as ordinary dirt: "
        f"{adapter_dirty} / {other_dirty}"
    )
    message, blocking = cli.codex_run_adapter_dirt_status(repo, allow=False)
    assert blocking is True
    assert "--allow-adapter-dirt" in message

    # A deleted HAND-WRITTEN adapter doc is still the lane's own work, by the same rule read from
    # the other side: the committed version carries no generated header.
    handwritten = repo / "AGENTS.md"
    handwritten.write_text("# Product - Codex Bootstrap\n\nhand-written\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "adopt a hand-written AGENTS.md")
    handwritten.unlink()

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)
    assert "AGENTS.md" in other_dirty
    assert "AGENTS.md" not in adapter_dirty


def test_the_discard_remedy_names_the_marker_this_repo_actually_has(review_repo):
    """R3 P2. A legacy lane's generated marker is `.minervit-ai-delivery.json`.

    A refusal that prints `git checkout -- .tautline.json` into a repo with no such file dies on
    "pathspec did not match" -- and a blocking refusal whose remedy does not run is a dead end,
    which is the one thing this framework's refusals may never be. The pathspec is therefore built
    from the files that are actually dirty.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    # A legacy-only lane: the canonical marker does not exist at all.
    legacy = repo / cli.LEGACY_LANE_ADAPTER_FILE
    legacy.write_text((repo / cli.LANE_ADAPTER_FILE).read_text(encoding="utf-8"), encoding="utf-8")
    (repo / cli.LANE_ADAPTER_FILE).unlink()
    (repo / "CLAUDE.md").unlink()
    (repo / "AGENTS.md").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "legacy-only lane")
    legacy.write_text(legacy.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)
    assert adapter_dirty == [cli.LEGACY_LANE_ADAPTER_FILE], (adapter_dirty, other_dirty)

    message, blocking = cli.codex_run_adapter_dirt_status(repo, allow=False)
    assert blocking is True
    assert f"--staged --worktree -- {cli.LEGACY_LANE_ADAPTER_FILE}" in message
    assert ".tautline.json" not in message, (
        "the remedy names a file this repository does not have; the pathspec would not match"
    )


def test_a_typechange_on_a_generated_adapter_is_still_adapter_dirt(review_repo):
    """R4. Replacing a generated adapter with a symlink emits porcelain status `T`.

    An enumerated status class that misses a code leaves the whole line unparsed, the raw text
    becomes the "path", it resolves to nothing, and the change slips the guard entirely. The class
    is therefore every uppercase code plus `?`/`!` and space, not a hand-listed set.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    # Point at a NON-generated file on purpose. Symlinking to AGENTS.md would pass even with a
    # symlink-following resolve, because the target carries a generated header of its own -- the
    # test would then prove nothing about the typechange.
    plain = repo / "notes.txt"
    plain.write_text("not a generated adapter\n", encoding="utf-8")
    claude = repo / "CLAUDE.md"
    claude.unlink()
    claude.symlink_to("notes.txt")

    porcelain = cli.run_git(repo, ["status", "--porcelain", "--untracked-files=all"])
    assert "T" in porcelain.split()[0], f"expected a typechange status, got {porcelain!r}"

    adapter_dirty, other_dirty = cli.adapter_only_dirty_files(repo)

    assert adapter_dirty == ["CLAUDE.md"], (adapter_dirty, other_dirty)


def test_a_renamed_adapter_remedy_covers_both_sides(review_repo):
    """R4 P2. `git checkout -- CLAUDE.old` neither shows nor undoes the DELETION of CLAUDE.md.

    A rename is one porcelain line but two working-tree changes. A remedy naming only the
    destination leaves the lane stuck behind a blocking refusal it cannot clear -- the same
    dead-end class as R3's hard-coded pathspec, reached from a different direction.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    _git(repo, "mv", "CLAUDE.md", "CLAUDE.old")

    adapter_dirty, _other = cli.adapter_only_dirty_files(repo)
    assert "CLAUDE.md" in adapter_dirty, adapter_dirty
    assert "CLAUDE.old" in adapter_dirty, adapter_dirty

    message, blocking = cli.codex_run_adapter_dirt_status(repo, allow=False)
    assert blocking is True
    assert "CLAUDE.md" in message and "CLAUDE.old" in message


@pytest.mark.parametrize(
    "shape",
    ["unstaged", "staged", "untracked", "staged-deletion", "renamed", "staged-add"],
)
def test_the_discard_remedy_actually_clears_every_status_it_classifies(review_repo, shape):
    """R5 P2, and the CLASS behind R3/R4/R5 rather than the instance.

    `git diff` shows nothing staged or untracked, and `git checkout` neither unstages a change nor
    removes an untracked file -- so for two of the three shapes this guard classifies, the
    advertised discard command left the dirt in place and the refusal fired again immediately. A
    blocking refusal whose remedy does not clear the condition is a dead end with extra steps.

    This runs the printed command and asserts the guard goes quiet, rather than asserting on the
    text: the property under test is that the remedy WORKS.
    """
    from importlib import import_module

    sys.path.insert(0, str(REPO_ROOT / "src"))
    cli = import_module("tautline_methodology.cli")
    repo, _marker, _env = review_repo

    claude = repo / "CLAUDE.md"
    if shape == "untracked":
        _git(repo, "rm", "-q", "--cached", "CLAUDE.md")
        _git(repo, "commit", "-q", "-m", "untrack the generated adapter")
    elif shape == "staged-deletion":
        # `git ls-files` reads the INDEX, so a staged deletion looks untracked there -- and the
        # remedy would become `git clean` on a path that no longer exists, which does nothing.
        _git(repo, "rm", "-q", "CLAUDE.md")
    elif shape == "staged-add":
        # In the INDEX but not in HEAD. `git clean` ignores staged additions, so a remedy that
        # reaches for it leaves the adapter staged and still in the next review's scope.
        _git(repo, "rm", "-q", "--cached", "CLAUDE.md")
        _git(repo, "commit", "-q", "-m", "untrack the generated adapter")
        _git(repo, "add", "CLAUDE.md")
    elif shape == "renamed":
        # A rename is a staged deletion of the source plus an addition of the destination; the
        # source needs restore-from-HEAD and the destination needs clean.
        _git(repo, "mv", "CLAUDE.md", "CLAUDE.old")
    else:
        claude.write_text(
            claude.read_text(encoding="utf-8") + "\n<!-- injected -->\n", encoding="utf-8"
        )
        if shape == "staged":
            _git(repo, "add", "CLAUDE.md")

    message, blocking = cli.codex_run_adapter_dirt_status(repo, allow=False)
    assert blocking is True, f"{shape} adapter dirt did not refuse: {message}"

    # Run every `git ...` command the refusal advertises as a discard step, in order.
    for command in re.findall(r"`(git (?:restore|rm|clean)[^`]*)`", message):
        subprocess.run(command, cwd=str(repo), shell=True, check=True, capture_output=True)

    assert cli.codex_run_adapter_dirt_status(repo, allow=False) is None, (
        f"the advertised discard commands did not clear {shape} adapter dirt; "
        f"the refusal would fire again"
    )
