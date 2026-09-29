"""What in-session enforcement a lane's runtime can actually run, and what it cannot.

THE POINT OF THIS MODULE IS THE HONEST ZERO. Seven of the framework's gates are harness hooks.
A lane whose builder runs in a harness that supplies no hooks loses all seven -- and before this
module, lost them with no signal at all: the controls simply never fired and nothing said so.
Reporting that is the whole job. It never blocks (decision D2); a `degradationPolicy` knob was
considered and cut as refuse-to-run re-entering through a side door.

CAPABILITIES ARE DATA. `methodology/runtime-capabilities.json` declares the vocabulary and the
shipped runtimes; an adapter adds or replaces entries for a runtime the framework has never seen.
Adding a harness is a data edit -- no enum, no code change, no upstream PR -- which is the same
rule `vendor` follows and for the same reason.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "tautline-runtime-capabilities/v1"
GATE = "gate"
CARRIER = "carrier"

# The record this module emits. Named as a constant because backlog item B4 (item 91) is a census
# of UNINVOKED controls and this is the runtime instance of the same idea -- controls that exist
# but CANNOT run here. The spec's cross-lock requires consuming B4's schema if it landed first or
# declaring the shared one explicitly; B4 has not landed, so this declares it.
DEGRADATION_RECORD_SCHEMA = "tautline-control-unavailable/v1"

_DATA_PATH = Path(__file__).resolve().parents[2] / "methodology" / "runtime-capabilities.json"


def _load(path: Path | None = None) -> dict:
    p = path or _DATA_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A MISSING TABLE IS ITS OWN STATE, and the first cut of this got it exactly backwards.
        # Returning empty dicts looked fail-safe -- zero capabilities, never full -- but it emptied
        # the VOCABULARY too. `gates_total` fell to 0, so nothing was missing, so `degraded()` was
        # false, so the lane went SILENT: the precise failure this module exists to prevent,
        # reached through its own fail-safe path. Found in review; the test meant to cover it
        # asserted on the primitives (`gate_ids() == []`) and never on the outcome.
        #
        # `_data_available` is what the record reads to say "the capability table could not be
        # read" rather than "this runtime has no gates". Different facts, different remedies:
        # repair the install versus accept the gaps.
        return {"capabilities": {}, "runtimes": {}, "_data_available": False}


def vocabulary(path: Path | None = None) -> dict[str, dict]:
    """capability id -> {kind, hook, event}."""
    data = _load(path)
    caps = data.get("capabilities")
    return caps if isinstance(caps, dict) else {}


def gate_ids(path: Path | None = None) -> list[str]:
    return sorted(k for k, v in vocabulary(path).items() if v.get("kind") == GATE)


def carrier_ids(path: Path | None = None) -> list[str]:
    return sorted(k for k, v in vocabulary(path).items() if v.get("kind") == CARRIER)


def shipped_runtimes(path: Path | None = None) -> dict[str, list[str]]:
    data = _load(path)
    runtimes = data.get("runtimes")
    return runtimes if isinstance(runtimes, dict) else {}


def effective_capabilities(data: dict, runtime: str, path: Path | None = None) -> list[str]:
    """The capabilities `runtime` actually supplies in this lane.

    WHOLE-ENTRY REPLACEMENT, PER RUNTIME, ADAPTER WINS -- never a union. Union semantics would
    make it impossible to REMOVE a capability the framework wrongly credits a runtime with: an
    adopter whose harness dropped a hook could never say so, and the framework would keep
    reporting enforcement that does not run. Runtimes the adapter does not name keep the shipped
    list untouched.

    An UNKNOWN runtime is zero-capable. That is the safe default rather than the intended path --
    `runtimeCapabilities` is how an adopter says what their harness really supplies.
    """
    name = str(runtime or "").strip()
    if not name:
        return []
    override = (data or {}).get("runtimeCapabilities")
    if isinstance(override, dict) and name in override:
        declared = override[name]
        if isinstance(declared, list):
            known = vocabulary(path)
            # Unknown ids are DROPPED rather than honoured. A typo would otherwise credit the
            # runtime with a gate that does not exist, which is the fail-open direction.
            return sorted({str(c) for c in declared} & set(known))
        return []
    shipped = shipped_runtimes(path).get(name)
    return sorted(shipped) if isinstance(shipped, list) else []


def lane_degradation(
    data: dict, role: str = "builder", path: Path | None = None
) -> dict:
    """The degradation record for the agent bound to `role`.

    Returns `available`/`missing` split by kind, plus the counts the surfaced line names. An
    unresolvable role or runtime yields the zero-capability record with `runtime: ""` -- the
    caller reports it, and reporting "nothing is known to run here" is more honest than silence.
    """
    from . import agents as agents_mod

    agent_id = agents_mod.role_agent_id(data, role) or ""
    record = agents_mod.agent_record(data, agent_id) or {}
    runtime = str(record.get("runtime", "")).strip()
    available = set(effective_capabilities(data, runtime, path))
    gates = gate_ids(path)
    carriers = carrier_ids(path)
    data_available = bool(_load(path).get("_data_available", True))
    return {
        "schema": DEGRADATION_RECORD_SCHEMA,
        "role": role,
        "agent": agent_id,
        "runtime": runtime,
        # UNRESOLVED IS NOT ZERO, and conflating them puts a false claim in a durable artifact.
        # A lane whose adapter never declares a builder is not a lane with no enforcement -- it is
        # a lane whose enforcement nobody stated. Reporting "0 of 7 gates" there would tell a PR
        # reviewer, months later, that the work was done ungated when it may have run under all
        # nine hooks. Overstating degradation is still a false report; the honesty this module
        # exists for cuts both ways.
        "resolved": bool(runtime),
        # Distinct from `resolved`. A lane can have a perfectly good runtime binding and still be
        # unreportable because the shipped capability table is missing -- a broken install, not a
        # broken adapter.
        "data_available": data_available,
        "gates_total": len(gates),
        "gates_available": sorted(available & set(gates)),
        "gates_missing": sorted(set(gates) - available),
        "carriers_total": len(carriers),
        "carriers_available": sorted(available & set(carriers)),
        "carriers_missing": sorted(set(carriers) - available),
    }


def degraded(record: dict) -> bool:
    """True when a RESOLVED runtime is missing something it should have.

    An unresolved lane is reported through `resolved`, not through this: "we could not tell" and
    "we checked and there is nothing" call for different responses -- declare the binding versus
    accept the missing gates -- and a single boolean that means both gets one of them wrong.
    """
    if not record.get("resolved"):
        return False
    if not record.get("data_available", True):
        # Cannot enumerate the gates, so cannot confirm any of them run. Reportable, not clean --
        # and deliberately NOT derived from `gates_missing`, which is empty here precisely because
        # the vocabulary could not be read.
        return True
    return bool(record.get("gates_missing") or record.get("carriers_missing"))


def summary_line(record: dict) -> str:
    """The one line every surface prints, so an operator reads the same sentence everywhere.

    Names BOTH counts. Crediting a runtime with an eighth gate that cannot block anything
    overstates enforcement, which is the same failure as hiding a missing one; the carriers are
    counted separately for exactly that reason.
    """
    if not record.get("data_available", True):
        return (
            "the shipped capability table could not be read, so no in-session gate can be "
            "confirmed for this lane; repair methodology/runtime-capabilities.json"
        )
    if not record.get("resolved"):
        # Distinct wording, deliberately. "supplies 0 of 7" is a measurement; this is the absence
        # of one, and the remedy differs -- declare the binding rather than accept the gaps.
        return (
            f"no runtime resolved for `roles.{record.get('role', 'builder')}`, so no in-session "
            "gate can be confirmed for this lane; declare the role and its agent's `runtime` to "
            "find out"
        )
    runtime = record.get("runtime")
    gates_ok = len(record.get("gates_available", []))
    carriers_ok = len(record.get("carriers_available", []))
    line = (
        f"runtime {runtime!r} supplies {gates_ok} of {record.get('gates_total', 0)} in-session "
        f"gates and {carriers_ok} of {record.get('carriers_total', 0)} session carriers"
    )
    # NAME what is missing, carriers included. Naming only the gates was safe while there were
    # seven of them; after the 2026-08-28 demolition left a carrier as the only declared
    # capability, a lane that supplies nothing would have printed a bare count and named nothing --
    # the "reports healthy while doing nothing" shape this line exists to prevent.
    missing = (record.get("gates_missing") or []) + (record.get("carriers_missing") or [])
    if missing:
        line += f"; ADVISORY in this lane: {', '.join(missing)}"
    return line
