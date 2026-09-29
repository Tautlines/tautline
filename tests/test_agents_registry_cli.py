import json
from pathlib import Path

EXAMPLE_ADAPTER = (
    Path(__file__).resolve().parents[1] / "adapters" / "projects" / "example-saas.json"
)


def _write_adapter(tmp_path, **blocks):
    """A MINIMAL adapter -- for `validate-adapter` only.

    That command reads the file directly and is the strict schema oracle, so a minimal fixture
    is the right shape there: it is exactly what an adopter's half-written adapter looks like.
    Nothing that goes through `load_project()` may use this.
    """
    data = {"project": "demo", "repo": "acme/demo"}
    data.update(blocks)
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _write_lane_adapter(lane, **blocks):
    """A FULL adapter at the trusted repo-local path -- for every lane command.

    `methodology-status` goes through `load_project()`, which requires the full adapter shape,
    and through `require_source_adapter_for_target`, which trusts only `adapters/projects`,
    `MINERVIT_METHODOLOGY_ADAPTER_ROOT`, or the target's `.tautline/adapter.json`. A minimal
    fixture at an ad-hoc path fails BOTH checks before the command reaches anything asserted here.
    """
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data.update(blocks)
    path = lane / ".tautline" / "adapter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_validate_adapter_rejects_a_role_naming_an_unregistered_agent(run_cli, tmp_path):
    path = _write_adapter(
        tmp_path,
        agents={"codex": {"vendor": "openai", "runtime": "codex", "instructionFile": "AGENTS.md"}},
        roles={"implementationReviewer": "gpt-9"},
    )
    result = run_cli("validate-adapter", "--project", str(path))
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "gpt-9" in combined
    assert "codex" in combined  # the remedy lists the available ids


def test_validate_adapter_accepts_invented_vendors_on_invented_runtimes(run_cli, tmp_path):
    """THE load-bearing property, and it must be asserted as a SUCCESS.

    `validate-adapter` is the strict schema oracle and the schema requires a dozen top-level
    keys. A minimal fixture would be rejected for unrelated missing keys, and a test that only
    checked for the absence of certain error strings would pass anyway -- proving nothing about
    invented vendors. Overlay the real adapter and assert exit 0.
    """
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["agents"] = {
        "acme-bot": {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "ACME.md"},
        "globex-bot": {"vendor": "globex", "runtime": "globex-tty", "instructionFile": "GLOBEX.md"},
    }
    data["roles"] = {"builder": "acme-bot", "implementationReviewer": "globex-bot"}
    path = tmp_path / "invented.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = run_cli("validate-adapter", "--project", str(path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_methodology_status_prints_the_synthesised_block_for_a_legacy_adapter(run_cli, tmp_path):
    """The shim REPORTS its guess so an operator can see it and pin it explicitly."""
    path = _write_lane_adapter(tmp_path)
    result = run_cli("methodology-status", "--project", str(path), "--target", str(tmp_path))
    combined = result.stdout + result.stderr
    assert "agents_roles_inferred" in combined
    assert "roles.implementationReviewer = codex" in combined
    assert "roles.builder = claude-code" in combined


def test_methodology_status_warns_that_legacy_keys_are_deprecated(run_cli, tmp_path):
    path = _write_lane_adapter(tmp_path)
    result = run_cli("methodology-status", "--project", str(path), "--target", str(tmp_path))
    combined = result.stdout + result.stderr
    assert "adapter_key_deprecated" in combined
    assert "review.codexWrapper" in combined
    assert "1.0.0" in combined  # the removal release is named


def test_methodology_status_says_nothing_new_for_a_fully_declared_adapter(run_cli, tmp_path):
    path = _write_lane_adapter(
        tmp_path,
        agents={
            "a": {"vendor": "acme", "runtime": "acme-shell", "instructionFile": "A.md"},
            "b": {"vendor": "globex", "runtime": "globex-tty", "instructionFile": "B.md"},
        },
        roles={"planner": "a", "planReviewer": "b", "builder": "a", "implementationReviewer": "b"},
        review={"crossModelTiming": "before-push"},
        goalExecution={},
    )
    result = run_cli("methodology-status", "--project", str(path), "--target", str(tmp_path))
    combined = result.stdout + result.stderr
    assert "agents_roles_inferred" not in combined
    assert "adapter_key_deprecated" not in combined


def test_validate_adapter_accepts_a_role_bound_to_a_shimmed_agent(run_cli, tmp_path):
    """The documented partial migration: `roles.implementationReviewer = "codex"` while the
    `codex` agent still comes from legacy `review.codexWrapper`.

    `validate-adapter` reads the file directly rather than through `load_project`, so nothing
    projects the shim for it. Checking references against raw JSON rejected exactly the path D3
    exists to support.
    """
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["roles"] = {"implementationReviewer": "codex"}
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = run_cli("validate-adapter", "--project", str(path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_validate_adapter_still_rejects_a_role_naming_nothing(run_cli, tmp_path):
    """The relaxation is scoped: a role may name a SHIMMED agent, not an absent one."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["roles"] = {"implementationReviewer": "gpt-9"}
    path = tmp_path / "absent.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = run_cli("validate-adapter", "--project", str(path))
    assert result.returncode != 0
    assert "gpt-9" in result.stdout + result.stderr


def test_validate_adapter_reports_a_top_level_array_instead_of_crashing(run_cli, tmp_path):
    """`validate-adapter` runs on adapters that are already invalid -- that is its whole job --
    so the registry check must be TOTAL on malformed shapes. Tracebacking before printing the
    schema report breaks the command's only contract."""
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    result = run_cli("validate-adapter", "--project", str(path))
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Traceback" not in combined
    assert "expected type object" in combined


def test_validate_adapter_reports_a_non_object_agents_block_instead_of_crashing(run_cli, tmp_path):
    """`agents: "oops"` alongside legacy keys drove the shim straight into an AttributeError."""
    data = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    data["agents"] = "oops"
    path = tmp_path / "badagents.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = run_cli("validate-adapter", "--project", str(path))
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Traceback" not in combined
    assert "agents" in combined
