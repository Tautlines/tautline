"""Legacy vendor-named adapter keys -> `agents`/`roles`.

THIS MODULE IS THE SINGLE SANCTIONED SITE OF VENDOR KNOWLEDGE IN FRAMEWORK CODE, and it is
DELETED at the removal release named in REMOVAL_RELEASE.

Synthesising `vendor: "openai"` from a key named `codexWrapper` is exactly the coupling the
agent-agnostic program removes. It is accepted here for one reason: preserving the behavior of
adapters written before the registry existed requires inference, and D3 chose additive keys
with deprecation over a hard cut that would break product adapters on machines whose pinned CLI
is a known recurring failure mode. It is contained by three constraints:

  1. it lives in this one module;
  2. tests/test_no_vendor_literals.py asserts this is the ONLY site in the codebase that maps a
     vendor name to a vendor value;
  3. it is deleted at REMOVAL_RELEASE.

Two rules govern every inference here:

  EXPLICIT WINS. If the adapter declares `agents` or a `roles.<seam>` itself, the shim fills the
  remaining gaps and never contradicts what was declared. The gap is per FIELD, not per agent:
  the realistic additive-migration state is an adapter that has begun declaring `agents.codex`
  while still carrying `review.codexWrapper`, and skipping the whole agent there would leave a
  registered reviewer with no wrapper at all.

  NO GUESSED DEFAULT. An adapter whose legacy keys are too sparse to infer a seam author gets
  NO inferred binding. It is the gate's job to refuse with a remedy ("declare `roles.builder`"),
  not this module's job to invent an author. A fail-open here would be a new instance of the
  dominant local defect class: a control that reads healthy because something upstream never let
  it run.
"""
from __future__ import annotations

import copy

from . import agents as agents_mod

REMOVAL_RELEASE = "1.0.0"


class ProjectedAdapter(dict):
    """An adapter dict that also remembers what it declared, and what was inferred, before
    projection.

    A dict subclass rather than an extra key, because the adapter schema is top-level
    `additionalProperties: false`: any key this module added would make every adapter fail
    validation. As a subclass it serialises, validates and reads exactly like the plain dict it
    replaces, and the framework state rides beside the payload instead of inside it.
    """

    registry_opt_in: bool = False
    inferred_registry: dict | None = None
    inferred_roles: dict | None = None
    inference_notes: list | None = None


def merged_registry(data) -> dict:
    """The adapter's `agents`, with legacy-inferred entries filling per-FIELD gaps.

    Merged on read rather than written into the mapping -- see `effective_agents`.
    """
    declared = _mapping(_mapping(data).get("agents"))
    # SYNTHESISE WHEN THE PROJECTION IS ABSENT, rather than silently returning declared-only.
    # `inferred_registry` exists only on a ProjectedAdapter, i.e. on data that came through
    # `load_project`. Every other caller -- and there are several, including gates invoked with
    # a plain dict -- would otherwise lose legacy read-compat WITHOUT SAYING SO: a legacy
    # adapter's reviewer would resolve to nothing and the gate would refuse it for having no
    # bound reviewer, which reads as a configuration error rather than a missing projection.
    # Falling back keeps one behaviour for one input regardless of how it was loaded.
    inferred = _mapping(getattr(data, "inferred_registry", None))
    if not inferred:
        inferred = _mapping(synthesise_agents(data)[0])
    if not inferred:
        return declared
    merged = {agent_id: dict(record) for agent_id, record in inferred.items()}
    for agent_id, record in declared.items():
        merged.setdefault(agent_id, {})
        if isinstance(record, dict):
            merged[agent_id].update(record)
        else:
            merged[agent_id] = record
    return merged


def merged_bindings(data) -> dict:
    """The adapter's `roles`, with legacy-inferred bindings filling gaps. Merged on read."""
    declared = _mapping(_mapping(data).get("roles"))
    inferred = _mapping(getattr(data, "inferred_roles", None))
    if not inferred:
        # Same fallback and the same reason as `merged_registry`.
        inferred = _mapping(synthesise_agents(data)[1])
    if not inferred:
        return declared
    merged = dict(inferred)
    if isinstance(declared, dict):
        merged.update(declared)
    return merged


# The vendor knowledge, in one named constant so it is greppable, reviewable, and deletable in a
# single edit at REMOVAL_RELEASE. Nothing else in the framework may map a vendor name to a value.
LEGACY_AGENT_SEEDS: dict[str, dict] = {
    "codex": {
        "vendor": "openai",
        "runtime": "codex",
        "instructionFile": "AGENTS.md",
        # Seeded so a legacy adapter's transcript-scan behaviour is bit-for-bit what it is today.
        "transcriptMarker": "codex",
    },
    "claude-code": {
        "vendor": "anthropic",
        "runtime": "claude-code",
        "instructionFile": "CLAUDE.md",
    },
}

# (legacy dotted key, agent id, target field on the agent record)
_AGENT_FIELD_MAP: tuple[tuple[str, str, str], ...] = (
    ("review.codexWrapper", "codex", "reviewWrapper"),
    ("review.codexPlanWrapper", "codex", "planReviewWrapper"),
    ("review.codexFastMode", "codex", "fastMode"),
    ("review.claudeReview", "claude-code", "reviewGuidance"),
    ("goalExecution.preferredClaudeCommand", "claude-code", "goalCommand"),
    ("goalExecution.claudeGoalGuidance", "claude-code", "goalGuidance"),
)

# (legacy dotted key, role, agent id) -- presence of the key infers the binding.
#
# `roles.planner` IS DELIBERATELY ABSENT. The design's migration table authorizes
# `review.claudeReview` to infer `roles.builder` and nothing else. `claudeReview` is
# schema-REQUIRED review guidance on every legacy adapter; it says who reviews, not who authored
# the plan. Inferring `planner` from it would make every legacy adapter claim Claude planned the
# work, so the plan-review vendor check would compare against a fabricated author and PASS
# instead of reporting an unresolvable planner. That is the fail-open the design says not to
# build: an adapter too sparse to infer a seam author gets the refusal, not a guess.
_ROLE_MAP: tuple[tuple[str, str, str], ...] = (
    ("review.codexWrapper", "implementationReviewer", "codex"),
    ("review.codexPlanWrapper", "planReviewer", "codex"),
    ("review.claudeReview", "builder", "claude-code"),
)

LEGACY_KEYS: tuple[str, ...] = tuple(dict.fromkeys(key for key, _, _ in _AGENT_FIELD_MAP))


def _mapping(value) -> dict:
    """`value` if it is a mapping, else an empty dict.

    THE SHIM TOLERATES MALFORMED SHAPES, deliberately, rather than each caller guarding.
    `validate-adapter` runs on adapters that are already invalid -- that is its whole job -- so
    it hands this module a top-level array, or `agents: "oops"`, and its contract is to REPORT
    the schema violations, not to traceback before printing them. Making the shim total is the
    fix; guarding at one call site would leave the next entry point to rediscover it, which this
    lane has already done three times with a related boundary.
    """
    return value if isinstance(value, dict) else {}


def _get(data, dotted: str):
    node = _mapping(data)
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def synthesise_agents(data: dict) -> tuple[dict, dict, list[str]]:
    """`(agents_block, roles_block, notes)` inferred from legacy keys.

    Only GAPS are filled: a FIELD already present on a declared agent, or a role already bound
    in `data["roles"]`, is left untouched and produces no note.
    """
    declared_agents = _mapping(_mapping(data).get("agents"))
    declared_roles = _mapping(_mapping(data).get("roles"))
    registry: dict[str, dict] = {}
    roles: dict[str, str] = {}
    notes: list[str] = []

    for dotted, agent_id, field in _AGENT_FIELD_MAP:
        value = _get(data, dotted)
        if value is None:
            continue
        # The gap is PER FIELD, not per agent (see the module docstring).
        declared = _mapping(declared_agents.get(agent_id))
        if field in declared:
            continue
        record = registry.setdefault(agent_id, dict(LEGACY_AGENT_SEEDS[agent_id]))
        record[field] = value
        notes.append(f"inferred agents.{agent_id}.{field} from legacy {dotted}")

    for dotted, role, agent_id in _ROLE_MAP:
        if _get(data, dotted) is None:
            continue
        if role in declared_roles:
            continue
        if agent_id not in registry and agent_id not in declared_agents:
            continue
        if role in roles:
            continue
        roles[role] = agent_id
        notes.append(f"inferred roles.{role} = {agent_id!r} from the presence of legacy {dotted}")

    return registry, roles, notes


def effective_agents(data: dict) -> ProjectedAdapter:
    """A COPY of `data` CARRYING the legacy inference -- without merging it into the mapping.

    THE INFERENCE IS NEVER WRITTEN INTO THE DICT, and that is the whole point. An earlier
    version merged it, and `render-adapters` promptly serialised a whole synthesised `agents`
    block into the repo's own generated `.tautline.json` -- breaking R1's inertness guarantee
    and, worse, turning a runtime convenience into adapter content an adopter never wrote. The
    generated adapter must be what the adopter wrote; anything a serialiser can reach will
    eventually be serialised.

    So the inference rides on the object as attributes, `agents.role_agent_id` and friends merge
    it on READ, and every consumer that walks the mapping -- renderers, `json.dumps`, the schema
    validator -- sees exactly the adapter that was loaded.

    Never mutates the input either: callers pass the adapter dict the whole CLI shares.
    """
    result = copy.deepcopy(_mapping(data))
    # Record what the adapter ACTUALLY declared, before anything is projected onto it. Every
    # gate downstream sees only the projected dict, so without this a pure-legacy adapter is
    # indistinguishable from a fully declared one and the non-regression boundary inverts.
    # Presence, not truthiness: a deliberate `"roles": {}` is an opt-in.
    #
    # NOT A KEY ON THE ADAPTER. The schema is top-level `additionalProperties: false`, so
    # writing this into the dict would make EVERY adapter fail validation the moment
    # `load_project()` validates the projected payload.
    declared = "agents" in result or "roles" in result
    registry, roles, notes = synthesise_agents(result)
    projected = ProjectedAdapter(result)
    projected.registry_opt_in = declared
    projected.inferred_registry = registry
    projected.inferred_roles = roles
    projected.inference_notes = notes
    return projected


def deprecation_warnings(data: dict) -> list[str]:
    """One warning per legacy key still present, each naming its replacement and the release
    that removes it."""
    warnings: list[str] = []
    for dotted, agent_id, field in _AGENT_FIELD_MAP:
        if _get(data, dotted) is None:
            continue
        warnings.append(
            f"adapter_key_deprecated: `{dotted}` is superseded by `agents.{agent_id}.{field}` "
            f"and is removed in {REMOVAL_RELEASE}; declare `agents` and `roles` explicitly"
        )
    return warnings


def inferred_summary_lines(data: dict) -> list[str]:
    """Operator-facing rendering of the guess, for `methodology-status`.

    The shim REPORTS what it inferred rather than applying it silently, so an operator can see
    the reconstruction and pin it explicitly.

    READS THE CARRIED RESULT, never recomputes on a projected dict -- see `effective_agents`.
    """
    carried = getattr(data, "inference_notes", None)
    if carried is not None:
        registry = getattr(data, "inferred_registry", None) or {}
        roles = getattr(data, "inferred_roles", None) or {}
        notes = carried
    else:
        registry, roles, notes = synthesise_agents(data)
    if not registry and not roles:
        return []
    lines = ["agents_roles_inferred: synthesised from legacy vendor-named keys --"]
    # PRINT THE EFFECTIVE VALUES, not the raw seeds. An adapter part-way through migration may
    # declare `agents.<id>` with its own vendor, runtime or instructionFile while still relying
    # on a legacy wrapper; explicit-wins means those declared values are what the framework
    # actually resolves. Printing the seed instead would show an operator something that is not
    # in force -- and the entire point of this output is that they can see the guess and pin it,
    # so pinning what it printed has to be a no-op.
    effective = merged_registry(data)
    declared_registry = _mapping(_mapping(data).get("agents"))
    for agent_id in sorted(registry):
        record = _mapping(effective.get(agent_id)) or registry[agent_id]
        declared_fields = set(_mapping(declared_registry.get(agent_id)))
        rendered = " ".join(
            f"{field}={record.get(field, '')}" + ("" if field in declared_fields else " (inferred)")
            for field in ("vendor", "runtime", "instructionFile")
        )
        lines.append(f"  agents.{agent_id}: {rendered}")
    for role in agents_mod.ROLE_NAMES:
        if role in roles:
            lines.append(f"  roles.{role} = {roles[role]}")
    lines.extend(f"  {note}" for note in notes)
    lines.append("  pin these explicitly in the adapter to stop relying on inference")
    return lines
