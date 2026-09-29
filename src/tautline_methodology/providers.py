"""Provider registry: declared intent, separated from actual capability.

Backlog finding `89b` names the trap this module closes. Every integration seam in the adapter
contract is a single-value ``enum``, and that enum does **two jobs at once**: it declares which
system the adopter intends to use, and it stands in as a capability check for whether the framework
can drive that system. Widening the enum alone would produce an adapter that says ``jira`` while
every read and write underneath still shells out to ``gh``. Separating the two jobs is the work:

* **Membership** -- "is this a provider the framework knows?" -- is owned by the registry, so
  adding one is a registration, not a schema edit and not a fork.
* **Availability** -- "can this provider serve this verb *today*?" -- is owned by a per-verb
  capability probe, so a partially-implemented provider is a first-class, honest state rather than
  a half-built one. It refuses **by name**; it never silently no-ops.

Two import rules, and the second is the load-bearing one:

* No ``cli`` import, so the module is unit-testable in isolation and only thin wiring touches the
  monolith.
* **No ``ghutil`` import.** A later release registers a ``backlog`` category whose GitHub
  implementation legitimately needs ``ghutil``'s cache, lock and rate-budget machinery. If the
  registry *core* reached for it, every future provider would inherit GitHub's transport as ambient
  truth -- which is precisely what makes a second provider a special case instead of a peer. The
  registry names verbs; implementations own their transports.
"""

from __future__ import annotations

import inspect

# Declared as tuples, deliberately. An UPPER_CASE list-of-str constant is auto-collected into the
# policy-phrase SSOT and would break tests/test_policy_phrases_ssot.py; a tuple is excluded.
PROVIDER_CATEGORIES: dict[str, tuple[str, ...]] = {
    "notify": ("post",),
    # The backlog board: reading what work exists and moving it. Every verb name is
    # provider-NEUTRAL. `board_identity` rather than `project_view`, `set_status` rather than
    # `item_edit_single_select` -- the moment one provider's vocabulary enters the contract, every
    # other provider inherits it, which is the trap `89b` names.
    "backlog": (
        "list_items",
        "list_fields",
        "board_identity",
        "board_order",
        "set_status",
        "export_item",
    ),
    # The issue/work-item body a board item points at: acceptance criteria in, evidence out.
    # A separate category because an adopter may legitimately run a Jira board over GitHub issues,
    # so nothing may assume these two resolve to the same provider.
    "issues": ("item_body", "post_comment"),
}

# The exact parameters each contract verb is invoked with. Declaring a verb's NAME is not enough:
# a `callable(getattr(impl, verb))` check accepts any signature, so a third-party provider written
# against the documented API would register as supported and then raise `TypeError` on its first
# real publication -- the framework reporting a capability it does not have. Registration checks
# these names against the implementation's actual signature so the mismatch is caught at import.
#
# Every name here is provider-NEUTRAL. `target` is "wherever this provider sends things" (a webhook
# URL for chat, an API base elsewhere); it is deliberately not `webhook_url`, which would bake one
# provider's vocabulary into the contract every other provider has to implement.
PROVIDER_VERB_PARAMETERS: dict[str, dict[str, tuple[str, ...]]] = {
    "notify": {"post": ("payload", "target", "label", "dry_run", "failure_label")},
    "backlog": {
        "list_items": ("data", "target", "limit", "use_scope_query"),
        "list_fields": ("data", "target", "refresh"),
        "board_identity": ("data", "target"),
        "board_order": ("data", "target"),
        "set_status": ("data", "target", "item_ref", "status"),
        "export_item": ("data", "target", "item_id", "field_name", "value"),
    },
    "issues": {
        "item_body": ("data", "target", "item"),
        "post_comment": ("data", "target", "item", "body", "context"),
    },
}

# Per-category contract version. The registry is the SSOT for which providers satisfy which
# version, which closes the gap where the adapter contract is unversioned and every release can
# silently break callers.
# The adapter fields each backlog provider needs to identify its board, and which of them are
# REQUIRED when the block is enabled. Before this existed the model was GitHub's -- `owner` plus a
# positive `projectNumber`, required unconditionally -- so a Jira adapter could not load without
# fake GitHub coordinates, and relaxing the two checks would not have helped because another
# provider's own keys were not in the schema at all.
#
# `secretEnvFields` name ENVIRONMENT VARIABLES, never values. The framework governs secrets by name
# everywhere else (`webhookEnv`) and this follows that rule exactly: nothing here may hold a token.
#: Re-exported from the client so the validator can bound a board id without importing transport
#: code. The bound exists because Python refuses int() above 4300 digits.
MAX_BOARD_ID_DIGITS = 19

PROVIDER_IDENTITY_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "github-projects": {
        "required": ("owner", "projectNumber"),
        "optional": (),
        "secretEnvFields": (),
    },
    "jira": {
        "required": ("siteUrl", "projectKey"),
        "optional": ("boardId",),
        "secretEnvFields": ("emailEnv", "apiTokenEnv"),
    },
}


def all_secret_env_fields() -> tuple[str, ...]:
    """Every adapter field ANY provider declares as an environment-variable reference.

    The format check iterates this rather than the SELECTED provider's fields, because the schema
    permits every identity key globally and normalization preserves them: a block still set to
    `github-projects` while Jira fields are being staged would otherwise carry an unchecked
    `apiTokenEnv` straight into the committed generated adapter. Selection decides what is
    REQUIRED; it must not decide what is INSPECTED.
    """
    return tuple(
        sorted(
            {
                field
                for contract in PROVIDER_IDENTITY_FIELDS.values()
                for field in contract["secretEnvFields"]
            }
        )
    )


def provider_identity_fields(provider_id: str) -> dict[str, tuple[str, ...]]:
    """The identity contract for one backlog provider, empty when it declares none."""
    return PROVIDER_IDENTITY_FIELDS.get(
        provider_id, {"required": (), "optional": (), "secretEnvFields": ()}
    )


PROVIDER_API_VERSIONS: dict[str, str] = {
    "notify": "1",
    "backlog": "1",
    "issues": "1",
}


class ProviderContractError(Exception):
    """A provider was registered that does not satisfy its category contract.

    Raised at REGISTRATION, not at first call. A provider that type-checks but cannot serve a verb
    is a runtime outage on somebody's release announcement, and the honest time to find out is
    import time.
    """


class ProviderCapabilityError(Exception):
    """A declared provider was asked for a verb it does not currently serve.

    Distinct from :class:`ProviderContractError`: nothing is misconfigured and nothing is missing
    from the contract. The adapter legitimately names this provider, and this particular verb is
    not available from it yet. The message says so, by name, and names what to do instead.
    """


class Provider:
    """Base for every provider implementation.

    Subclasses set ``provider_id``, ``category``, and -- when they cannot yet serve part of their
    contract -- ``unavailable_verbs``. They must still *define* every contract verb; declaring one
    unavailable changes what happens when it is called, not whether it exists.
    """

    provider_id: str = ""
    category: str = ""
    #: Contract verbs this implementation declares it cannot currently serve.
    unavailable_verbs: frozenset[str] = frozenset()
    #: True only for the no-op provider, which answers "no" to everything without that being an
    #: error. An `enabled: true` block resolving to a null provider is a misconfiguration, but that
    #: is the adapter validator's check, not this one's.
    is_null: bool = False

    def contract_verbs(self) -> tuple[str, ...]:
        return PROVIDER_CATEGORIES.get(self.category, ())

    def supports(self, verb: str) -> bool:
        """True when ``verb`` is in this provider's category contract and is available from it."""
        if verb not in self.contract_verbs():
            return False
        return verb not in self.unavailable_verbs

    def capability_error(self, verb: str) -> str:
        """A specific message: which provider, which verb, and what the adopter can do instead."""
        if verb not in self.contract_verbs():
            known = ", ".join(self.contract_verbs()) or "none"
            return (
                f"{verb!r} is not a verb of the {self.category!r} provider contract "
                f"(contract verbs: {known})"
            )
        alternatives = [
            other
            for other in providers_serving(self.category, verb)
            if other != self.provider_id
        ]
        remedy = (
            f"declare a {self.category} provider that serves it ({', '.join(alternatives)})"
            if alternatives
            else f"no other registered {self.category} provider serves it either"
        )
        return (
            f"provider {self.provider_id!r} does not currently serve the {self.category!r} verb "
            f"{verb!r}; {remedy}"
        )

    def capability_exception(self, verb: str) -> "ProviderCapabilityError":
        """The refusal as an exception, for an implementation that wants to raise it directly."""
        return ProviderCapabilityError(self.capability_error(verb))

    def require(self, verb: str) -> None:
        """Raise unless ``verb`` is available. The one call site every verb wrapper goes through,
        so an unavailable verb can never reach an implementation body and quietly do nothing."""
        if not self.supports(verb):
            raise ProviderCapabilityError(self.capability_error(verb))


def _signature_mismatch(verb: object, expected: tuple[str, ...]) -> str:
    """``""`` when the contract's exact invocation can bind to ``verb``; otherwise why it cannot.

    Checking that the expected NAMES appear is not enough, and the gap is not academic: a `post`
    that accepts every expected name and also requires a `token` binds by name, registers as
    supported, and raises `TypeError` on the first real call -- the same "declared a capability it
    does not have" failure the name check was added to close, one level down. So this asks the
    question the caller actually asks: can this be CALLED the way the contract calls it? It binds a
    trial invocation, which catches missing names and unsatisfiable extra requirements in one step.

    A ``**kwargs`` catch-all binds anything, which is the escape hatch a wrapper or decorator needs.
    """
    try:
        signature = inspect.signature(verb)
    except (TypeError, ValueError):  # pragma: no cover - builtins/C callables
        return ""
    first, *rest = expected
    try:
        signature.bind(_CONTRACT_PROBE, **{name: _CONTRACT_PROBE for name in rest})
    except TypeError as exc:
        return f"cannot be called as {verb.__name__ if hasattr(verb, '__name__') else 'verb'}" \
               f"({', '.join(expected)}): {exc}"
    return ""


#: Sentinel bound into the trial invocation. Never passed to a real implementation -- `bind` only
#: matches arguments to parameters and never calls anything.
_CONTRACT_PROBE = object()


_REGISTRY: dict[tuple[str, str], Provider] = {}


def register_provider(implementation: Provider) -> Provider:
    """Register ``implementation``, checking its category contract first.

    Returns the implementation so a module can register at definition site.
    """
    category = getattr(implementation, "category", "")
    provider_id = getattr(implementation, "provider_id", "")
    if category not in PROVIDER_CATEGORIES:
        known = ", ".join(sorted(PROVIDER_CATEGORIES)) or "none"
        raise ProviderContractError(
            f"provider {provider_id!r} declares unknown category {category!r}; "
            f"known categories: {known}"
        )
    if not provider_id:
        raise ProviderContractError(f"a {category!r} provider was registered without a provider_id")
    if provider_id != provider_id.strip():
        # `resolve_provider` strips the adapter's value before lookup, so a padded id would
        # register successfully and then be unreachable forever -- a provider that exists and
        # cannot be named. Refuse rather than normalise: registration is programmer-facing, and a
        # silent fixup hides the mismatch from the only person who can correct it.
        raise ProviderContractError(
            f"provider id {provider_id!r} for category {category!r} has leading or trailing "
            "whitespace; ids are looked up stripped, so this one could never be resolved"
        )
    missing = [
        verb
        for verb in PROVIDER_CATEGORIES[category]
        if not callable(getattr(implementation, verb, None))
    ]
    if missing:
        raise ProviderContractError(
            f"provider {provider_id!r} does not satisfy the {category!r} contract; "
            f"missing verb(s): {', '.join(missing)}"
        )
    for verb, expected in PROVIDER_VERB_PARAMETERS.get(category, {}).items():
        mismatch = _signature_mismatch(getattr(implementation, verb), expected)
        if mismatch:
            raise ProviderContractError(
                f"provider {provider_id!r} declares {category!r} verb {verb!r} with a signature "
                f"the contract cannot call: {mismatch}. A callable with the wrong signature "
                "registers as supported and then fails at the first real call."
            )
    _REGISTRY[(category, provider_id)] = implementation
    return implementation


def registered_providers() -> dict[tuple[str, str], Provider]:
    """Every registered implementation, keyed ``(category, provider_id)``."""
    return dict(_REGISTRY)


def registered_provider_ids(category: str) -> list[str]:
    """Sorted provider ids registered for ``category``."""
    return sorted(pid for (cat, pid) in _REGISTRY if cat == category)


def providers_serving(category: str, verb: str) -> list[str]:
    """Sorted ids of providers registered for ``category`` that actually serve ``verb``.

    Every remedy message is built from this, never from the bare registration list. A remedy that
    named the full list would offer the null provider as the fix for "nothing was delivered" --
    recommending the exact non-delivering choice it had just refused. A suggestion the user cannot
    act on is worse than no suggestion, because it reads as guidance.
    """
    return sorted(
        provider_id
        for (cat, provider_id), impl in _REGISTRY.items()
        if cat == category and impl.supports(verb)
    )


def resolve_provider(category: str, provider_id: str) -> Provider | None:
    """The registered implementation, or ``None`` when the id is not registered."""
    return _REGISTRY.get((category, (provider_id or "").strip()))


def provider_validation_error(category: str, provider_id: str, label: str = "") -> str:
    """``""`` when ``provider_id`` is registered for ``category``; otherwise a specific message.

    The message names the category, the offending value and the registered ids -- no less specific
    than the hand-rolled ``must be <the one value>`` refusals it replaces, while the mechanism
    underneath is open.
    """
    if category not in PROVIDER_CATEGORIES:
        known = ", ".join(sorted(PROVIDER_CATEGORIES)) or "none"
        return f"unknown provider category {category!r}; known categories: {known}"
    if resolve_provider(category, provider_id) is not None:
        return ""
    known_ids = ", ".join(registered_provider_ids(category)) or "none"
    where = f"{label}.provider " if label else ""
    return (
        f"{where}{provider_id!r} is not a registered {category} provider. "
        f"Known: {known_ids}."
    )


# Built-in providers register on import of this module, so `resolve_provider` is usable without a
# caller having to know which module defines what.
from tautline_methodology import providers_notify as _providers_notify  # noqa: E402,F401
from tautline_methodology import providers_github as _providers_github  # noqa: E402,F401
from tautline_methodology import providers_jira as _providers_jira  # noqa: E402,F401
