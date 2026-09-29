"""R4: what a lane's runtime can actually enforce, and the honest zero when it cannot."""
import json
from pathlib import Path

import pytest

from tautline_methodology import runtime_capabilities as rc

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "plugins" / "tautline-core" / "hooks" / "hooks.json"


def _hook_commands():
    """Every command registered in hooks.json, with its event."""
    data = json.loads(HOOKS.read_text(encoding="utf-8"))
    found = []
    for event, entries in data.get("hooks", {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                if hook.get("type") == "command":
                    found.append((event, hook["command"]))
    return found


def test_the_vocabulary_is_exactly_the_hooks_that_exist():
    """The anti-abstraction guard, and the reason the vocabulary is derived rather than invented.

    One capability per registered hook. If the vocabulary could drift from `hooks.json`, the
    degradation report would describe a gate set nobody runs -- a control reporting on controls,
    itself unfalsifiable. A hook added or removed without touching the capability data fails
    here, which is the point: this test is what makes the report checkable.
    """
    registered = _hook_commands()
    vocab = rc.vocabulary()
    assert len(vocab) == len(registered), (
        f"{len(registered)} hooks registered but {len(vocab)} capabilities declared; "
        "every hook needs exactly one capability and vice versa"
    )
    # Match on the command TEXT, not on a hand-maintained name map: the command is what actually
    # runs, so a rename that forgot the capability data cannot pass by matching a stale label.
    declared = {v["hook"] for v in vocab.values()}
    for event, command in registered:
        assert any(d in command for d in declared), (
            f"hook {command!r} ({event}) has no capability entry"
        )


def test_gates_and_carriers_are_counted_separately():
    """The counts the surfaced line quotes. A carrier blocks nothing, so counting one as a gate
    would overstate enforcement -- the same failure as hiding a missing gate, in the opposite
    direction.

    The 2026-08-28 process-bankruptcy demolition removed all seven in-session GATES with the hooks
    behind them, leaving one carrier (`lane-status`). The distinction the assertion protects is
    still the point: whatever is declared, a carrier must never be counted as a gate."""
    # The carrier assertion is the one that bites today: it is the only DECLARED capability, so a
    # mislabel would flip it. The two gate assertions are vacuous over an empty gate set and are
    # kept deliberately -- they are what catches the mislabel on the day a gate is declared again.
    assert rc.carrier_ids() == ["hook.lane-status"]
    assert set(rc.gate_ids()) & set(rc.carrier_ids()) == set()
    assert all(rc.vocabulary()[cid]["kind"] == "gate" for cid in rc.gate_ids())


def test_codex_ships_zero_capabilities():
    """Re-verified at R4 rather than inherited, as the spec requires.

    `.codex-plugin/plugin.json` declares `skills` and has no `hooks` key, so a Codex-runtime lane
    supplies nothing in session. Writing down a capability the runtime does not have is exactly
    the fail-open this whole section closes.
    """
    codex_plugin = json.loads(
        (REPO / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json").read_text()
    )
    assert "hooks" not in codex_plugin, (
        "the Codex plugin grew a hooks key; re-derive its capability list rather than "
        "leaving the zero in place"
    )
    assert rc.shipped_runtimes()["codex"] == []


def test_an_unknown_runtime_is_zero_capable_not_fully_capable():
    """The safe default. An adopter on a harness the framework has never seen is told nothing
    runs, not that everything does."""
    assert rc.effective_capabilities({}, "never-heard-of-this") == []


def test_an_adapter_replaces_a_runtime_entry_outright():
    """WHOLE-ENTRY REPLACEMENT, and the removal case is why.

    Union semantics would make it impossible to remove a capability the framework wrongly credits
    a runtime with: an adopter whose harness dropped a hook could never say so. This asserts the
    replacement DROPS the rest, which a union would silently keep.
    """
    data = {"runtimeCapabilities": {"claude-code": ["hook.lane-status"]}}
    assert rc.effective_capabilities(data, "claude-code") == ["hook.lane-status"]


def test_an_unnamed_runtime_keeps_its_shipped_list():
    # `sorted` on the right, because `effective_capabilities` sorts and the raw table need not be.
    # With one shipped capability the difference was invisible; the second one
    # (`hook.builder-guard`) reddened this test on ORDER while the behaviour it names -- an
    # unnamed runtime keeps its own list -- was exactly right.
    data = {"runtimeCapabilities": {"acme-shell": ["hook.lane-status"]}}
    assert rc.effective_capabilities(data, "claude-code") == sorted(
        rc.shipped_runtimes()["claude-code"]
    )


def test_an_unknown_capability_id_is_dropped_not_honoured():
    """A typo must not credit the runtime with a gate that does not exist."""
    data = {"runtimeCapabilities": {"acme": ["hook.lane-status", "hook.not-a-real-thing"]}}
    assert rc.effective_capabilities(data, "acme") == ["hook.lane-status"]


def test_a_missing_capability_table_is_reported_as_degraded_not_as_silence(tmp_path):
    """THE FAIL-SAFE PATH MUST NOT BE THE SILENT PATH, which is how this was first written.

    Returning empty dicts on a missing table looked safe -- zero capabilities, never full -- but
    it emptied the VOCABULARY too. `gates_total` fell to 0, so nothing was missing, so `degraded()`
    was false, so the lane said nothing: the precise failure this module exists to prevent,
    reached through its own fail-safe.

    Asserted on the OUTCOME a reader sees, not on the primitives. The test this replaces checked
    `gate_ids() == []` and passed the whole time the end-to-end behaviour was silence -- a test
    can be green and still be looking at the wrong thing.
    """
    missing = tmp_path / "absent.json"
    record = rc.lane_degradation(_lane("claude-code"), path=missing)
    assert record["resolved"] is True, "the adapter binding is fine; the TABLE is what is missing"
    assert record["data_available"] is False
    assert rc.degraded(record), "a lane whose gates cannot be enumerated must not read as clean"
    line = rc.summary_line(record)
    assert "capability table could not be read" in line
    assert "0 of 0" not in line, "an unreadable table must not be phrased as a measured zero"


def test_a_missing_table_still_credits_no_capability_to_any_runtime(tmp_path):
    """The half that WAS right: nothing is credited when the table cannot be read."""
    missing = tmp_path / "absent.json"
    assert rc.effective_capabilities({}, "claude-code", missing) == []


def _lane(runtime):
    return {
        "agents": {"bot": {"vendor": "acme", "runtime": runtime, "instructionFile": "A.md"}},
        "roles": {"builder": "bot"},
    }


def test_a_fully_capable_lane_is_not_degraded():
    record = rc.lane_degradation(_lane("claude-code"))
    assert record["gates_missing"] == []
    assert record["carriers_missing"] == []
    assert not rc.degraded(record)


def test_a_zero_capability_lane_names_every_missing_gate():
    """The defect this release exists to expose: capabilities lost with no signal.

    Written against the DECLARED vocabulary rather than a hardcoded count, so the demolition of the
    gate family (2026-08-28) could not turn this into a test that passes by measuring nothing: the
    totals come from the capability table, and the assertion that every missing id is NAMED in the
    line -- not merely counted -- is the part that catches a silent loss."""
    record = rc.lane_degradation(_lane("codex"))
    assert record["gates_total"] == len(rc.gate_ids())
    assert record["carriers_total"] == len(rc.carrier_ids())
    assert record["gates_missing"] == rc.gate_ids()
    assert record["carriers_missing"] == rc.carrier_ids()
    assert rc.degraded(record)
    line = rc.summary_line(record)
    assert f"0 of {len(rc.gate_ids())} in-session gates" in line
    assert f"0 of {len(rc.carrier_ids())} session carriers" in line
    for capability in record["gates_missing"] + record["carriers_missing"]:
        assert capability in line, "the line must name what is advisory, not just count it"


def test_an_unresolved_lane_is_not_reported_as_zero_capable():
    """UNRESOLVED IS NOT ZERO, and conflating them puts a false claim in a durable artifact.

    A lane whose adapter never declares a builder is not a lane with no enforcement -- it is one
    whose enforcement nobody stated. Reporting "0 of 7 gates" would tell a PR reviewer, months
    later, that the work was done ungated when it may have run under all nine hooks. Overstating
    degradation is still a false report; the honesty this module exists for cuts both ways.

    The two states call for different responses -- declare the binding, versus accept the missing
    gates -- so the WORDING differs, not just a flag.
    """
    record = rc.lane_degradation({"agents": {}, "roles": {}})
    assert record["resolved"] is False
    assert not rc.degraded(record), "unresolved must not read as a measured zero"
    line = rc.summary_line(record)
    assert "no runtime resolved" in line
    assert "0 of 7" not in line, "an absence of measurement must not be phrased as a measurement"


def test_a_resolved_zero_capability_lane_still_reads_as_degraded():
    """The other side of the same distinction: a runtime that IS resolved and supplies nothing is
    a measured zero, and must not be softened by the unresolved wording."""
    record = rc.lane_degradation(_lane("codex"))
    assert record["resolved"] is True
    assert rc.degraded(record)
    assert f"0 of {len(rc.gate_ids())} in-session gates" in rc.summary_line(record)


def test_the_degradation_record_declares_its_shared_schema():
    """Cross-lock with backlog B4 (item 91), a census of UNINVOKED controls. This is the runtime
    instance of the same idea -- controls that exist but CANNOT run here. B4 has not landed, so
    the shared schema is declared here explicitly rather than invented twice."""
    record = rc.lane_degradation(_lane("codex"))
    assert record["schema"] == "tautline-control-unavailable/v1"


@pytest.mark.parametrize("runtime", ["claude-code", "codex"])
def test_the_shipped_lists_only_use_declared_capability_ids(runtime):
    known = set(rc.vocabulary())
    assert set(rc.shipped_runtimes()[runtime]) <= known


def test_the_capability_data_file_ships_with_the_release():
    """Capabilities are DATA, so the table ships the way the schema does. A release carrying the
    module without its table would report every runtime as zero-capable -- the fail-safe
    direction, but wrong, and silently so."""
    from tautline_methodology import cli

    assert "methodology/runtime-capabilities.json" in cli.RELEASE_ARTIFACT_PATHS
    assert "src/tautline_methodology/runtime_capabilities.py" in cli.RELEASE_ARTIFACT_PATHS


def test_the_adapter_schema_accepts_runtime_capabilities():
    schema = json.loads((REPO / "methodology" / "adapter-schema.json").read_text())
    key = schema["properties"]["runtimeCapabilities"]
    assert key["type"] == "object"
    assert key["additionalProperties"]["type"] == "array"


def test_a_legacy_adapter_is_not_reported_as_degraded():
    """THE NON-REGRESSION CASE, and the one most likely to be got wrong.

    The compat shim projects a legacy adapter's builder onto the `claude-code` runtime. If that
    projection were missed, every existing lane would start reporting `0 of 7 gates` at session
    start while actually running all nine hooks -- a false alarm on every adopter, from a feature
    whose entire purpose is to be believed about enforcement. Crying wolf here would be worse
    than the silence it replaces.
    """
    from tautline_methodology import agent_compat

    # `claudeReview` is what the shim reads to project a BUILDER. An adapter with only
    # `codexWrapper` declares a reviewer and no builder, which is the unresolved case above
    # rather than the non-regression case under test here -- a distinction this test got wrong
    # on its first writing.
    projected = agent_compat.effective_agents(
        {"review": {"codexWrapper": "./x.sh", "claudeReview": {"enabled": True}}}
    )
    record = rc.lane_degradation(projected)
    assert record["runtime"] == "claude-code"
    assert record["resolved"] is True
    assert not rc.degraded(record), rc.summary_line(record)
