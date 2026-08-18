"""Item 70 WS1 / RCA 2026-07-22 control 5: a channel/branch contradiction demands a resolution.

The incident: an exec-root tracking a non-release branch met the sync's non-release-branch refusal,
was reported as a bare warning, and the warning was carried forward for weeks because nothing ever
demanded it be resolved.

**The arming condition is the whole design, and it was narrowed against measurement.** A first
version armed on ANY branch that was not the channel's release branch. This repo's own adapter
carries no framework pin, so the channel resolves to `stable` -> release branch `main`, while every
lane here lives on `experimental` and on feature branches. That rule turned every framework session
on any feature branch into exit-2 debt, and two of its three enumerated exits are impossible for a
feature branch, leaving a machine-wide `maintainer-mode on` as the only durable escape.

A fail-closed control whose cheapest exit is a global gate standdown teaches the bypass this
cluster exists to delete. So `required` fires only on a CONTRADICTION -- the checkout sits on
another channel's release branch -- and every other non-release branch is `advisory`, exit 0.
"""

import pytest


@pytest.fixture()
def reconcile(cli, monkeypatch):
    """Drive the pure function with the checkout's branch and mode stubbed.

    The git probe and the maintainer-mode predicate have their own suites; driving them here would
    make these tests about the probes instead of about the arming condition.
    """

    def _run(
        branch,
        channel="stable",
        *,
        armed=False,
        allow_non_main=False,
        env=None,
        is_repo=True,
        package_mode=False,
        target=None,
    ):
        monkeypatch.setattr(cli, "running_from_installed_package", lambda: package_mode)
        monkeypatch.setattr(cli, "maintainer_mode_armed", lambda: armed)
        monkeypatch.setattr(
            cli,
            "run_git",
            lambda _repo, args: (
                "true"
                if args[:1] == ["rev-parse"] and is_repo
                else ("false" if args[:1] == ["rev-parse"] else branch)
            ),
        )
        monkeypatch.setattr(cli, "maintainer_mode_armed", lambda: armed)
        monkeypatch.setattr(
            cli.util_module(), "resolve_env", lambda name, *a, **k: (env or {}).get(name, "")
        )
        return cli.framework_checkout_reconciliation(
            channel, cli.framework_channel_branch(channel), allow_non_main, target
        )

    return _run


# --- the arming condition -----------------------------------------------------------------------


def test_contradiction_is_required(reconcile):
    """Channel `stable` (releases from `main`), checkout on `experimental`: the incident state."""
    state, line = reconcile("experimental", channel="stable")
    assert state == "required"
    assert "tracks experimental" in line
    assert "channel 'stable' releases from main" in line


def test_the_other_direction_is_also_required(reconcile):
    """Channel `experimental`, checkout on `main`.

    A behaviour FLIP, pinned so it is deliberate: the previous warning hardcoded `main` as the
    expected branch, so this state -- a genuine contradiction -- was silent.
    """
    state, _line = reconcile("main", channel="experimental")
    assert state == "required"


def test_the_channels_own_release_branch_is_ok(reconcile):
    assert reconcile("main", channel="stable") == ("ok", "")
    # And the other flip: `experimental` on channel `experimental` WARNED before this change.
    assert reconcile("experimental", channel="experimental") == ("ok", "")


def test_a_feature_branch_is_advisory_not_required(reconcile):
    """THE ANTI-LOCKOUT PIN, and the reason this control has a narrow arming condition at all.

    Under an any-non-release-branch rule this state is exit-2 debt on every framework lane on the
    machine, and its only durable exit is a machine-wide standdown.
    """
    state, line = reconcile("feat/some-work", channel="stable")
    assert state == "advisory"
    # It still says everything the required case says -- the operator loses no information.
    assert "tracks feat/some-work" in line
    assert "maintainer-mode on" in line


def test_detached_head_is_advisory(reconcile):
    """Baseline correction: this state DOES warn today, so the pin is advisory-not-required.

    An earlier draft claimed detached HEAD was currently warning-free. It was not.
    """
    state, line = reconcile("", channel="stable")
    assert state == "advisory"
    assert "detached HEAD" in line


def test_unavailable_branch_and_non_repo_are_silent(reconcile):
    assert reconcile("unavailable", channel="stable") == ("ok", "")
    assert reconcile("feat/x", channel="stable", is_repo=False) == ("ok", "")


# --- the escapes, each executed rather than described -------------------------------------------


def test_maintainer_mode_stands_down(reconcile):
    state, line = reconcile("experimental", channel="stable", armed=True)
    assert state == "ok"
    assert "maintainer mode manages this checkout" in line


def test_the_env_escape_defers_and_exits_zero(reconcile):
    """An escape that still exits 2 is not an escape."""
    state, line = reconcile(
        "experimental", channel="stable", env={"MINERVIT_METHODOLOGY_ALLOW_NON_MAIN": "1"}
    )
    assert state == "deferred"
    assert "single intentional deviation" in line


def test_the_allow_non_main_argument_defers_too(reconcile):
    state, _line = reconcile("experimental", channel="stable", allow_non_main=True)
    assert state == "deferred"


# --- the enumerated resolutions must be real ----------------------------------------------------


def test_every_named_resolution_is_a_registered_subcommand(cli, reconcile):
    """No dead ends. Four wrong remedy lists shipped in this cluster before anyone ran one.

    Every `tautline <verb>` the line names must exist in the real argparse registry -- not in a
    plan's sketch of it.
    """
    import re

    _state, line = reconcile("experimental", channel="stable")
    named = set(re.findall(r"`tautline ([a-z][a-z0-9-]*)", line))
    assert named, line
    registered = set(cli.registered_subcommand_names())
    assert named <= registered, sorted(named - registered)


def test_the_contradiction_names_the_channel_repoint_and_a_feature_branch_does_not(reconcile):
    """Resolution (3) differs by state because one of the two is impossible for the other.

    A feature branch cannot be a channel's release branch, so `set-framework-channel` would be a
    dead end there -- and printing a dead end is how this cluster's earlier remedy lists failed.
    """
    _state, contradiction = reconcile("experimental", channel="stable")
    assert "set-framework-channel experimental" in contradiction

    _state, feature = reconcile("feat/some-work", channel="stable")
    assert "set-framework-channel" not in feature
    assert "finish or park it" in feature


def test_the_checkout_remedy_names_the_channels_branch_not_main(reconcile):
    """The resolver is the channel's, so the remedy cannot drift back to a hardcoded `main`."""
    _state, line = reconcile("main", channel="experimental")
    assert "checkout experimental" in line
    assert "checkout main" not in line


# --- the debt classification --------------------------------------------------------------------


def test_required_is_debt_not_integrity(cli):
    """A lane with this contradiction can still start and still prove things.

    Classifying it as integrity would exit 1 ("launcher still refuses") rather than 2 (remediation),
    which is the wrong recovery for a state the agent can fix itself.
    """
    assert "framework_checkout_failures" in cli.METHODOLOGY_STATUS_DEBT_GATES
    assert "framework_checkout_failures" not in cli.METHODOLOGY_STATUS_INTEGRITY_GATES


def test_only_required_populates_the_failure_list(cli, reconcile):
    """Advisory must never reach the gate list, or the anti-lockout property is undone."""
    for branch, expected in (("experimental", "required"), ("feat/x", "advisory"), ("main", "ok")):
        state, _line = reconcile(branch, channel="stable")
        assert state == expected, branch


# --- Codex R1: the control must not lock out populations that did nothing wrong ------------------


def test_package_mode_stands_down(reconcile):
    """Codex R1 P1. In package mode the canonical checkout is IRRELEVANT.

    `sync-methodology` already stands down here because pip/pipx updates the running code, so a
    leftover clone sitting on another channel's branch says nothing about what this runtime
    executes. Without this, a pip-installed lane with an old clone lying around cannot start -- a
    lockout of a population that has done nothing wrong, which is exactly what this control's
    narrow arming condition exists to avoid.
    """
    state, line = reconcile("experimental", channel="stable", package_mode=True)
    assert state == "ok"
    # It SAYS why it stood down. A silent standdown and a silent pass read identically, and this
    # cluster is about controls that report health while doing nothing.
    assert "package mode" in line


def test_the_remedies_name_the_resolved_target_not_the_cwd(reconcile, tmp_path):
    """Codex R1 P1. `--target /elsewhere` printing `--target .` repins the WRONG worktree.

    This cluster shipped four wrong remedy lists. A remedy that runs somewhere else is the same
    defect wearing a different hat, and it leaves the original gate uncleared.
    """
    lane = tmp_path / "some-lane"
    lane.mkdir()
    _state, line = reconcile("experimental", channel="stable", target=lane)
    assert "--target ." not in line
    assert str(lane) in line


def test_the_checkout_path_is_shell_safe(reconcile, monkeypatch, cli):
    """Codex R1 P2. An unquoted path with a space is split by the shell, so the printed recovery
    cannot perform the recovery it advertises."""
    from pathlib import Path as _P

    monkeypatch.setattr(cli, "canonical_methodology_repo", lambda: _P("/tmp/a path/with spaces"))
    _state, line = reconcile("experimental", channel="stable")
    assert "git -C '/tmp/a path/with spaces' checkout" in line


def test_both_startup_surfaces_accept_the_same_deviation_flag(cli):
    """Codex R1 P2. The supported two-step startup is lane-start then methodology-status.

    An escape that works on the first surface and not the second is not an escape: the lane starts
    successfully under `--allow-non-main` and then immediately fails its own required gate.
    """
    import inspect
    import re

    source = inspect.getsource(cli)
    for verb, parser_var in (("lane-start", "lane"), ("methodology-status", "status")):
        pattern = rf'{parser_var}\.add_argument\(\s*"--allow-non-main"'
        assert re.search(pattern, source), verb


def test_a_generic_auto_rescue_opt_out_does_not_bypass_the_gate(reconcile):
    """Codex R3 P1, and it caught an OVER-CORRECTION for R2 that was worse than R2's finding.

    An earlier version keyed the operator standdown on `DISABLE_AUTO_RESCUE=1`. Any managed session
    may set that to suppress destructive rescue WITHOUT claiming ownership of the checkout, so a
    stable lane sitting on `experimental` -- the exact contradiction this control exists to catch --
    bypassed the gate entirely by way of a generic safety setting.
    """
    state, _line = reconcile(
        "experimental",
        channel="stable",
        env={"MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE": "1"},
    )
    assert state == "required"


def test_the_operator_launcher_session_stands_down(reconcile):
    """Codex R2 P1, and the THIRD population this control locked out.

    `install-claude-launcher --operator-channel experimental` deliberately runs a non-release
    checkout and exports `DISABLE_AUTO_RESCUE=1`. Its whole contract is that it never blocks, so
    telling it to reconcile breaks the one workflow that had already declared its intent -- and it
    declared it explicitly, which is more than most.
    """
    state, line = reconcile(
        "experimental",
        channel="stable",
        env={"MINERVIT_METHODOLOGY_OPERATOR_CHANNEL": "experimental"},
    )
    assert state == "ok"
    assert "operator-managed checkout" in line


def test_every_standdown_is_enumerated_in_one_place(cli, reconcile):
    """Two rounds each found a different locked-out population; a third would be a pattern.

    The exemptions live in ONE function so "who is exempt?" has a single answer a test can read,
    rather than a condition scattered through the arming logic. Each is exercised here.
    """
    import inspect

    source = inspect.getsource(cli.framework_checkout_standdown_reason)
    for signal in (
        "running_from_installed_package",
        "maintainer_mode_armed",
        "OPERATOR_CHANNEL",
    ):
        assert signal in source, signal

    assert reconcile("experimental", channel="stable", package_mode=True)[0] == "ok"
    assert reconcile("experimental", channel="stable", armed=True)[0] == "ok"
    assert reconcile(
        "experimental", channel="stable", env={"MINERVIT_METHODOLOGY_OPERATOR_CHANNEL": "experimental"}
    )[0] == "ok"
    # ...and the non-vacuity floor: with none of them, the contradiction still arms.
    assert reconcile("experimental", channel="stable")[0] == "required"


def test_the_operator_launcher_exports_the_dedicated_signal(cli):
    """The standdown is only reachable if the launcher actually emits the signal it keys on."""
    body = cli.operator_launcher_content("yolo", "experimental", "/repo")
    assert "MINERVIT_METHODOLOGY_OPERATOR_CHANNEL=experimental" in body
    assert "TAUTLINE_METHODOLOGY_OPERATOR_CHANNEL=experimental" in body
