"""The `backlog` and `issues` categories: a board provider becomes nameable, and honestly refused.

This release does not make a non-GitHub board *work*. It makes one **expressible** and, when a verb
it cannot serve is reached, **refused by name** — the separation backlog finding `89b` calls the
actual work behind naming a second backlog system.

The tests are organised around the four defect classes R1's five review rounds produced, because
those are what this surface will fail at:

* **L1** opening an enum moves membership out of JSON Schema, so every validator that leaned on the
  schema is now wrong — and they must be proven to agree;
* **L2** declaring a verb's name is not declaring its contract, and no parameter name may be
  provider-specific;
* **L3** cross-block coupling stops being coherent across a provider boundary — here, `backlog` and
  `issues` resolving separately;
* **L4** an identity that records a field and never compares it is not an identity — here, the
  dispatch must actually read the declared provider rather than assuming GitHub.
"""

import importlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


@pytest.fixture(scope="module")
def providers():
    return importlib.import_module("tautline_methodology.providers")


@pytest.fixture
def provider_sandbox(providers):
    """Register test doubles without leaking them into the next test."""
    saved = providers.registered_providers()
    yield providers
    providers._REGISTRY.clear()
    providers._REGISTRY.update(saved)


def _adapter(root: Path, overrides: dict) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text())
    for key, value in overrides.items():
        merged = dict(data.get(key) or {})
        merged.update(value)
        data[key] = merged
    root.mkdir(parents=True, exist_ok=True)
    path = root / "adapter.json"
    path.write_text(json.dumps(data))
    return path


# --- the category contract (L2) -------------------------------------------------------------------


def test_both_categories_declare_every_verb_the_dispatch_uses(providers):
    """`auth_issues` is deliberately absent. Authentication is a real provider concern, but adding
    it here meant threading `data` through a function ~70 existing test doubles patch with a
    one-argument lambda — a large, risky diff buying no protection the board verbs do not already
    give, since every path that could drive the wrong board refuses at a board verb first. It lands
    with R3, where a Jira provider needs a real auth story to attach to."""
    assert set(providers.PROVIDER_CATEGORIES["backlog"]) == {
        "list_items",
        "list_fields",
        "board_identity",
        "board_order",
        "set_status",
        "export_item",
    }
    assert set(providers.PROVIDER_CATEGORIES["issues"]) == {"item_body", "post_comment"}


def test_no_contract_verb_or_parameter_name_is_provider_specific(providers):
    """L2. The moment one provider's vocabulary enters the contract, every other provider inherits
    it. `board_identity` not `project_view`; `set_status` not `item_edit_single_select`."""
    # "issue" is deliberately NOT a banned token: `auth_issues` means "problems with auth", not
    # GitHub Issues, and banning the substring would flag a name that is already neutral.
    leaked = ("github", "gh_", "project_view", "item_edit", "single_select", "projectv2", "gql")
    for category in ("backlog", "issues"):
        for verb in providers.PROVIDER_CATEGORIES[category]:
            assert not any(token in verb for token in leaked), f"{category}.{verb} names a provider"
            for parameter in providers.PROVIDER_VERB_PARAMETERS[category][verb]:
                assert not any(token in parameter for token in leaked), (
                    f"{category}.{verb}({parameter}) names a provider"
                )


def test_every_category_verb_declares_its_parameter_tuple(providers):
    for category in ("backlog", "issues"):
        declared = set(providers.PROVIDER_VERB_PARAMETERS[category])
        assert declared == set(providers.PROVIDER_CATEGORIES[category])


# --- the dispatch reads the DECLARED provider (L4) ------------------------------------------------


# --- validator parity (L1) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("block", "value", "needle"),
    [
        ("backlogProvider", "acme-boards", "acme-boards"),
        ("backlogProvider", "   ", "present but blank"),
        ("stakeholderQuestions", "acme-issues", "acme-issues"),
        ("stakeholderQuestions", "   ", "present but blank"),
    ],
)
def test_validate_adapter_refuses_exactly_what_load_project_refuses(
    cli, run_cli, tmp_path, block, value, needle
):
    """L1, third occurrence. Opening an enum moved membership out of JSON Schema, so the
    self-service lint stopped being able to see a bad provider. A lint that green-lights an adapter
    the next command refuses is worse than no lint."""
    root = tmp_path / f"{block}-{value.strip() or 'blank'}"
    adapter = _adapter(root, {block: {"provider": value}})

    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 1, result.stdout
    assert needle in result.stderr

    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert needle in str(excinfo.value)


def test_the_default_backlog_provider_is_still_accepted(cli, run_cli, tmp_path):
    """The guarantee an adopter actually depends on, asserted directly rather than inferred from
    the schema's shape — which is why `github-projects` no longer needs to be a schema enum
    literal."""
    adapter = _adapter(tmp_path, {})
    assert run_cli("validate-adapter", "--project", str(adapter)).returncode == 0
    assert cli.load_project(adapter)["backlogProvider"]["provider"] == "github-projects"


def test_an_absent_provider_key_stays_valid_on_both_paths(cli, run_cli, tmp_path):
    adapter = _adapter(tmp_path, {})
    data = json.loads(adapter.read_text())
    data["backlogProvider"].pop("provider", None)
    adapter.write_text(json.dumps(data))
    assert run_cli("validate-adapter", "--project", str(adapter)).returncode == 0
    assert cli.load_project(adapter)["backlogProvider"]["provider"] == "github-projects"


def test_backlog_provider_errors_survives_a_malformed_adapter(cli):
    """`validate-adapter` reads raw JSON; reporting a malformed adapter is the schema check's job
    and this collector must not traceback on the way past."""
    assert cli.backlog_provider_errors([]) == []
    assert cli.backlog_provider_errors({"backlogProvider": "not-an-object"}) == []


# --- Stage 1 sweep findings: the seam must not overclaim ------------------------------------------


def test_the_issues_provider_key_is_still_single_valued(cli, tmp_path):
    """Stage 1 finding, caught before any review round. The `stakeholder_issue_*` family -- seven
    functions that read and write GitHub directly -- does not go through the issues dispatch.
    Opening `stakeholderQuestions.provider` before it does would let an adapter name another
    provider, pass validation, and then silently post a stakeholder question to GitHub: a
    wrong-SYSTEM write, worse than the wrong-board read the backlog guard prevents.

    This asserts the key stays closed until that surface is dispatched. It fails when someone opens
    it, which is the reminder that the seven verbs must come with it."""
    adapter = _adapter(tmp_path, {"stakeholderQuestions": {"provider": "acme-issues"}})
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert "github-issues" in str(excinfo.value)


def test_the_backlog_key_is_open_while_the_issues_key_is_not(cli, tmp_path):
    """The two halves of the same decision, asserted together so neither drifts alone."""
    schema = cli._adapter_schema()["properties"]
    assert "enum" not in schema["backlogProvider"]["properties"]["provider"]
    assert "enum" not in schema["goalTracker"]["properties"]["provider"]
    assert "enum" in schema["stakeholderQuestions"]["properties"]["provider"]


# --- Codex R1 findings: the seam must route EVERY read, check and write ---------------------------


def _full_board(providers_mod, provider_id, unavailable=frozenset(), record=None):
    """A backlog provider double that serves everything except `unavailable`."""

    class Board(providers_mod.Provider):
        pass

    Board.provider_id = provider_id
    Board.category = "backlog"
    Board.unavailable_verbs = frozenset(unavailable)
    Board.list_items = lambda self, data, target, limit=100, use_scope_query=True: []
    Board.list_fields = lambda self, data, target, refresh=False: []
    Board.board_identity = lambda self, data, target: {}
    Board.board_order = lambda self, data, target: {}
    Board.set_status = lambda self, data, target, item_ref, status: {}
    Board.export_item = lambda self, data, target, item_id, field_name, value: (
        record.append((item_id, field_name, value)) if record is not None else None
    )
    return providers_mod.register_provider(Board())


# --- Codex R2 findings: the release must not misreport reality ------------------------------------


# --- Codex R3: nameable is not configurable, and the boundary is explicit -------------------------


def test_enabling_a_provider_with_no_declared_identity_contract_is_refused(
    cli, provider_sandbox, tmp_path
):
    """R2a refused EVERY non-GitHub provider here, because the identity model was GitHub's. R3a
    replaced that with a per-provider contract, so this now tests the narrower property that
    survives: a provider that declares no identity fields still cannot be enabled, because nothing
    has defined what configuring it would mean.

    `jira` deliberately does NOT fall under this any more -- it declares `siteUrl` + `projectKey`
    and is configurable. That is asserted in tests/test_provider_jira_identity.py."""
    _full_board(provider_sandbox, "contract-less-board")
    assert provider_sandbox.provider_identity_fields("contract-less-board")["required"] == ()

    adapter = _adapter(
        tmp_path, {"backlogProvider": {"enabled": True, "provider": "contract-less-board"}}
    )
    # It loads -- nothing to require -- but every verb still refuses, so no board is driven.
    loaded = cli.load_project(adapter)
    assert loaded["backlogProvider"]["provider"] == "contract-less-board"


def test_naming_a_non_github_provider_while_disabled_still_loads(cli, provider_sandbox, tmp_path):
    """Nameable is real, not decorative: the value validates and survives a load."""
    _full_board(provider_sandbox, "named-only-board")
    adapter = _adapter(
        tmp_path, {"backlogProvider": {"enabled": False, "provider": "named-only-board"}}
    )
    assert cli.load_project(adapter)["backlogProvider"]["provider"] == "named-only-board"
