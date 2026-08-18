"""Item 74 PR-C / policy 16a: the go-live readiness profile.

**The enforcement boundary is the design, and it was chosen against a measured constraint.**
`methodology-status --target . --fail-on-drift` is the mandated lane-start command rendered into
every generated adapter, and `adapters/projects/example-saas.json` already carries a
`milestoneClose` deployment target. A drift failure keyed on "milestone-close target without the
profile" would therefore red every live-surface lane at session start on upgrade, with no
migration -- the adapter-removal 0.6.115 class, where a control shipped faster than lanes could
adopt it and had to be reverted.

So a lane that has not opted in gets a warn line and nothing else, at any flag combination; the
forcing function is a shipped, tested switch rather than silence.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rows(**states):
    return [{"control": control, "state": state, "detail": ""} for control, state in states.items()]


def _all_blocking(cli):
    return _rows(**{control: "block" for control in cli.GO_LIVE_CONTROLS})


LIVE_SURFACE = {"deploymentTargets": [{"name": "web", "milestoneClose": True}]}


# --- the un-opted lane: warn only, never a failure ----------------------------------------------


def test_unopted_live_surface_never_fails_drift(cli):
    """THE PIN this whole design rests on. One warn line, zero failing issues.

    If this ever returns a failing issue, every live-surface lane on the fleet reds at session
    start on upgrade with no migration path.
    """
    issues, warns = cli.go_live_posture_issues(dict(LIVE_SURFACE), _rows())
    assert issues == []
    assert len(warns) == 1
    assert "goLiveReadiness.profile" in warns[0]


def test_a_lane_with_no_live_surface_says_nothing(cli):
    assert cli.go_live_posture_issues({}, _rows()) == ([], [])
    assert cli.go_live_posture_issues({"deploymentTargets": [{"name": "x"}]}, _rows()) == ([], [])


def test_go_live_readiness_enforcement_defaults_warn(cli):
    """The forcing function ships now and is OFF by default; flipping it is a separate release."""
    assert cli.DEFAULT_GO_LIVE_READINESS["enforcement"] == "warn"
    assert cli.DEFAULT_GO_LIVE_READINESS["profile"] == "off"


def test_the_lane_can_flip_its_own_switch(cli):
    """`enforcement: block` makes the un-opted live-surface case drift, for that lane only."""
    data = {**LIVE_SURFACE, "goLiveReadiness": {"enforcement": "block"}}
    issues, warns = cli.go_live_posture_issues(data, _rows())
    assert len(issues) == 1
    assert warns == []


def test_declining_the_profile_itself_silences_the_warn(cli):
    data = {
        **LIVE_SURFACE,
        "goLiveReadiness": {
            "declines": [
                {
                    "control": "goLiveReadiness.profile",
                    "reason": "internal tooling lane; no customer surface behind this target",
                }
            ]
        },
    }
    assert cli.go_live_posture_issues(data, _rows()) == ([], [])


# --- the opted-in lane: held to the gates -------------------------------------------------------


def test_opting_in_holds_every_gate(cli):
    data = {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}
    issues, warns = cli.go_live_posture_issues(data, _rows())
    assert warns == []
    assert len(issues) == len(cli.GO_LIVE_CONTROLS)
    # The refusal NAMES the control -- a refusal that reports a total is not actionable.
    for control in cli.GO_LIVE_CONTROLS:
        assert any(control in issue for issue in issues), control


def test_all_controls_blocking_is_clean(cli):
    """Non-vacuity floor: the gate must be satisfiable, or it is a wall rather than a gate."""
    data = {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}
    assert cli.go_live_posture_issues(data, _all_blocking(cli)) == ([], [])


def test_a_recorded_decline_clears_one_control_and_only_that_one(cli):
    data = {
        **LIVE_SURFACE,
        "goLiveReadiness": {
            "profile": "live-tenant",
            "declines": [
                {
                    "control": "healthContract",
                    "reason": "no customer-visible outcome to contract on",
                }
            ],
        },
    }
    issues, _warns = cli.go_live_posture_issues(data, _rows())
    assert not any("healthContract" in issue for issue in issues)
    assert any("ciTestGate" in issue for issue in issues)


def test_a_decline_must_actually_say_something(cli):
    """A decline nobody wrote a reason for is an undeclared gap wearing a declaration's clothes."""
    data = {
        **LIVE_SURFACE,
        "goLiveReadiness": {
            "profile": "live-tenant",
            "declines": [{"control": "healthContract", "reason": "n/a"}],
        },
    }
    issues, _warns = cli.go_live_posture_issues(data, _rows())
    assert any("healthContract" in issue for issue in issues)


def test_a_missing_row_is_treated_as_off_not_as_satisfied(cli):
    """A control the posture engine did not report is an unknown, and unknown is not `block`.

    Defaulting a missing row to satisfied is the fail-open shape this program keeps finding.
    """
    data = {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}
    issues, _warns = cli.go_live_posture_issues(data, [])
    assert len(issues) == len(cli.GO_LIVE_CONTROLS)


# --- the table and the policy module must name the same gates -----------------------------------


def test_go_live_gate_controls_are_all_real_posture_controls(cli):
    """Every control this gate names must be one the posture engine actually emits.

    A gate keyed on a control nobody reports refuses forever and cannot be satisfied.
    """
    data = cli.load_project(REPO_ROOT / "adapters" / "projects" / "example-saas.json")
    emitted = {row["control"] for row in cli.control_posture_rows(data)}
    assert set(cli.GO_LIVE_CONTROLS) <= emitted, set(cli.GO_LIVE_CONTROLS) - emitted


def test_go_live_gate_labels_match_policy_module(cli):
    """The policy text and the table must name the same gates.

    A gate in prose and not in the table is a control nobody enforces; one in the table and not in
    prose is a refusal nobody can read about.
    """
    module = (REPO_ROOT / "methodology" / "policy" / "16a-go-live-readiness.md").read_text(
        encoding="utf-8"
    )
    for label, _controls in cli.GO_LIVE_GATES:
        assert label in module, label


def test_the_policy_module_is_in_the_canonical_assembly(cli):
    assembled = cli.canonical_policy_text_from_modules()
    assert "## Go-Live Readiness Gate" in assembled


def test_the_schema_declares_the_key_with_the_shipped_defaults(cli):
    schema = json.loads(
        (REPO_ROOT / "methodology" / "adapter-schema.json").read_text(encoding="utf-8")
    )
    props = schema["properties"]["goLiveReadiness"]["properties"]
    assert props["profile"]["enum"] == ["off", "live-tenant"]
    assert props["enforcement"]["default"] == cli.DEFAULT_GO_LIVE_READINESS["enforcement"]
    assert props["declines"]["items"]["required"] == ["control", "reason"]


def test_the_refusal_names_a_fix_the_adopter_can_actually_perform(cli):
    """Codex R1 P2. "Set it to enforcement block" is a DEAD END for a control with no such field.

    `criticalJourneys` is an array; `readiness` and `flakyQuarantine` report `unreachable` until
    their paths or sources exist. The posture row already carries the specific detail and default
    status output hides it, so the refusal carries it. A refusal naming a fix the adopter cannot
    perform is the dead-end class this program exists to delete.
    """
    rows = [
        {
            "control": "criticalJourneys",
            "state": "empty",
            "detail": "no declared critical journeys: the pending ratchet guards nothing",
        }
    ]
    data = {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}
    issues, _warns = cli.go_live_posture_issues(data, rows)
    journey = next(issue for issue in issues if "criticalJourneys" in issue)
    assert "no declared critical journeys" in journey
    # ...and it still offers both routes, so declining stays available.
    assert "goLiveReadiness.declines" in journey


def test_a_control_with_no_detail_still_produces_a_clean_message(cli):
    """The detail is optional; the refusal must not grow an empty parenthesis."""
    rows = [{"control": "ciTestGate", "state": "off", "detail": ""}]
    data = {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}
    issues, _warns = cli.go_live_posture_issues(data, rows)
    gate = next(issue for issue in issues if "ciTestGate" in issue)
    assert "()" not in gate


# --- Codex R1: a crash, a deadlock, and a safety classification that would have been false --------


def test_a_malformed_key_is_an_actionable_error_not_a_crash(cli):
    """Adapter validation continues with semantic checks when the schema is unreadable.

    So a malformed value reaches this code, and a truthy non-object used to raise TypeError out of
    `methodology-status`. A crash is not an actionable adapter error: it names no key, and it takes
    down the surface that would have named one.
    """
    data = {"goLiveReadiness": "live-tenant", "deploymentTargets": [{"milestoneClose": True}]}
    issues, warns = cli.go_live_posture_issues(data, [])
    assert warns == []
    assert "must be an object" in issues[0]

    data = {"goLiveReadiness": {"declines": "healthContract"}, **LIVE_SURFACE}
    issues, _warns = cli.go_live_posture_issues(data, [])
    assert "declines must be an array" in issues[0]


def test_a_malformed_decline_entry_grants_no_exemption(cli):
    """Skipping is the safe direction: a decline nobody can parse must not silence its control."""
    data = {
        **LIVE_SURFACE,
        "goLiveReadiness": {"profile": "live-tenant", "declines": ["healthContract", None]},
    }
    issues, _warns = cli.go_live_posture_issues(data, [])
    assert any("healthContract" in issue for issue in issues)


def test_following_the_go_live_advice_cannot_deadlock_remediation(cli):
    """Codex R1 P2, and it is a DEADLOCK rather than a missing convenience.

    Setting `healthContract` to enforcement block clears the go_live issue and ACTIVATES
    health_contract_failures on a target with no outcomeSignals. The marker then carries only
    `health_contract`, and the source-adapter edit that adds the signals needs `render-adapters` --
    which only the go_live entry permitted. The adopter is left in a remediation session that
    refuses the one command that clears it.
    """
    recovery = cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS
    assert "render-adapters" in recovery["go_live"]
    assert "render-adapters" in recovery["health_contract"]


def test_wip_safety_composes_down_from_the_predecessor_it_carries(cli):
    """This release's own change is WIP-safe; the migrations it CARRIES are not.

    A jump upgrade consumes only the newest report, so a lane skipping 0.79.0 reads this one and
    nothing else. Advertising that path as WIP-safe would be false for exactly the population that
    cannot see the classification it skipped. Safety composes down, never up.
    """
    predecessor = cli.release_migration_report_data("0.79.0")
    current = cli.release_migration_report_data("0.80.0")
    assert predecessor["wipSafe"] is False
    assert current["wipSafe"] is False
    # ...and the reason it is false is that it carries that predecessor's migration.
    carried = {entry["id"] for entry in current["requiredMigrations"]}
    assert "reconcile-a-contradicting-framework-checkout" in carried


def test_a_declines_fields_must_be_strings_not_anything_stringifiable(cli):
    """Codex R2. `str()` coercion let malformed configuration DISABLE enforcement.

    `reason: 123456789012` stringifies to twelve characters and cleared the floor; a list of words
    cleared it too. The schema requires strings, and when the schema is unreadable -- a supported
    fail-open path -- this check is the only thing between a typo and a silenced gate.
    """
    for bad_reason in (123456789012, ["not", "a", "reason"], {"why": "because"}, True):
        data = {
            **LIVE_SURFACE,
            "goLiveReadiness": {
                "declines": [{"control": "goLiveReadiness.profile", "reason": bad_reason}]
            },
        }
        _issues, warns = cli.go_live_posture_issues(data, [])
        assert warns, f"a {type(bad_reason).__name__} reason silenced the gate"

    # A non-string control is equally inert.
    data = {
        **LIVE_SURFACE,
        "goLiveReadiness": {
            "profile": "live-tenant",
            "declines": [{"control": 7, "reason": "x" * 20}],
        },
    }
    issues, _warns = cli.go_live_posture_issues(data, [])
    assert len(issues) == len(cli.GO_LIVE_CONTROLS)


def test_every_downstream_gate_can_be_re_rendered_during_remediation(cli):
    """Codex R2, and the R1 fix for this was PARTIAL -- it covered one gate of five.

    Bringing a go-live control to `block` activates that control's own gate, whose fix is a
    source-adapter edit plus a re-render. R1 fixed `health_contract`; R2 found `ciTestGate` has the
    identical shape. Driven by a list now, so a control added to GO_LIVE_GATES cannot silently miss
    its downstream entry.
    """
    recovery = cli.STARTUP_REMEDIATION_GATE_RECOVERY_COMMANDS
    for gate in cli.GO_LIVE_DOWNSTREAM_GATES:
        assert "render-adapters" in recovery.get(gate, ()), gate
    # ...and every one names a real gate, or the list is protecting nothing.
    display = set(cli.METHODOLOGY_STATUS_GATE_DISPLAY_NAMES.values())
    assert set(cli.GO_LIVE_DOWNSTREAM_GATES) <= display


def test_a_misspelled_opt_in_is_refused_by_name(cli):
    """Codex R3, and the third round to find a fail-open in this same input-validation surface.

    `profile: "live_tenant"` used to read as the UN-OPTED case: with the default warn enforcement it
    contributed no failure at all while enforcing none of the go-live controls. A misspelled opt-in
    is the most dangerous input here, because the lane that wrote it believes it is covered.
    Refusing it by name is the only answer that leaves the adopter better off than silence.
    """
    for bad in (
        {"profile": "live_tenant"},
        {"profile": "LIVE-TENANT"},
        {"profile": None},
        {"profile": "live-tenant", "enforcement": "blocK"},
        {"profile": "live-tenant", "enforcement": True},
    ):
        issues, warns = cli.go_live_posture_issues({**LIVE_SURFACE, "goLiveReadiness": bad}, [])
        assert issues, bad
        assert warns == [], bad
        assert "SOURCE adapter" in issues[0]


def test_the_accepted_vocabularies_match_the_published_schema(cli):
    """The check and the schema must not drift: a value the schema allows must not be refused."""
    schema = json.loads(
        (REPO_ROOT / "methodology" / "adapter-schema.json").read_text(encoding="utf-8")
    )
    props = schema["properties"]["goLiveReadiness"]["properties"]
    assert tuple(props["profile"]["enum"]) == cli.GO_LIVE_PROFILES
    assert tuple(props["enforcement"]["enum"]) == cli.GO_LIVE_ENFORCEMENTS
    # ...and the shipped defaults are themselves valid members.
    assert cli.DEFAULT_GO_LIVE_READINESS["profile"] in cli.GO_LIVE_PROFILES
    assert cli.DEFAULT_GO_LIVE_READINESS["enforcement"] in cli.GO_LIVE_ENFORCEMENTS


def test_the_adoption_checklist_exists_and_names_every_live_adapter(cli):
    """Codex R4. "Gated on adoption" is a sentence unless the gate has a written criterion.

    The release claims the default flip to `block` is gated on adoption. Without a checklist there
    is nothing to be gated ON: no enumeration of the lanes that must adopt, and no zero-open
    criterion. This asserts the list exists AND covers every adapter that would be affected, because
    a checklist that silently stops covering new lanes reports zero open rows while lanes go
    untracked -- worse than none.
    """
    checklist = (REPO_ROOT / "docs" / "backlog" / "methodology-backlog.md").read_text(
        encoding="utf-8"
    )
    assert "Go-live readiness adoption checklist" in checklist

    # It names the ENUMERATION COMMAND rather than transcribing adapters. A hand-typed list goes
    # stale the moment an adapter gains a milestone-close target, and a checklist that silently
    # stops covering new lanes reports zero open rows while lanes go untracked. The command cannot
    # go stale, and the public-boundary scan independently forbids naming a product here.
    assert "grep -ln milestoneClose adapters/projects/*.json" in checklist
    assert "zero open rows" in checklist
    # ...and the command it names must actually find the live lanes.
    live = [
        path.name
        for path in sorted((REPO_ROOT / "adapters" / "projects").glob("*.json"))
        if "milestoneClose" in path.read_text(encoding="utf-8")
    ]
    assert live, "the enumeration command finds nothing; the checklist would be vacuous"


def test_the_policy_does_not_prescribe_an_impossible_state(cli):
    """Codex R4. `criticalJourneys` is an array; adding `enforcement` to it is schema-invalid.

    Telling an adopter to put every gate at `enforcement: block` names a fix that cannot be applied
    for exactly the controls most likely to be unsatisfied -- the same dead end already fixed in the
    CLI's per-control message, surviving in the canonical prose.
    """
    module = (REPO_ROOT / "methodology" / "policy" / "16a-go-live-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "satisfiable enforcing state" in module
    assert "schema-invalid" in module


def test_the_checklist_predicate_keeps_a_row_open_until_the_work_is_done(cli):
    """Codex R5. A warn-only predicate closes the row the moment a lane DECLARES intent.

    Opting in stops `go_live_posture_warn` and starts emitting per-control `go_live_posture_issue`
    lines, so "open while it warns" marks the row closed before any control is satisfied -- letting
    the zero-open criterion be reached by declaring intent rather than doing the work, which is
    exactly what the gate exists to prevent.
    """
    checklist = (REPO_ROOT / "docs" / "backlog" / "methodology-backlog.md").read_text(
        encoding="utf-8"
    )
    assert "go_live_posture_warn:" in checklist
    assert "go_live_posture_issue:" in checklist

    # The behaviour the predicate has to track: opting in swaps warns for issues.
    unopted_issues, unopted_warns = cli.go_live_posture_issues(dict(LIVE_SURFACE), _rows())
    assert unopted_warns and not unopted_issues
    opted = {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}
    opted_issues, opted_warns = cli.go_live_posture_issues(opted, _rows())
    assert opted_issues and not opted_warns


def test_the_adoption_migration_does_not_prescribe_an_impossible_state(cli):
    """Codex R5. The same dead end, surviving in the PRIMARY actionable instruction.

    Policy 16a and the CLI message were both corrected; the generated migration text still said
    "enforcement: block" for every gate. That is the one an upgrading adopter reads first.
    """
    report = cli.release_migration_report_data("0.80.0")
    adopt = next(
        entry
        for entry in report["optionalMigrations"]
        if entry["id"] == "adopt-the-go-live-readiness-profile"
    )
    assert "SCHEMA-INVALID" in adopt["description"]
    assert "its own satisfying state" in adopt["description"].lower()


def test_no_surface_anywhere_prescribes_a_blanket_enforcement_block(cli):
    """Codex, FOURTH sighting. The same wrong remedy kept surviving in surfaces I had not swept.

    Corrected in the CLI per-control message (R1), policy 16a (R4), the generated migration (R5),
    and finally the adapter schema description, the behaviour-changes text and the CHANGELOG. When a
    remedy is wrong it is usually wrong everywhere it is written, and the copy nobody thought of is
    the one users hit -- so this asserts the property across EVERY surface at once rather than
    fixing them one review round at a time.
    """
    surfaces = {
        "schema": json.loads(
            (REPO_ROOT / "methodology" / "adapter-schema.json").read_text(encoding="utf-8")
        )["properties"]["goLiveReadiness"]["description"],
        "policy": (REPO_ROOT / "methodology" / "policy" / "16a-go-live-readiness.md").read_text(
            encoding="utf-8"
        ),
        "behaviour": " ".join(cli.release_migration_report_data("0.80.0")["behaviorChanges"]),
        "migration": " ".join(
            entry["description"]
            for entry in cli.release_migration_report_data("0.80.0")["optionalMigrations"]
        ),
    }
    for name, text in surfaces.items():
        lowered = text.lower()
        # Every surface that mentions the enforcing state must also say it is NOT uniform.
        assert "schema-invalid" in lowered, name
        assert (
            "own satisfying state" in lowered
            or "own satisfiable enforcing state" in lowered
        ), name


# --- Codex R2: three more ways a control can look satisfied while asserting nothing --------------


def test_a_misspelled_readiness_key_is_refused_by_name(cli):
    """`{"profil": "live-tenant"}` used to merge cleanly and read as un-opted.

    This is the most dangerous input on the surface, because the lane that wrote it BELIEVES it is
    covered. On the supported unreadable-schema path nothing else stands between the typo and a
    disabled gate.
    """
    data = {**LIVE_SURFACE, "goLiveReadiness": {"profil": "live-tenant"}}
    issues, warns = cli.go_live_posture_issues(data, _all_blocking(cli))
    assert warns == []
    assert len(issues) == 1
    assert "profil" in issues[0] and "unknown key" in issues[0]


def test_a_valid_readiness_block_is_not_refused_as_unknown(cli):
    """The negative half: rejecting unknown keys must not reject the supported ones."""
    data = {
        **LIVE_SURFACE,
        "goLiveReadiness": {"profile": "live-tenant", "enforcement": "warn", "declines": []},
    }
    issues, _warns = cli.go_live_posture_issues(data, _all_blocking(cli))
    assert issues == []


def test_a_registry_nothing_asserts_is_not_a_satisfied_control(cli, tmp_path):
    """Registered secrets + `enforcement: block` + no assertion command = nothing is verified.

    The row used to read `block` on exactly that input, so the gate reported satisfied while no
    command on the lane ever checked a single declared secret -- the #448 shape.
    """
    data = {
        "runtimeConfig": {
            "enforcement": "block",
            "requiredSecrets": [{"name": "STRIPE_KEY"}],
            "bootAssertionCommand": "",
            "secretParityCommand": "",
        }
    }
    row = next(
        r
        for r in cli.control_posture_rows(data, tmp_path)
        if r["control"] == "runtimeConfig.requiredSecrets"
    )
    assert row["state"] == "empty"
    assert "nothing asserts them" in row["detail"]


def test_an_asserted_registry_is_satisfied(cli, tmp_path):
    """Non-vacuity: the control must still be reachable, or the gate is simply always unmet."""
    data = {
        "runtimeConfig": {
            "enforcement": "block",
            "requiredSecrets": [{"name": "STRIPE_KEY"}],
            "bootAssertionCommand": "./scripts/assert-secrets.sh",
        }
    }
    row = next(
        r
        for r in cli.control_posture_rows(data, tmp_path)
        if r["control"] == "runtimeConfig.requiredSecrets"
    )
    assert row["state"] == "block"


def test_both_refusals_name_the_reason_length_floor(cli):
    """A refusal that asks for "a reason" from someone who supplied one is not actionable."""
    profile_decline = cli.go_live_posture_issues(
        {**LIVE_SURFACE, "goLiveReadiness": {"enforcement": "block"}}, _all_blocking(cli)
    )[0]
    rows = _all_blocking(cli)
    rows[0] = {**rows[0], "state": "off"}
    control_decline = cli.go_live_posture_issues(
        {**LIVE_SURFACE, "goLiveReadiness": {"profile": "live-tenant"}}, rows
    )[0]
    for message in (profile_decline[0], control_decline[0]):
        assert f"at least {cli.GO_LIVE_DECLINE_MIN_REASON} characters" in message


def test_the_profile_predicate_refuses_a_malformed_block(cli):
    """`go_live_profile_active` must never report an opt-in the validator is about to refuse."""
    assert cli.go_live_profile_active({"goLiveReadiness": {"profile": "live-tenant"}})
    assert not cli.go_live_profile_active({"goLiveReadiness": "live-tenant"})
    assert not cli.go_live_profile_active({"goLiveReadiness": {"profile": "live_tenant"}})
    assert not cli.go_live_profile_active({})
