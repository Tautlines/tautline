"""The provider registry: an adapter's DECLARED intent, separated from an implementation's
ACTUAL capability.

Backlog finding 89b names the trap this module exists to close: the single-value provider enums
declare intent *and* gate capability at once, so widening an enum would yield an adapter that names
a provider while every call underneath still goes to the old one. The registry owns membership; the
per-verb capability probe owns availability. They are different questions and they get different
answers.
"""

import ast
import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def providers():
    return importlib.import_module("tautline_methodology.providers")


# --- the category contract -------------------------------------------------------------------


def test_every_registered_provider_implements_its_category_contract(providers):
    """Registration is the point at which a contract is checked. A provider that type-checks but
    cannot serve a verb is a runtime outage on someone's release announcement."""
    for (category, provider_id), impl in providers.registered_providers().items():
        for verb in providers.PROVIDER_CATEGORIES[category]:
            assert callable(getattr(impl, verb, None)), (
                f"{provider_id!r} registered for {category!r} without a callable {verb!r}"
            )


def test_an_implementation_missing_a_verb_fails_registration(providers):
    class Truncated:
        provider_id = "truncated"
        category = "notify"
        # no `post`

    with pytest.raises(providers.ProviderContractError) as excinfo:
        providers.register_provider(Truncated())
    message = str(excinfo.value)
    assert "truncated" in message and "post" in message


def test_registration_rejects_an_unknown_category(providers):
    class Stray:
        provider_id = "stray"
        category = "telepathy"

    with pytest.raises(providers.ProviderContractError) as excinfo:
        providers.register_provider(Stray())
    assert "telepathy" in str(excinfo.value)


def test_provider_categories_constant_is_not_collected_into_the_policy_phrase_ssot(providers):
    """An UPPER_CASE list-of-str constant is auto-collected into the policy-phrase SSOT and breaks
    tests/test_policy_phrases_ssot.py. Tuples are excluded, so the contract uses tuples."""
    for category, verbs in providers.PROVIDER_CATEGORIES.items():
        assert isinstance(verbs, tuple), f"{category} verbs must be a tuple, not {type(verbs)}"


def test_every_category_declares_an_api_version(providers):
    assert set(providers.PROVIDER_API_VERSIONS) == set(providers.PROVIDER_CATEGORIES)
    for version in providers.PROVIDER_API_VERSIONS.values():
        assert isinstance(version, str) and version


# --- membership: the intent half ---------------------------------------------------------------


def test_unregistered_provider_id_message_names_category_value_and_valid_ids(providers):
    message = providers.provider_validation_error("notify", "carrier-pigeon")
    assert "carrier-pigeon" in message
    assert "notify" in message
    for known in providers.registered_provider_ids("notify"):
        assert known in message


def test_a_registered_provider_id_produces_no_validation_error(providers):
    for provider_id in providers.registered_provider_ids("notify"):
        assert providers.provider_validation_error("notify", provider_id) == ""


def test_resolve_provider_returns_none_for_an_unregistered_id(providers):
    assert providers.resolve_provider("notify", "carrier-pigeon") is None


def test_unknown_category_validation_error_names_the_category(providers):
    message = providers.provider_validation_error("telepathy", "anything")
    assert "telepathy" in message


# --- capability: the availability half ---------------------------------------------------------


def test_declared_provider_with_an_unavailable_verb_refuses_by_name(providers):
    """Amendment A2. A provider may be legitimately NAMED while a verb is unavailable -- that is
    the state a partially-implemented provider is honestly in. It must refuse specifically, never
    no-op and never raise a generic error."""

    class PartiallyBuilt(providers.Provider):
        provider_id = "partially-built"
        category = "notify"
        unavailable_verbs = frozenset({"post"})

        def post(self, payload=None, *, target="", label="", dry_run=False, failure_label=""):
            raise AssertionError("an unavailable verb must refuse before it is invoked")

    impl = PartiallyBuilt()
    assert impl.supports("post") is False
    with pytest.raises(providers.ProviderCapabilityError) as excinfo:
        impl.require("post")
    assert "partially-built" in str(excinfo.value)
    assert "post" in str(excinfo.value)


def test_capability_error_names_provider_verb_and_remedy(providers):
    class PartiallyBuilt(providers.Provider):
        provider_id = "partially-built"
        category = "notify"
        unavailable_verbs = frozenset({"post"})

        def post(self, payload=None, *, target="", label="", dry_run=False, failure_label=""):
            raise AssertionError  # pragma: no cover

    class FullyBuilt(providers.Provider):
        provider_id = "fully-built"
        category = "notify"

        def post(self, payload=None, *, target="", label="", dry_run=False, failure_label=""):
            return {"delivered": True}

    providers.register_provider(FullyBuilt())
    message = PartiallyBuilt().capability_error("post")
    assert "partially-built" in message
    assert "post" in message
    # A remedy, not just a complaint: the adopter is told what to do instead. The remedy must be a
    # provider that actually SERVES the verb, which is why this registers one: after the 2026-08-28
    # demolition removed the Google Chat transport, no shipped notify provider delivers `post`, and
    # the message correctly says so rather than naming a provider that cannot help either.
    assert "fully-built" in message


def test_supports_is_false_for_a_verb_outside_the_category_contract(providers):
    impl = providers.resolve_provider("notify", "none")
    assert impl.supports("transmogrify") is False


def test_the_null_provider_is_unavailable_without_that_being_an_error(providers):
    """The one implementation allowed to answer 'no' to everything. `enabled: true` resolving to
    null is caught at load; that is a different check and it lives in the adapter validator."""
    null = providers.resolve_provider("notify", "none")
    assert null.is_null is True
    assert null.supports("post") is False


def test_a_fully_capable_provider_supports_its_contract_verbs(providers):
    """A provider that declares no unavailable verb serves every verb in its category contract.

    Registered here rather than reaching for a shipped provider: the 2026-08-28 demolition deleted
    every transport, so every SHIPPED provider is now legitimately verb-unavailable. The property
    under test belongs to the contract, not to any one implementation."""

    class FullyCapable(providers.Provider):
        provider_id = "fully-capable"
        category = "notify"

        def post(self, payload=None, *, target="", label="", dry_run=False, failure_label=""):
            return {"delivered": True}

    impl = FullyCapable()
    assert impl.is_null is False
    for verb in providers.PROVIDER_CATEGORIES["notify"]:
        assert impl.supports(verb) is True
        impl.require(verb)  # does not raise


# --- purity: the registry names verbs, implementations own transports ---------------------------


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_registry_core_imports_neither_cli_nor_ghutil():
    """Amendment A1. `cli` keeps the module unit-testable. `ghutil` matters for a different and
    sharper reason: R2 registers a backlog category whose GitHub implementation legitimately needs
    it, and if the registry CORE reaches for it, every future provider inherits GitHub's cache,
    lock and rate-budget machinery as ambient truth -- which is exactly what makes a second
    provider a special case instead of a peer."""
    imports = _module_imports(REPO_ROOT / "src" / "tautline_methodology" / "providers.py")
    for banned in ("cli", "ghutil"):
        offenders = {name for name in imports if name.split(".")[-1] == banned}
        assert not offenders, f"providers.py must not import {banned}: {offenders}"


def test_resolve_provider_is_pure_and_imports_no_cli(providers):
    """Importable and usable with no CLI module loaded and no adapter on disk."""
    assert providers.resolve_provider("notify", "google-chat-webhook") is not None
    assert providers.resolve_provider("notify", "none") is not None
