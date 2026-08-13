"""The generated hook resolves the CLI in a pinned order, and the lane wins (backlog item 1).

The defect these tests exist for: every release through 0.47.1 probed the baked install path --
whichever checkout last ran ``lane-start`` -- BEFORE ``TAUTLINE_METHODOLOGY_REPO``, which made the
env branches unreachable whenever the baked path existed and was executable. A release that ADDS an
adapter-schema key therefore could not be pushed from such a machine: the hook validated the new
adapter against the old install's schema, ``additionalProperties: false`` refused it, and the only
way out was ``--no-verify`` on a release boundary.

Two kinds of test here, and the split is deliberate. The resolution tests use stub CLIs, so a full
hook run costs milliseconds and the question "which one did it pick?" is answered by reading what
the winner printed. The regression pair uses two REAL framework installs, because the refusal it
reproduces comes from a real schema read -- and because a fix asserted only against stubs would not
have shown that the old install still refuses the key it never learned about.
"""

from __future__ import annotations

import inspect
import re
import subprocess
from pathlib import Path

import pytest

from _hook_skew_fixtures import (
    SKEW_KEY,
    build_real_skew_lane,
    build_resolution_lane,
    install_hooks_with_baked_path,
)

HOOK_NAMES = ("pre-commit", "pre-push")


def _probe_labels(text: str) -> list[str]:
    return re.findall(r"# probe: ([a-z0-9-]+)", text)


def _resolved(stdout: str) -> str:
    """The path the winning stub printed. First occurrence: later gates reuse the cache."""
    match = re.search(r"resolved_cli: (\S+)", stdout)
    assert match, f"no stub CLI reported a resolution:\n{stdout}"
    return match.group(1)


# --- the pinned order, asserted against the constant rather than against a copy of it -----------


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_cli_resolution_order_is_pinned(cli, hook_name):
    """The emitted probes equal HOOK_CLI_RESOLUTION_ORDER exactly: no extras, no omissions.

    Asserting equality rather than containment is the point. A containment check would pass while
    a probe was silently added in the wrong place, which is precisely how the original defect --
    an ordering, not a missing branch -- stayed invisible.
    """
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), hook_name)
    assert tuple(_probe_labels(content)) == cli.HOOK_CLI_RESOLUTION_ORDER


def test_hook_cli_resolution_order_is_a_tuple_not_a_phrase_list(cli):
    """A list of str would auto-enrol in the policy-phrases SSOT; these are probe labels."""
    assert isinstance(cli.HOOK_CLI_RESOLUTION_ORDER, tuple)
    assert "HOOK_CLI_RESOLUTION_ORDER" not in cli.render_policy_phrases_json()


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_emitted_template_braces_are_balanced(cli, tmp_path, hook_name):
    """The template is an f-string with doubled braces; ``sh -n`` is the proof it still parses."""
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), hook_name)
    script = tmp_path / f"{hook_name}.sh"
    script.write_text(content, encoding="utf-8")
    result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- which candidate actually wins, run through the real emitted hook ---------------------------


def test_lane_self_checkout_outranks_everything(tmp_path):
    """A tree carrying the engine AND the schema is the authority on its own schema."""
    lane = build_resolution_lane(tmp_path)
    install_hooks_with_baked_path(lane.root, lane.baked_install)
    result = lane.run_hook(
        "pre-push",
        TAUTLINE_METHODOLOGY_REPO=str(lane.tautline_env_repo),
        MINERVIT_METHODOLOGY_REPO=str(lane.minervit_env_repo),
    )
    assert result.returncode == 0, result.stderr
    assert _resolved(result.stdout) == str(lane.root / "bin" / "tautline")


def test_baked_path_no_longer_outranks_the_env_override(tmp_path):
    """The exact regression from the intake: env set, baked path executable, lane not a framework
    checkout. Before this change the baked path won and the env branch was dead code."""
    lane = build_resolution_lane(tmp_path, framework_shaped=False)
    install_hooks_with_baked_path(lane.root, lane.baked_install)
    result = lane.run_hook("pre-push", TAUTLINE_METHODOLOGY_REPO=str(lane.tautline_env_repo))
    assert result.returncode == 0, result.stderr
    resolved = _resolved(result.stdout)
    assert resolved == str(lane.tautline_env_repo / "bin" / "tautline")
    assert resolved != str(lane.baked_install / "bin" / "tautline")


def test_product_lane_falls_through_to_baked_path_when_no_env_is_set(tmp_path):
    """No adopter loses resolution. A lane with no engine and no exports still gets the install."""
    lane = build_resolution_lane(tmp_path, framework_shaped=False)
    install_hooks_with_baked_path(lane.root, lane.baked_install)
    result = lane.run_hook("pre-push")
    assert result.returncode == 0, result.stderr
    assert _resolved(result.stdout) == str(lane.baked_install / "bin" / "tautline")


@pytest.mark.parametrize(
    ("engine", "schema"),
    [(True, False), (False, True)],
    ids=["engine-without-schema", "schema-without-engine"],
)
def test_self_probe_requires_both_engine_and_schema(tmp_path, engine, schema):
    """Half a framework checkout is not an authority on a schema it does not carry."""
    lane = build_resolution_lane(tmp_path, engine=engine, schema=schema)
    install_hooks_with_baked_path(lane.root, lane.baked_install)
    result = lane.run_hook("pre-push", TAUTLINE_METHODOLOGY_REPO=str(lane.tautline_env_repo))
    assert result.returncode == 0, result.stderr
    resolved = _resolved(result.stdout)
    assert resolved != str(lane.root / "bin" / "tautline")
    assert resolved == str(lane.tautline_env_repo / "bin" / "tautline")


def test_self_probe_survives_a_hook_environment_with_git_dir_set(tmp_path):
    """GIT_DIR exported is a real hook environment, and ``git rev-parse`` failing is a real one.

    The second half is the ``set -u`` case: command substitution swallows the non-zero exit and the
    ``.`` fallback keeps the probe harmless rather than aborting the hook.
    """
    lane = build_resolution_lane(tmp_path)
    install_hooks_with_baked_path(lane.root, lane.baked_install)

    with_git_dir = lane.run_hook("pre-push", GIT_DIR=str(lane.root / ".git"))
    assert with_git_dir.returncode == 0, with_git_dir.stderr
    assert _resolved(with_git_dir.stdout) == str(lane.root / "bin" / "tautline")

    # Break `git` outright: the probe must fall back to `.`, which from the hook's cwd is still
    # the lane root, so resolution is unchanged and nothing aborts.
    (lane.path_dir / "git").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (lane.path_dir / "git").chmod(0o755)
    broken = lane.run_hook("pre-push")
    assert broken.returncode == 0, broken.stderr
    assert _resolved(broken.stdout) == "./bin/tautline"


def test_resolver_returns_one_when_nothing_resolves(tmp_path):
    """Nothing resolvable is still the pre-existing hard refusal, with its original wording."""
    lane = build_resolution_lane(tmp_path, framework_shaped=False)
    install_hooks_with_baked_path(lane.root, lane.root / "no-such-install")
    result = lane.run_hook("pre-push")
    assert result.returncode != 0
    assert "tautline CLI not found; refusing commit/push" in result.stderr


def test_resolver_memoizes_the_resolved_path(cli, tmp_path):
    """One ``git rev-parse`` per hook run, not one per gate.

    ``resolve_minervit_cli`` is reached through command substitution, which runs in a subshell, so
    a cache written inside it cannot survive. The cache therefore lives in the caller's shell and
    is primed before the first gate -- including the one gate whose own call site is a command
    substitution. Counting real invocations is the only assertion that can tell the difference
    between a cache that works and a cache-shaped variable that does not.
    """
    content = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-push")
    assert "minervit_cli_cache=" in content
    assert '"$minervit_cli_cache" "$@"' in content

    lane = build_resolution_lane(tmp_path)
    install_hooks_with_baked_path(lane.root, lane.baked_install)
    lane.reset_git_count()
    result = lane.run_hook("pre-push")
    assert result.returncode == 0, result.stderr
    assert lane.git_invocations() == 1, (
        f"expected exactly one git invocation from the resolver, got {lane.git_invocations()}"
    )


# --- the drift substrings, and the surfaces this release provably does not touch -----------------


def test_hook_state_substrings_are_byte_unchanged(cli):
    """This release adds no required hook STEP, so the drift gate must keep forcing reinstall for
    exactly the steps it forced before -- no more, and no fewer."""
    substrings = (
        "work-profile-check --target . --event",
        "graphify-status --target . --strict",
        "backlog-provider-active-check",
        "guard-check --target . --boundary prepush",
    )
    state_source = inspect.getsource(cli.git_branch_liveness_hook_state)
    for substring in substrings:
        assert substring in state_source, substring
    assert "GIT_BRANCH_LIVENESS_HOOK_MARKER" in state_source

    pre_push = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-push")
    pre_commit = cli.git_branch_liveness_hook_content(Path("/nonexistent/backup"), "pre-commit")
    for substring in substrings:
        if substring.startswith("guard-check"):
            assert substring in pre_push
            assert substring not in pre_commit
        else:
            assert substring in pre_push and substring in pre_commit
    assert cli.GIT_BRANCH_LIVENESS_HOOK_MARKER in pre_push
    assert cli.GIT_BRANCH_LIVENESS_HOOK_MARKER in pre_commit


def test_hook_invoked_command_derivation_is_unchanged(cli):
    """The reorder adds no ``run_minervit_command`` token, so the derived verb set is untouched."""
    source = inspect.getsource(cli.git_branch_liveness_hook_content)
    invoked = set(re.findall(r"run_minervit_command '[^']*' ([a-z][a-z0-9-]*)", source))
    assert invoked == {
        "work-profile-check",
        "graphify-status",
        "branch-liveness-check",
        "backlog-provider-active-check",
        "guard-check",
    }
    assert invoked <= set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)


def test_no_plan_review_surface_in_this_release():
    """The cross-program non-contention claim, in the half pytest can actually hold.

    The diff-scoped half of this claim -- that the outgoing diff mentions none of these symbols --
    lives in the stage-1 sweep and the PR body, where a diff exists and is inspected. Asserted here
    it would be vacuous in CI (a merged commit has no PR diff) and flaky locally (it would see
    unrelated dirty or rebased changes). What IS always true and always meaningful is that the two
    modules this release adds reference none of the plan-review surfaces RCA waves 1.3 and 2.2 own.
    """
    # Assembled from fragments on purpose. Spelling these out as literals makes the test its own
    # first violation -- it finds itself, fails, and teaches nothing. Joining at runtime keeps the
    # scan honest without the scanner appearing in its own corpus.
    forbidden = (
        "plan_finalization" + "_precheck_errors",
        "plan_review" + "_manifest_path",
        "plan_review" + "_import_manifest_path",
        "PLAN_REVIEW" + "_TRUSTED_RECORDERS",
    )
    here = Path(__file__).resolve().parent
    for module in (here / "test_prepush_schema_skew.py", here / "_hook_skew_fixtures.py"):
        text = module.read_text(encoding="utf-8")
        for symbol in forbidden:
            assert symbol not in text, f"{module.name} references {symbol}"


def test_show_toplevel_resolves_the_lane_root_in_a_linked_worktree(tmp_path):
    """Probe 1's assumption, measured rather than inferred.

    ``--show-toplevel`` must return the LINKED worktree's root, not the common dir -- the opposite
    of ``--git-common-dir``, which ``fleet_state_dir`` deliberately uses for the shared case. If
    this ever stopped holding, probe 1 would resolve a sibling checkout's CLI, which is a worse
    failure than the one this release fixes.
    """
    lane = build_resolution_lane(tmp_path, framework_shaped=False)
    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "-C", str(lane.root), "worktree", "add", "-q", "-b", "linked", str(linked)],
        check=True,
        capture_output=True,
    )
    toplevel = subprocess.run(
        ["git", "-C", str(linked), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert Path(toplevel).resolve() == linked.resolve()
    assert Path(toplevel).resolve() != lane.root.resolve()


# --- the regression pair: the old install still refuses, and the hook no longer routes to it -----


@pytest.fixture(scope="module")
def real_skew_lane(tmp_path_factory):
    """Built once: it copies two framework installs and renders an adapter, and both tests that
    use it are read-only against that state."""
    return build_real_skew_lane(tmp_path_factory.mktemp("skew"))


def test_fixture_reproduces_the_unknown_property_refusal(real_skew_lane):
    """The half of the mechanism that stays true after the fix, and must.

    The older install has not been relaxed and its schema has not been widened -- invoked directly
    against the lane's adapter it still refuses the key it never learned about. That is what makes
    the headline regression below meaningful rather than vacuous: the hook stopped routing to this
    CLI, and this CLI did not stop refusing.
    """
    result = real_skew_lane.run_cli(
        real_skew_lane.older_cli, "validate-adapter", "--project", str(real_skew_lane.lane_adapter)
    )
    assert result.returncode != 0
    assert "not allowed by the adapter schema" in result.stderr
    assert SKEW_KEY in result.stderr


def test_the_lane_own_cli_accepts_the_key_the_old_install_refuses(real_skew_lane):
    """The other half: the schema being pushed does declare the key, so the disagreement is real
    version skew and not a typo. Without this, the test above could pass on a broken fixture."""
    result = real_skew_lane.run_cli(
        real_skew_lane.lane_cli, "validate-adapter", "--project", str(real_skew_lane.lane_adapter)
    )
    assert result.returncode == 0, result.stderr


def test_lane_adds_a_key_with_the_old_installed_cli_resolvable(real_skew_lane):
    """The headline regression, run through the real installed hook.

    A framework lane that adds a top-level adapter key commits clean with hooks active while the
    older install is still present, executable, and baked into the hook as ``script_path``. Before
    the reorder this exited non-zero on ``unknown property``, and the recorded workaround was
    ``--no-verify`` on a release boundary.
    """
    hook = real_skew_lane.root / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    result = subprocess.run(
        [str(hook)],
        cwd=real_skew_lane.root,
        env=real_skew_lane.env(),
        text=True,
        capture_output=True,
        timeout=180,
        input="",
    )
    assert "not allowed by the adapter schema" not in result.stderr, result.stderr
    assert SKEW_KEY not in result.stderr, result.stderr
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_a_misspelled_key_still_refuses_after_the_reorder(tmp_path):
    """Authority over your own schema is not permission to invent keys.

    The reorder hands probe 1 to the lane's own checkout, and the obvious way to get this release
    wrong would be for that authority to make every unknown key acceptable. Same fixture, same
    probe-1 win, same lane CLI answering -- but the key is one **no** schema declares, so it is a
    typo rather than skew, and the hook must still refuse. This is the closed half of the pair;
    ``test_lane_adds_a_key_with_the_old_installed_cli_resolvable`` is the open half.
    """
    typo_lane = build_real_skew_lane(tmp_path, adapter_key="fixtureOnlyMisspelledKye")
    hook = typo_lane.root / ".git" / "hooks" / "pre-commit"
    result = subprocess.run(
        [str(hook)],
        cwd=typo_lane.root,
        env=typo_lane.env(),
        text=True,
        capture_output=True,
        timeout=180,
        input="",
    )
    assert result.returncode != 0, f"a misspelled key was accepted:\n{result.stdout}"
    assert "not allowed by the adapter schema" in result.stderr, result.stderr
    assert "fixtureOnlyMisspelledKye" in result.stderr, result.stderr
