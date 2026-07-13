"""Tests for the release tail: registry copy, `release-tail`, and `release-drift-check`.

Everything here is hermetic. The real tail pushes to a public mirror, creates a
GitHub Release, and publishes to two registries -- all irreversible. So the tests
intercept the one subprocess boundary (`run_command`) and the one network boundary
(`release_http_json`), and assert on the commands that WOULD have been run.
"""

import json
import re
from pathlib import Path

import pytest

MIRROR = "tautlines/tautline"
NOTES_BLOCK = {
    "version": "0.9.7",
    "date": "2026-07-13",
    "body": "\n### Added\n\n- A thing.\n",
}


# --------------------------------------------------------------------------
# Hermetic world: models the mirror, the GitHub Release, the workflow runs and
# the two registries. Intercepts `run_command` (every git/gh subprocess) and
# `release_http_json` (every registry lookup). Nothing here touches a network,
# a real `gh`, or a real push.
# --------------------------------------------------------------------------
class World:
    def __init__(
        self,
        *,
        mirror_head="mirror0ldhead",
        new_sha="newc0mmitsha",
        mirror_changed=True,
        tag_sha=None,
        tag_peeled=None,
        release=None,
        npm_versions=(),
        pypi_versions=(),
        runs=None,
        export_issues=(),
    ):
        self.mirror_head = mirror_head
        self.new_sha = new_sha
        self.mirror_changed = mirror_changed
        self.tag_sha = tag_sha                 # None => tag absent on the mirror
        # The sha the tag ref PEELS to. An annotated tag's ref points at a tag
        # OBJECT (tag_sha) that dereferences to a commit (tag_peeled); a
        # lightweight tag has no peeled entry and tag_sha is already the commit.
        self.tag_peeled = tag_peeled
        self.release = release                 # None => no Release; else dict(isDraft=...)
        self.npm_versions = list(npm_versions)
        self.pypi_versions = list(pypi_versions)
        self.runs = runs if runs is not None else {}   # workflow file -> [run dicts]
        self.export_issues = list(export_issues)

        self.commands = []          # every argv run_command saw
        self.commit_parents = []    # HEAD at the moment each commit was created
        self.export_destination = None
        self.clone_dir = None
        self.head = mirror_head     # the clone's current HEAD
        self.dispatched = []        # (workflow, version, ref)

    # -- seams -------------------------------------------------------------
    def run_command(self, command, cwd=None, timeout=None, env=None):
        command = [str(part) for part in command]
        self.commands.append(command)
        return self._dispatch(command)

    def export_repository(self, source_root, destination, **kwargs):
        self.export_destination = destination
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "VERSION").write_text("0.9.7\n")
        return {"files": 3, "commit": "exp0rt", "issues": list(self.export_issues)}

    def http_json(self, url, timeout=20):
        if "registry.npmjs.org" in url:
            versions = self.npm_versions
        elif "pypi.org" in url:
            versions = self.pypi_versions
        else:
            raise AssertionError(f"unexpected URL: {url}")
        if not versions:
            return None
        return {
            "dist-tags": {"latest": versions[-1]},
            "versions": {v: {} for v in versions},
            "info": {"version": versions[-1]},
            "releases": {v: [] for v in versions},
        }

    # -- the modelled world ------------------------------------------------
    def _dispatch(self, command):
        joined = " ".join(command)

        if command[:2] == ["git", "clone"]:
            self.clone_dir = command[-1]
            clone = Path(self.clone_dir)
            (clone / ".git").mkdir(parents=True, exist_ok=True)
            (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            (clone / "VERSION").write_text("0.9.6\n")     # the mirror's current content
            (clone / "STALE.md").write_text("dropped by the export\n")
            return 0, "", ""
        if "rev-parse" in command and "HEAD" in command:
            return 0, self.head, ""
        if "status" in command and "--porcelain" in command:
            return 0, ("M VERSION" if self.mirror_changed else ""), ""
        if command[3:4] == ["add"] or "add" in command[:5] and "-A" in command:
            return 0, "", ""
        if "commit" in command:
            self.commit_parents.append(self.head)   # the commit lands ON TOP of this
            self.head = self.new_sha
            return 0, "", ""
        if "ls-remote" in command:
            if self.tag_sha:
                lines = [f"{self.tag_sha}\trefs/tags/v0.9.7"]
                # Real git reports a peeled entry for an ANNOTATED tag only.
                if self.tag_peeled:
                    lines.append(f"{self.tag_peeled}\trefs/tags/v0.9.7^{{}}")
                return 0, "\n".join(lines), ""
            return 0, "", ""
        if command[:1] == ["git"] and "tag" in command:
            # `bin/tautline` creates the tag with `git tag -a`: ANNOTATED. The ref
            # therefore points at a tag object, which peels to the commit.
            self.tag_sha = f"tagobject0f{self.head}"
            self.tag_peeled = self.head
            return 0, "", ""
        if "push" in command:
            return 0, "", ""
        if "config" in command:
            return 0, "", ""

        if command[:3] == ["gh", "release", "view"]:
            if self.release is None:
                return 1, "", "release not found"
            return 0, json.dumps(self.release), ""
        if command[:3] == ["gh", "release", "create"]:
            self.release = {
                "isDraft": "--draft" in command,
                "tagName": "v0.9.7",
                "targetCommitish": self.head,
                "url": "https://github.com/tautlines/tautline/releases/tag/v0.9.7",
            }
            return 0, self.release["url"], ""
        if command[:3] == ["gh", "release", "edit"]:
            assert self.release is not None
            self.release["isDraft"] = False
            return 0, "", ""
        if command[:3] == ["gh", "workflow", "run"]:
            workflow = command[3]
            version = next((p.split("=", 1)[1] for p in command if p.startswith("version=")), None)
            ref = command[command.index("--ref") + 1] if "--ref" in command else None
            self.dispatched.append((workflow, version, ref))
            # the dispatched workflow publishes: the registry acquires the version
            if version:
                target = self.npm_versions if "npm" in workflow else self.pypi_versions
                target.append(version)
            # a dispatch produces a run at the tag's commit
            self.runs.setdefault(workflow, []).append(
                {
                    "databaseId": 999,
                    # A workflow run reports the COMMIT it ran at, never a tag object.
                    "headSha": self.tag_peeled or self.tag_sha or self.head,
                    "headBranch": "v0.9.7",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "url": f"https://github.com/{MIRROR}/actions/runs/999",
                }
            )
            return 0, "", ""
        if command[:3] == ["gh", "run", "list"]:
            workflow = command[command.index("--workflow") + 1]
            return 0, json.dumps(self.runs.get(workflow, [])), ""

        raise AssertionError(f"unmodelled command: {joined}")


def install(cli, monkeypatch, world):
    monkeypatch.setattr(cli, "run_command", world.run_command)
    monkeypatch.setattr(cli, "public_release_export_repository", world.export_repository)
    monkeypatch.setattr(cli, "release_http_json", world.http_json)
    monkeypatch.setattr(cli, "plugin_version", lambda: "0.9.7")
    monkeypatch.setattr(
        cli,
        "changelog_release_block",
        lambda version: dict(NOTES_BLOCK),
    )
    monkeypatch.setattr(
        cli,
        "changelog_release_blocks",
        lambda path=None: [dict(NOTES_BLOCK)],
    )
    return world


def tail_args(cli, **overrides):
    defaults = dict(
        dry_run=False,
        skip_registry=False,
        # Deliberately tiny: in a passing scenario the matching run is found on the
        # first poll, so a real wait means something is wrong -- and the suite should
        # find that out in seconds, not spin.
        timeout=2,
        poll_interval=0,
        allow_empty_private_terms=True,
        private_terms_file=None,
    )
    defaults.update(overrides)
    return cli.argparse.Namespace(**defaults)


def successful_runs(sha):
    return {
        "publish-npm.yml": [
            {
                "databaseId": 1,
                "headSha": sha,
                "headBranch": "v0.9.7",
                "event": "release",
                "status": "completed",
                "conclusion": "success",
                "url": "u1",
            }
        ],
        "publish-pypi.yml": [
            {
                "databaseId": 2,
                "headSha": sha,
                "headBranch": "v0.9.7",
                "event": "release",
                "status": "completed",
                "conclusion": "success",
                "url": "u2",
            }
        ],
    }


def gh_calls(world):
    return [c for c in world.commands if c[0] == "gh"]


def push_calls(world):
    return [c for c in world.commands if "push" in c]


# --------------------------------------------------------------------------
# Task 2: `release-tail` -- the button
# --------------------------------------------------------------------------


def test_dry_run_mutates_nothing_and_prints_the_whole_plan(cli, monkeypatch, capsys):
    world = install(cli, monkeypatch, World())
    assert cli.release_tail(tail_args(cli, dry_run=True)) == 0
    out = capsys.readouterr().out

    assert world.commands == [], "a dry run must not shell out at all"
    assert world.export_destination is None, "a dry run must not write an export"
    assert "release_tail_mode: dry-run" in out
    for step in ("export", "mirror", "tag", "release", "publish", "drift"):
        assert f"release_tail_plan_{step}" in out, f"the plan must name the {step} step"
    assert MIRROR in out


def test_mirror_commit_lands_on_the_mirrors_previous_head(cli, monkeypatch, capsys):
    """The export is a FRESH repo with a root commit -- it shares no ancestor with
    the mirror. The mirror commit must therefore be built by overlaying the export
    onto a clone of the mirror and committing on top of the mirror's current HEAD."""
    world = install(cli, monkeypatch, World(mirror_head="0ldm1rr0r"))
    world.runs = successful_runs("newc0mmitsha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]

    assert cli.release_tail(tail_args(cli)) == 0

    assert world.commit_parents == ["0ldm1rr0r"], (
        f"the mirror commit's parent must be the mirror's previous HEAD, got {world.commit_parents}"
    )
    clones = [c for c in world.commands if c[:2] == ["git", "clone"]]
    assert clones, "the mirror must be cloned (real history), not re-created"
    # the tree we push is the clone, never the fresh export repo
    pushes = push_calls(world)
    assert pushes, "the mirror commit must be pushed"
    for push in pushes:
        assert world.clone_dir in push, "the push must come from the mirror clone"
    assert str(world.export_destination) != world.clone_dir


def test_no_force_push_is_ever_constructed(cli, monkeypatch):
    world = install(cli, monkeypatch, World())
    world.runs = successful_runs("newc0mmitsha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]
    assert cli.release_tail(tail_args(cli)) == 0

    for command in push_calls(world):
        joined = " ".join(command)
        assert "--force" not in command, f"force-push constructed: {joined}"
        assert "-f" not in command, f"force-push constructed: {joined}"
        assert "--force-with-lease" not in command, f"force-push constructed: {joined}"
        assert not any(part.startswith("+") for part in command), f"force refspec: {joined}"


def test_every_gh_call_is_pinned_to_the_public_repo(cli, monkeypatch):
    """Run from this checkout, bare `gh` defaults to tautlines/tautline-dev. An
    unpinned call creates the Release in the wrong repo: a silent no-op where the
    mirror's publish workflows never fire."""
    world = install(cli, monkeypatch, World())
    world.runs = successful_runs("newc0mmitsha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]
    assert cli.release_tail(tail_args(cli)) == 0

    calls = gh_calls(world)
    assert calls, "the tail must talk to gh"
    for command in calls:
        assert "--repo" in command, (
            f"unpinned gh call (defaults to the dev repo!): {' '.join(command)}"
        )
        assert command[command.index("--repo") + 1] == MIRROR, f"gh call not pinned to {MIRROR}"


def test_release_is_created_against_the_exact_pushed_sha(cli, monkeypatch):
    world = install(cli, monkeypatch, World(new_sha="pushed5ha"))
    world.runs = successful_runs("pushed5ha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]
    assert cli.release_tail(tail_args(cli)) == 0

    create = [c for c in world.commands if c[:3] == ["gh", "release", "create"]]
    assert create, "a Release must be created"
    command = create[0]
    assert "--target" in command
    assert command[command.index("--target") + 1] == "pushed5ha"


def test_refuses_when_the_export_gate_is_not_ok(cli, monkeypatch, capsys):
    world = install(
        cli,
        monkeypatch,
        World(
            # NB: a literal private-adapter path here would itself trip the
            # public-release scanner when this test file is exported. The gate only
            # cares that the export returned issues at all, so keep the sample inert.
            export_issues=[
                {
                    "code": "private-term",
                    "path": "docs/example.md",
                    "message": "private term in a public surface",
                }
            ]
        ),
    )
    assert cli.release_tail(tail_args(cli)) != 0
    err = capsys.readouterr().err
    assert "release_tail_error" in err
    assert push_calls(world) == [], "nothing may be pushed when the export gate blocks"
    assert gh_calls(world) == []


@pytest.mark.parametrize(
    "leak",
    [
        "METH-FU-CLI-PACKAGE-SPLIT",
        "docs/backlog/roadmap.md",
        "docs/productization/pricing.md",
        # A local absolute path. Deliberately not a real username: the repo-wide
        # boundary scan forbids person-specific machine tokens in any tracked file,
        # and this fixture only needs the `/Users/` prefix to exercise the guard.
        "/Users/operator/secret",
    ],
)
def test_refuses_when_the_release_notes_contain_a_leak_term(cli, monkeypatch, capsys, leak):
    """Release notes are a permanent public surface; a leak cannot be taken back."""
    world = install(cli, monkeypatch, World())
    monkeypatch.setattr(
        cli,
        "changelog_release_block",
        lambda version: {**NOTES_BLOCK, "body": f"\n### Added\n\n- See {leak}\n"},
    )
    assert cli.release_tail(tail_args(cli)) != 0
    err = capsys.readouterr().err
    assert "release_tail_error" in err
    assert push_calls(world) == []
    assert gh_calls(world) == []


def test_refuses_when_version_disagrees_with_the_changelog(cli, monkeypatch, capsys):
    world = install(cli, monkeypatch, World())
    monkeypatch.setattr(
        cli,
        "changelog_release_blocks",
        lambda path=None: [{"version": "0.9.5", "date": "2026-07-01", "body": "\n- Older.\n"}],
    )
    monkeypatch.setattr(cli, "changelog_release_block", lambda version: None)
    assert cli.release_tail(tail_args(cli)) != 0
    err = capsys.readouterr().err
    assert "release_tail_error" in err
    assert "0.9.5" in err and "0.9.7" in err
    assert push_calls(world) == []


# -- resume semantics ------------------------------------------------------


def test_resumes_from_mirror_pushed_but_not_tagged(cli, monkeypatch, capsys):
    """The mirror already carries this tree (a previous run pushed it and died)."""
    world = install(cli, monkeypatch, World(mirror_head="alreadypushed", mirror_changed=False))
    world.runs = successful_runs("alreadypushed")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]

    assert cli.release_tail(tail_args(cli)) == 0
    out = capsys.readouterr().out

    assert world.commit_parents == [], "an unchanged mirror must not get an empty duplicate commit"
    assert push_calls(world), "the tag still has to be pushed"
    assert "release_tail_mirror: current" in out
    tags = [c for c in world.commands if c[0] == "git" and "tag" in c]
    assert tags, "the tail must continue to the tag step"
    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]]


def test_resumes_from_tagged_but_no_release(cli, monkeypatch):
    world = install(
        cli,
        monkeypatch,
        World(mirror_head="taggedsha", mirror_changed=False, tag_sha="taggedsha"),
    )
    world.runs = successful_runs("taggedsha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]

    assert cli.release_tail(tail_args(cli)) == 0

    created = [c for c in world.commands if c[:2] == ["git", "tag"]]
    assert created == [], "an existing tag must not be recreated"
    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]], (
        "the Release must still be created"
    )


def test_refuses_when_the_tag_exists_but_points_somewhere_else(cli, monkeypatch, capsys):
    """A tag already pointing at a different commit means someone else shipped this
    version. Moving it would rewrite a published release; fail closed instead."""
    world = install(
        cli,
        monkeypatch,
        World(mirror_head="ourhead", mirror_changed=False, tag_sha="someothersha"),
    )
    assert cli.release_tail(tail_args(cli)) != 0
    err = capsys.readouterr().err
    assert "release_tail_error" in err
    assert "someothersha" in err
    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]] == []


def test_resumes_when_the_existing_tag_is_annotated_and_points_at_our_commit(cli, monkeypatch):
    """An annotated tag's ref points at a TAG OBJECT, not at a commit.

    The tail creates its tag with `git tag -a`, so on any resume the sha it reads
    back for that ref is a tag object's -- which can never equal the commit sha it
    pushed. Comparing the two unpeeled made `release-tail` refuse its OWN, correctly
    placed tag, breaking the documented resume path. Peel first, then compare.
    """
    world = install(
        cli,
        monkeypatch,
        World(
            mirror_head="ourhead",
            mirror_changed=False,
            tag_sha="7baf5ea2tag0bject",     # what the ref points at: the tag object
            tag_peeled="ourhead",            # ...which dereferences to exactly our commit
        ),
    )
    world.runs = successful_runs("ourhead")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]

    assert cli.release_tail(tail_args(cli)) == 0

    created = [c for c in world.commands if c[:2] == ["git", "tag"]]
    assert created == [], "a tag already on the right commit must not be recreated"
    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]], (
        "the tail must proceed to the Release step instead of refusing its own tag"
    )


def test_refuses_when_an_annotated_tag_peels_to_a_different_commit(cli, monkeypatch, capsys):
    """Peeling must not weaken the guard.

    A tag that genuinely resolves to another commit means someone else shipped this
    version; moving it would rewrite a published release. Fail closed, as before.
    """
    world = install(
        cli,
        monkeypatch,
        World(
            mirror_head="ourhead",
            mirror_changed=False,
            tag_sha="s0metag0bject",
            tag_peeled="someothercommit",    # a DIFFERENT commit: genuinely published elsewhere
        ),
    )
    assert cli.release_tail(tail_args(cli)) != 0
    err = capsys.readouterr().err
    assert "release_tail_error" in err
    assert "refusing to move a published tag" in err
    assert "someothercommit" in err, "the refusal must name the COMMIT, not the tag object"
    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]] == []


def test_resumes_from_release_published_with_one_registry_missing(cli, monkeypatch, capsys):
    """The Release event already fired and npm published, but PyPI did not. A re-run
    must dispatch ONLY the missing registry -- and must not create a second Release."""
    world = install(
        cli,
        monkeypatch,
        World(
            mirror_head="livesha",
            mirror_changed=False,
            tag_sha="livesha",
            release={
                "isDraft": False,
                "tagName": "v0.9.7",
                "targetCommitish": "livesha",
                "url": "u",
            },
            npm_versions=["0.9.7"],
            pypi_versions=["0.8.2"],
        ),
    )
    assert cli.release_tail(tail_args(cli)) == 0
    out = capsys.readouterr().out

    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]] == [], (
        "no second Release"
    )
    assert [w for w, _v, _r in world.dispatched] == ["publish-pypi.yml"], (
        f"only the missing registry may be re-dispatched, got {world.dispatched}"
    )
    assert world.dispatched[0][1] == "0.9.7", "the dispatch must pin the version"
    assert "release_tail_npm: 0.9.7" in out


# -- bootstrap: --skip-registry drafts, --resume publishes the draft --------


def test_skip_registry_creates_a_draft_release_and_fires_nothing(cli, monkeypatch, capsys):
    """A draft Release emits no `published` event, so no publish workflow fires.
    That is what lets the operator configure Trusted Publishing against workflows
    that already exist on the mirror, before any publish is attempted."""
    world = install(cli, monkeypatch, World())
    assert cli.release_tail(tail_args(cli, skip_registry=True)) == 0
    out = capsys.readouterr().out

    create = [c for c in world.commands if c[:3] == ["gh", "release", "create"]]
    assert create, "the Release must still be created (as a draft)"
    assert "--draft" in create[0], (
        "--skip-registry must create a DRAFT, or the bootstrap version gets no Release"
    )
    assert world.release["isDraft"] is True
    assert world.dispatched == [], "no workflow may be dispatched"
    assert [c for c in world.commands if c[:3] == ["gh", "run", "list"]] == [], (
        "nothing to wait for"
    )
    assert "release_tail_release: drafted" in out


def test_resume_publishes_the_existing_draft_exactly_once(cli, monkeypatch, capsys):
    """The bootstrap's second half: the draft already exists, Trusted Publishing is
    now configured, so publishing THAT draft fires the event exactly once. Creating
    a second Release instead would double-publish."""
    world = install(
        cli,
        monkeypatch,
        World(
            mirror_head="draftsha",
            mirror_changed=False,
            tag_sha="draftsha",
            release={
                "isDraft": True,
                "tagName": "v0.9.7",
                "targetCommitish": "draftsha",
                "url": "u",
            },
        ),
    )
    world.runs = successful_runs("draftsha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]

    assert cli.release_tail(tail_args(cli)) == 0
    out = capsys.readouterr().out

    assert [c for c in world.commands if c[:3] == ["gh", "release", "create"]] == [], (
        "the existing draft must be published, not replaced by a second Release"
    )
    edits = [c for c in world.commands if c[:3] == ["gh", "release", "edit"]]
    assert len(edits) == 1, "the draft must be published exactly once"
    assert "--draft=false" in edits[0]
    assert world.dispatched == [], "publishing the draft fires the workflows; no dispatch needed"
    assert "release_tail_release: published" in out


# -- waiting on the RIGHT workflow runs ------------------------------------


def test_a_stale_successful_run_is_never_mistaken_for_this_release(cli, monkeypatch, capsys):
    """A previous release's successful run of the same workflow must not be read as
    this release's success. No run at the current SHA = still waiting, never done."""
    world = install(cli, monkeypatch, World(new_sha="thisrelease"))
    # BOTH workflows have a green run -- but from a PREVIOUS release. Nothing else in
    # this scenario stops the wait from passing, so only the exact-SHA match can. If
    # the match were on workflow name alone, the tail would sail through the wait and
    # then fail later on drift; asserting on "timed out" specifically is what pins the
    # guard rather than the downstream symptom.
    stale = successful_runs("anoldersha")
    for runs in stale.values():
        runs[0]["headBranch"] = "v0.9.6"
    world.runs = stale

    assert cli.release_tail(tail_args(cli, timeout=0)) != 0
    combined = capsys.readouterr()
    assert "release_tail_error" in combined.err
    assert "timed out" in (combined.err + combined.out).lower(), (
        "a stale green run of the same workflow was mistaken for this release's run"
    )
    assert "thisrelease" in combined.err, "the wait must name the SHA it is waiting for"


def test_a_failed_publish_run_fails_the_tail(cli, monkeypatch, capsys):
    world = install(cli, monkeypatch, World(new_sha="failsha"))
    world.runs = successful_runs("failsha")
    world.runs["publish-npm.yml"][0]["conclusion"] = "failure"
    world.pypi_versions = ["0.9.7"]

    assert cli.release_tail(tail_args(cli)) != 0
    err = capsys.readouterr().err
    assert "release_tail_error" in err
    assert "publish-npm.yml" in err


def test_a_still_running_publish_is_not_success(cli, monkeypatch, capsys):
    world = install(cli, monkeypatch, World(new_sha="runsha"))
    world.runs = successful_runs("runsha")
    world.runs["publish-pypi.yml"][0]["status"] = "in_progress"
    world.runs["publish-pypi.yml"][0]["conclusion"] = None

    assert cli.release_tail(tail_args(cli, timeout=0)) != 0
    assert "release_tail_error" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Task 3: registry copy is generated, not hand-written
# --------------------------------------------------------------------------

# The exact untruth that shipped to both registries for months: the 0.8.2 packages
# promised "a native package install lands with the 0.9.0 package split". It was
# false when published and stayed false. Copy is generated now so it cannot drift.
UNTRUTH_PATTERNS = (
    r"lands with the \d+\.\d+",
    r"package split",
    r"pipx install tautline",
    r"npm install -g tautline",
)


def registry_copy(cli, registry: str, version: str = "0.9.7") -> str:
    """All generated text for a registry, concatenated -- copy must be truthful everywhere."""
    return "\n".join(cli.registry_package_files(registry, version).values())


@pytest.mark.parametrize("registry", ["npm", "pypi"])
def test_registry_copy_contains_the_working_install_sequence(cli, registry: str) -> None:
    readme = cli.registry_package_files(registry, "0.9.7")["README.md"]
    assert "git clone https://github.com/tautlines/tautline" in readme
    assert "cd tautline" in readme, "the install sequence is broken without `cd tautline`"
    assert "bin/tautline install-cli" in readme


@pytest.mark.parametrize("registry", ["npm", "pypi"])
def test_registry_copy_makes_no_packaged_install_promise(cli, registry: str) -> None:
    """The generated copy must not claim a packaged install has landed or will land."""
    text = registry_copy(cli, registry)
    for pattern in UNTRUTH_PATTERNS:
        assert not re.search(pattern, text, re.IGNORECASE), (
            f"{registry} copy contains the historical untruth /{pattern}/: {text!r}"
        )


@pytest.mark.parametrize("registry", ["npm", "pypi"])
def test_registry_copy_says_plainly_that_it_is_a_namespace_pointer(cli, registry: str) -> None:
    readme = cli.registry_package_files(registry, "0.9.7")["README.md"]
    assert "namespace pointer" in readme.lower(), (
        "the package must state what it is: a name reservation that does not install the CLI"
    )
    assert "does not install" in readme.lower()


@pytest.mark.parametrize("registry", ["npm", "pypi"])
def test_registry_copy_points_at_the_public_roadmap(cli, registry: str) -> None:
    readme = cli.registry_package_files(registry, "0.9.7")["README.md"]
    assert "ROADMAP.md" in readme


def test_registry_copy_is_one_source_of_truth(cli) -> None:
    """npm and PyPI must ship the same README -- two hand-written copies is how they drifted."""
    npm = cli.registry_package_files("npm", "0.9.7")["README.md"]
    pypi = cli.registry_package_files("pypi", "0.9.7")["README.md"]
    assert npm == pypi


def test_npm_package_manifest_is_valid_and_versioned(cli) -> None:
    files = cli.registry_package_files("npm", "0.9.7")
    manifest = json.loads(files["package.json"])
    assert manifest["name"] == "tautline"
    assert manifest["version"] == "0.9.7"
    assert manifest["repository"]["url"].endswith("tautlines/tautline.git")
    assert files["LICENSE"].startswith("MIT License")


def test_pypi_package_manifest_is_versioned(cli) -> None:
    files = cli.registry_package_files("pypi", "0.9.7")
    pyproject = files["pyproject.toml"]
    assert 'name = "tautline"' in pyproject
    assert 'version = "0.9.7"' in pyproject
    assert '__version__ = "0.9.7"' in files["src/tautline/__init__.py"]


def test_registry_package_rejects_an_unknown_registry(cli) -> None:
    with pytest.raises(SystemExit):
        cli.registry_package_files("cargo", "0.9.7")


def test_registry_package_command_writes_the_tree(cli, tmp_path, capsys) -> None:
    args = cli.argparse.Namespace(
        registry="npm", version="0.9.7", destination=tmp_path / "pkg", write=True
    )
    assert cli.registry_package(args) == 0
    out = capsys.readouterr().out
    assert "registry_package_written:" in out
    manifest = json.loads((tmp_path / "pkg" / "package.json").read_text())
    assert manifest["version"] == "0.9.7"


def test_registry_package_command_dry_run_writes_nothing(cli, tmp_path, capsys) -> None:
    dest = tmp_path / "pkg"
    args = cli.argparse.Namespace(registry="pypi", version="0.9.7", destination=dest, write=False)
    assert cli.registry_package(args) == 0
    assert not dest.exists()
    assert "registry_package_written: no" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Task 4: `release-drift-check` -- make stale registries impossible to miss
# --------------------------------------------------------------------------


def drift_args(cli, **overrides):
    defaults = dict(as_json=False)
    defaults.update(overrides)
    return cli.argparse.Namespace(**defaults)


def install_registries(cli, monkeypatch, *, repo, npm, pypi):
    world = World(npm_versions=[npm] if npm else [], pypi_versions=[pypi] if pypi else [])
    monkeypatch.setattr(cli, "release_http_json", world.http_json)
    monkeypatch.setattr(cli, "plugin_version", lambda: repo)
    return world


def test_drift_check_reproduces_the_historical_failure(cli, monkeypatch, capsys):
    """The exact state that shipped for months and nothing caught: a 0.9.1 repo
    against 0.8.2 on both registries. It must fail, and it must name all three."""
    install_registries(cli, monkeypatch, repo="0.9.1", npm="0.8.2", pypi="0.8.2")
    assert cli.release_drift_check(drift_args(cli)) != 0
    out = capsys.readouterr().out

    assert "release_drift_repo: 0.9.1" in out
    assert "release_drift_npm: 0.8.2" in out
    assert "release_drift_pypi: 0.8.2" in out
    assert "release_drift_verdict: drift" in out
    # the verdict must name every surface that disagrees, not just say "drift"
    assert "npm" in out and "pypi" in out


def test_drift_check_passes_when_every_surface_agrees(cli, monkeypatch, capsys):
    install_registries(cli, monkeypatch, repo="0.9.7", npm="0.9.7", pypi="0.9.7")
    assert cli.release_drift_check(drift_args(cli)) == 0
    out = capsys.readouterr().out
    assert "release_drift_verdict: aligned" in out


@pytest.mark.parametrize("stale", ["npm", "pypi"])
def test_drift_check_fails_when_a_single_registry_lags(cli, monkeypatch, capsys, stale):
    versions = {"npm": "0.9.7", "pypi": "0.9.7"}
    versions[stale] = "0.9.6"
    install_registries(cli, monkeypatch, repo="0.9.7", **versions)
    assert cli.release_drift_check(drift_args(cli)) != 0
    out = capsys.readouterr().out
    assert "release_drift_verdict: drift" in out
    assert f"release_drift_{stale}: 0.9.6" in out


def test_drift_check_treats_a_missing_registry_package_as_drift(cli, monkeypatch, capsys):
    install_registries(cli, monkeypatch, repo="0.9.7", npm=None, pypi="0.9.7")
    assert cli.release_drift_check(drift_args(cli)) != 0
    out = capsys.readouterr().out
    assert "release_drift_npm: absent" in out
    assert "release_drift_verdict: drift" in out


def test_drift_check_emits_json(cli, monkeypatch, capsys):
    install_registries(cli, monkeypatch, repo="0.9.1", npm="0.8.2", pypi="0.8.2")
    assert cli.release_drift_check(drift_args(cli, as_json=True)) != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["surfaces"] == {"repo": "0.9.1", "npm": "0.8.2", "pypi": "0.8.2"}
    assert sorted(payload["drifted"]) == ["npm", "pypi"]


def test_drift_check_fails_closed_when_a_registry_is_unreadable(cli, monkeypatch, capsys):
    """An unreadable registry is not evidence of alignment."""
    monkeypatch.setattr(cli, "plugin_version", lambda: "0.9.7")

    def explode(url, timeout=20):
        raise OSError("network unreachable")

    monkeypatch.setattr(cli, "release_http_json", explode)
    assert cli.release_drift_check(drift_args(cli)) != 0
    out = capsys.readouterr().out
    assert "release_drift_verdict: drift" in out or "unreadable" in out.lower()


def test_release_tail_runs_the_drift_check_after_publishing(cli, monkeypatch, capsys):
    """Creating the Release is not completion. The tail must confirm the registries
    actually landed the version before it reports success."""
    world = install(cli, monkeypatch, World(new_sha="donesha"))
    world.runs = successful_runs("donesha")
    world.npm_versions = ["0.9.7"]
    world.pypi_versions = ["0.9.7"]
    assert cli.release_tail(tail_args(cli)) == 0
    out = capsys.readouterr().out
    assert "release_drift_verdict: aligned" in out


def test_release_tail_fails_when_the_registries_never_land_the_version(cli, monkeypatch, capsys):
    """The workflows went green but the version is not on the registry: that is a
    failure, not a success. Green CI is not evidence of a published package."""
    world = install(cli, monkeypatch, World(new_sha="greensha"))
    world.runs = successful_runs("greensha")
    world.npm_versions = ["0.8.2"]     # never got 0.9.7
    world.pypi_versions = ["0.9.7"]
    assert cli.release_tail(tail_args(cli)) != 0
    combined = capsys.readouterr()
    assert "drift" in (combined.out + combined.err).lower()


def test_overlay_preserves_the_mirrors_history_and_applies_deletions(cli, tmp_path):
    """Correction 1, asserted directly.

    The export repo carries a FRESH root commit that shares no ancestor with the
    mirror. Letting its `.git/` overwrite the mirror's would destroy the mirror's
    history -- the force-push this design exists to avoid. And an export-EXCLUDED
    path must become a real deletion, not linger on the mirror forever.
    """
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    (clone / ".git" / "MIRROR_HISTORY").write_text("the mirror's real history\n")
    (clone / "VERSION").write_text("0.9.6\n")
    (clone / "STALE.md").write_text("export-excluded; must be deleted\n")
    (clone / "docs").mkdir()
    (clone / "docs" / "old.md").write_text("gone\n")

    export = tmp_path / "export"
    (export / ".git").mkdir(parents=True)
    (export / ".git" / "FRESH_ROOT").write_text("the export's unrelated history\n")
    (export / "VERSION").write_text("0.9.7\n")
    (export / "docs").mkdir()
    (export / "docs" / "new.md").write_text("shipped\n")

    cli.release_tail_overlay(export, clone)

    assert (clone / ".git" / "MIRROR_HISTORY").is_file(), "the mirror's history must survive"
    assert not (clone / ".git" / "FRESH_ROOT").exists(), (
        "the export's fresh root history must never overwrite the mirror's"
    )
    assert (clone / "VERSION").read_text() == "0.9.7\n"
    assert (clone / "docs" / "new.md").is_file()
    assert not (clone / "STALE.md").exists(), "export-excluded paths must become real deletions"
    assert not (clone / "docs" / "old.md").exists()
