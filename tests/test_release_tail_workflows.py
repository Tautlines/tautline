"""Guard tests for the OIDC publish workflows (release-tail Task 1).

These workflows publish to npm and PyPI, which is IRREVERSIBLE: a version can
never be re-published. They also ship to the public mirror through
`public-release-export`, so they are a permanent public surface. The invariants
asserted here are the reason the workflows are safe to own that power:

- no secrets, ever (OIDC Trusted Publishing only);
- an explicit `permissions:` block is an ALLOWLIST, so `id-token: write` alone
  silently breaks `actions/checkout` -- `contents: read` must be listed too;
- a `workflow_dispatch` carries no release payload, so the version must be an
  explicit required input, verified against the `VERSION` at the checked-out tag;
- both `release: published` events and dispatches can be replayed, so each
  workflow preflights the registry and no-ops when the version already exists.

The workflows are parsed as YAML rather than regexed as text so a restructure
cannot quietly drop an invariant.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
NPM_WORKFLOW = WORKFLOW_DIR / "publish-npm.yml"
PYPI_WORKFLOW = WORKFLOW_DIR / "publish-pypi.yml"
PUBLISH_WORKFLOWS = (NPM_WORKFLOW, PYPI_WORKFLOW)

# npm gained OIDC Trusted Publishing in 11.5.1; anything older cannot authenticate
# without a token, which is exactly the failure mode this plan exists to remove.
NPM_OIDC_MIN = (11, 5, 1)


def load_workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def workflow_triggers(workflow: dict) -> dict:
    """Return the `on:` block.

    YAML 1.1 (which PyYAML implements) resolves the bare key `on` to the boolean
    True, so a naive workflow["on"] raises KeyError on a perfectly valid file.
    """
    if "on" in workflow:
        return workflow["on"]
    return workflow[True]


def is_publishing_step(step: dict) -> bool:
    """The one step that irreversibly hands a version to a registry."""
    uses = str(step.get("uses", ""))
    run = str(step.get("run", ""))
    return uses.startswith("pypa/gh-action-pypi-publish") or "npm publish" in run


def workflow_steps(workflow: dict) -> list[dict]:
    steps: list[dict] = []
    for job in workflow["jobs"].values():
        steps.extend(job.get("steps", []) or [])
    return steps


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_exists(path: Path) -> None:
    assert path.is_file(), f"missing publish workflow: {path}"


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_references_no_secret(path: Path) -> None:
    """The central invariant: reintroducing a token must fail loudly.

    Asserted against the raw text, not the parsed tree, so a secret smuggled into
    a `run:` script, an `env:` value, or a `with:` input is caught the same way.
    """
    text = path.read_text(encoding="utf-8")
    assert "secrets." not in text, f"{path.name} references a secret; publishing must be OIDC-only"
    assert "NPM_TOKEN" not in text
    assert "PYPI_TOKEN" not in text
    assert "NODE_AUTH_TOKEN" not in text
    assert "TWINE_PASSWORD" not in text


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_permissions_are_a_complete_allowlist(path: Path) -> None:
    """`permissions:` removes everything unlisted -- id-token alone breaks checkout."""
    workflow = load_workflow(path)
    for scope in (workflow, *workflow["jobs"].values()):
        permissions = scope.get("permissions")
        if permissions is None:
            continue
        assert permissions.get("id-token") == "write", f"{path.name}: OIDC needs id-token: write"
        assert permissions.get("contents") == "read", (
            f"{path.name}: an explicit permissions block is an allowlist; "
            "without contents: read, actions/checkout cannot read the repo"
        )
    granted = workflow.get("permissions") or {}
    for job in workflow["jobs"].values():
        granted = job.get("permissions") or granted
    assert granted.get("id-token") == "write"
    assert granted.get("contents") == "read"


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_triggers_on_release_published_and_dispatch(path: Path) -> None:
    triggers = workflow_triggers(load_workflow(path))
    assert "release" in triggers, f"{path.name} must fire on a published Release"
    assert triggers["release"]["types"] == ["published"], (
        f"{path.name}: only `published` may fire a publish; a draft Release emits no event, "
        "which is what makes the bootstrap safe"
    )
    assert "workflow_dispatch" in triggers, f"{path.name} must be re-runnable by dispatch"


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_dispatch_requires_an_explicit_version(path: Path) -> None:
    """A dispatch has no release payload; deriving the version from the default
    branch would publish whatever that branch has drifted to."""
    triggers = workflow_triggers(load_workflow(path))
    inputs = (triggers["workflow_dispatch"] or {}).get("inputs") or {}
    assert "version" in inputs, f"{path.name}: workflow_dispatch must take an explicit version"
    assert inputs["version"].get("required") is True, (
        f"{path.name}: the dispatch version input must be required -- an optional version "
        "would fall back to the default branch and publish untargeted content"
    )


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_checks_out_the_tag_not_the_default_branch(path: Path) -> None:
    checkouts = [
        s
        for s in workflow_steps(load_workflow(path))
        if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkouts, f"{path.name} must check out the repository"
    for step in checkouts:
        ref = str((step.get("with") or {}).get("ref", ""))
        assert "refs/tags/" in ref, (
            f"{path.name}: checkout must pin refs/tags/<tag> for the version being released; "
            "checking out the default branch publishes whatever it has drifted to"
        )


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_verifies_version_against_the_tag(path: Path) -> None:
    """The resolved version must be verified against the VERSION file at the tag."""
    runs = "\n".join(str(step.get("run", "")) for step in workflow_steps(load_workflow(path)))
    assert "VERSION" in runs, f"{path.name} must read the VERSION file at the checked-out tag"
    assert "exit 1" in runs, (
        f"{path.name} must fail closed when VERSION disagrees with the target version"
    )


@pytest.mark.parametrize(
    "path,registry_host",
    [(NPM_WORKFLOW, "registry.npmjs.org"), (PYPI_WORKFLOW, "pypi.org")],
    ids=["npm", "pypi"],
)
def test_publish_workflow_preflights_the_registry_and_no_ops_when_already_published(
    path: Path, registry_host: str
) -> None:
    """A publish is irreversible; release events replay and dispatches get re-run.

    The workflow must ask the registry whether the version already exists and skip
    the publish when it does, rather than attempting a republish.
    """
    steps = workflow_steps(load_workflow(path))
    preflight = [s for s in steps if s.get("id") == "preflight"]
    assert preflight, f"{path.name} must have a step with id `preflight`"
    preflight_run = str(preflight[0].get("run", ""))
    assert registry_host in preflight_run, (
        f"{path.name}: preflight must query {registry_host} for the target version"
    )
    assert "already_published" in preflight_run, (
        f"{path.name}: preflight must record whether the version exists"
    )
    assert "GITHUB_OUTPUT" in preflight_run, (
        f"{path.name}: preflight must publish its verdict as a step output"
    )

    # Pin the assertion to the IRREVERSIBLE step itself. Asserting merely that
    # *some* step carries the guard is worthless: the setup/build steps carry it
    # too, so dropping it from the publish step alone would still pass.
    publishing = [s for s in steps if is_publishing_step(s)]
    assert publishing, f"{path.name}: no step actually publishes to the registry"
    for step in publishing:
        condition = str(step.get("if", ""))
        assert "steps.preflight.outputs.already_published" in condition, (
            f"{path.name}: the step that actually publishes "
            f"({step.get('name') or step.get('uses')!r}) "
            "must be guarded by the preflight verdict, or a replayed event will attempt "
            "an irreversible republish"
        )


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_only_runs_on_the_public_mirror(path: Path) -> None:
    """These workflows also live in the dev repo (they ship via the export).

    A Release cut in the dev repo, or in a fork, must not attempt a publish.
    Trusted Publishing would refuse the OIDC exchange anyway, but skipping
    cleanly beats failing noisily on a repo that was never meant to publish.
    """
    for job in load_workflow(path)["jobs"].values():
        assert "tautlines/tautline'" in str(job.get("if", "")), (
            f"{path.name}: the publish job must be pinned to "
            "github.repository == 'tautlines/tautline'"
        )


def test_npm_workflow_pins_an_npm_cli_new_enough_for_trusted_publishing() -> None:
    """npm Trusted Publishing (OIDC) requires npm >= 11.5.1.

    Ubuntu runners ship an older npm with Node LTS; without an explicit upgrade the
    publish silently falls back to wanting a token.
    """
    text = NPM_WORKFLOW.read_text(encoding="utf-8")
    import re

    pins = re.findall(r"npm@(\d+)\.(\d+)\.(\d+)", text)
    assert pins, "publish-npm.yml must pin an explicit npm CLI version (npm@X.Y.Z)"
    for pin in pins:
        assert tuple(int(part) for part in pin) >= NPM_OIDC_MIN, (
            f"npm@{'.'.join(pin)} predates OIDC trusted publishing "
            f"(needs >= {'.'.join(map(str, NPM_OIDC_MIN))})"
        )


def test_npm_workflow_configures_no_registry_auth_token() -> None:
    """setup-node's `registry-url` writes a TOKEN EXPECTATION npm can never satisfy.

    Given `registry-url`, actions/setup-node writes an .npmrc holding
    `//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}` and points npm at it via
    NPM_CONFIG_USERCONFIG -- but it only exports NODE_AUTH_TOKEN when the caller
    supplies one. This workflow has NO SECRETS by design, so that credential
    resolves to nothing: npm presents an empty token instead of exchanging its OIDC
    identity, and the registry answers `E404 ... PUT /tautline`. That is precisely
    how tautline@0.9.7 failed to publish while PyPI (which does none of this)
    succeeded over OIDC from the same commit.

    This is the same class as the no-secrets invariant above: a token expectation
    with no token behind it is worse than either having a token or having none.
    """
    workflow = load_workflow(NPM_WORKFLOW)
    for step in workflow_steps(workflow):
        if str(step.get("uses", "")).startswith("actions/setup-node"):
            assert "registry-url" not in (step.get("with") or {}), (
                "setup-node's registry-url makes it write an auth-token line into "
                ".npmrc; with no secret behind it npm sends an empty credential and "
                "never authenticates over OIDC"
            )
    # Belt and braces: the token expectation must not return by any other route -- a
    # hand-written .npmrc, an `npm config set`, an env var on the publish step. Scanned
    # with comments stripped, so the prose explaining WHY these are absent (which must
    # name them to be useful) cannot itself trip the guard.
    config_text = "\n".join(
        line.split("#", 1)[0] for line in NPM_WORKFLOW.read_text(encoding="utf-8").splitlines()
    )
    for forbidden in ("registry-url", "_authToken", "NODE_AUTH_TOKEN", "npm config set", ".npmrc"):
        assert forbidden not in config_text, (
            f"publish-npm.yml must not configure a registry auth token ({forbidden!r}); "
            "OIDC trusted publishing mints its own short-lived credential"
        )


def test_pypi_workflow_uses_the_official_action_without_a_password() -> None:
    steps = workflow_steps(load_workflow(PYPI_WORKFLOW))
    publish = [s for s in steps if str(s.get("uses", "")).startswith("pypa/gh-action-pypi-publish")]
    assert publish, (
        "publish-pypi.yml must publish with the official PyPA action "
        "(it performs the OIDC exchange)"
    )
    for step in publish:
        with_block = step.get("with") or {}
        assert "password" not in with_block, (
            "the PyPA action must authenticate by OIDC, not a password/token"
        )


@pytest.mark.parametrize("path", PUBLISH_WORKFLOWS, ids=lambda p: p.name)
def test_publish_workflow_is_exported_to_the_public_mirror(cli, path: Path) -> None:
    """These workflows are useless if the export drops them: Trusted Publishing binds
    to owner + repo + workflow FILENAME, and the mirror is where the workflows run."""
    rel = path.relative_to(REPO_ROOT)
    assert cli.public_release_export_path_included(rel), f"{rel} must survive public-release-export"


# --------------------------------------------------------------------------
# Task 4: the scheduled drift check
# --------------------------------------------------------------------------
DRIFT_WORKFLOW = WORKFLOW_DIR / "release-drift-check.yml"


def test_drift_workflow_runs_on_a_schedule() -> None:
    """Six months of stale registries went unnoticed because nothing ever looked.
    A daily scheduled run turns that silence into a red check within a day."""
    assert DRIFT_WORKFLOW.is_file()
    triggers = workflow_triggers(load_workflow(DRIFT_WORKFLOW))
    assert "schedule" in triggers, "the drift check must run on a schedule, not only on demand"
    assert triggers["schedule"], "the schedule must declare at least one cron entry"
    assert all("cron" in entry for entry in triggers["schedule"])
    assert "workflow_dispatch" in triggers


def test_drift_workflow_actually_runs_the_drift_check() -> None:
    runs = "\n".join(str(s.get("run", "")) for s in workflow_steps(load_workflow(DRIFT_WORKFLOW)))
    assert "release-drift-check" in runs


def test_drift_workflow_is_scoped_to_the_public_mirror() -> None:
    """On the dev repo VERSION legitimately runs ahead of the registries between a
    merge and its release, so a drift check there would cry wolf daily. On the
    mirror, VERSION only moves when release-tail publishes -- so drift there is real."""
    for job in load_workflow(DRIFT_WORKFLOW)["jobs"].values():
        assert "tautlines/tautline'" in str(job.get("if", ""))


def test_drift_workflow_needs_no_secret_and_no_write_access() -> None:
    text = DRIFT_WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    workflow = load_workflow(DRIFT_WORKFLOW)
    permissions = workflow.get("permissions") or {}
    assert permissions.get("contents") == "read"
    assert "write" not in str(permissions.values()), "a read-only check needs no write scope"


def test_drift_workflow_is_exported_to_the_public_mirror(cli) -> None:
    assert cli.public_release_export_path_included(DRIFT_WORKFLOW.relative_to(REPO_ROOT))
