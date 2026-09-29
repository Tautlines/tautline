"""The `notify` category end to end: Google Chat unchanged, and "I have no chat tool" expressible.

Two properties carry this release. First, **nothing moves for an existing adopter** -- the payload
and the sent-state semantics are identical, and that is proven rather than asserted. Second,
silence-on-purpose and silence-by-accident stay distinguishable: a null provider that quietly
swallows a configured delivery would be the "control that reports success while doing nothing"
defect this repository keeps paying for.
"""

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def providers():
    return importlib.import_module("tautline_methodology.providers")


@pytest.fixture
def provider_sandbox(providers):
    """Register test doubles without leaking them into the next test.

    A double left in the registry changes what `providers_serving` returns module-wide, which is
    precisely the state `test_this_release_registers_exactly_one_delivering_notify_provider` exists
    to detect -- so a leak turns a real safety assertion into a flake.
    """
    saved = providers.registered_providers()
    yield providers
    providers._REGISTRY.clear()
    providers._REGISTRY.update(saved)


def _notify_block(**overrides):
    block = {
        "enabled": False,
        "provider": "google-chat-webhook",
        "webhookEnv": "",
        "chatSpace": "X",
    }
    block.update(overrides)
    return block


# --- Google Chat: byte-for-byte the same call ---------------------------------------------------


# --- the null provider ---------------------------------------------------------------------------


def test_null_notify_provider_performs_no_io_and_does_not_raise(providers, monkeypatch):
    import urllib.request

    def explode(*args, **kwargs):  # pragma: no cover - reached only on a defect
        raise AssertionError("the null provider must perform no network I/O")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    result = providers.resolve_provider("notify", "none").post({}, label="milestone_update")
    assert result["delivered"] is False
    assert "no notify provider configured" in result["reason"]


def test_null_notify_provider_reports_rather_than_silently_succeeding(providers):
    """`delivered: False` with a reason, never an empty success. A caller that logs the result can
    tell a reader that nothing was sent; an empty success cannot."""
    result = providers.resolve_provider("notify", "none").post({}, label="product_note")
    assert set(result) >= {"delivered", "provider", "reason"}
    assert result["provider"] == "none"


# --- the load-time boundary between the two silences ---------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["milestoneUpdate", "productChat", "deploymentNotification"],
)
def test_enabled_notify_with_none_provider_refuses_at_load(cli, tmp_path, key):
    block = _notify_block(enabled=True, provider="none", webhookEnv="X_HOOK")
    adapter = _adapter(tmp_path, {key: block})
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    message = str(excinfo.value)
    assert key in message and "none" in message


@pytest.mark.parametrize(
    "key",
    ["milestoneUpdate", "productChat", "deploymentNotification"],
)
def test_disabled_notify_with_none_provider_loads_and_runs(cli, tmp_path, key):
    adapter = _adapter(tmp_path, {key: _notify_block(enabled=False, provider="none")})
    data = cli.load_project(adapter)
    assert data[key]["provider"] == "none"


def test_an_unregistered_notify_provider_is_refused_with_the_registered_ids_named(cli, tmp_path):
    adapter = _adapter(tmp_path, {"productChat": _notify_block(provider="carrier-pigeon")})
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    message = str(excinfo.value)
    assert "carrier-pigeon" in message
    assert "google-chat-webhook" in message and "none" in message


def test_sent_state_dir_semantics_are_unchanged_under_both_providers(cli, tmp_path):
    """`sentStateDir` and the trigger are delivery bookkeeping, not provider concerns; they must
    not have moved behind the seam."""
    for provider in ("google-chat-webhook", "none"):
        adapter = _adapter(
            tmp_path / provider,
            {"milestoneUpdate": _notify_block(provider=provider, sentStateDir=".ai-work/mu")},
        )
        data = cli.load_project(adapter)
        assert data["milestoneUpdate"]["sentStateDir"] == ".ai-work/mu"
        assert data["milestoneUpdate"]["trigger"] == "milestone-complete"


# --- fixture plumbing -----------------------------------------------------------------------------


def _adapter(root, overrides):
    """A minimal valid project adapter with `overrides` merged over the example adapter."""
    repo_root = Path(__file__).resolve().parents[1]
    base = json.loads((repo_root / "adapters" / "projects" / "example-saas.json").read_text())
    for key, value in overrides.items():
        merged = dict(base.get(key) or {})
        merged.update(value)
        base[key] = merged
    root.mkdir(parents=True, exist_ok=True)
    path = root / "adapter.json"
    path.write_text(json.dumps(base))
    return path


# --- Codex R1 findings: each fix gets the test that would have caught it -------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"productChat": {"provider": "carrier-pigeon"}}, "carrier-pigeon"),
        ({"productChat": {"enabled": True, "provider": "none", "webhookEnv": "X_HOOK"}}, "none"),
    ],
)
def test_validate_adapter_refuses_what_load_project_refuses(run_cli, tmp_path, overrides, expected):
    """R1 P1. Opening the four enums moved membership out of JSON Schema and into the registry, so
    schema validation alone stopped being able to see a bad provider. `validate-adapter` is the
    self-service lint an adopter and CI run; without the registry check wired in it printed
    "matches the adapter schema" for an adapter the very next command refuses. A lint that
    green-lights an unusable config is worse than no lint."""
    adapter = _adapter(tmp_path, overrides)
    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 1, result.stdout
    assert expected in result.stderr


def test_validate_adapter_still_accepts_the_reference_adapter(run_cli):
    repo_root = Path(__file__).resolve().parents[1]
    example = repo_root / "adapters" / "projects" / "example-saas.json"
    result = run_cli("validate-adapter", "--project", str(example))
    assert result.returncode == 0, result.stderr


def test_validate_adapter_accepts_a_notify_block_with_no_provider_key(run_cli, tmp_path):
    """`validate-adapter` reads the file directly, with no defaults projected, so an unset provider
    must not be reported as invalid -- every notify block defaults to a real one."""
    adapter = _adapter(tmp_path, {})
    data = json.loads(adapter.read_text())
    data["productChat"].pop("provider", None)
    adapter.write_text(json.dumps(data))
    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 0, result.stderr


# --- Codex R2 findings: normalisation parity between the two validators -------------------------


def test_a_blank_provider_is_refused_by_the_lint_as_well_as_the_load_path(run_cli, tmp_path):
    """R2 P1. `load_project` normalises BEFORE it validates, so `"   "` reaches the schema as `""`
    and is refused for `minLength`. `validate-adapter` reads the file raw, where `"   "` satisfies
    `minLength: 1`. Reading a blank value as "unset" here would let the lint pass the exact adapter
    the next command refuses -- the divergence this collector exists to close, one layer down."""
    adapter = _adapter(tmp_path, {"productChat": {"enabled": False, "provider": "   "}})
    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 1, result.stdout
    assert "present but blank" in result.stderr


def test_a_blank_provider_is_still_refused_on_the_load_path(cli, tmp_path):
    adapter = _adapter(tmp_path, {"productChat": {"enabled": False, "provider": "   "}})
    with pytest.raises(SystemExit):
        cli.load_project(adapter)


def test_an_absent_provider_key_stays_valid_on_both_paths(cli, run_cli, tmp_path):
    """The other half of the same distinction: absent is a default, not a mistake."""
    adapter = _adapter(tmp_path, {})
    data = json.loads(adapter.read_text())
    data["productChat"].pop("provider", None)
    adapter.write_text(json.dumps(data))
    assert run_cli("validate-adapter", "--project", str(adapter)).returncode == 0
    assert cli.load_project(adapter)["productChat"]["provider"] == "google-chat-webhook"


def test_a_padded_provider_id_is_refused_at_registration(provider_sandbox):
    """R2 P2. Every lookup strips the adapter's value, so a padded id would register successfully
    and then be unreachable forever -- a provider that exists and cannot be named."""

    class Padded(provider_sandbox.Provider):
        provider_id = " padded-id "
        category = "notify"

        def post(self, payload=None, *, target="", label="", dry_run=False, failure_label=""):
            return {}  # pragma: no cover

    with pytest.raises(provider_sandbox.ProviderContractError) as excinfo:
        provider_sandbox.register_provider(Padded())
    assert "whitespace" in str(excinfo.value)


def test_every_registered_provider_id_is_already_canonical(providers):
    for (_, provider_id) in providers.registered_providers():
        assert provider_id == provider_id.strip()


# --- Codex R3/R4 findings: the seam's own contract ------------------------------------------------


def test_a_provider_with_the_wrong_post_signature_is_refused_at_registration(provider_sandbox):
    """R3 P1. `callable(getattr(impl, verb))` accepts ANY signature, so a provider written against
    the documented API registered as supported and then raised `TypeError` on its first real
    publication -- the framework reporting a capability it does not have. The signature is now part
    of the contract and checked at import."""

    class WrongShape(provider_sandbox.Provider):
        provider_id = "wrong-shape"
        category = "notify"

        def post(self, payload, target=None):  # missing label/dry_run/failure_label
            return {}  # pragma: no cover

    with pytest.raises(provider_sandbox.ProviderContractError) as excinfo:
        provider_sandbox.register_provider(WrongShape())
    message = str(excinfo.value)
    assert "wrong-shape" in message
    for missing in ("label", "dry_run", "failure_label"):
        assert missing in message


def test_a_provider_accepting_kwargs_satisfies_the_signature_contract(provider_sandbox):
    """The escape hatch a wrapper or decorator needs; a catch-all genuinely can be called."""

    class Wrapped(provider_sandbox.Provider):
        provider_id = "kwargs-wrapped"
        category = "notify"

        def post(self, payload=None, **kwargs):
            return {"delivered": False, "provider": self.provider_id}

    provider_sandbox.register_provider(Wrapped())
    assert provider_sandbox.resolve_provider("notify", "kwargs-wrapped") is not None


def test_every_shipped_provider_can_be_called_the_way_the_contract_calls_it(providers):
    for (category, provider_id), impl in providers.registered_providers().items():
        for verb, expected in providers.PROVIDER_VERB_PARAMETERS.get(category, {}).items():
            mismatch = providers._signature_mismatch(getattr(impl, verb), expected)
            assert not mismatch, f"{provider_id}.{verb}: {mismatch}"


def test_the_null_provider_is_honoured_without_the_deferred_routing_checks(cli, tmp_path):
    """Why the deferral costs nothing here. `none` is only legal while the block is disabled,
    and a disabled block never publishes -- so the null provider is fully honoured by the enabled
    check alone. Nothing here can name a delivering provider the router could mis-send."""
    for key in ("milestoneUpdate", "productChat", "deploymentNotification"):
        adapter = _adapter(tmp_path / key, {key: _notify_block(enabled=False, provider="none")})
        loaded = cli.load_project(adapter)
        assert loaded[key]["provider"] == "none"
        assert loaded[key]["enabled"] is False


def test_a_post_requiring_an_extra_argument_is_refused_at_registration(provider_sandbox):
    """R4 P2. A `post` that accepts every expected NAME and also requires an unsupplied `token`
    binds by name, registers as supported, and raises `TypeError` on the first real call -- the
    same "declared a capability it does not have" failure the name check closed, one level down.
    The check now binds the contract's exact invocation instead of matching names."""

    class NeedsToken(provider_sandbox.Provider):
        provider_id = "needs-token"
        category = "notify"

        def post(
            self, payload=None, *, target="", label="", dry_run=False, failure_label="", token
        ):
            return {}  # pragma: no cover

    with pytest.raises(provider_sandbox.ProviderContractError) as excinfo:
        provider_sandbox.register_provider(NeedsToken())
    assert "needs-token" in str(excinfo.value)


def test_a_post_with_extra_optional_arguments_still_registers(provider_sandbox):
    """Optional extras are the provider's business; only unsatisfiable requirements refuse."""

    class ExtraOptional(provider_sandbox.Provider):
        provider_id = "extra-optional"
        category = "notify"

        def post(
            self, payload=None, *, target="", label="", dry_run=False, failure_label="", retries=3
        ):
            return {"delivered": False, "provider": self.provider_id}

    provider_sandbox.register_provider(ExtraOptional())
    assert provider_sandbox.resolve_provider("notify", "extra-optional") is not None
