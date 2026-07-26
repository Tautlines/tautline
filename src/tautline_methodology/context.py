"""Context-rotation leaf: the pure rotation decision core that maps a measured (or estimated)
context-usage percent to an action/urgency verdict, capping any non-host-sourced percent to
advisory (provenance gate RCA 20260615T181937Z). The stateful context verb handlers
(context_bootstrap, context_status, context_rotation_check, context_rotation_heartbeat_hook,
...) stay in bin/tautline; they reach lane/adapter/goal-run state and delegate the decision
core here."""

from __future__ import annotations


def context_rotation_decision(
    rotation: dict, percent: "int | None", safe_boundary: bool, source: "str | None"
) -> dict:
    """Decide the rotation action/urgency, capping a non-host-sourced percent at advisory.

    Provenance gate (RCA 20260615T181937Z): only a percent the host literally measured
    (source == 'host') may produce a 'mandatory' verdict. A self-estimate -- or a percent
    supplied with no --context-percent-source -- is treated as an estimate and capped to
    'recommended' (advisory) so a fabricated high number can never sanction a mandatory stop.
    The cap touches only the hard branch; soft-band, below-soft, None, and disabled paths are
    byte-identical regardless of source.
    """
    # Resolve the source label: omitted-with-a-percent resolves to 'estimate' (the safe
    # default); None percent has no source to report.
    if percent is None:
        resolved_source = "none"
    else:
        resolved_source = "host" if source == "host" else "estimate"
    source_is_host = resolved_source == "host"
    capped = False
    cap_reason = ""
    if not rotation["enabled"]:
        action = "continue"
        urgency = "disabled"
        reason = "context rotation disabled by adapter"
    elif percent is None:
        action = "check-visible-context"
        urgency = "unknown"
        reason = (
            "visible context percent was not supplied; inspect the host context indicator at the "
            "boundary. A self-estimated percentage is advisory only and is never a mandatory-rotation "
            "trigger or a stop reason; if the host exposes no percentage, continue to the next genuine "
            "safe boundary"
        )
    elif percent >= rotation["hardPercent"] and source_is_host:
        action = "rotate-now" if safe_boundary else "rotate-mandatory-at-next-safe-boundary"
        urgency = "mandatory"
        reason = f"context {percent}% is at or above hard threshold {rotation['hardPercent']}%"
    elif percent >= rotation["softPercent"]:
        # Both the genuine soft band and a capped (non-host) hard-band percent land here as
        # advisory. The cap flag/reason distinguish the two for machine-visible auditing.
        action = "rotate-now" if safe_boundary else "rotate-at-next-safe-boundary"
        urgency = "recommended"
        if percent >= rotation["hardPercent"]:
            capped = True
            cap_reason = (
                f"context {percent}% is at or above hard threshold {rotation['hardPercent']}%, but the "
                "percent source is an estimate, not a host-exposed counter, so rotation is capped to "
                "advisory (recommended) and is not mandatory"
            )
            reason = cap_reason
        else:
            reason = f"context {percent}% is at or above soft threshold {rotation['softPercent']}%"
    else:
        action = "continue"
        urgency = "none"
        reason = f"context {percent}% is below soft threshold {rotation['softPercent']}%"
    return {
        "action": action,
        "urgency": urgency,
        "reason": reason,
        "source": resolved_source,
        "capped": capped,
        "cap_reason": cap_reason,
    }
