"""Unit cover for the lean profile's edges.

`tests/test_upgrade_path_e2e.py` proves the whole migration against the real renderer and the real
hook installer; it is the gate. This file covers what a single end-to-end journey structurally
cannot reach: the validator's rejections, the adapter budget under a project with more rules than
fit, a target that is not a git repository, and the containment rule that keeps a hostile or merely
wrong config path from moving files outside the project.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tautline_methodology import backlog, lean  # noqa: E402


LEGACY_MINIMAL = {
    "schemaVersion": "1.0.0",
    "project": "Widget Co",
    "repo": "widget-org/widget",
    "latestCode": {"base": "develop", "remote": "origin"},
    "commands": {"fullPreflight": "make check", "fastPreflight": "make fast"},
    "review": {"roundBudgets": {"T1": 2}, "codexWrapper": "./scripts/codex-review.sh"},
    "knownProjectRules": ["Tenants are isolated at the query layer."],
    "technologyStack": {"nonNegotiable": ["No plaintext secrets."]},
    "planningArtifacts": {"sourceOfTruth": "docs/plans/"},
}


def _write(target: Path, data: dict, name: str = ".tautline.json") -> Path:
    path = target / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


# --- the contract ------------------------------------------------------------------------------


def test_lean_config_from_legacy_keeps_identity_and_drops_ceremony():
    lean_cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    assert lean.lean_config_errors(lean_cfg) == []
    assert lean_cfg["project"] == {"name": "Widget Co", "repo": "widget-org/widget"}
    assert lean_cfg["integrationBranch"] == "develop"
    assert lean_cfg["commands"]["test"] == "make check"
    assert lean_cfg["projectRules"] == [
        "Tenants are isolated at the query layer.",
        "No plaintext secrets.",
    ]
    assert "roundBudgets" not in json.dumps(lean_cfg)
    assert "codexWrapper" not in json.dumps(lean_cfg)


def test_a_dict_shaped_review_key_does_not_become_the_review_norm():
    """1.x `review` is a machinery object. Stringifying it into the prose norm would put a round
    budget back into the adapter through the one key that is allowed to carry prose."""
    lean_cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    assert lean_cfg["review"] == lean.DEFAULT_REVIEW_NORM


@pytest.mark.parametrize(
    "mutate, expected_fragment",
    [
        (lambda cfg: cfg.update(schemaVersion="1.0.0"), "schemaVersion"),
        (lambda cfg: cfg.pop("integrationBranch"), "integrationBranch"),
        (lambda cfg: cfg.update(commands={}), "commands.test"),
        (lambda cfg: cfg.update(project={"repo": "x/y"}), "project.name"),
        (lambda cfg: cfg.update(laneStatus="block"), "laneStatus"),
        (lambda cfg: cfg.update(handoffs="yes"), "handoffs"),
        (lambda cfg: cfg.update(roundBudgets={"T1": 2}), "unknown property"),
        (lambda cfg: cfg.update(projectRules=[""]), "projectRules"),
        (lambda cfg: cfg.update(review={"roundBudgets": {}}), "review"),
        # Track G: cap-overflow fix. One case per free-text length cap, each one character over,
        # so a copy-paste mistake in any single check (wrong constant, wrong field, wrong
        # attribute) fails on its own line instead of hiding behind a neighbor's pass.
        (
            lambda cfg: cfg["project"].update(name="N" * (lean.LEAN_PROJECT_NAME_MAX_CHARS + 1)),
            "project.name",
        ),
        (
            lambda cfg: cfg["project"].update(repo="R" * (lean.LEAN_PROJECT_REPO_MAX_CHARS + 1)),
            "project.repo",
        ),
        (
            lambda cfg: cfg.update(
                integrationBranch="B" * (lean.LEAN_INTEGRATION_BRANCH_MAX_CHARS + 1)
            ),
            "integrationBranch",
        ),
        (
            lambda cfg: cfg["commands"].update(test="T" * (lean.LEAN_TEST_COMMAND_MAX_CHARS + 1)),
            "commands.test",
        ),
        (lambda cfg: cfg.update(review="V" * (lean.LEAN_REVIEW_MAX_CHARS + 1)), "over the"),
        (
            lambda cfg: cfg.update(
                release={"upgradePathTest": "U" * (lean.LEAN_UPGRADE_TEST_MAX_CHARS + 1)}
            ),
            "release.upgradePathTest",
        ),
    ],
)
def test_lean_config_errors_rejects(mutate, expected_fragment):
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    mutate(cfg)
    errors = lean.lean_config_errors(cfg)
    assert any(expected_fragment in error for error in errors), errors


def test_the_shipped_lean_schema_matches_the_validator():
    """The JSON schema is what a human reads; `lean_config_errors` is what runs. They must agree
    on the required keys, or the documented contract and the enforced one drift apart."""
    schema_path = Path(__file__).resolve().parents[1] / "methodology" / "adapter-schema-lean.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schemaVersion"]["const"] == lean.LEAN_SCHEMA_VERSION
    for key in schema["required"]:
        cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
        cfg.pop(key, None)
        assert lean.lean_config_errors(cfg), f"schema requires {key} but the validator allows it"
    documented = set(schema["properties"])
    accepted = set(lean.lean_config_from_legacy(LEGACY_MINIMAL)) | {"$schema"}
    assert accepted <= documented, accepted - documented


# --- the adapter budget ------------------------------------------------------------------------


def test_the_adapter_stays_in_budget_and_says_what_it_dropped():
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    cfg["projectRules"] = [f"Rule {index}: " + ("x" * 90) for index in range(40)]
    text = lean.render_lean_adapter(cfg)
    assert len(text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
    # The process norms are never what gets cut.
    for norm in lean.PROCESS_NORMS:
        assert norm in text
    assert "Rule 0:" in text, "trimming must drop from the END, keeping the first rules"
    assert "further project rule(s) preserved" in text, "a silent drop is a lost project rule"
    assert lean.ARCHIVE_DIRNAME in text


def test_a_project_with_no_rules_renders_no_empty_section():
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    cfg.pop("projectRules")
    text = lean.render_lean_adapter(cfg)
    assert "## Project rules" not in text
    assert "## Process - this is the whole process" in text


# --- Track H: continuity handoffs ---------------------------------------------------------------


def test_handoffs_true_adds_exactly_the_two_lines_and_stays_in_budget():
    base_cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    on_cfg = dict(base_cfg, handoffs=True)

    base_text = lean.render_lean_adapter(base_cfg)
    on_text = lean.render_lean_adapter(on_cfg)
    base_lines = base_text.splitlines()
    on_lines = on_text.splitlines()

    # Removing exactly the two expected lines (in order, first occurrence each) from the
    # handoffs-on render must reconstruct the handoffs-off render byte for byte -- proving the
    # flag adds precisely these two lines and changes nothing else, without pinning WHERE in the
    # file they land.
    remaining = list(on_lines)
    for expected in (f"- {line}" for line in lean.HANDOFF_PROCESS_LINES):
        remaining.remove(expected)
    assert remaining == base_lines
    assert len(on_lines) == len(base_lines) + 2

    assert len(on_text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
    assert (
        "On session start, read `.ai-continuity/HANDOFF.md` if present and continue from it."
        in on_text
    )
    assert (
        "Refresh the handoff at checkpoints — after a merge, before long or risky "
        "operations, and when the operator asks (`/handoff`)." in on_text
    )


@pytest.mark.parametrize("drop_key", [False, True])
def test_handoffs_off_or_absent_adds_no_handoff_lines(drop_key):
    """`handoffs: false` and an absent key must render identically -- both mean "off"."""
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    if drop_key:
        cfg.pop("handoffs", None)
    else:
        cfg["handoffs"] = False
    text = lean.render_lean_adapter(cfg)
    assert ".ai-continuity/HANDOFF.md" not in text
    assert "/handoff" not in text
    assert "Refresh the handoff at checkpoints" not in text


def test_handoffs_true_survives_project_rule_trimming():
    """The two handoff lines are unconditional prose, like the six PROCESS_NORMS -- a project with
    more rules than fit must never trim these to make room."""
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    cfg["handoffs"] = True
    cfg["projectRules"] = [f"Rule {index}: " + ("x" * 90) for index in range(40)]
    text = lean.render_lean_adapter(cfg)
    assert len(text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
    for line in lean.HANDOFF_PROCESS_LINES:
        assert line in text


# --- Track G: standing working-style norms -------------------------------------------------------
#
# docs/reference/goals.md and the `/goal` skill lean on this block existing in EVERY render: a
# composed goal states only what is specific to its own scope because the autonomy/blocked/fan-out/
# evidence norms are ambient here, not because an author remembered to add them.


def test_working_style_lines_render_unconditionally():
    """No config key turns these off, same as the six PROCESS_NORMS -- the minimal fixture carries
    no `handoffs`, no `backlog`, and only the rules LEGACY_MINIMAL itself named."""
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    text = lean.render_lean_adapter(cfg)
    assert len(lean.WORKING_STYLE_LINES) == 4
    for line in lean.WORKING_STYLE_LINES:
        assert line in text


def test_working_style_lines_survive_project_rule_trimming():
    """Unconditional prose, like PROCESS_NORMS and the handoff lines -- a project with more rules
    than fit must never trim these to make room."""
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    cfg["handoffs"] = True
    cfg["projectRules"] = [f"Rule {index}: " + ("x" * 90) for index in range(40)]
    text = lean.render_lean_adapter(cfg)
    assert len(text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
    for line in lean.WORKING_STYLE_LINES:
        assert line in text
    assert "further project rule(s) preserved" in text


def test_the_worst_case_render_leaves_room_for_at_least_one_project_rule():
    """The adapter's own headroom budget, pinned so a future addition to the unconditional content
    trips this deliberately instead of silently eating what is left of a project's rule budget.

    `handoffs` on plus a configured `backlog` plus zero project rules is the biggest a render gets
    before any project rule is added -- what remains is the room every adopting project actually
    has. Measured against this file's own LEGACY_MINIMAL fixture on the day the working-style block
    landed: 1754 bytes at zero rules, 294 bytes of headroom under the 2048 cap (was ~809 before the
    block; a felt, real trade-off, not a free addition). A short project rule renders at roughly 43
    bytes (`- Tenants are isolated at the query layer.\\n`), so the floor asserted here is real
    headroom, not a hypothetical one.
    """
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    cfg["handoffs"] = True
    cfg["backlog"] = {"provider": "github", "repo": "widget-org/widget"}
    cfg.pop("projectRules", None)
    text = lean.render_lean_adapter(cfg)
    worst_case_bytes = len(text.encode("utf-8"))
    headroom = lean.LEAN_ADAPTER_MAX_BYTES - worst_case_bytes
    assert worst_case_bytes <= lean.LEAN_ADAPTER_MAX_BYTES
    assert headroom >= 150, f"only {headroom} bytes left for project rules in the worst case"


def _maximal_backlog_block(provider: str) -> dict:
    """The named provider's backlog block, every one of ITS OWN free-text fields at
    `backlog._BACKLOG_FIELD_MAX_CHARS` -- the per-provider half of the maximal-valid-config
    scenario, kept beside the test that builds the other half so the two cannot drift apart."""
    cap = backlog._BACKLOG_FIELD_MAX_CHARS
    if provider == "local":
        return {"provider": "local", "path": "P" * cap["path"]}
    if provider == "github":
        n = cap["repo"]
        half = n // 2
        return {"provider": "github", "repo": ("r" * half) + "/" + ("r" * (n - half - 1))}
    if provider == "jira":
        return {
            "provider": "jira",
            "site": "https://team.atlassian.net",
            "project": "P" * cap["project"],
            "board": "9" * 19,  # jira_client.MAX_BOARD_ID_DIGITS -- a real digit-count bound,
            # not part of this PR's retightening (see backlog.py's _BACKLOG_FIELD_MAX_CHARS
            # comment for why).
        }
    raise AssertionError(f"no maximal backlog block defined for provider {provider!r}")


def _maximal_cfg(provider: str) -> dict:
    return {
        "schemaVersion": "lean-1",
        "project": {
            "name": "N" * lean.LEAN_PROJECT_NAME_MAX_CHARS,
            "repo": "R" * lean.LEAN_PROJECT_REPO_MAX_CHARS,
        },
        "integrationBranch": "B" * lean.LEAN_INTEGRATION_BRANCH_MAX_CHARS,
        "commands": {"test": "T" * lean.LEAN_TEST_COMMAND_MAX_CHARS},
        "review": "V" * lean.LEAN_REVIEW_MAX_CHARS,
        "release": {"upgradePathTest": "U" * lean.LEAN_UPGRADE_TEST_MAX_CHARS},
        # `handoffs` ON is part of the MAXIMAL scenario, not an orthogonal one: PR #630 review
        # (R1 P1) found that the original version of this test never combined the two, so nobody
        # had measured the config a real project with both a backlog AND continuity handoffs
        # configured can actually reach -- and it did not fit (149 bytes over the cap, with zero
        # project rules left to trim).
        "handoffs": True,
        "workCoordination": True,
        "backlog": _maximal_backlog_block(provider),
    }


#: Below this margin the render is treated as failing the invariant even though it technically
#: still fits -- the SAME floor `docs/reference/backlog.md`'s norm-line change was held to (PR
#: #630 review). A joint worst case that clears the cap by a handful of bytes is one sentence away
#: from raising `LeanAdapterBudgetExceeded` again the next time anyone touches this file.
MINIMUM_MAXIMAL_CONFIG_MARGIN = 40


@pytest.mark.parametrize("provider", backlog.PROVIDERS)
@pytest.mark.parametrize("agent", ["Claude", "Codex"])
def test_the_maximal_valid_config_still_renders_under_the_cap(provider, agent):
    """P2: the floor above (`test_the_worst_case_render_leaves_room_for_at_least_one_project_rule`)
    is real-world headroom against a REALISTIC config; this is the property the cap-overflow fix
    actually enables -- every free-text field simultaneously AT its own cap, `handoffs` ON, zero
    project rules (rules are a separately-tested trimmable dimension, not part of this invariant),
    still fits with real headroom, FOR EVERY PROVIDER THE SEAM DECLARES.

    Parametrized over `backlog.PROVIDERS` rather than hand-listing `local`/`github`/`jira` here: a
    provider added to the seam without a maximal-backlog case in `_maximal_backlog_block` fails
    loudly (the `raise AssertionError` there), so this is discovery-complete against the same
    source of truth `backlog.REFERENCE_GRAMMAR` is, not a second hand-maintained list that could
    silently stop covering a real provider.

    LEAN_*_MAX_CHARS and backlog's `_BACKLOG_FIELD_MAX_CHARS` were tuned TOGETHER against this
    exact scenario, not chosen independently -- if either grows without lowering another, this is
    the test that catches it before a valid config starts refusing.
    """
    cfg = _maximal_cfg(provider)
    assert lean.lean_config_errors(cfg) == [], "the maximal config must itself be schema-valid"
    text = lean.render_lean_adapter(cfg, agent=agent)
    size = len(text.encode("utf-8"))
    margin = lean.LEAN_ADAPTER_MAX_BYTES - size
    assert margin >= MINIMUM_MAXIMAL_CONFIG_MARGIN, (
        f"{provider}/{agent}: maximal valid config (handoffs on) rendered {size} bytes, only "
        f"{margin} bytes of margin under the {lean.LEAN_ADAPTER_MAX_BYTES}-byte cap -- want at "
        f"least {MINIMUM_MAXIMAL_CONFIG_MARGIN}"
    )


def test_a_config_with_no_rules_and_one_oversized_field_is_refused_not_silently_shipped():
    """CRITICAL, reviewer's exact repro: 2 short project rules plus an oversized `review`
    string. Before the fix, the trim loop popped both rules (still over budget), `kept` went
    empty, the loop exited on `while kept and ...`, and `render_lean_adapter` returned the
    over-cap text anyway -- 2048 was enforced in name only. Now: refused, at BOTH layers."""
    cfg = {
        "schemaVersion": "lean-1",
        "project": {"name": "Widget Co"},
        "integrationBranch": "main",
        "commands": {"test": "scripts/test.sh"},
        "review": "x" * 1200,
        "projectRules": ["Rule one is short.", "Rule two is also short."],
    }
    # Layer 1: validation refuses before any render is attempted.
    errors = lean.lean_config_errors(cfg)
    assert any("review" in err and "1200" in err for err in errors), errors

    # Layer 2: even calling the renderer directly (bypassing config validation, as a hand-built
    # dict in a test -- or a future caller -- could) never returns an over-cap string.
    with pytest.raises(lean.LeanAdapterBudgetExceeded) as excinfo:
        lean.render_lean_adapter(cfg)
    message = str(excinfo.value)
    assert "2048" in message
    assert "review" in message and "1200" in message, "must name the actual oversized contributor"


def test_slim_refuses_rather_than_writes_an_over_cap_adapter(tmp_path):
    """The reviewer's repro end to end through `slim`: a legacy adapter that converts to a
    schema-valid-looking lean config (no per-field caps on the LEGACY side) with an oversized
    `review`. `lean_config_errors` catches it at slim's existing pre-render check -- refused,
    nothing written, nonzero exit -- never a silently-shipped over-cap CLAUDE.md."""
    target = tmp_path / "project"
    target.mkdir(parents=True)
    legacy = dict(LEGACY_MINIMAL)
    legacy["review"] = "x" * 900
    (target / ".tautline.json").write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="review"):
        lean.slim_project(target)
    assert not (target / "CLAUDE.md").exists()


def test_all_project_rules_dropped_still_prints_a_notice():
    """The drop-notice line used to be nested under `if rules:` -- the surviving-rules list -- so a
    project whose rules were ALL trimmed away lost the notice along with the heading: no section,
    no notice, no trace any rules ever existed. Individually-oversized rules here (not a long
    `review`) so the render succeeds once they are gone, distinguishing this from the refusal
    case above."""
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    cfg["projectRules"] = ["x" * 900, "y" * 900, "z" * 900]
    text = lean.render_lean_adapter(cfg)
    assert len(text.encode("utf-8")) <= lean.LEAN_ADAPTER_MAX_BYTES
    assert "## Project rules" in text
    assert "all 3 project rule(s) omitted for the size cap" in text
    assert lean.ARCHIVE_DIRNAME in text


def test_slim_rerenders_stale_adapter_files_from_the_current_template(tmp_path):
    """The documented pickup path for an ALREADY-migrated project (docs/reference/lean-migration.md
    step 6): update the framework checkout, re-run `slim`. This is what makes that true -- a lean-1
    project whose CLAUDE.md/AGENTS.md were written by an OLDER template (missing the working-style
    block, say) gets them backed up and rewritten from the CURRENT template, not left stale, even
    though the config itself does not change. Empirically re-confirmed against the real CLI after
    #619 (`tautline init`) landed: `render-adapters --project .tautline.json --write` refuses an
    already-lean project's own config outright (it demands a trusted 1.x source), so `slim` -- not
    `render-adapters` -- is the one command that works here.
    """
    target = tmp_path / "project"
    target.mkdir()
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    (target / ".tautline.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    stale = lean.GENERATED_HEADER + "stale content from an older template\n"
    (target / "CLAUDE.md").write_text(stale, encoding="utf-8")
    (target / "AGENTS.md").write_text(stale, encoding="utf-8")

    result = lean.slim_project(target)

    assert result.changed
    assert "CLAUDE.md" in result.rewrote
    assert "AGENTS.md" in result.rewrote
    assert any(source == "CLAUDE.md" for source, _dest in result.backed_up)
    rerendered = (target / "CLAUDE.md").read_text(encoding="utf-8")
    for line in lean.WORKING_STYLE_LINES:
        assert line in rerendered
    assert "stale content from an older template" not in rerendered
    # Idempotent immediately after: the SAME config re-run once more must be a no-op, proving the
    # rewrite converged on the current template rather than merely changing it again.
    assert lean.slim_project(target).changed is False


# --- slim, off the happy path --------------------------------------------------------------------


def test_slim_migrates_a_target_that_is_not_a_git_repository(tmp_path):
    """No git means no `git mv` and no tracked/untracked distinction -- everything moves, and
    nothing may be lost, because there is no history to recover it from."""
    target = tmp_path / "plain"
    target.mkdir()
    _write(target, LEGACY_MINIMAL)
    plans = target / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "0001.md").write_text("plan\n", encoding="utf-8")
    (target / "CLAUDE.md").write_text("<!-- GENERATED -->\nheavy\n", encoding="utf-8")

    result = lean.slim_project(target)
    assert result.changed
    archive = target / lean.ARCHIVE_DIRNAME
    assert (archive / "docs" / "plans" / "0001.md").read_text(encoding="utf-8") == "plan\n"
    assert (archive / "CLAUDE.md").read_text(encoding="utf-8") == "<!-- GENERATED -->\nheavy\n"
    assert not plans.exists()
    config = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert config["schemaVersion"] == lean.LEAN_SCHEMA_VERSION
    assert lean.slim_project(target).changed is False


def test_slim_will_not_move_anything_outside_the_target(tmp_path):
    """A config path that escapes the project -- absolute, or `../` -- is ignored, not followed."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.md").write_text("not yours\n", encoding="utf-8")
    target = tmp_path / "project"
    target.mkdir()
    legacy = dict(LEGACY_MINIMAL)
    legacy["planningArtifacts"] = {"sourceOfTruth": "../outside"}
    _write(target, legacy)

    lean.slim_project(target)
    assert (outside / "precious.md").is_file()
    assert not (target / lean.ARCHIVE_DIRNAME / "outside").exists()


def test_slim_reads_the_hand_authored_source_when_the_root_marker_is_gone(tmp_path):
    target = tmp_path / "project"
    _write(target, LEGACY_MINIMAL, name=".tautline/adapter.json")
    result = lean.slim_project(target)
    assert result.changed
    config = json.loads((target / ".tautline.json").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "Widget Co"
    assert not (target / ".tautline" / "adapter.json").exists(), (
        "the 1.x source must be archived, or one render reinflates the adapter"
    )


def test_slim_refuses_an_adapter_it_cannot_parse(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    (target / ".tautline.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="not valid JSON"):
        lean.slim_project(target)


def test_gitignored_lane_scratch_is_left_where_it_is(tmp_path):
    """Moving ignored scratch under `docs/` would un-ignore it and stage whatever was on disk.

    `.ai-continuity/` (Track H: continuity handoffs) is covered alongside `.ai-work/` rather than
    in its own test -- it is the same LEGACY_SCRATCH_ROOT_DIRS mechanism, and a second real-git
    fixture proving the identical behavior would not catch anything this one cannot.
    """
    target = tmp_path / "project"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True, capture_output=True)
    _write(target, LEGACY_MINIMAL)
    (target / ".gitignore").write_text(".ai-work/\n.ai-continuity/\n", encoding="utf-8")
    (target / ".ai-work").mkdir()
    (target / ".ai-work" / "LANE_STATUS.json").write_text("{}\n", encoding="utf-8")
    (target / ".ai-continuity").mkdir()
    (target / ".ai-continuity" / "HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")

    result = lean.slim_project(target)
    assert (target / ".ai-work" / "LANE_STATUS.json").is_file()
    assert ".ai-work" in result.left_in_place
    assert not (target / lean.ARCHIVE_DIRNAME / ".ai-work").exists()
    assert (target / ".ai-continuity" / "HANDOFF.md").is_file()
    assert ".ai-continuity" in result.left_in_place
    assert not (target / lean.ARCHIVE_DIRNAME / ".ai-continuity").exists()


# Every form `install-hooks` can produce, including the path forms its per-hook `--*-command`
# overrides and a non-PATH install make routine. A substring match missed all of these while
# matching the mentions below -- wrong in both directions at once.
INVOCATION_FORMS = (
    "tautline lane-status --hook",
    "/opt/tautline/bin/tautline lane-status --hook",
    "./bin/tautline response-guard-hook",
    "~/.local/bin/tautline latest-code-hook",
    '"$HOME"/.local/bin/tautline fleet-guard-hook',
    "${REPO}/bin/tautline question-guard-hook",
    "exec tautline branch-liveness-hook",
    "minervit-methodology plan-finalization-hook",
    "/usr/local/bin/minervit-methodology background-command-hook",
    "/bin/sh -c 'command -v tautline >/dev/null 2>&1 && tautline "
    "autonomy-directive --hook 2>/dev/null || true'",
)

# Commands that MENTION the CLI without invoking it. A hook running one of these belongs to the
# user, and removing it is the worst thing this module can do.
MENTION_FORMS = (
    "grep tautline",
    "--config tautline.toml",
    "echo see the tautline-lint docs",
    "gh repo view tautlines/tautline-dev",
    "cat notes-about-tautline.md",
    "ls /opt/tautline/",
    "npm run lint",
    "echo user-authored",
)


@pytest.mark.parametrize("command", INVOCATION_FORMS)
def test_every_invocation_form_is_recognised(command):
    assert lean._invokes_cli(command), command


@pytest.mark.parametrize("command", MENTION_FORMS)
def test_a_mention_is_not_an_invocation(command):
    assert not lean._invokes_cli(command), command


def test_hook_identification_needs_an_invocation_not_a_mention(tmp_path):
    """The discriminator is content, because the framework stamps none of its Claude hooks."""
    ours = [{"type": "command", "command": command} for command in INVOCATION_FORMS]
    theirs = [{"type": "command", "command": command} for command in MENTION_FORMS]
    settings = {
        "hooks": {"SessionStart": [{"matcher": "*", "hooks": [*ours, *theirs]}]},
        "tautlineQuestionGuardCommands": ["tautline question-guard-hook"],
        "env": {"TAUTLINE_CLAUDE_AUTOCOMPACT_PCT": "85"},
        "permissions": {"allow": ["Bash"]},
    }
    cleaned, removed = lean._strip_settings_hooks(settings)
    assert len(removed) == len(INVOCATION_FORMS), removed
    assert cleaned["hooks"]["SessionStart"][0]["hooks"] == theirs
    assert "tautlineQuestionGuardCommands" not in cleaned
    assert cleaned["env"] == {"TAUTLINE_CLAUDE_AUTOCOMPACT_PCT": "85"}, "env is not ceremony"
    assert cleaned["permissions"] == {"allow": ["Bash"]}, "permissions are not ceremony"


def test_slim_does_not_remove_the_hook_the_installer_displaced(tmp_path):
    """`pre-commit.before-minervit` IS the user's hook. It may well call the CLI itself; deleting
    it because of that would destroy the only copy the installer left them."""
    target = tmp_path / "project"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True, capture_output=True)
    _write(target, LEGACY_MINIMAL)
    hooks = target / ".git" / "hooks"
    marked = "#!/bin/sh\n# MINERVIT-BRANCH-LIVENESS-HOOK\ntautline branch-liveness-check\n"
    (hooks / "pre-commit").write_text(marked, encoding="utf-8")
    displaced = "#!/bin/sh\ntautline lane-status --target .\nnpm run lint\n"
    (hooks / "pre-commit.before-minervit").write_text(displaced, encoding="utf-8")

    result = lean.slim_project(target)
    assert result.removed_git_hooks == ["pre-commit"]
    assert not (hooks / "pre-commit").exists()
    assert (hooks / "pre-commit.before-minervit").read_text(encoding="utf-8") == displaced
    assert any("restore it with: mv" in note for note in result.notes), result.notes


def test_a_symlinked_dot_claude_does_not_pull_home_settings_into_the_repo(tmp_path):
    """CRITICAL regression. `Path.is_relative_to` is a LEXICAL test: with `<project>/.claude`
    symlinked to `~/.claude`, the machine-wide settings file -- permission grants, env values --
    spells as inside the project while being the real home file. A lexical containment check filed
    it into the repository's archive, and the summary then told the user to commit it."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = home / ".claude" / "settings.json"
    secret = "sk-not-a-real-key-000"
    settings.write_text(
        json.dumps(
            {
                "env": {"MACHINE_TOKEN": secret},
                "permissions": {"allow": ["Bash"]},
                "hooks": {
                    "SessionStart": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "tautline x"}]}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "project"
    target.mkdir()
    _write(target, LEGACY_MINIMAL)
    (target / ".claude").symlink_to(home / ".claude", target_is_directory=True)

    result = lean.slim_project(target, home_settings=settings)

    archive = target / lean.ARCHIVE_DIRNAME
    leaked = [
        path
        for path in archive.rglob("*")
        if path.is_file() and secret in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not leaked, f"machine-wide settings were archived into the repository: {leaked}"
    assert not (archive / ".claude").exists()
    backup = settings.with_name("settings.json.before-tautline-slim")
    assert backup.is_file(), "the home file must still be backed up -- beside itself"
    assert secret in backup.read_text(encoding="utf-8")
    assert result.removed_hooks, "the hooks must still be removed"
    assert secret not in "\n".join(lean.format_slim_summary(target, result, dry_run=False))


def test_an_artifact_path_containing_the_archive_is_skipped_with_a_reason(tmp_path):
    """`sourceOfTruth: "docs"` names an ANCESTOR of `docs/archive-prebankruptcy/`. Moving it would
    move a directory into a destination inside itself: `shutil.move` raises mid-way, the project is
    left half-migrated, and every re-run raises in the same place."""
    target = tmp_path / "project"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True, capture_output=True)
    legacy = dict(LEGACY_MINIMAL)
    legacy["planningArtifacts"] = {"sourceOfTruth": "docs"}
    _write(target, legacy)
    (target / "docs").mkdir()
    (target / "docs" / "architecture.md").write_text("kept\n", encoding="utf-8")

    result = lean.slim_project(target)

    assert (target / "docs" / "architecture.md").read_text(encoding="utf-8") == "kept\n"
    assert any("CONTAINS the archive destination" in note for note in result.notes), result.notes
    # ...and it is still idempotent: the skip must not become a per-run crash.
    assert lean.slim_project(target).changed is False


def test_a_hand_authored_adapter_is_proposed_beside_not_overwritten(tmp_path):
    """A file without the `<!-- GENERATED -->` header is prose a person wrote."""
    target = tmp_path / "project"
    target.mkdir()
    _write(target, LEGACY_MINIMAL)
    handwritten = "# Widget Co\n\nNotes a human wrote about this repo.\n"
    (target / "CLAUDE.md").write_text(handwritten, encoding="utf-8")
    (target / "AGENTS.md").write_text("<!-- GENERATED -->\ngenerated, mine to replace\n", encoding="utf-8")

    result = lean.slim_project(target)

    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == handwritten
    proposed = target / f"CLAUDE.md{lean.PROPOSED_ADAPTER_SUFFIX}"
    assert proposed.is_file()
    assert "## Process - this is the whole process" in proposed.read_text(encoding="utf-8")
    assert ("CLAUDE.md", proposed.name) in result.proposed
    # the generated one IS replaced, because the renderer owns it
    assert (target / "AGENTS.md").read_text(encoding="utf-8").startswith(lean.GENERATED_HEADER)
    assert "AGENTS.md" in result.rewrote
    summary = "\n".join(lean.format_slim_summary(target, result, dry_run=False))
    assert "hand-authored" in summary
    assert lean.slim_project(target).changed is False

    # Deleting a reviewed proposal must not cause every subsequent run to recreate it.
    proposed.unlink()
    assert lean.slim_project(target).changed is False
    assert not proposed.exists()
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == handwritten


def test_slim_keeps_handwritten_bootstraps_on_an_already_lean_project(tmp_path):
    cfg = lean.lean_config_from_legacy(LEGACY_MINIMAL)
    _write(tmp_path, cfg)
    for name in ("CLAUDE.md", "AGENTS.md"):
        (tmp_path / name).write_text("# Project-specific instructions\n", encoding="utf-8")

    result = lean.slim_project(tmp_path)

    assert not result.proposed
    assert not list(tmp_path.glob("*.lean-proposed"))
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == "# Project-specific instructions\n"


def test_an_unparseable_settings_file_fails_loudly_rather_than_reporting_success(tmp_path):
    """The hooks live in this file. If it cannot be parsed they are still installed and still
    firing, so a success-shaped summary would be the exact defect this migration exists to remove."""
    target = tmp_path / "project"
    target.mkdir()
    _write(target, LEGACY_MINIMAL)
    (target / ".claude").mkdir()
    broken = target / ".claude" / "settings.json"
    broken.write_text('{"hooks": {},}\n', encoding="utf-8")  # trailing comma

    result = lean.slim_project(target)

    assert result.failed, "an unparseable settings file must be reported as a failure"
    assert any("were NOT removed" in entry for entry in result.failed)
    summary = "\n".join(lean.format_slim_summary(target, result, dry_run=False))
    assert "FAILED - these were NOT migrated:" in summary
    assert broken.read_text(encoding="utf-8") == '{"hooks": {},}\n', "the file must be left alone"

    args = argparse.Namespace(target=str(target), dry_run=False, keep_agent_hooks=True)
    assert lean.slim_command(args) == 1, "a partial migration must not exit 0"


def test_a_byte_order_mark_is_tolerated_not_reported_as_broken(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    _write(target, LEGACY_MINIMAL)
    (target / ".claude").mkdir()
    settings = target / ".claude" / "settings.json"
    payload = {
        "hooks": {
            "Stop": [{"matcher": None, "hooks": [{"type": "command", "command": "tautline x"}]}]
        }
    }
    settings.write_text("﻿" + json.dumps(payload), encoding="utf-8")

    result = lean.slim_project(target)

    assert not result.failed, result.failed
    assert result.removed_hooks, "a BOM must not stop the hooks being removed"


def test_an_untracked_review_ledger_is_still_archived(tmp_path):
    """Discovery walks the filesystem, not the git index. An untracked ledger is still the record
    of a review that happened -- and this repository carries untracked `.plan-reviews/` rounds."""
    target = tmp_path / "project"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True, capture_output=True)
    _write(target, LEGACY_MINIMAL)
    (target / ".gitignore").write_text(".plan-reviews/\n", encoding="utf-8")
    ledger = target / "docs" / "engineering" / ".plan-reviews" / "rounds"
    ledger.mkdir(parents=True)
    (ledger / "r1.json").write_text('{"round": 1}\n', encoding="utf-8")

    result = lean.slim_project(target)

    archived = target / lean.ARCHIVE_DIRNAME / "docs" / "engineering" / ".plan-reviews"
    assert (archived / "rounds" / "r1.json").read_text(encoding="utf-8") == '{"round": 1}\n'
    assert not ledger.exists()
    assert any(".plan-reviews" in source for source, _ in result.moved), result.moved


def test_dry_run_changes_nothing_but_reports_everything(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    _write(target, LEGACY_MINIMAL)
    (target / "CLAUDE.md").write_text("heavy\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}

    result = lean.slim_project(target, dry_run=True)
    assert result.changed
    assert result.rewrote
    assert {p: p.read_bytes() for p in target.rglob("*") if p.is_file()} == before
    lines = lean.format_slim_summary(target, result, dry_run=True)
    assert any("would " in line for line in lines)
    assert any("dry-run" in line for line in lines)
