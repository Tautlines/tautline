"""Agent registry and per-seam role bindings.

Pure leaf module (no cli imports) so the registry and its validation are unit-testable in
isolation and only thin wiring touches the cli.py monolith -- the plan_authoring.py precedent.

THIS MODULE KNOWS WHAT A VENDOR FIELD IS AND NOTHING ABOUT ANY PARTICULAR VENDOR. It compares
two vendor strings for inequality and does nothing else with them: no enum, no allowlist, no
known-vendor table, no equality against a literal. That is the load-bearing constraint of the
whole design -- backlog item B2 measured the failure mode it avoids ("ten SystemExit refusals
and ten single-member schema enums still reject any non-Minervit value"). An adopter running
Mistral and a local Llama registers "mistral" and "meta" and every gate works unchanged.

Vendor and runtime are SEPARATE AXES and both are load-bearing. `runtime` identifies the
harness and determines what enforcement is available; `vendor` identifies the model provider
and determines blind-spot independence. Collapsing them yields either "two Claude Code lanes on
different models count as cross-model" or "a vendor may only have one harness", both wrong.
"""
from __future__ import annotations

import re
from pathlib import Path

ROLE_NAMES: tuple[str, ...] = (
    "planner",
    "planReviewer",
    "builder",
    "implementationReviewer",
)

REQUIRED_AGENT_FIELDS: tuple[str, ...] = ("vendor", "runtime", "instructionFile")

# An agent id becomes a directory name (`<runsDir>/<agent-id>-fast-mode-bin/`), so it is
# validated as a slug rather than trusted.
_SAFE_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _safe_instruction_file(value: str) -> bool:
    """A single project-relative path component -- the SYNTACTIC half of the check.

    This module never sees the render target, so it cannot resolve symlinks; that half is
    `instruction_file_escapes_target` below, called by the renderer where the target is known.
    Claiming resolution here would be a guarantee this function cannot make.
    """
    candidate = str(value or "")
    if not candidate or candidate.startswith("/"):
        return False
    parts = candidate.replace("\\", "/").split("/")
    return len(parts) == 1 and parts[0] not in ("", ".", "..")


def instruction_file_escapes_target(target, instruction_file: str) -> bool:
    """True when writing `instruction_file` inside `target` would land outside it.

    The RESOLUTION half. A syntactically clean single component still escapes if the path
    already exists as a symlink -- `ACME.md -> /etc/x` in the target makes a write to `ACME.md`
    a write to `/etc/x`. Called by the renderer, which is the only layer that knows the target.
    """
    root = Path(target).resolve(strict=False)
    resolved = (root / instruction_file).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return True
    return False


def canonical_vendor(value) -> str:
    """The comparison form of a vendor value.

    Free-form is NOT the same as uncanonicalised, and conflating them opens a hole in the
    load-bearing check: "OpenAI" and "openai" are the same provider, but a raw string
    inequality calls them different, so `enforcement: block` would pass a same-provider review
    as independent -- losing exactly the property D1 exists to assert.

    This adds no allowlist and no knowledge of any particular provider. It only stops the check
    being defeated by capitalisation or stray whitespace.
    """
    return str(value or "").strip().casefold()


def _registry(data: dict) -> dict:
    """The effective `agents` block: what the adapter declared, plus any legacy inference.

    The inference is merged HERE, on read, and never written into the adapter mapping -- see
    `agent_compat.effective_agents`. Anything a serialiser can reach eventually gets serialised,
    and a synthesised registry landing in a generated adapter turns a runtime convenience into
    content the adopter never wrote.

    Imported lazily so this stays a leaf module: `agent_compat` imports `agents`, not the
    reverse.
    """
    from . import agent_compat

    return agent_compat.merged_registry(data)


def _bindings(data: dict) -> dict:
    """The effective `roles` block. Same read-time merge as `_registry`."""
    from . import agent_compat

    return agent_compat.merged_bindings(data)


def _declared_registry(data: dict) -> dict:
    """Only what the adapter literally declared -- for VALIDATION, which judges the adopter's
    own document and must not report errors about entries the shim synthesised.

    Total on malformed input: `validate-adapter` runs on adapters that are already invalid, and
    its contract is to REPORT the violations rather than traceback before printing them."""
    block = data.get("agents") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def _declared_bindings(data: dict) -> dict:
    block = data.get("roles") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def agent_ids(data: dict) -> list[str]:
    """Every registered agent id, sorted, for stable remedy messages."""
    return sorted(_registry(data))


def agent_record(data: dict, agent_id: str) -> dict | None:
    record = _registry(data).get(str(agent_id or ""))
    return record if isinstance(record, dict) else None


def role_agent_id(data: dict, role: str) -> str | None:
    """The agent id bound to `role`, or None. NEVER a default -- an unbound role is unbound,
    and the gate that needs it refuses with a remedy rather than guessing."""
    value = _bindings(data).get(str(role or ""))
    value = str(value).strip() if isinstance(value, str) else ""
    return value or None


def role_agent(data: dict, role: str) -> dict | None:
    agent_id = role_agent_id(data, role)
    return agent_record(data, agent_id) if agent_id else None


def role_vendor(data: dict, role: str) -> str | None:
    """The role's vendor in CANONICAL form, or None. Callers compare these directly."""
    record = role_agent(data, role)
    if record is None:
        return None
    return canonical_vendor(record.get("vendor")) or None


def role_runtime(data: dict, role: str) -> str | None:
    record = role_agent(data, role)
    if record is None:
        return None
    value = str(record.get("runtime", "")).strip()
    return value or None


def agents_registry_errors(data: dict) -> list[str]:
    """Structural errors in `agents`/`roles`; empty means valid.

    An adapter declaring neither block is VALID -- R1 is inert by construction and must not
    make a legacy adapter newly invalid.
    """
    errors: list[str] = []
    # TWO DIFFERENT VIEWS, on purpose.
    #
    # Agent RECORDS are validated from what the adapter DECLARED: validation judges the adopter's
    # own document, and reporting a missing field on a record the shim synthesised would be an
    # error about something they never wrote.
    #
    # Role REFERENCES are resolved against the EFFECTIVE registry, which includes shim-synthesised
    # agents. An adapter that declares `roles.implementationReviewer = "codex"` while still
    # carrying `review.codexWrapper` is the additive partial migration D3 exists to support --
    # rejecting it would refuse the exact path the shim was built to make possible.
    declared = _declared_registry(data)
    effective = _registry(data)
    available = sorted(effective)
    for agent_id in sorted(declared):
        record = declared[agent_id]
        if not isinstance(record, dict):
            errors.append(f"agents.{agent_id} must be an object")
            continue
        for field in REQUIRED_AGENT_FIELDS:
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"agents.{agent_id} is missing a non-empty {field}; "
                    f"every registered agent needs {', '.join(REQUIRED_AGENT_FIELDS)}"
                )
        # The vendor must be non-empty AFTER canonicalisation, or the comparison it feeds is
        # meaningless -- a whitespace-only vendor would compare equal to another whitespace-only
        # vendor and read as a same-vendor refusal, or unequal to a real one and pass.
        if "vendor" in record and not canonical_vendor(record.get("vendor")):
            errors.append(f"agents.{agent_id}.vendor is empty after trimming")
        # PATH SAFETY. Both of these become filesystem paths the adapter controls: the agent id
        # becomes `<runsDir>/<agent-id>-fast-mode-bin/`, and instructionFile becomes a rendered
        # output name. `../../etc/x` in either would write outside the target. Validated, never
        # silently sanitised -- rewriting a path an adopter wrote is how a config error becomes
        # a mystery.
        if not _SAFE_AGENT_ID.fullmatch(agent_id):
            errors.append(
                f"agents.{agent_id} is not a safe agent id; ids must match "
                f"{_SAFE_AGENT_ID.pattern} (no path separators) because the id becomes a "
                "fast-mode shim directory name"
            )
        instruction_file = str(record.get("instructionFile") or "")
        if instruction_file and not _safe_instruction_file(instruction_file):
            errors.append(
                f"agents.{agent_id}.instructionFile {instruction_file!r} must be a single "
                "project-relative path component: no leading '/', no '..' segment, no separator"
            )
        # NOTE: this is the syntactic half only. The renderer calls
        # `instruction_file_escapes_target` with the real target, because a syntactically clean
        # name still escapes when it already exists there as a symlink.
    for role in sorted(_declared_bindings(data)):
        if role not in ROLE_NAMES:
            errors.append(
                f"roles.{role} is not a known role; roles are {', '.join(ROLE_NAMES)}"
            )
            continue
        raw = _declared_bindings(data).get(role)
        agent_id = str(raw).strip() if isinstance(raw, str) else ""
        if not agent_id:
            errors.append(f"roles.{role} must name a non-empty agent id")
            continue
        if agent_id not in effective:
            listed = ", ".join(available) if available else "(none registered)"
            errors.append(
                f"roles.{role} names agent id {agent_id!r}, which is absent from `agents`; "
                f"available ids: {listed}"
            )
    return errors


def declared_role_agent_id(data: dict, role: str) -> str | None:
    """The agent the ADOPTER bound to `role`, ignoring the legacy inference.

    The gates use this to answer a different question from `role_agent_id`: not "who reviews
    this seam" but "did the adopter actually nominate anyone". Once an adapter declares a
    `roles` block it is a declaration, and a gap in it means unbound -- letting the shim refill
    that gap would let any registered, vendor-different agent bind evidence it was never
    nominated for, which is read-compat becoming a bypass.
    """
    value = _declared_bindings(data).get(role)
    return str(value).strip() if isinstance(value, str) and value.strip() else None
