"""Jira becomes configurable: an adapter can describe a Jira board, and nothing pretends it works.

The previous release stopped at *nameable, not configurable* — `owner` + `projectNumber` were
required of every enabled backlog provider, and another provider's own keys were not in the schema,
so `additionalProperties` refused them. This release closes exactly that gap.

Two properties carry it, and they pull in opposite directions on purpose:

* a Jira adapter **loads, validates and renders** — otherwise "configurable" is a word, not a fact;
* **no Jira call is made anywhere**, every verb refuses by name, and the release notes say so — a
  provider that has never spoken to a live instance must not read as working.
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


def _jira_block(**overrides):
    block = {
        "enabled": True,
        "provider": "jira",
        "siteUrl": "https://example-team.atlassian.net",
        "projectKey": "PROJ",
        "emailEnv": "JIRA_EMAIL",
        "apiTokenEnv": "JIRA_API_TOKEN",
        "statusField": "Status",
        "readyStatuses": ["Ready"],
        "activeStatuses": ["In Progress"],
        "doneStatuses": ["Done"],
    }
    block.update(overrides)
    return block


def _adapter(root: Path, block: dict) -> Path:
    data = json.loads(EXAMPLE_ADAPTER.read_text())
    merged = dict(data["backlogProvider"])
    # GitHub coordinates are removed, not left alongside: the point is that a Jira adapter needs
    # none of them.
    for github_only in ("owner", "projectNumber"):
        merged.pop(github_only, None)
    merged.update(block)
    data["backlogProvider"] = merged
    root.mkdir(parents=True, exist_ok=True)
    path = root / "adapter.json"
    path.write_text(json.dumps(data))
    return path


# --- configurable, for real -----------------------------------------------------------------------


def test_a_jira_adapter_loads_without_any_github_coordinates(cli, tmp_path):
    """The whole release in one assertion. Before this, an enabled non-GitHub provider was refused
    at load; a Jira adapter could not exist without fake `owner`/`projectNumber` values."""
    loaded = cli.load_project(_adapter(tmp_path, _jira_block()))
    block = loaded["backlogProvider"]
    assert block["provider"] == "jira"
    assert block["siteUrl"] == "https://example-team.atlassian.net"
    assert block["projectKey"] == "PROJ"
    assert not block["owner"], "a Jira adapter must not need a GitHub owner"


def test_a_jira_adapter_passes_the_self_service_lint(run_cli, tmp_path):
    adapter = _adapter(tmp_path, _jira_block())
    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 0, result.stderr


def test_the_github_identity_model_is_unchanged(cli, run_cli, tmp_path):
    """A GitHub adapter must see exactly the checks and messages it always did."""
    adapter = _adapter(tmp_path, {"provider": "github-projects", "owner": "", "projectNumber": 1})
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert "owner must be non-blank when enabled" in str(excinfo.value)

    example = REPO_ROOT / "adapters" / "projects" / "example-saas.json"
    assert run_cli("validate-adapter", "--project", str(example)).returncode == 0


# --- each provider is judged on the fields IT needs -----------------------------------------------


@pytest.mark.parametrize("missing", ["siteUrl", "projectKey"])
def test_a_jira_adapter_missing_its_own_required_field_is_refused(cli, tmp_path, missing):
    adapter = _adapter(tmp_path / missing, _jira_block(**{missing: ""}))
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    message = str(excinfo.value)
    assert missing in message and "jira" in message


def test_a_jira_adapter_does_not_need_the_optional_board_id(cli, tmp_path):
    loaded = cli.load_project(_adapter(tmp_path, _jira_block()))
    assert loaded["backlogProvider"]["boardId"] == ""


def test_a_github_adapter_is_not_asked_for_jira_fields(cli):
    """The inverse of the same rule: `github-projects` declares no Jira fields, so a GitHub adapter
    must never be refused for lacking `siteUrl`."""
    loaded = cli.load_project(EXAMPLE_ADAPTER)
    assert loaded["backlogProvider"]["siteUrl"] == ""
    assert loaded["backlogProvider"]["apiTokenEnv"] == ""


# --- credentials are NAMED, never carried ---------------------------------------------------------


@pytest.mark.parametrize("field", ["emailEnv", "apiTokenEnv"])
def test_a_credential_env_field_must_name_a_variable_not_hold_a_value(cli, tmp_path, field):
    """The adapter is committed to a repository. A field that names an environment variable is the
    mechanism that keeps the secret out of it, so a value shaped like a credential rather than a
    variable name is refused — otherwise the mechanism is decorative."""
    adapter = _adapter(tmp_path / field, _jira_block(**{field: "not-a-var-name@example.com"}))
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    message = str(excinfo.value)
    assert "must NAME an environment variable" in message
    assert "committed to a repository" in message


@pytest.mark.parametrize("field", ["emailEnv", "apiTokenEnv"])
def test_a_jira_adapter_requires_its_credential_env_names(cli, tmp_path, field):
    adapter = _adapter(tmp_path / f"{field}-blank", _jira_block(**{field: ""}))
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert field in str(excinfo.value)


def test_no_adapter_field_holds_a_credential_shaped_value(providers):
    """Structural: every declared secret field is an env-NAME field. If a future provider adds a
    field intended to hold a token directly, this fails."""
    for provider_id, contract in providers.PROVIDER_IDENTITY_FIELDS.items():
        for field in contract["secretEnvFields"]:
            assert field.endswith("Env"), (
                f"{provider_id}.{field} is declared a secret field but is not named as an "
                "environment-variable reference"
            )


# --- configurable is not working ------------------------------------------------------------------



def test_the_jira_provider_serves_only_what_it_has_implemented(providers):
    """0.142.0 asserted jira served NOTHING. 0.143.0 wires `board_identity`, so the property becomes
    the narrower and more useful one: it advertises exactly what it implements, and nothing else."""
    jira = providers.resolve_provider("backlog", "jira")
    for verb in providers.PROVIDER_CATEGORIES["backlog"]:
        implemented = verb in jira._IMPLEMENTED
        assert jira.supports(verb) is implemented, (
            f"jira advertises {verb} as {jira.supports(verb)} but implements it as {implemented}"
        )
        listed = "jira" in providers.providers_serving("backlog", verb)
        assert listed is implemented, (
            f"the serving list for {verb} disagrees with what jira implements"
        )


def test_the_unavailable_set_is_derived_from_the_contract(providers):
    """Listing the verbs by hand would let a verb added later become silently "available" on a
    provider that cannot serve it."""
    jira = providers.resolve_provider("backlog", "jira")
    contract = frozenset(providers.PROVIDER_CATEGORIES["backlog"])
    assert jira.unavailable_verbs == contract - jira._IMPLEMENTED


def test_no_jira_board_verb_body_can_return_a_plausible_empty_value(cli, providers, tmp_path):
    """Defence in depth. `require` refuses on every dispatch path, so reaching a body means a caller
    bypassed the seam — which must fail loudly rather than return `[]`, which reads as "the board is
    empty" and is the more dangerous answer."""
    jira = providers.resolve_provider("backlog", "jira")
    with pytest.raises(providers.ProviderCapabilityError):
        jira.list_items({}, Path("."))


# --- the board pin follows the provider -----------------------------------------------------------


# --- census: GitHub-shaped assumptions reachable by another provider ----------------------------


def test_the_block_projection_carries_every_providers_identity_fields(cli, tmp_path):
    """Found by census, not by review — which is the point of running one.

    `goal_tracker_from_backlog_provider` copied `owner` and `projectNumber` and nothing else, so an
    enabled Jira `backlogProvider` projected a `goalTracker` describing no board at all: two blocks
    disagreeing about which board the lane is on. The projection now carries every registered
    provider's identity fields, derived from the contract rather than listed, so a provider added
    later crosses the projection without anyone remembering to add it.
    """
    loaded = cli.load_project(_adapter(tmp_path, _jira_block()))
    backlog, tracker = loaded["backlogProvider"], loaded["goalTracker"]
    assert backlog["provider"] == tracker["provider"] == "jira"
    for field in ("siteUrl", "projectKey", "boardId", "emailEnv", "apiTokenEnv"):
        assert backlog[field] == tracker[field], (
            f"{field} did not cross the projection: the two blocks describe different boards"
        )


def test_the_projection_is_derived_from_the_contract_not_a_hand_list(cli, providers, tmp_path):
    """A hand-written list fails open: someone adds a provider, forgets the list, and the identity
    silently stops crossing. Deriving it from `PROVIDER_IDENTITY_FIELDS` means a new provider's
    fields cross by construction — this asserts the derivation, so replacing it with a literal list
    breaks the test."""
    declared = {
        field
        for contract in providers.PROVIDER_IDENTITY_FIELDS.values()
        for group in ("required", "optional", "secretEnvFields")
        for field in contract[group]
    }
    loaded = cli.load_project(_adapter(tmp_path, _jira_block()))
    for field in declared:
        assert field in loaded["goalTracker"], (
            f"{field} is a declared identity field but does not exist on the projected block"
        )


# --- Codex R1: the credential path, and the census's own blind spot -----------------------------


def test_a_pasted_credential_is_never_echoed_in_the_refusal(cli, tmp_path):
    """R1 P1, and the sharpest defect in this release. The refusal interpolated the offending value
    — and the offending value is, by construction, the case where an adopter pasted a real token
    into this field. So the check built to keep a secret out of the repository wrote it to stderr,
    and from there to CI logs and agent transcripts."""
    secret = "ATATT3xFfGF0-NOT-A-REAL-TOKEN-abc123"
    adapter = _adapter(tmp_path, _jira_block(apiTokenEnv=secret))
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    message = str(excinfo.value)
    assert secret not in message, "the refusal echoed the value that may BE the secret"
    assert "apiTokenEnv" in message, "the field must still be identified"
    assert "may BE the secret" in message


def test_a_pasted_credential_is_refused_even_while_the_block_is_disabled(cli, tmp_path):
    """R1 P1. The format check ran only under `enabled`, and a disabled block is exactly where a
    staging configuration sits. A secret pasted into one is committed just as surely."""
    adapter = _adapter(
        tmp_path, _jira_block(enabled=False, apiTokenEnv="ATATT3xFfGF0-NOT-A-REAL-TOKEN")
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert "apiTokenEnv" in str(excinfo.value)


def test_a_disabled_block_does_not_require_fields_it_is_not_using(cli, tmp_path):
    """The other half: presence is required only when enabled. Format is checked either way."""
    adapter = _adapter(tmp_path, _jira_block(enabled=False, siteUrl="", apiTokenEnv=""))
    assert cli.load_project(adapter)["backlogProvider"]["enabled"] is False


@pytest.mark.parametrize(
    "site",
    [
        "https://jira.internal.example",
        "http://team.atlassian.net",
        "https://atlassian.net.evil.example",
    ],
)
def test_a_non_cloud_site_is_refused_at_configuration(cli, tmp_path, site):
    """R1 P2. Cloud-only is documented; accepting a Server/DC or arbitrary host defers the failure
    to an unexplained 404 from an endpoint that does not exist there."""
    adapter = _adapter(tmp_path / site.replace("/", "_"), _jira_block(siteUrl=site))
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert "CLOUD" in str(excinfo.value)


def test_a_cloud_site_is_accepted(cli, tmp_path):
    for site in ("https://team.atlassian.net", "https://my-team-1.atlassian.net/"):
        adapter = _adapter(tmp_path / site.replace("/", "_"), _jira_block(siteUrl=site))
        assert cli.load_project(adapter)["backlogProvider"]["provider"] == "jira"


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("siteUrl", "", "siteUrl"),
        ("projectKey", "", "projectKey"),
        ("apiTokenEnv", "", "apiTokenEnv"),
        ("siteUrl", "https://jira.internal.example", "CLOUD"),
    ],
)
def test_validate_adapter_refuses_exactly_what_load_project_refuses(
    cli, run_cli, tmp_path, field, value, needle
):
    """R1 P1, and the FOURTH occurrence of one lesson: opening a field moves validation out of the
    schema, and every validator that leaned on the schema has to be re-checked. The lint had gained
    the membership check but not the identity check, so it exited 0 for an adapter `load_project`
    refuses — while the migration note points adopters at that very command."""
    adapter = _adapter(tmp_path / f"{field}-{needle}", _jira_block(**{field: value}))
    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 1, result.stdout
    assert needle in result.stderr
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert needle in str(excinfo.value)


def test_every_enabled_only_validation_still_fires_when_enabled(cli):
    """A guard against the mistake I made fixing R1 P1.

    Moving the secret check out of the `enabled` branch, I wrote an `else:` that silently captured
    every validation after it — `statusField`, `readyStatuses`, `activeStatuses`, `doneStatuses`,
    `authoritativeFor`, `repoPlanRequired`, `linkPolicy` — so they ran only when the block was
    DISABLED. An enabled board with no statuses would have loaded. One existing test caught it;
    this one covers the whole class rather than the one member that happened to be asserted.
    """
    base = {
        "enabled": True,
        "provider": "github-projects",
        "owner": "example-org",
        "projectNumber": 1,
        "scopeQuery": "",
        "statusField": "Status",
        "linkPolicy": "links",
        "readyStatuses": ["Ready"],
        "activeStatuses": ["In Progress"],
        "doneStatuses": ["Done"],
        "blockedStatuses": [],
        "authoritativeFor": ["goal-status"],
        "repoPlanRequired": True,
        "doneEvidence": {"acTable": "off"},
    }
    # Sanity: the baseline is valid, so each failure below is caused by the field under test.
    cli.normalize_tracker_adapter_config(
        dict(base), cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider"
    )

    enabled_only = {
        "statusField": "",
        "readyStatuses": [],
        "activeStatuses": [],
        "doneStatuses": [],
        "authoritativeFor": [],
        "repoPlanRequired": False,
        "linkPolicy": "",
    }
    for field, broken in enabled_only.items():
        config = dict(base)
        config[field] = broken
        with pytest.raises(SystemExit, match="when enabled|must be true"):
            cli.normalize_tracker_adapter_config(
                config, cli.DEFAULT_BACKLOG_PROVIDER, "backlogProvider"
            )


# --- Codex R2: the census, widened from tokens to the word itself -------------------------------


#: GitHub mentions that are LEGITIMATE in a Jira lane's adapter, because a Jira adopter still runs
#: code and CI on GitHub. This is the census's classification layer: every mention must be either
#: here or absent, so a NEW one fails until somebody decides which it is. That is the property my
#: earlier token list lacked — it could only find what I had already thought of.
FORGE_GITHUB_MENTIONS = (
    "Do not substitute GitHub Actions for local preflight or as a feedback loop.",
)

def test_a_pasted_credential_is_refused_under_every_provider_selection(cli, providers, tmp_path):
    """R3 P1, and the THIRD variant of one class — which is the finding about my own method.

    Variant 1: the refusal echoed the value. Variant 2: the check ran only when enabled.
    Variant 3: the check iterated the SELECTED provider's secret fields, so a block still set to
    `github-projects` — which declares none — carried an unchecked `apiTokenEnv` while Jira fields
    were being staged, straight into the committed generated adapter.

    I fixed the first two member by member, which is exactly why the third existed. So this test is
    written over the CLASS: every field any provider declares secret, under every provider
    selection, enabled and disabled. A fourth variant has to invent a new dimension to get through.
    """
    secret = "ATATT3xFfGF0-NOT-A-REAL-TOKEN-abc123"
    selections = ("github-projects", "jira")
    for provider in selections:
        for enabled in (True, False):
            for field in providers.all_secret_env_fields():
                block = _jira_block(enabled=enabled, provider=provider, **{field: secret})
                if provider == "github-projects":
                    block.update({"owner": "example-org", "projectNumber": 1})
                root = tmp_path / f"{provider}-{enabled}-{field}"
                with pytest.raises(SystemExit) as excinfo:
                    cli.load_project(_adapter(root, block))
                message = str(excinfo.value)
                assert field in message, f"{provider}/{enabled}/{field}: field not named"
                assert secret not in message, (
                    f"{provider}/{enabled}/{field}: the refusal echoed the secret"
                )


def test_presence_is_the_selected_providers_business_but_inspection_is_not(cli, tmp_path):
    """The two halves that variant 3 conflated. A GitHub adapter is not REQUIRED to supply Jira
    credential fields — but anything it does supply is still INSPECTED."""
    github = _jira_block(provider="github-projects", owner="example-org", projectNumber=1)
    for jira_only in ("siteUrl", "projectKey", "emailEnv", "apiTokenEnv"):
        github.pop(jira_only, None)
    assert cli.load_project(_adapter(tmp_path / "gh-clean", github))["backlogProvider"]["enabled"]

    github_with_token = dict(github)
    github_with_token["apiTokenEnv"] = "ATATT3xFfGF0-NOT-A-REAL-TOKEN"
    with pytest.raises(SystemExit, match="apiTokenEnv"):
        cli.load_project(_adapter(tmp_path / "gh-token", github_with_token))


def test_the_secret_field_union_covers_every_registered_provider(providers):
    """The mechanism the class fix rests on: if a provider is added with a new secret field and the
    union is not derived, the next variant walks straight through."""
    union = set(providers.all_secret_env_fields())
    for provider_id, contract in providers.PROVIDER_IDENTITY_FIELDS.items():
        for field in contract["secretEnvFields"]:
            assert field in union, f"{provider_id}.{field} is not in the inspected union"


@pytest.mark.parametrize("board", ["abc", "12x", "-1", "1.5", " "])
def test_a_nonnumeric_jira_board_id_is_refused(cli, tmp_path, board):
    """R3 P2. A Jira board id is a positive integer. Anything else renders an authoritative
    `/boards/<junk>` pin that resolves to nothing — and the pin is the ONE board a lane is told it
    may work against."""
    adapter = _adapter(tmp_path / f"board-{board.strip() or 'blank'}", _jira_block(boardId=board))
    if not board.strip():
        assert cli.load_project(adapter)["backlogProvider"]["boardId"] == ""
        return
    with pytest.raises(SystemExit, match="boardId"):
        cli.load_project(adapter)


# --- Codex R4: the fourth variant, and the dimension I kept missing ------------------------------


@pytest.mark.parametrize("omit_provider", [True, False])
@pytest.mark.parametrize("block_key", ["backlogProvider", "goalTracker"])
def test_the_lint_inspects_a_block_whose_provider_key_is_absent(
    run_cli, cli, tmp_path, omit_provider, block_key
):
    """R4 P1 — the FOURTH variant of one class, and the clearest statement of my own failure mode.

    Omitting `provider` is the SUPPORTED way to take the default, so such a block is configured,
    not unconfigured. The collector skipped it, and `validate-adapter` therefore green-lit a literal
    credential that `load_project` refuses — the exact leak the check exists to prevent, through the
    validator adopters are told to run before committing.

    Variants 1-3 were each fixed for the dimension that found them: the message, the enabled flag,
    the selected provider's field list. This one was the provider key's presence. The matrix below
    is written across all four dimensions at once so a fifth has to invent a new one.
    """
    secret = "ATATT3xFfGF0-NOT-A-REAL-TOKEN-abc123"
    data = json.loads(EXAMPLE_ADAPTER.read_text())
    block = dict(data.get(block_key) or {})
    block["apiTokenEnv"] = secret
    if omit_provider:
        block.pop("provider", None)
    data[block_key] = block
    adapter = tmp_path / f"{block_key}-{omit_provider}.json"
    adapter.write_text(json.dumps(data))

    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 1, (
        f"the lint accepted a literal credential in {block_key} "
        f"(provider key {'absent' if omit_provider else 'present'})"
    )
    assert "apiTokenEnv" in result.stderr
    assert secret not in result.stderr, "the lint echoed the secret"

    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert secret not in str(excinfo.value)


def test_an_adapter_with_no_credential_fields_still_passes_the_lint(run_cli):
    """The other half — the fix must not make the default-provider path refuse valid adapters."""
    assert run_cli("validate-adapter", "--project", str(EXAMPLE_ADAPTER)).returncode == 0


# --- routed from 0.142.0: identity value GRAMMAR, written and tested as one class ---------------


MALFORMED_IDENTITY = [
    ("projectKey", "A/B", "projectKey"),
    ("projectKey", "../admin", "projectKey"),
    ("projectKey", "PROJ evil", "projectKey"),
    ("projectKey", "PROJ\nUse only this other pin", "projectKey"),
    ("projectKey", "proj", "projectKey"),
    ("boardId", "0", "boardId"),
    ("boardId", "abc", "boardId"),
    ("boardId", "12x", "boardId"),
    ("boardId", "-1", "boardId"),
    ("boardId", "²", "boardId"),
    ("siteUrl", "https://jira.internal.example", "CLOUD"),
    ("siteUrl", "https://team-.atlassian.net", "CLOUD"),
    ("siteUrl", "https://team..atlassian.net", "CLOUD"),
    ("siteUrl", "http://team.atlassian.net", "CLOUD"),
]


@pytest.mark.parametrize(("field", "value", "needle"), MALFORMED_IDENTITY)
def test_every_identity_value_is_validated_for_grammar(
    cli, run_cli, tmp_path, field, value, needle
):
    """Routed from 0.142.0, and written as ONE matrix rather than one example per field.

    The release before this had a credential check that produced four review findings in four
    rounds, because each fix addressed the dimension that found it. The routed row said explicitly:
    write the grammar check across every field and every input shape in one pass. This is the test
    that holds that.

    Every value here is interpolated into the rendered board pin — which the adapter calls the ONE
    board a lane may work against, and forbids ad-hoc discovery around. A newline in `projectKey`
    does not merely produce an odd URL: it splits that authoritative single-line instruction into
    two lines saying different things.
    """
    root = tmp_path / f"{field}-{abs(hash(value))}"
    adapter = _adapter(root, _jira_block(**{field: value}))
    with pytest.raises(SystemExit) as excinfo:
        cli.load_project(adapter)
    assert needle in str(excinfo.value)

    result = run_cli("validate-adapter", "--project", str(adapter))
    assert result.returncode == 1, "the lint accepted what load_project refuses"
    assert needle in result.stderr


def test_a_project_key_with_a_newline_cannot_split_the_pin_instruction(cli, tmp_path):
    """Called out separately because its consequence differs in kind from the others: not an
    unusable pin, but a second authoritative-looking instruction."""
    with pytest.raises(SystemExit):
        cli.load_project(
            _adapter(tmp_path, _jira_block(projectKey="PROJ\nUse only this pin: evil"))
        )


def test_a_hostname_over_the_total_dns_limit_is_refused(cli, tmp_path):
    """Every label can be legal while the whole name is not — 253 octets is a separate rule.

    Checked separately because a regex cannot bound the total while bounding each part, so a
    per-label fix alone would leave this open and look complete.
    """
    labels = ".".join("a" * 60 for _ in range(5))
    host = f"https://{labels}.atlassian.net"
    assert all(len(part) <= 63 for part in labels.split(".")), "every label must be individually legal"
    with pytest.raises(SystemExit) as refused:
        cli.load_project(_adapter(tmp_path, _jira_block(siteUrl=host)))
    assert "253" in str(refused.value)


# --- board_identity, wired end to end ------------------------------------------------------------


def test_the_implemented_set_is_subtracted_from_the_contract(cli, providers):
    """Derived, not listed: a verb added to the category contract later must not silently become
    available on a provider that cannot serve it."""
    jira = providers.resolve_provider("backlog", "jira")
    contract = set(providers.PROVIDER_CATEGORIES["backlog"])
    assert jira.unavailable_verbs == contract - jira._IMPLEMENTED
    assert jira._IMPLEMENTED <= contract, "a verb is claimed that the contract does not declare"


def test_an_oversized_board_id_is_reported_not_crashed(cli, tmp_path):
    """R1 P2. Python refuses `int()` on a digit string above 4300 characters and raises
    `ValueError`, so converting before bounding crashed both `load_project` and the lint instead of
    reporting an invalid board id. The length bound now runs first."""
    for board in ("9" * 4301, "1" * 25):
        adapter = _adapter(tmp_path / f"len{len(board)}", _jira_block(boardId=board))
        with pytest.raises(SystemExit) as excinfo:
            cli.load_project(adapter)
        assert "boardId" in str(excinfo.value)


def test_a_realistic_board_id_is_still_accepted(cli, tmp_path):
    loaded = cli.load_project(_adapter(tmp_path, _jira_block(boardId="1234567")))
    assert loaded["backlogProvider"]["boardId"] == "1234567"
