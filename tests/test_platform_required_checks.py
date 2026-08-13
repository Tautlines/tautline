"""The lane must be TOLD when no platform gate is actually protecting the integration branch.

Backlog item 21 (`2026-07-24-experimental-required-checks`), acceptance item 2. Agents own merge,
and the policy that lets them assumes CI gates the merge. On this repository that assumption is
false: branch protection and rulesets are paid features for private repositories, so every branch
here -- including `main` -- returns 403, and a green CI run gates nothing at all.

That is not a Tautline accident. A private repo on a free plan is the single most common adopter
configuration, so a methodology that assumes platform-enforced required checks silently degrades
to NO gate for exactly its most typical adopter. These pins keep the degradation loud.

Report-only, permanently: whether GitHub can gate a merge is not something the lane can fix, so
failing on it would be a lockout with no remedy.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from tautline_methodology import cli


UPGRADE_403 = (
    '{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.",'
    '"status":"403"}'
)


NOT_PROTECTED = "Branch not protected (HTTP 404)"


def _fake_gh(monkeypatch, *, code: int, payload: object, error: str = "", rules=None):
    """Answer both endpoints the probe consults.

    `rules` is the (code, payload, error) triple for `repos/.../rules/branches/...`; when omitted,
    the ruleset endpoint reports an empty rule list (nothing armed).
    """
    rules_reply = rules if rules is not None else (0, [], "")

    def fake(command, cwd=None, timeout=None):
        assert command[:2] == ["gh", "api"]
        if "/rules/branches/" in command[2]:
            return rules_reply
        return code, payload, error

    monkeypatch.setattr(cli, "command_json", fake)


def test_armed_reports_the_required_check_names(monkeypatch):
    _fake_gh(
        monkeypatch,
        code=0,
        payload={"required_status_checks": {"contexts": ["python (3.12)", "validate"]}},
    )
    state, detail = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_ARMED
    assert detail == "python (3.12), validate"


def test_paid_feature_403_is_unavailable_not_absent(monkeypatch):
    """The distinction is the whole point. `absent` invites "then go turn it on"; `unavailable`
    says the platform refuses, which is an operator/billing decision, not a settings toggle."""
    _fake_gh(monkeypatch, code=1, payload=None, error=UPGRADE_403)
    state, detail = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_UNAVAILABLE
    assert "paid feature" in detail


def test_unprotected_branch_with_no_ruleset_is_absent(monkeypatch):
    _fake_gh(monkeypatch, code=1, payload=None, error=NOT_PROTECTED)
    state, _ = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_ABSENT


def test_a_ruleset_can_arm_the_gate_without_legacy_branch_protection(monkeypatch):
    """Codex R1 P2. `branches/<b>/protection` 404s on a ruleset-protected branch, so consulting it
    alone would report `absent` and tell an operator whose gate IS armed that CI is advisory."""
    _fake_gh(
        monkeypatch,
        code=1,
        payload=None,
        error=NOT_PROTECTED,
        rules=(
            0,
            [
                {"type": "deletion"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [
                            {"context": "python (3.12)"},
                            {"context": "validate"},
                        ]
                    },
                },
            ],
            "",
        ),
    )
    state, detail = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_ARMED
    assert detail == "python (3.12), validate"


def test_a_generic_404_is_unverifiable_not_absent(monkeypatch):
    """Codex R1 P2. A token without access, a wrong slug, and a deleted branch all 404. Only the
    explicit `Branch not protected` message is evidence that there is no gate."""
    _fake_gh(monkeypatch, code=1, payload=None, error="Not Found (HTTP 404)")
    state, _ = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_UNVERIFIABLE


def test_a_ruleset_endpoint_we_cannot_read_is_unverifiable(monkeypatch):
    _fake_gh(
        monkeypatch, code=1, payload=None, error=NOT_PROTECTED,
        rules=(1, None, "gh auth login required"),
    )
    state, _ = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_UNVERIFIABLE


def test_a_paid_plan_refusal_on_the_ruleset_endpoint_is_unavailable(monkeypatch):
    _fake_gh(
        monkeypatch, code=1, payload=None, error=NOT_PROTECTED,
        rules=(1, None, UPGRADE_403),
    )
    state, detail = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_UNAVAILABLE
    assert "rulesets" in detail


def test_protection_without_required_checks_falls_through_to_rulesets(monkeypatch):
    """Protected but requiring nothing is a gate that cannot block -- unless a ruleset arms it."""
    _fake_gh(monkeypatch, code=0, payload={"required_status_checks": {"contexts": []}})
    state, _ = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_ABSENT

    _fake_gh(monkeypatch, code=0, payload={})
    state, _ = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_ABSENT

    _fake_gh(
        monkeypatch,
        code=0,
        payload={},
        rules=(
            0,
            [{
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "python (3.12)"}]},
            }],
            "",
        ),
    )
    state, detail = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_ARMED
    assert detail == "python (3.12)"


@pytest.mark.parametrize(
    "error",
    [
        "gh: command not found",
        "gh auth login required",
        "dial tcp: lookup api.github.com",
        "Not Found (HTTP 404)",
    ],
)
def test_cannot_ask_is_unverifiable_never_absent(monkeypatch, error):
    """A check we could not run must never be reported as a check that is not there."""
    _fake_gh(monkeypatch, code=1, payload=None, error=error)
    state, _ = cli.platform_required_checks_state("o/r", "experimental", Path("."))
    assert state == cli.PLATFORM_PROTECTION_UNVERIFIABLE


def test_missing_slug_or_branch_is_unverifiable():
    assert cli.platform_required_checks_state("", "experimental", Path("."))[0] == (
        cli.PLATFORM_PROTECTION_UNVERIFIABLE
    )
    assert cli.platform_required_checks_state("o/r", "", Path("."))[0] == (
        cli.PLATFORM_PROTECTION_UNVERIFIABLE
    )


def _lines(monkeypatch, **kwargs):
    _fake_gh(monkeypatch, **kwargs)
    data = {"repo": "o/r", "laneStatus": {"integrationBranch": "experimental"}}
    return cli.platform_required_checks_lines(data, Path("."))


def test_an_unarmed_branch_says_plainly_that_nothing_is_blocking(monkeypatch):
    lines = _lines(monkeypatch, code=1, payload=None, error=UPGRADE_403)
    assert lines[0].startswith("platform_required_checks: unavailable")
    note = next(line for line in lines if line.startswith("platform_required_checks_note:"))
    assert "no platform gate is blocking merges" in note
    # The note must not overclaim what the local gates can do either.
    assert "cannot stop a merge someone else performs" in note


def test_an_unverifiable_probe_says_UNKNOWN_and_never_claims_there_is_no_gate(monkeypatch):
    """Codex R2 P2. The note used to be appended for every non-armed state, so a probe that could
    not run announced that nothing was blocking merges -- contradicting the state line directly
    above it, and telling an operator whose gate IS armed that they are unprotected."""
    lines = _lines(monkeypatch, code=1, payload=None, error="gh auth login required")
    assert lines[0].startswith("platform_required_checks: unverifiable")
    note = next(line for line in lines if line.startswith("platform_required_checks_note:"))
    assert "UNKNOWN" in note
    assert "not a report that no gate exists" in note
    assert "no platform gate is blocking merges" not in note
    # It must name what would make the state knowable, not just decline to answer.
    assert "gh auth status" in note


def test_the_no_gate_note_appears_only_where_absence_was_established(monkeypatch):
    for error, expected in (
        (UPGRADE_403, cli.PLATFORM_PROTECTION_UNAVAILABLE),
        (NOT_PROTECTED, cli.PLATFORM_PROTECTION_ABSENT),
    ):
        lines = _lines(monkeypatch, code=1, payload=None, error=error)
        assert lines[0].startswith(f"platform_required_checks: {expected}")
        note = next(line for line in lines if line.startswith("platform_required_checks_note:"))
        assert "no platform gate is blocking merges" in note


def test_an_armed_branch_adds_no_warning(monkeypatch):
    lines = _lines(
        monkeypatch, code=0, payload={"required_status_checks": {"contexts": ["python (3.12)"]}}
    )
    assert len(lines) == 1
    assert lines[0].startswith("platform_required_checks: armed")


def test_the_reporter_never_raises(monkeypatch):
    """It runs inside ci_health_check at the prepush boundary. A reporter that can explode is
    worse than no reporter -- the 2026-07-22 startup-gate lesson."""

    def boom(*args, **kwargs):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(cli, "platform_required_checks_state", boom)
    lines = cli.platform_required_checks_lines({"repo": "o/r"}, Path("."))
    assert lines == ["platform_required_checks: unverifiable (probe failed)"]


def test_ci_health_check_prints_the_platform_state_and_never_blocks_on_it(monkeypatch, capsys):
    """Wiring tests into CI and CI being able to BLOCK a merge are different properties, and this
    repo proves they come apart. ci_health_check must report the second without gating on it."""
    monkeypatch.setattr(cli, "lane_project", lambda args: ({"repo": "o/r"}, None, Path(".")))
    monkeypatch.setattr(cli, "print_ci_test_gate_status", lambda data, target: [])
    monkeypatch.setattr(cli, "ci_test_gate_config", lambda data: {"enforcement": "block"})
    monkeypatch.setattr(
        cli,
        "platform_required_checks_lines",
        lambda data, target: ["platform_required_checks: unavailable branch=experimental (paid)"],
    )
    code = cli.ci_health_check(argparse.Namespace(target=Path("."), project=None, strict=True))
    out = capsys.readouterr().out
    assert code == 0, "an unarmed platform gate must never block the lane; it has no remedy"
    assert "platform_required_checks: unavailable" in out
    assert "ci_health_check: ok" in out
