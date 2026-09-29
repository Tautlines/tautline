"""The lean profile: the `lean-1` project contract, the thin generated adapter, `tautline slim`,
and `tautline init`.

Adopted 2026-08-28 after the process-bankruptcy audit. The framework used to render a ~16KB
instruction file per project and a ~25KB `.tautline.json` describing plan manifests, review-round
budgets, board sync, journals, guard registries and session-start directive walls. This module is
the whole replacement: a config with four required keys, an adapter under 2KB, and two commands
that get a project onto it -- `slim` moves one from the old world without losing a byte of
history, `init` writes the first adapter for a project that never had one.

`slim` is a MIGRATION, so its first obligation is not elegance, it is that a user's repository is
never worse off for having run it:

  * nothing is deleted -- every artifact it stops using is MOVED into `docs/archive-prebankruptcy/`
    (via `git mv` when the path is tracked, so history follows it), and every file it rewrites is
    copied there first;
  * the archive never clobbers: a destination that already exists gets a numbered sibling;
  * it is idempotent by CONSTRUCTION rather than by a "did I already run" flag -- each step asks
    "is this artifact still in its pre-lean state?" and does nothing when the answer is no. A
    second run therefore writes no backups, which is the property that matters: a re-run must not
    be able to overwrite the first run's backup with post-migration content.

Nothing here imports `cli`; `cli` imports this. That direction is deliberate -- the lean profile has
to outlive the monolith.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tautline_methodology import builder

LEAN_SCHEMA_VERSION = "lean-1"

# Both adapter filenames a project may carry. `.tautline.json` is current; the minervit-era name is
# still on deployed machines and `slim` must recognise a project by either.
ADAPTER_FILENAMES = (".tautline.json", ".minervit-ai-delivery.json")

# Where every displaced artifact lands. One directory, inside the project, committed with the
# migration: "rollback" then means `git revert`, and "where did my plan go" has one answer.
ARCHIVE_DIRNAME = "docs/archive-prebankruptcy"

GENERATED_HEADER = "<!-- GENERATED -->\n"
# Where the lean adapter goes when the file it would replace was written by a HUMAN.
PROPOSED_ADAPTER_SUFFIX = ".lean-proposed"

# Track G: goal-advice salvage. Migrating the files is not the same as turning on the Claude Code
# plugin -- that is a client-side setting no file migration can write -- so every summary this
# module prints (slim; `init`'s too, once it exists) names the one step still left by hand. Kept
# as one shared constant so both call sites say exactly the same thing.
PLUGIN_ENABLEMENT_HINT = (
    "enable /goal, /handoff, and the advisory lane-status hook in Claude Code: see "
    "docs/reference/lean-migration.md#enable-the-claude-code-plugin"
)

LEAN_ADAPTER_MARKER = "<!-- tautline-lean-adapter: lean-1 -->"

# The adapter budget. The old one was ~16000 bytes of process the agent had to read before every
# session; the point of the lean profile is that the project-specific part is small enough to be
# read every time. Trimming PROJECT RULES is the first lever -- the process norms and the identity
# facts are never truncated, because a half-sentence norm is worse than no norm -- but trimming
# rules to zero does not GUARANTEE the cap: a config with no rules at all and one long free-text
# field can still exceed it. Two more layers close that gap, deliberately redundant with each
# other: the per-field caps below catch one pathological field early with a message naming it, and
# `render_lean_adapter`'s own check after the trim loop is the authoritative backstop -- several
# fields near their individual caps can still sum past LEAN_ADAPTER_MAX_BYTES, so a render that is
# STILL over budget once there is nothing left to trim refuses outright rather than shipping it.
LEAN_ADAPTER_MAX_BYTES = 2048

# Track G: cap-overflow fix. Sane per-field ceilings for the free-text lean-config fields that feed
# the render. Not ONLY about catching one pathological field early (an accidentally pasted
# paragraph, a whole file dropped into `review`) with a message naming the ONE field to fix --
# these are also sized so that a config where EVERY field sits at its own cap simultaneously still
# renders under LEAN_ADAPTER_MAX_BYTES with room to spare (see
# test_the_maximal_valid_config_still_renders_under_the_cap), which is what makes the render guard
# a backstop that a normal valid config should never actually reach, not the primary defense.
#
# RETIGHTENED (PR #630 review, R1 P1): the ORIGINAL numbers here only ever proved that claim
# against a config with NO backlog and `handoffs` unset -- the maximal-valid-config test never
# combined `handoffs: true` with a configured backlog, so nobody had measured the joint worst case
# a real project can actually reach. It did not fit: every field at its OLD cap plus `handoffs` plus
# a maxed jira backlog rendered 149 bytes OVER the 2048 cap (127 over even before this PR's own
# +22-byte norm-line addition) -- a schema-VALID config `render_lean_adapter` refused outright
# (`LeanAdapterBudgetExceeded`), with zero project rules left to trim it out of. These caps are two
# days old, not sacred: retightened here, verified against the TRUE joint worst case -- every field
# at its cap, `handoffs` on, a maxed backlog, zero project rules, for EACH provider in
# `backlog.PROVIDERS` -- rather than against the partial scenario the original comment claimed to
# cover. See test_the_maximal_valid_config_still_renders_under_the_cap (now parametrized over every
# provider) for the measured margins. Still generous against real values: this repo's own
# `commands.test` ("scripts/test.sh", 15 chars) and `project.name`/`project.repo` (32/22 chars) all
# clear their new caps with room to spare; `review` stays 15 characters above
# DEFAULT_REVIEW_NORM's 60 for a genuinely customized one-sentence override.
LEAN_PROJECT_NAME_MAX_CHARS = 40
LEAN_PROJECT_REPO_MAX_CHARS = 35
LEAN_INTEGRATION_BRANCH_MAX_CHARS = 25
LEAN_TEST_COMMAND_MAX_CHARS = 75
LEAN_REVIEW_MAX_CHARS = 75
LEAN_UPGRADE_TEST_MAX_CHARS = 30

# The six process norms, verbatim from the adopted lean canon. Prose, not configuration: there is
# no key that turns one of these off, because turning one off is a conversation, not a toggle.
PROCESS_NORMS = (
    "Take the top backlog item; specs are one page.",
    "Failing test first; small diffs.",
    "One adversarial review before merge; fix Critical/P1; merge.",
    "Never commit secrets or customer data.",
    "Releases are batched scripts, run when there is something to ship; a release must not break "
    "deployed users.",
    "Keep controls when catches justify false blocks, coordination when it saves time. "
    "Preserve speed; fix incidents with tests.",
)

DEFAULT_REVIEW_NORM = "One adversarial review before merge; fix Critical/P1; merge."
DEFAULT_INTEGRATION_BRANCH = "main"
DEFAULT_TEST_COMMAND = "scripts/test.sh"

# Track G: goal-advice salvage, operator-directed addition. Standing working norms -- rendered
# for every project, unconditionally, folded into "## Process" rather than a separate heading
# because that costs one fewer heading line and one fewer blank line, and HANDOFF_PROCESS_LINES
# below already extends the same section without a sub-heading of its own.
#
# This is what makes a composed goal (docs/reference/goals.md, the `/goal` skill) able to omit the
# autonomy grant: it is ambient here, in every session, so a goal states only what is specific to
# its own scope instead of carrying a second copy of this text that could drift from it.
WORKING_STYLE_LINES = (
    "Work autonomously; assume the operator is AFK. Log non-obvious decisions with "
    "`tautline decision-record`.",
    "If blocked, exhaust other work in scope. Ask one exact question per true blocker asynchronously; "
    "no option menus.",
    "Use subagents for independent work; smaller models where suitable.",
    "Verify and read results before claiming success.",
)

WORK_COORDINATION_LINE = (
    "Use `tautline work`: `status` on wake/resume and before new work; "
    "`declare` before edits; `update` on scope changes; `finish` or `abandon` to retire scope."
)


# Track H: continuity handoffs. One file, latest wins -- see docs/reference/handoffs.md for the
# template. The path is scratch (LEGACY_SCRATCH_ROOT_DIRS below), so it is never archived by
# `slim` and is expected to be gitignored, not committed.
HANDOFF_RELPATH = ".ai-continuity/HANDOFF.md"

# The two process-norm bullets a project buys by turning `handoffs` on. Not in PROCESS_NORMS
# itself: those six render unconditionally, and these two are opt-in prose gated on a config key,
# which the six deliberately have none of.
HANDOFF_PROCESS_LINES = (
    f"On session start, read `{HANDOFF_RELPATH}` if present and continue from it.",
    "Refresh the handoff at checkpoints — after a merge, before long or risky operations, "
    "and when the operator asks (`/handoff`).",
)

# The pinned `backlog.provider` enum (methodology/adapter-schema-lean.json). `local` is the
# default for a config that never asked -- an ABSENT `backlog` key means the same thing as
# `{"provider": "local"}`. `init` always writes the key anyway (see `lean_config_from_answers`):
# it just asked the question, so the answer is recorded, not defaulted away.
BACKLOG_PROVIDERS = ("local", "github", "jira")
DEFAULT_BACKLOG_PATH = "QUEUE.md"
DEFAULT_BACKLOG_LABEL = "backlog"

# Adapter keys that carried a test/gate command in 1.x, best first. `fullPreflight` is the one that
# meant "the whole gate"; the others are progressively narrower, and a narrow gate is still a far
# better answer than inventing `scripts/test.sh` for a project that does not have it.
LEGACY_TEST_COMMAND_KEYS = (
    "fullPreflight",
    "fastPreflight",
    "testEnvironment",
    "mainStatus",
    "earlyWarningSmoke",
    "test",
)

# Every 1.x key whose VALUE is a path to a process-artifact directory inside the project. Read from
# the target's own config so a project that relocated its plans is still found.
#
# Deliberately NOT here: `goalArtifacts.sourceOfTruth` and `readiness.sources`. Those keys belong to
# framework machinery, but the paths they name hold documents the OPERATOR wrote about the product.
# Filing someone's product docs under "archive-prebankruptcy" because the process that referenced
# them died is the migration overreaching.
LEGACY_ARTIFACT_PATH_KEYS = (
    ("planningArtifacts", "sourceOfTruth"),
    ("iterationReview", "recordDir"),
    ("laneCoordination", "laneStatusDir"),
)

# Review-ledger directory names. They live beside the thing they review, at any depth, so they are
# found by walking rather than by a fixed path.
LEGACY_ARTIFACT_DIR_NAMES = (".plan-reviews", ".impl-reviews", ".review-ledger")

# Process HISTORY the framework creates without asking the config. Archived whether or not git
# tracks it: an untracked review ledger is still the record of a review that happened, and this
# repository itself carries untracked `.plan-reviews/` rounds today.
LEGACY_HISTORY_ROOT_DIRS = (
    "docs/superpowers/plans",
    "docs/superpowers/specs",
    "docs/iteration-reviews",
    # The two-layer adapter: `.tautline/adapter.json` is the hand-authored 1.x source that
    # `.tautline.json` was rendered FROM, and `.tautline/pin.json` is the version pin the repin
    # treadmill ran on. Leaving the source in place would let one `render-adapters` reinflate the
    # 16KB adapter this migration just replaced.
    ".tautline",
    ".minervit",
)

# Bulk runtime SCRATCH. Archived only when git tracks something inside it. These are gitignored lane
# state on a real machine, and moving ignored files under `docs/` un-ignores them -- turning a
# migration into a commit of whatever lane junk happened to be on disk. There is no history in them
# to preserve, and after the migration nothing writes them again.
LEGACY_SCRATCH_ROOT_DIRS = (
    ".ai-runs",
    ".ai-work",
    ".ai-continuity",
)

# The hand-authored 1.x adapter sources, in preference order. Read as a FALLBACK when the rendered
# root marker is missing, so a project that only ever kept its source is still migrable.
SOURCE_ADAPTER_RELPATHS = (".tautline/adapter.json", ".minervit/adapter.json")

# A Claude settings hook entry belongs to Tautline when its command INVOKES the CLI. Identifying by
# content rather than by a catalogue of hook names is the point: the catalogue drifts every release
# (eighteen entries across five events at 0.143.0, from twelve writers), a hook this file has never
# heard of is exactly the one a stale machine still runs, and `install-hooks` lets an operator
# override every command string, so a name catalogue could not match them anyway.
#
# "Invokes" is the whole difficulty, and a substring test gets it wrong in BOTH directions: it misses
# every path-form invocation the operator flag produces (`/opt/tautline/bin/tautline`,
# `"$HOME"/.local/bin/tautline`) and it matches bare mentions (`grep tautline`, `--config
# tautline.toml`) whose hooks belong to the user. So the match is: an optional path prefix, then the
# CLI's BASENAME, in command position.
CLI_BASENAMES = ("tautline", "minervit-methodology")

_CLI_INVOCATION_RE = re.compile(
    # command position: start of string/line, or after a shell separator -- `;`, `|`, `&`, a
    # subshell/group opener, a backtick, or `$(`. Scanning finds the LAST `&` of a `&&`, so the
    # wrapped SessionStart hook (`command -v tautline ... && tautline lane-status --hook`) matches
    # on its real invocation and not on the `command -v` probe.
    r"(?:^|[\n;|&(){}`]|\$\()"
    r"\s*"
    r"(?:exec\s+)?"
    # optional path prefix -- anything up to the final `/`, so quoted and variable-bearing paths
    # (`"$HOME"/bin/`, `${REPO}/bin/`, `./bin/`, `~/.local/bin/`) all resolve to their basename.
    r"(?:[^\s;|&]*/)?"
    r"(?:" + "|".join(CLI_BASENAMES) + r")"
    # ...and the basename ENDS here: `tautline-lint` and `tautline.toml` are different programs.
    r"(?![\w.-])"
)

# Generator stamps the framework writes into the git hooks it installs. Git-hook identification is
# stamp-ONLY: every hook the framework installs carries one, and the invocation heuristic above --
# applied to a whole shell script rather than a single command string -- produced false positives
# only, which for a git hook means deleting somebody's executable.
GIT_HOOK_GENERATED_MARKERS = (
    # cli.py GIT_BRANCH_LIVENESS_HOOK_MARKER, line 2 of every generated pre-commit/pre-push.
    "MINERVIT-BRANCH-LIVENESS-HOOK",
    # exported by the same template; a sibling stamp, kept so an edited line 2 is still caught.
    "TAUTLINE_HOOK_BOUNDARY",
    # the release-main pre-commit hook.
    "Generated by minervit-methodology. Protects release main from local commits.",
    "Generated by tautline lane-start.",
)

# The suffix the framework gives a pre-existing hook it displaced. Slim reports these rather than
# reinstating them: silently re-arming an executable that runs on every commit, which the user may
# not have seen in a year, is a bigger surprise than a line of output.
DISPLACED_HOOK_SUFFIX = ".before-minervit"
# The other spelling, from the release-main pre-commit installer: `<hook>.pre-minervit-<stamp>`.
PRE_MINERVIT_HOOK_MARKER = ".pre-minervit-"

CLAUDE_SETTINGS_RELPATH = ".claude/settings.json"

# Bookkeeping keys the framework writes at the TOP LEVEL of a Claude settings file. Dead weight once
# the hooks they track are gone.
SETTINGS_BOOKKEEPING_KEYS = ("tautlineQuestionGuardCommands", "minervitQuestionGuardCommands")


# --------------------------------------------------------------------------------------------
# lean-1 config
# --------------------------------------------------------------------------------------------


def is_lean_config(data: object) -> bool:
    """True when `data` declares the lean contract. The single discriminator, used everywhere."""
    return isinstance(data, dict) and data.get("schemaVersion") == LEAN_SCHEMA_VERSION


def lean_config_errors(data: object) -> list[str]:
    """Validate a lean adapter. Stdlib only -- the CLI has no third-party runtime dependency, and a
    contract this small does not earn one.

    Returns human-readable errors; empty means valid.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"(root): expected object, got {type(data).__name__}"]
    if data.get("schemaVersion") != LEAN_SCHEMA_VERSION:
        found = data.get("schemaVersion")
        errors.append(f"schemaVersion: expected {LEAN_SCHEMA_VERSION!r}, got {found!r}")

    allowed = {
        "$schema",
        "schemaVersion",
        "project",
        "integrationBranch",
        "commands",
        "review",
        "security",
        "release",
        "laneStatus",
        "handoffs",
        "workCoordination",
        "projectRules",
        "backlog",
        # The builder lane's board coordinates. Listed here because this validator refuses ANY key
        # it does not know, so a project that adopts the builder verbs would otherwise have
        # `validate-adapter` reject the very block those verbs require.
        builder.CONFIG_KEY,
    }
    for key in sorted(set(data) - allowed):
        errors.append(f"(root): unknown property {key!r} -- lean-1 has no ceremony keys")

    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("project: required object with a 'name'")
    else:
        for key in sorted(set(project) - {"name", "repo"}):
            errors.append(f"project: unknown property {key!r}")
        name = project.get("name")
        if not isinstance(name, str) or not name:
            errors.append("project.name: required non-empty string")
        elif len(name) > LEAN_PROJECT_NAME_MAX_CHARS:
            errors.append(
                f"project.name: {len(name)} characters, over the "
                f"{LEAN_PROJECT_NAME_MAX_CHARS}-character cap"
            )
        if "repo" in project:
            repo = project["repo"]
            if not isinstance(repo, str):
                errors.append("project.repo: expected string")
            elif len(repo) > LEAN_PROJECT_REPO_MAX_CHARS:
                errors.append(
                    f"project.repo: {len(repo)} characters, over the "
                    f"{LEAN_PROJECT_REPO_MAX_CHARS}-character cap"
                )

    branch = data.get("integrationBranch")
    if not isinstance(branch, str) or not branch:
        errors.append("integrationBranch: required non-empty string")
    elif len(branch) > LEAN_INTEGRATION_BRANCH_MAX_CHARS:
        errors.append(
            f"integrationBranch: {len(branch)} characters, over the "
            f"{LEAN_INTEGRATION_BRANCH_MAX_CHARS}-character cap"
        )

    commands = data.get("commands")
    if not isinstance(commands, dict):
        errors.append("commands: required object with a 'test'")
    else:
        for key in sorted(set(commands) - {"test"}):
            errors.append(f"commands: unknown property {key!r}")
        test_cmd = commands.get("test")
        if not isinstance(test_cmd, str) or not test_cmd:
            errors.append("commands.test: required non-empty string")
        elif len(test_cmd) > LEAN_TEST_COMMAND_MAX_CHARS:
            errors.append(
                f"commands.test: {len(test_cmd)} characters, over the "
                f"{LEAN_TEST_COMMAND_MAX_CHARS}-character cap"
            )

    if "review" in data:
        review = data["review"]
        if not isinstance(review, str):
            errors.append("review: expected a one-sentence string, not machinery")
        elif len(review) > LEAN_REVIEW_MAX_CHARS:
            errors.append(
                f"review: {len(review)} characters, over the {LEAN_REVIEW_MAX_CHARS}-character "
                "cap -- a goal or a spec is not the place for detail this long, this is one line "
                "of adapter prose"
            )
    if "laneStatus" in data and data["laneStatus"] != "advisory":
        errors.append("laneStatus: the only accepted value is 'advisory' -- it never blocks")
    if "workCoordination" in data and not isinstance(data["workCoordination"], bool):
        errors.append("workCoordination: expected boolean")
    if "handoffs" in data and not isinstance(data["handoffs"], bool):
        errors.append("handoffs: expected boolean")
    if "projectRules" in data:
        rules = data["projectRules"]
        bad = not isinstance(rules, list) or any(
            not isinstance(rule, str) or not rule for rule in rules
        )
        if bad:
            errors.append("projectRules: expected a list of non-empty strings")
    if "backlog" in data:
        # Imported HERE rather than at module scope: `backlog` imports this module for the config
        # loader, so a top-level import would be a cycle. The grammar for a Jira site, a project key
        # and a board id belongs with the client that sends those values to a live API, so this
        # validator delegates instead of keeping a second copy that would drift.
        from tautline_methodology import backlog as backlog_mod

        errors.extend(backlog_mod.backlog_config_errors(data["backlog"]))
    if builder.CONFIG_KEY in data:
        # DELEGATED, for the same reason `backlog` above is: the grammar of a board's coordinates
        # belongs with the contract the verbs read them through, so there is one definition of
        # "usable `builderGithub` block" rather than two that can disagree.
        errors.extend(builder.board_config_errors(data))
    sections = (
        ("security", {"secretScan", "customerDataScan"}),
        ("release", {"batched", "upgradePathTest"}),
    )
    for key, subkeys in sections:
        if key in data:
            value = data[key]
            if not isinstance(value, dict):
                errors.append(f"{key}: expected object")
                continue
            for sub in sorted(set(value) - subkeys):
                errors.append(f"{key}: unknown property {sub!r}")
    release = data.get("release")
    if isinstance(release, dict):
        upgrade_test = release.get("upgradePathTest")
        if isinstance(upgrade_test, str) and len(upgrade_test) > LEAN_UPGRADE_TEST_MAX_CHARS:
            errors.append(
                f"release.upgradePathTest: {len(upgrade_test)} characters, over the "
                f"{LEAN_UPGRADE_TEST_MAX_CHARS}-character cap"
            )
    return errors


def load_lean_config(path: Path) -> dict | None:
    """Read a lean adapter, or return None when `path` is absent or is not a lean adapter.

    Never raises on a malformed file: callers on the session-start path (`lane-status`) must not be
    wedged by a config they can simply decline to understand.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if is_lean_config(data) else None


def find_lean_adapter(root: Path) -> Path | None:
    for name in ADAPTER_FILENAMES:
        candidate = root / name
        if candidate.is_file() and load_lean_config(candidate) is not None:
            return candidate
    return None


def _first_str(mapping: object, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def lean_config_from_legacy(data: dict) -> dict:
    """Translate a 1.x adapter into `lean-1`, preserving identity and dropping ceremony.

    Every value kept here is a fact about the PROJECT that an agent cannot derive from the tree:
    what it is called, where it lives, which branch integrates, how to run the tests, and the hard
    rules the project has learned. Everything else in a 1.x adapter describes the framework's own
    process, which is now prose in the generated adapter, so it is dropped rather than translated.
    """
    if is_lean_config(data):
        return json.loads(json.dumps(data))

    raw_project = data.get("project")
    if isinstance(raw_project, dict):
        name = str(raw_project.get("name") or "").strip()
        repo = str(raw_project.get("repo") or "").strip()
    else:
        name = str(raw_project or "").strip()
        repo = str(data.get("repo") or "").strip()

    lane_status_cfg = data.get("laneStatus") if isinstance(data.get("laneStatus"), dict) else {}
    branch = (
        _first_str(data.get("latestCode"), ("base",))
        or _first_str(lane_status_cfg, ("integrationBranch",))
        or DEFAULT_INTEGRATION_BRANCH
    )

    commands = data.get("commands")
    test_command = _first_str(commands, LEGACY_TEST_COMMAND_KEYS) or DEFAULT_TEST_COMMAND

    review = data.get("review")
    review_norm = DEFAULT_REVIEW_NORM
    if isinstance(review, str) and review.strip():
        review_norm = review.strip()

    rules: list[str] = []
    for rule in data.get("knownProjectRules") or []:
        if isinstance(rule, str) and rule.strip():
            rules.append(rule.strip())
    stack = data.get("technologyStack")
    if isinstance(stack, dict):
        for rule in stack.get("nonNegotiable") or []:
            if isinstance(rule, str) and rule.strip() and rule.strip() not in rules:
                rules.append(rule.strip())

    lean: dict = {
        "$schema": "https://tautline.dev/schemas/adapter/lean-1.json",
        "schemaVersion": LEAN_SCHEMA_VERSION,
        "project": {"name": name or (repo.rsplit("/", 1)[-1] if repo else "project")},
        "integrationBranch": branch,
        "commands": {"test": test_command},
        "review": review_norm,
        "security": {"secretScan": True, "customerDataScan": True},
        "release": {"batched": True},
        "laneStatus": "advisory",
    }
    if repo:
        lean["project"]["repo"] = repo
    upgrade_test = _first_str(data.get("migrationSafety"), ("upgradePathTest",))
    if upgrade_test:
        lean["release"]["upgradePathTest"] = upgrade_test
    if rules:
        lean["projectRules"] = rules
    return lean


# --------------------------------------------------------------------------------------------
# the thin adapter
# --------------------------------------------------------------------------------------------


def _adapter_body(cfg: dict, agent: str, *, rules: list[str], dropped: int) -> str:
    project = cfg.get("project") or {}
    name = str(project.get("name") or "Project")
    repo = str(project.get("repo") or "")
    branch = str(cfg.get("integrationBranch") or DEFAULT_INTEGRATION_BRANCH)
    test_command = str((cfg.get("commands") or {}).get("test") or DEFAULT_TEST_COMMAND)
    review_norm = str(cfg.get("review") or DEFAULT_REVIEW_NORM)
    upgrade_test = str((cfg.get("release") or {}).get("upgradePathTest") or "")

    lines = [
        GENERATED_HEADER.rstrip("\n"),
        LEAN_ADAPTER_MARKER,
        f"# {name} - {agent} Adapter",
        "",
    ]
    if repo:
        lines.append(f"- Repo: `{repo}`")
    lines.append(f"- Integration branch: `{branch}` - base branches and PRs on it.")
    lines.append(f"- Gate: `{test_command}` green is required to merge.")
    lines.append("")

    if rules or dropped:
        # `or dropped`, not just `if rules`: a config whose rules were trimmed to NOTHING (every
        # one dropped for the size cap) must still say so. Nesting the whole section under `if
        # rules` alone made the drop notice disappear exactly when it mattered most -- the project
        # had rules, and the render carries no trace of any of them.
        lines.append("## Project rules")
        lines.extend(f"- {rule}" for rule in rules)
        if dropped and rules:
            lines.append(
                f"- ({dropped} further project rule(s) preserved in `{ARCHIVE_DIRNAME}/` -- "
                "move the ones that still matter up into this list.)"
            )
        elif dropped:
            lines.append(
                f"- all {dropped} project rule(s) omitted for the size cap; preserved in "
                f"`{ARCHIVE_DIRNAME}/` -- move the ones that still matter into this file by hand."
            )
        lines.append("")

    lines.append("## Process - this is the whole process")
    for norm in PROCESS_NORMS:
        if norm.startswith("One adversarial review") and review_norm != DEFAULT_REVIEW_NORM:
            lines.append(f"- {review_norm}")
            continue
        if norm.startswith("Releases are batched") and upgrade_test:
            lines.append(f"- {norm[:-1]} (`{upgrade_test}` proves the transition).")
            continue
        lines.append(f"- {norm}")
    lines.extend(f"- {line}" for line in WORKING_STYLE_LINES)
    if cfg.get("workCoordination") is True:
        lines.append(f"- {WORK_COORDINATION_LINE}")
    if cfg.get("handoffs") is True:
        lines.extend(f"- {line}" for line in HANDOFF_PROCESS_LINES)
    lines.append("")
    backlog_line = _backlog_norm(cfg)
    if backlog_line:
        lines.append(backlog_line)
        lines.append("")
    lines.append(
        f"Process history (plans, review ledgers, RCAs) is archived read-only under "
        f"`{ARCHIVE_DIRNAME}/` - reference, not authority."
    )
    return "\n".join(lines) + "\n"


def _backlog_norm(cfg: dict) -> str:
    """The one line a configured backlog adds to the adapter, or "" when none is configured.

    The provider is the project's EXCLUSIVE backlog surface, so the line has to say the negative
    part too: an agent that files a follow-up into a `TODO.md` has created a second backlog, and a
    second backlog is what a sync engine is eventually built to reconcile. Rendered from the config
    rather than written by hand so it can never name a board the project does not have.
    """
    block = cfg.get("backlog")
    if not isinstance(block, dict):
        return ""
    from tautline_methodology import backlog as backlog_mod

    described = backlog_mod.describe_config(block)
    closing = (
        "The queue file is the only backlog surface."
        if str(block.get("provider") or "local") == "local"
        else "Never create backlog/TODO files in the repo."
    )
    return (
        f"Backlog lives in {described}. File follow-ups and deferred work with "
        f"`tautline backlog add`; `tautline backlog list` is what's next. "
        f"PRs: `Backlog: <id>`. {closing}"
    )


class LeanAdapterBudgetExceeded(ValueError):
    """Raised by `render_lean_adapter` when a render cannot fit under `LEAN_ADAPTER_MAX_BYTES`
    even with every project rule trimmed away -- the untrimmable content itself is too big.

    `lean_config_errors`'s per-field caps catch most causes of this before render ever runs, but
    several fields sitting near their own individual caps can still sum past the byte budget, and
    the caps do not cover every contributor (the fixed process/working-style text, for one). This
    is the authoritative backstop: `slim_project`/`init_command` catch it and surface the refusal
    through their own failed/nonzero-exit paths. Nothing may write a rendered file that is over
    cap and call it success.
    """


def _budget_contributors(cfg: dict) -> list[tuple[str, int]]:
    """The free-text fields that feed the render, named and measured in characters, longest
    first -- so a budget refusal can point at what to shorten instead of only repeating the byte
    count. Zero-length fields are omitted; there is nothing actionable to say about an empty one."""
    project = cfg.get("project") or {}
    contributors = [
        ("project.name", len(str(project.get("name") or ""))),
        ("project.repo", len(str(project.get("repo") or ""))),
        ("integrationBranch", len(str(cfg.get("integrationBranch") or ""))),
        ("commands.test", len(str((cfg.get("commands") or {}).get("test") or ""))),
        ("review", len(str(cfg.get("review") or ""))),
        (
            "release.upgradePathTest",
            len(str((cfg.get("release") or {}).get("upgradePathTest") or "")),
        ),
        ("backlog (rendered line)", len(_backlog_norm(cfg))),
    ]
    return sorted((c for c in contributors if c[1] > 0), key=lambda c: c[1], reverse=True)


def render_lean_adapter(cfg: dict, *, agent: str = "Claude") -> str:
    """Render the thin instruction file for one runtime.

    Stays under `LEAN_ADAPTER_MAX_BYTES` by dropping project rules from the END of the list and
    saying how many it dropped and where they still live. The alternative -- silently truncating
    mid-sentence, or letting the file grow back toward the 16KB it replaced -- both defeat the
    reason the budget exists.

    Dropping every rule is not guaranteed to be enough: a config with no rules at all, or with
    long-but-individually-valid free-text fields, can still be over budget once there is nothing
    left to trim. That is `LeanAdapterBudgetExceeded`, raised rather than returned -- writing a
    file that is over the cap and calling it success is the exact defect this function exists to
    prevent, and a caller that forgets to check a return value cannot forget to catch an
    exception it never expected.
    """
    rules = [str(rule) for rule in (cfg.get("projectRules") or []) if str(rule).strip()]
    kept = list(rules)
    dropped = 0
    text = _adapter_body(cfg, agent, rules=kept, dropped=dropped)
    while kept and len(text.encode("utf-8")) > LEAN_ADAPTER_MAX_BYTES:
        kept.pop()
        dropped += 1
        text = _adapter_body(cfg, agent, rules=kept, dropped=dropped)
    size = len(text.encode("utf-8"))
    if size > LEAN_ADAPTER_MAX_BYTES:
        contributors = _budget_contributors(cfg)
        named = "; ".join(f"{field} ({length} chars)" for field, length in contributors) or (
            "no single long field -- the fixed process/working-style text alone accounts for it"
        )
        rule_note = f"{dropped} project rule(s) trimmed away" if dropped else "no project rules to trim"
        raise LeanAdapterBudgetExceeded(
            f"lean adapter render for {agent!r} is {size} bytes, "
            f"{size - LEAN_ADAPTER_MAX_BYTES} over the {LEAN_ADAPTER_MAX_BYTES}-byte cap, even "
            f"with {rule_note}. Longest contributing field(s): {named}. Shorten one of these and "
            "try again."
        )
    return text


def lean_adapter_files(cfg: dict) -> dict[str, str]:
    """The generated instruction files, keyed by repo-relative path."""
    return {
        "CLAUDE.md": render_lean_adapter(cfg, agent="Claude"),
        "AGENTS.md": render_lean_adapter(cfg, agent="Codex"),
    }


def write_lean_adapter_files(target: Path, cfg: dict) -> tuple[list[str], list[tuple[str, str]]]:
    """Write CLAUDE.md/AGENTS.md for `cfg` into `target`. Never clobbers hand-authored content.

    Same hand-authored protection as `slim_project` step 4 (a destination that exists and does
    NOT start with `GENERATED_HEADER` was written by a person, so it gets a `.lean-proposed`
    sibling instead of being overwritten), factored out so `init` -- a green-field write with no
    archive to fall back on -- shares it rather than re-deciding the same question. `slim_project`
    keeps its own inline loop: unlike `init`, it also archives the file it is about to overwrite,
    which this helper has no target directory convention for.

    Returns (written relpaths, proposed (original, proposed) relpath pairs).
    """
    written: list[str] = []
    proposed: list[tuple[str, str]] = []
    for rel, content in lean_adapter_files(cfg).items():
        dest = target / rel
        current = dest.read_text(encoding="utf-8") if dest.is_file() else None
        if current == content:
            continue
        if current is not None and not current.startswith(GENERATED_HEADER):
            proposed_path = dest.with_name(dest.name + PROPOSED_ADAPTER_SUFFIX)
            if proposed_path.is_file() and proposed_path.read_text(encoding="utf-8") == content:
                continue
            proposed.append((rel, f"{rel}{PROPOSED_ADAPTER_SUFFIX}"))
            proposed_path.write_text(content, encoding="utf-8")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(rel)
    return written, proposed


# --------------------------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------------------------


def _git(target: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(target), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def is_git_repo(target: Path) -> bool:
    proc = _git(target, "rev-parse", "--is-inside-work-tree")
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _tracks_anything(target: Path, path: Path) -> bool:
    """True when git tracks `path` or anything under it."""
    rel = path.relative_to(target).as_posix()
    proc = _git(target, "ls-files", "-z", "--", rel)
    return proc.returncode == 0 and bool(proc.stdout.strip("\0").strip())


def _unique_destination(dest: Path) -> Path:
    """Never clobber. A destination that exists gets `name-2`, `name-3`, ..."""
    if not dest.exists():
        return dest
    stem, suffix = (dest.stem, dest.suffix) if dest.is_file() or dest.suffix else (dest.name, "")
    for index in range(2, 100):
        candidate = dest.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find a free archive destination beside {dest}")


# --------------------------------------------------------------------------------------------
# slim
# --------------------------------------------------------------------------------------------


class SlimResult:
    """What `slim` did (or, in dry-run, would do). Every mutation is recorded as a line."""

    def __init__(self) -> None:
        self.moved: list[tuple[str, str]] = []
        self.backed_up: list[tuple[str, str]] = []
        self.rewrote: list[str] = []
        self.removed_hooks: list[str] = []
        self.removed_git_hooks: list[str] = []
        self.left_in_place: list[str] = []
        self.proposed: list[tuple[str, str]] = []
        self.failed: list[str] = []
        self.notes: list[str] = []

    @property
    def changed(self) -> bool:
        """Whether this run MUTATED anything. `left_in_place` is deliberately excluded: reporting
        untouched scratch is not a change, and a second run must still read as a no-op."""
        return bool(
            self.moved
            or self.backed_up
            or self.rewrote
            or self.removed_hooks
            or self.removed_git_hooks
            or self.proposed
        )


def _archive_root(target: Path) -> Path:
    return target / ARCHIVE_DIRNAME


def _archive_move(target: Path, source: Path, result: SlimResult, *, dry_run: bool) -> None:
    """Move a process artifact into the archive. `git mv` when tracked, so history follows it."""
    archive = _archive_root(target)
    dest = _unique_destination(archive / source.relative_to(target))
    rel_source = source.relative_to(target).as_posix()
    rel_dest = dest.relative_to(target).as_posix()
    result.moved.append((rel_source, rel_dest))
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_git_repo(target):
        proc = _git(target, "mv", "--", rel_source, rel_dest)
        if proc.returncode == 0:
            return
        result.notes.append(
            f"git mv declined ({proc.stderr.strip()}); moved on the filesystem instead"
        )
    shutil.move(str(source), str(dest))


def _archive_copy(target: Path, source: Path, result: SlimResult, *, dry_run: bool) -> None:
    """Copy a file into the archive before it is rewritten in place."""
    archive = _archive_root(target)
    dest = _unique_destination(archive / source.relative_to(target))
    result.backed_up.append((_display(source, target), _display(dest, target)))
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(dest))


def _review_ledger_dirs(target: Path) -> list[Path]:
    """Every `.plan-reviews` / `.impl-reviews` / `.review-ledger` DIRECTORY in the target.

    A FILESYSTEM walk, deliberately, not `git ls-files`: the index misses an untracked or gitignored
    ledger, and an untracked ledger is still the record of a review that happened. This repository
    itself carries untracked `.plan-reviews/` rounds right now, so the index-based version had a
    live counterexample in the tree it shipped from. `.git/` is pruned so the walk never descends
    into the object store.
    """
    found: set[Path] = set()
    skip = {".git"}
    stack = [target]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if entry.name in skip:
                continue
            if entry.name in LEGACY_ARTIFACT_DIR_NAMES:
                found.add(entry)
                # Do not descend: everything under a ledger moves with it.
                continue
            stack.append(entry)
    return sorted(found)


def _candidate_artifact_paths(target: Path, legacy: dict) -> tuple[list[Path], list[Path], list[str]]:
    """Split this project's process-artifact paths into (archive, leave-in-place, skip notes).

    Named by the project's own config, plus the directories the framework creates unasked.
    Returned in a stable order, de-duplicated, existing only.

    Two classes, because they earn different answers when git does not track them:

      * process HISTORY -- plan directories, review ledgers, iteration reviews, the 1.x adapter
        source -- is archived either way. An untracked review ledger is still a record.
      * bulk runtime SCRATCH (`.ai-work/`, `.ai-runs/`, `.ai-continuity/`) is left in place unless
        git tracks something inside it. Those are gitignored lane state on a real machine, and
        moving ignored files under `docs/` un-ignores them, turning a migration into a commit of
        whatever junk was on disk. Nothing writes them after the migration.
    """
    history: list[Path] = []
    scratch: list[Path] = []
    notes: list[str] = []
    seen: set[Path] = set()
    resolved_target = target.resolve()
    archive = _archive_root(target).resolve()

    def add(rel: str, bucket: list[Path]) -> None:
        # `lstrip("./")` would be a character-set strip, not a prefix strip: it turns ".ai-work"
        # into "ai-work" and every dotted process directory silently stops matching, so slim
        # reports success having archived none of them.
        rel = rel.strip()
        while rel.startswith("./"):
            rel = rel[2:]
        rel = rel.rstrip("/")
        if not rel:
            return
        path = (target / rel).resolve()
        # Containment: an adapter value like "../../etc" or an absolute path must never make slim
        # move something outside the project it was pointed at.
        if not path.is_relative_to(resolved_target) or path == resolved_target:
            return
        # Already inside the archive: nothing to do, and re-archiving is how a second run undoes
        # the first one's work.
        if archive == path or archive in path.parents:
            return
        # ...and the reverse, which is the one that CRASHES rather than no-ops: a config naming an
        # ANCESTOR of the archive ("docs") would move a directory into a destination inside itself.
        # `shutil.move` raises mid-way, leaving the project half-migrated and every re-run raising
        # in the same place. Skip it and say why -- the user chose that path, so they can move the
        # part they meant.
        if path in archive.parents:
            notes.append(
                f"{path.relative_to(resolved_target).as_posix()} CONTAINS the archive destination "
                f"({ARCHIVE_DIRNAME}) and was left alone -- archive the process artifacts inside "
                "it by hand, or point the config at a narrower path"
            )
            return
        if path in seen or not path.exists():
            return
        seen.add(path)
        bucket.append(path)

    for key, subkey in LEGACY_ARTIFACT_PATH_KEYS:
        section = legacy.get(key)
        if not isinstance(section, dict):
            continue
        value = section.get(subkey)
        if isinstance(value, str):
            add(value, history)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    add(item, history)
    for rel in LEGACY_HISTORY_ROOT_DIRS:
        add(rel, history)
    for rel in LEGACY_SCRATCH_ROOT_DIRS:
        add(rel, scratch)
    for path in _review_ledger_dirs(target):
        add(path.relative_to(target).as_posix(), history)

    def prune(paths: list[Path]) -> list[Path]:
        return [path for path in paths if not any(parent in seen for parent in path.parents)]

    to_archive = prune(history)
    scratch = prune(scratch)
    if is_git_repo(target):
        to_archive += [path for path in scratch if _tracks_anything(target, path)]
        left = [path for path in scratch if not _tracks_anything(target, path)]
    else:
        to_archive += scratch
        left = []
    return sorted(set(to_archive)), sorted(set(left)), notes


def _hook_is_tautline(entry: object) -> bool:
    """A Claude settings hook entry belongs to Tautline when its command invokes the CLI."""
    if not isinstance(entry, dict):
        return False
    return _invokes_cli(str(entry.get("command") or ""))


def _strip_settings_hooks(settings: dict) -> tuple[dict, list[str]]:
    """Return (cleaned settings, removed command strings). User-authored hooks are untouched.

    The framework writes eighteen hook entries across five events from twelve writer functions,
    and stamps NONE of them -- its own health checks identify a hook by substring-matching the verb
    name inside the serialised entry. So this walks the whole tree and drops any entry whose command
    invokes the CLI, which is both broader than the verb catalogue and immune to it drifting.

    `settings["env"]` is left alone on purpose: the autocompact knobs there change how the user's
    session behaves, they are not process ceremony, and a migration should not silently retune
    someone's context window.
    """
    removed: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        cleaned = {
            key: value
            for key, value in settings.items()
            if key not in SETTINGS_BOOKKEEPING_KEYS
        }
        return cleaned, removed
    cleaned_events: dict = {}
    for event, matchers in hooks.items():
        if not isinstance(matchers, list):
            cleaned_events[event] = matchers
            continue
        kept_matchers = []
        for matcher in matchers:
            if not isinstance(matcher, dict):
                kept_matchers.append(matcher)
                continue
            entries = matcher.get("hooks")
            if not isinstance(entries, list):
                kept_matchers.append(matcher)
                continue
            kept_entries = []
            for entry in entries:
                if _hook_is_tautline(entry):
                    removed.append(f"{event}: {str(entry.get('command') or '').strip()}")
                else:
                    kept_entries.append(entry)
            if not kept_entries:
                # The whole matcher existed only to carry framework hooks: drop it rather than
                # leave an empty shell that a later reader has to decide about.
                continue
            kept_matchers.append({**matcher, "hooks": kept_entries})
        if kept_matchers:
            cleaned_events[event] = kept_matchers
    cleaned = {
        key: value
        for key, value in settings.items()
        if key != "hooks" and key not in SETTINGS_BOOKKEEPING_KEYS
    }
    if cleaned_events:
        cleaned["hooks"] = cleaned_events
    return cleaned, removed


def _git_hooks_dir(target: Path) -> Path | None:
    proc = _git(target, "rev-parse", "--git-path", "hooks")
    if proc.returncode != 0:
        return None
    hooks = Path(proc.stdout.strip())
    if not hooks.is_absolute():
        hooks = target / hooks
    return hooks if hooks.is_dir() else None


def _invokes_cli(command: str) -> bool:
    """Whether a hook COMMAND invokes the CLI, rather than merely mentioning it.

    See `_CLI_INVOCATION_RE`. Getting this wrong is the worst bug this module can have in either
    direction: a miss leaves a hook running and reports success for removing it, a false positive
    deletes something the user wrote.
    """
    return _CLI_INVOCATION_RE.search(command) is not None


def _is_displaced_hook(name: str) -> bool:
    """Whether `name` is a hook the installer moved aside -- the USER's, by construction, since
    only UNMARKED hooks are ever backed up. Both spellings the framework has used: the plain
    `.before-minervit` suffix and the timestamped `.pre-minervit-<stamp>` one."""
    return DISPLACED_HOOK_SUFFIX in name or PRE_MINERVIT_HOOK_MARKER in name


def _git_hook_is_tautline(path: Path) -> bool:
    """STAMP-ONLY. Every git hook the framework installs carries one of
    `GIT_HOOK_GENERATED_MARKERS`, so there is no need to guess -- and guessing here is worse than
    useless: an invocation heuristic applied to a whole shell script (rather than to one command
    string) matched comments, docs URLs and `command -v` probes, and a false positive on a git hook
    means deleting somebody's executable."""
    if not path.is_file() or path.suffix == ".sample":
        return False
    if _is_displaced_hook(path.name):
        return False
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    return any(marker in text for marker in GIT_HOOK_GENERATED_MARKERS)


def _inside_target(path: Path, target: Path) -> bool:
    """Containment, decided on RESOLVED paths.

    `Path.is_relative_to` is a lexical string test: it answers about the spelling, not the file. A
    project whose `.claude` is a symlink to `~/.claude` spells its settings file inside the project
    while it IS the machine-wide one -- so a lexical check would file `~/.claude/settings.json`,
    with its `env` values and permission grants, into the repository's archive, and the summary
    would then tell the user to commit it. Resolve first, always.
    """
    try:
        return path.resolve().is_relative_to(target.resolve())
    except OSError:
        return False


def _settings_backup_path(settings_path: Path, target: Path) -> Path:
    """Where a settings file's pre-migration copy goes.

    A file genuinely inside the project goes in the project's archive. `~/.claude/settings.json`
    does NOT: that file carries machine-wide `env` values and permission grants, and copying it
    into a repository is how a migration turns into a secret leak. Its backup stays beside itself.
    """
    if _inside_target(settings_path, target):
        resolved = settings_path.resolve()
        return _unique_destination(_archive_root(target) / resolved.relative_to(target.resolve()))
    beside = settings_path.with_name(settings_path.name + ".before-tautline-slim")
    return _unique_destination(beside)


def _slim_claude_settings(
    settings_path: Path, target: Path, result: SlimResult, *, dry_run: bool
) -> None:
    if not settings_path.is_file():
        return
    label = _display(settings_path, target)
    try:
        # utf-8-sig, so a byte-order mark -- which several editors add and `json.loads` rejects --
        # is tolerated rather than being reported as a broken file.
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        # A FAILURE, not a note. This is the file the framework's hooks actually live in: if it
        # cannot be parsed, the hooks are still installed and still firing, and a summary that
        # printed a success shape here would be the exact control-reports-success-while-doing-
        # nothing defect this migration exists to remove from the project.
        result.failed.append(
            f"{label} could not be parsed, so its hooks were NOT removed: {exc}. "
            "Fix the file (a trailing comma or a comment is the usual cause), then re-run slim."
        )
        return
    if not isinstance(settings, dict):
        result.failed.append(
            f"{label} does not contain a JSON object, so its hooks were NOT removed. "
            "Fix the file, then re-run slim."
        )
        return
    cleaned, removed = _strip_settings_hooks(settings)
    if not removed and cleaned == settings:
        return
    result.removed_hooks.extend(f"{label}  {entry}" for entry in removed)
    backup = _settings_backup_path(settings_path, target)
    result.backed_up.append((label, _display(backup, target)))
    result.rewrote.append(label)
    if dry_run:
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(settings_path), str(backup))
    settings_path.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _display(path: Path, target: Path) -> str:
    if _inside_target(path, target):
        return path.resolve().relative_to(target.resolve()).as_posix()
    return str(path)


def slim_project(
    target: Path, *, dry_run: bool = False, home_settings: Path | None = None
) -> SlimResult:
    """Migrate one adapted project to the lean profile. Idempotent; never deletes content."""
    result = SlimResult()
    target = target.resolve()
    if not target.is_dir():
        raise SystemExit(f"slim: {target} is not a directory")

    # The rendered root marker is the config the project actually runs on, so it is read first; the
    # hand-authored source under `.tautline/` is the fallback for a project that kept only that.
    # The lean config is always WRITTEN to the root marker either way.
    read_path: Path | None = None
    write_path: Path | None = None
    for name in ADAPTER_FILENAMES:
        if (target / name).is_file():
            read_path = write_path = target / name
            break
    if read_path is None:
        for rel in SOURCE_ADAPTER_RELPATHS:
            if (target / rel).is_file():
                read_path = target / rel
                write_path = target / ADAPTER_FILENAMES[0]
                break
    if read_path is None or write_path is None:
        raise SystemExit(
            f"slim: no Tautline adapter found in {target} (looked for "
            f"{', '.join((*ADAPTER_FILENAMES, *SOURCE_ADAPTER_RELPATHS))}) -- nothing to migrate"
        )

    try:
        legacy = json.loads(read_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"slim: {read_path} is not valid JSON: {exc}") from exc
    if not isinstance(legacy, dict):
        raise SystemExit(f"slim: {read_path} does not contain a JSON object")
    adapter_path = write_path

    already_lean = is_lean_config(legacy)
    lean_cfg = lean_config_from_legacy(legacy)
    errors = lean_config_errors(lean_cfg)
    if errors:
        joined = "\n  ".join(errors)
        raise SystemExit(f"slim: refusing to write an invalid lean adapter:\n  {joined}")

    # 1. archive the process artifacts -------------------------------------------------------
    to_archive, left_in_place, skip_notes = _candidate_artifact_paths(target, legacy)
    result.notes.extend(skip_notes)
    for path in to_archive:
        _archive_move(target, path, result, dry_run=dry_run)
    for path in left_in_place:
        result.left_in_place.append(path.relative_to(target).as_posix())

    # 2. hooks --------------------------------------------------------------------------------
    _slim_claude_settings(target / CLAUDE_SETTINGS_RELPATH, target, result, dry_run=dry_run)
    if home_settings:
        # THE one that actually fires. Every hook writer in the framework targets
        # `~/.claude/settings.json`; the target-local file is only ever READ, as a detection
        # fallback. A migration that cleaned only the project directory would remove nothing the
        # agent can feel -- the session-start directive wall, the latest-code nag on seven tool
        # matchers and the Stop gate would all still run -- and would report success for it.
        _slim_claude_settings(home_settings, target, result, dry_run=dry_run)

    hooks_dir = _git_hooks_dir(target)
    if hooks_dir is not None:
        for hook in sorted(hooks_dir.iterdir()):
            if not _git_hook_is_tautline(hook):
                continue
            result.removed_git_hooks.append(hook.name)
            displaced = hooks_dir / f"{hook.name}{DISPLACED_HOOK_SUFFIX}"
            if displaced.is_file():
                # The hook this project had BEFORE Tautline, which the installer moved aside.
                # Reported, never auto-restored: silently re-arming an executable that runs on
                # every commit -- one the user may not have looked at in a year -- is a worse
                # surprise than a line of output naming the exact command to run.
                result.notes.append(
                    f"your pre-Tautline {hook.name} is still at "
                    f"{_display(displaced, target)}"
                    f" -- restore it with: mv '{displaced}' '{hook}'"
                )
            if dry_run:
                continue
            # Copied into the archive before removal: the hook is framework-generated, but a
            # migration that can be rolled back completely is worth one kilobyte.
            archived = _unique_destination(_archive_root(target) / "git-hooks" / hook.name)
            archived.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(hook), str(archived))
            hook.unlink()

    # 3. the config ----------------------------------------------------------------------------
    lean_text = json.dumps(lean_cfg, indent=2, sort_keys=True) + "\n"
    current_cfg = adapter_path.read_text(encoding="utf-8") if adapter_path.is_file() else None
    if current_cfg != lean_text:
        # Backed up only when there is a pre-lean config to lose. On a second run the texts match
        # and nothing happens at all, which is the property that stops a re-run from overwriting
        # the first run's backup with post-migration content.
        if current_cfg is not None and not already_lean:
            _archive_copy(target, adapter_path, result, dry_run=dry_run)
        result.rewrote.append(adapter_path.name)
        if not dry_run:
            adapter_path.write_text(lean_text, encoding="utf-8")

    # 4. the adapter ---------------------------------------------------------------------------
    try:
        adapter_files = lean_adapter_files(lean_cfg)
    except LeanAdapterBudgetExceeded as exc:
        # A FAILURE, not a silent short-write: every other step still runs (archiving, hooks), but
        # CLAUDE.md/AGENTS.md are left exactly as they were rather than written over-cap. `slim`
        # exits nonzero and the FAILED section names the field to shorten.
        result.failed.append(str(exc))
        adapter_files = {}
    for rel, content in adapter_files.items():
        dest = target / rel
        current = dest.read_text(encoding="utf-8") if dest.is_file() else None
        if current == content:
            continue
        proposed = target / f"{rel}{PROPOSED_ADAPTER_SUFFIX}"
        if current is not None and not current.startswith(GENERATED_HEADER):
            # Propose once during migration. Once the project is lean, a handwritten file is
            # the user's choice; recreating a deleted proposal dirties every subsequent run.
            if already_lean:
                continue
            # HAND-AUTHORED. The `<!-- GENERATED -->` header is what the renderer stamps on a file
            # it owns; without it this is prose a person wrote, and overwriting it is the one
            # unrecoverable-feeling thing a migration can do even when git could undo it. Write the
            # lean adapter beside it and say so.
            if proposed.is_file() and proposed.read_text(encoding="utf-8") == content:
                continue
            result.proposed.append((rel, f"{rel}{PROPOSED_ADAPTER_SUFFIX}"))
            if not dry_run:
                proposed.write_text(content, encoding="utf-8")
            continue
        if current is not None:
            _archive_copy(target, dest, result, dry_run=dry_run)
        result.rewrote.append(rel)
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")

    return result


def format_slim_summary(target: Path, result: SlimResult, *, dry_run: bool) -> list[str]:
    prefix = "would " if dry_run else ""
    lines = [f"TAUTLINE SLIM - {target}" + ("  [dry-run: nothing was changed]" if dry_run else "")]
    if not result.changed:
        lines.append("  already lean - no changes")
        lines.append("  (running slim again is a no-op by design)")
        for rel in result.left_in_place:
            lines.append(f"  keep      {rel} (untracked lane scratch; nothing writes it now)")
        lines.append(f"  next      {PLUGIN_ENABLEMENT_HINT}")
        lines.extend(_failure_lines(result))
        return lines
    for source, dest in result.moved:
        lines.append(f"  {prefix}archive   {source} -> {dest}")
    for source, dest in result.backed_up:
        lines.append(f"  {prefix}back up   {source} -> {dest}")
    for command in result.removed_hooks:
        lines.append(f"  {prefix}unhook    {command}")
    for name in result.removed_git_hooks:
        lines.append(
            f"  {prefix}unhook    .git/hooks/{name} "
            f"(copy kept in {ARCHIVE_DIRNAME}/git-hooks/)"
        )
    for rel in result.rewrote:
        lines.append(f"  {prefix}rewrite   {rel}")
    for rel, dest in result.proposed:
        lines.append(
            f"  {prefix}propose   {dest} (kept {rel}: it is hand-authored, not generated -- "
            "review the proposal and move it into place yourself)"
        )
    for rel in result.left_in_place:
        lines.append(f"  keep      {rel} (untracked lane scratch; nothing writes it now)")
    for note in result.notes:
        lines.append(f"  note      {note}")
    lines.append("")
    lines.append(
        "  rollback: git can restore everything; the archive holds the rest "
        f"({ARCHIVE_DIRNAME}/)."
    )
    if not dry_run:
        lines.append("  review the archive, then commit the migration.")
    lines.append(f"  next      {PLUGIN_ENABLEMENT_HINT}")
    lines.extend(_failure_lines(result))
    return lines


def _failure_lines(result: SlimResult) -> list[str]:
    """The FAILED section. Separated from the change list and printed last, because a migration
    that half-worked has to end on what did NOT happen -- and `slim_command` exits nonzero when
    this is non-empty, so a script cannot read a partial migration as a whole one."""
    if not result.failed:
        return []
    lines = ["", "  FAILED - these were NOT migrated:"]
    lines.extend(f"    - {entry}" for entry in result.failed)
    return lines


def slim_command(args: argparse.Namespace) -> int:
    target = Path(getattr(args, "target", ".") or ".").expanduser()
    dry_run = bool(getattr(args, "dry_run", False))
    home_settings: Path | None = Path.home() / ".claude" / "settings.json"
    if getattr(args, "keep_agent_hooks", False):
        home_settings = None
    result = slim_project(target, dry_run=dry_run, home_settings=home_settings)
    for line in format_slim_summary(target.resolve(), result, dry_run=dry_run):
        print(line)
    # Nonzero when anything was left un-migrated. The alternative -- a success exit beside a FAILED
    # section -- is how a control comes to report success while doing nothing.
    return 1 if result.failed else 0


# --------------------------------------------------------------------------------------------
# lane-status interop
# --------------------------------------------------------------------------------------------


def legacy_lane_view(cfg: dict) -> dict:
    """Present a lean adapter in the shape `lane-status` reads.

    `lane-status` is advisory and report-only, and it is on the KEEP list -- so it has to keep
    ANSWERING on a lean project, not degrade to "could not be computed". A report that goes quiet
    when the config changes shape is a control that reports nothing.
    """
    project = cfg.get("project") or {}
    branch = cfg.get("integrationBranch", DEFAULT_INTEGRATION_BRANCH)
    return {
        "project": project.get("name", ""),
        "repo": project.get("repo", ""),
        "latestCode": {"base": branch, "remote": "origin"},
        "laneStatus": {"integrationBranch": branch},
        "workCoordination": cfg.get("workCoordination", False),
    }


def load_project_lean_aware(marker_path: Path, legacy_loader):
    """`load_project` for callers that must also understand lean adapters.

    A lean adapter fails 1.x schema validation by design (it has none of the required ceremony
    keys), so a caller that only knows `load_project` sees a lean project as a broken one.
    """
    cfg = load_lean_config(marker_path)
    if cfg is not None:
        return legacy_lane_view(cfg)
    return legacy_loader(marker_path)


# --------------------------------------------------------------------------------------------
# continuity handoffs (Track H)
# --------------------------------------------------------------------------------------------

# Read only enough to find the `## Doing:` line near the top of a one-page file. A pathological
# huge file degrades to "no doing text" rather than costing `lane-status` its collection budget.
_HANDOFF_READ_CAP_BYTES = 8192

_HANDOFF_DOING_RE = re.compile(r"^##\s*Doing:\s*(.*)$", re.MULTILINE)


def _handoffs_declared(root: Path) -> bool:
    """True when THIS project's own lean adapter has `"handoffs": true`.

    Legacy 1.x adapters have no such key -- and are not consulted here -- because a project on
    the old profile still gets the freshness line for free the moment it writes the file; see
    `handoff_status_line`, whose file-presence branch runs regardless of adapter flavor.
    """
    lean_path = find_lean_adapter(root)
    if lean_path is None:
        return False
    cfg = load_lean_config(lean_path)
    return bool(cfg) and cfg.get("handoffs") is True


def _handoff_age(elapsed_seconds: float) -> str:
    """A compact age string in the same s/m/h/d/w vocabulary `util.parse_duration_seconds` reads,
    so a human who has seen one has seen the other."""
    whole = max(0, int(elapsed_seconds))
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if whole >= size:
            return f"{whole // size}{unit}"
    return f"{whole}s"


def handoff_status_line(root: Path, *, now: float | None = None) -> str | None:
    """The `lane-status` freshness line for `HANDOFF_RELPATH`, or None when this project has not
    opted into handoffs AND no handoff file exists either -- so a project that never turned the
    feature on sees nothing new.

    Returns the line UNSANITIZED: `HANDOFF.md` is agent-written free text, and this module never
    prints -- the caller (`cli.py`'s `lane_status`) owns output sanitization for everything it
    puts in a SessionStart report, the same as every other value that report prints.

    A symlinked leaf, or a symlinked `.ai-continuity/` parent, is treated as ABSENT before this
    ever stats or opens anything. This runs unconditionally on file PRESENCE from a SessionStart
    hook (`cli.py`'s `lane_status`), so a cloned repository that ships
    `.ai-continuity/HANDOFF.md` symlinked to an arbitrary path -- `~/.ssh/id_rsa`, say -- would
    otherwise turn opening the session into an existence/mtime oracle for that path, plus up to
    200 chars of its content if a `## Doing:`-shaped line lands in the first 8KB. `_inside_target`
    resolves the whole chain, so it alone catches an escaping parent directory; `is_symlink()`
    additionally refuses a leaf symlink that resolves back INSIDE the repo, which is not a shape
    this feature ever writes on its own.
    """
    handoff_path = root / HANDOFF_RELPATH
    try:
        if handoff_path.is_symlink() or not _inside_target(handoff_path, root):
            raise OSError
        if not handoff_path.is_file():
            raise OSError
        mtime = handoff_path.stat().st_mtime
    except OSError:
        return "handoff: none" if _handoffs_declared(root) else None

    doing = ""
    try:
        with handoff_path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_HANDOFF_READ_CAP_BYTES)
        match = _HANDOFF_DOING_RE.search(head)
        if match:
            doing = match.group(1).strip()
    except OSError:
        pass

    moment = time.time() if now is None else now
    age = _handoff_age(moment - mtime)
    return f"handoff: {age} old — {doing}" if doing else f"handoff: {age} old"


# --------------------------------------------------------------------------------------------
# validation report -- shared by `validate-adapter` (cli.py) and `init`, below
# --------------------------------------------------------------------------------------------


def lean_validation_report(path_label: str, errors: list[str]) -> list[str]:
    """The exact lines a lean config's validation prints. `validate-adapter` and `init` call this
    one formatter so a config that fails one fails the other with byte-identical wording -- "the
    same path" the two are supposed to share."""
    if not errors:
        return [f"adapter {path_label} matches the lean-1 schema"]
    lines = [f"adapter {path_label} has {len(errors)} schema violation(s):"]
    lines.extend(f"  - {err}" for err in errors)
    return lines


# --------------------------------------------------------------------------------------------
# init: the setup interview
# --------------------------------------------------------------------------------------------
#
# `slim` MIGRATES an existing 1.x adapter; `init` has no ceremony predecessor to translate -- it
# is the first adapter this project has ever had. So it asks for exactly the facts the lean-1
# schema and `render_lean_adapter` need and nothing else: identity (name, repo), the integration
# branch, the test gate, where the backlog lives, whether continuity handoffs are on, and up to
# three project rules. <=8 questions, ever, regardless of which backlog provider is chosen -- see
# `_ask_backlog_fields`, which asks exactly one follow-up whatever the provider.
#
# Every question has a flag, so an agent can run this non-interactively; `--yes` accepts the
# prefilled default for whichever questions were not answered by a flag. NO SYNC: like `backlog`
# and `slim`, this writes once, on an explicit invocation, and nothing here runs again on its own.

INIT_NUDGE_LINE = "no Tautline config here yet -- run `tautline init` to set one up"


def _init_git(target: Path, *args: str) -> str:
    proc = _git(target, *args)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _default_project_name(target: Path, existing: dict | None) -> str:
    if existing:
        name = (existing.get("project") or {}).get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return target.resolve().name or "project"


# Same two patterns `gitutil.infer_repo_slug` uses. Not imported from there: this module does not
# depend on the rest of the package (see the module docstring), and the pattern is three lines.
_REPO_SLUG_PATTERNS = (
    re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$"),
    re.compile(r"(?P<owner>[^/:]+)/(?P<repo>[^/.]+)(?:\.git)?$"),
)


def _default_repo(target: Path, existing: dict | None) -> str:
    if existing:
        repo = (existing.get("project") or {}).get("repo")
        if isinstance(repo, str) and repo.strip():
            return repo.strip()
    remote = _init_git(target, "config", "--get", "remote.origin.url")
    if not remote:
        return ""
    for pattern in _REPO_SLUG_PATTERNS:
        match = pattern.search(remote)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    return ""


def _default_branch(target: Path, existing: dict | None) -> str:
    if existing:
        branch = existing.get("integrationBranch")
        if isinstance(branch, str) and branch.strip():
            return branch.strip()
    head_ref = _init_git(target, "symbolic-ref", "refs/remotes/origin/HEAD")
    prefix = "refs/remotes/origin/"
    if head_ref.startswith(prefix):
        return head_ref[len(prefix) :]
    return _init_git(target, "branch", "--show-current") or DEFAULT_INTEGRATION_BRANCH


def _default_test_command(target: Path, existing: dict | None) -> str:
    if existing:
        cmd = (existing.get("commands") or {}).get("test")
        if isinstance(cmd, str) and cmd.strip():
            return cmd.strip()
    return DEFAULT_TEST_COMMAND


def _default_backlog(existing: dict | None) -> dict:
    if existing and isinstance(existing.get("backlog"), dict):
        return dict(existing["backlog"])
    return {"provider": "local"}


def _default_rules(existing: dict | None) -> list[str]:
    if existing and isinstance(existing.get("projectRules"), list):
        return [str(rule).strip() for rule in existing["projectRules"] if str(rule).strip()][:3]
    return []


def _ask(prompt: str, default: str, *, yes: bool) -> str:
    if yes:
        return default
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ")
    return raw.strip() or default


def _ask_choice(prompt: str, default: str, choices: tuple[str, ...], *, yes: bool) -> str:
    if yes:
        return default
    while True:
        raw = input(f"{prompt} ({'/'.join(choices)}) [{default}]: ").strip().lower()
        if not raw:
            return default
        if raw in choices:
            return raw
        print(f"  please answer one of: {', '.join(choices)}")


def _ask_bool(prompt: str, default: bool, *, yes: bool) -> bool:
    if yes:
        return default
    marker = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{marker}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _ask_rules(default: list[str], *, yes: bool) -> list[str]:
    if yes:
        return default
    print("Project rules an agent would otherwise get wrong -- 0-3 short lines, blank to stop:")
    if default:
        print(f"  (current: {' | '.join(default)} -- retype what you want to keep)")
    rules: list[str] = []
    while len(rules) < 3:
        raw = input(f"  rule {len(rules) + 1} (blank to stop): ").strip()
        if not raw:
            break
        rules.append(raw)
    return rules


def _ask_backlog_fields(
    provider: str,
    project_repo: str,
    existing_backlog: dict,
    flags: argparse.Namespace,
    *,
    yes: bool,
) -> dict:
    """The ONE follow-up question `init` asks about the backlog, whatever provider was chosen --
    this is what keeps the interview at <=8 questions regardless of which provider that is."""
    fields: dict[str, str] = {}
    if provider == "local":
        default_path = str(existing_backlog.get("path") or DEFAULT_BACKLOG_PATH)
        path = flags.backlog_path
        if path is None:
            path = _ask("Queue file path", default_path, yes=yes)
        if path and path != DEFAULT_BACKLOG_PATH:
            fields["path"] = path
    elif provider == "github":
        default_repo = str(existing_backlog.get("repo") or project_repo)
        repo = flags.backlog_repo
        if repo is None:
            repo = _ask("Backlog repo (owner/name)", default_repo, yes=yes)
        if repo:
            fields["repo"] = repo
        label = flags.backlog_label
        if label is None:
            label = str(existing_backlog.get("label") or DEFAULT_BACKLOG_LABEL)
        if label and label != DEFAULT_BACKLOG_LABEL:
            fields["label"] = label
    elif provider == "jira":
        if flags.backlog_site is not None or flags.backlog_project is not None:
            site = flags.backlog_site or ""
            project = flags.backlog_project or ""
        else:
            default_site = str(existing_backlog.get("site") or "")
            default_project = str(existing_backlog.get("project") or "")
            default_pair = (
                f"{default_site},{default_project}" if (default_site or default_project) else ""
            )
            raw = _ask(
                "Jira site and project key, comma-separated "
                "(e.g. https://your-domain.atlassian.net,PROJ)",
                default_pair,
                yes=yes,
            )
            site, _, project = raw.partition(",")
            site, project = site.strip(), project.strip()
        if site:
            fields["site"] = site
        if project:
            fields["project"] = project
        board = flags.backlog_board
        if board is None:
            board = str(existing_backlog.get("board") or "")
        if board:
            fields["board"] = board
    return fields


def _run_interview(target: Path, flags: argparse.Namespace, existing: dict | None) -> dict:
    """Ask (or read from flags) the <=8 questions, in order. Returns raw answers; unaffected by
    what shape the final config takes -- `lean_config_from_answers` decides that."""
    yes = bool(getattr(flags, "yes", False))
    name = flags.name or _ask("Project name", _default_project_name(target, existing), yes=yes)
    repo = (
        flags.repo
        if flags.repo is not None
        else _ask("Repo (owner/name)", _default_repo(target, existing), yes=yes)
    )
    branch = flags.branch or _ask(
        "Integration branch", _default_branch(target, existing), yes=yes
    )
    test_cmd = flags.test_cmd or _ask(
        "Test command", _default_test_command(target, existing), yes=yes
    )
    existing_backlog = _default_backlog(existing)
    default_provider = str(existing_backlog.get("provider") or "local")
    if default_provider not in BACKLOG_PROVIDERS:
        default_provider = "local"
    provider = flags.backlog or _ask_choice(
        "Where does your backlog live?", default_provider, BACKLOG_PROVIDERS, yes=yes
    )
    backlog_fields = _ask_backlog_fields(provider, repo, existing_backlog, flags, yes=yes)
    # Confirm line, echoed right after the answer that decides it -- one call into
    # `_backlog_norm`, the SAME function that renders the adapter's own backlog norm, so this
    # echo can never say something the adapter itself does not (or drift from it later).
    print(_backlog_norm({"backlog": {"provider": provider, **backlog_fields}}))
    if flags.handoffs is not None:
        handoffs = bool(flags.handoffs)
    else:
        handoffs = _ask_bool(
            "Continuity handoffs on?", bool((existing or {}).get("handoffs", False)), yes=yes
        )
    print(
        "Local work declarations are advisory; `tautline work status` shows peer scope. "
        "New projects enable this guidance; --no-work-coordination disables it."
    )
    if flags.rules is not None:
        # FAIL LOUD rather than silently keeping only the first 3: `--rule` is explicit user
        # intent, and a config quietly missing the 4th rule is a control that reports success
        # while dropping what it was asked to do. The interactive loop below never has this
        # failure mode -- it simply stops asking after 3.
        if len(flags.rules) > 3:
            raise SystemExit(
                f"init: --rule was given {len(flags.rules)} times; projectRules holds at most 3"
            )
        rules = flags.rules
    else:
        rules = _ask_rules(_default_rules(existing), yes=yes)
    return {
        "name": name,
        "repo": repo,
        "branch": branch,
        "test_cmd": test_cmd,
        "backlog_provider": provider,
        "backlog_fields": backlog_fields,
        "handoffs": handoffs,
        "work_coordination": (
            getattr(flags, "work_coordination", None)
            if getattr(flags, "work_coordination", None) is not None
            else (existing.get("workCoordination", False) if existing else True)
        ),
        "rules": [str(rule).strip() for rule in rules if str(rule).strip()][:3],
    }


def lean_config_from_answers(answers: dict) -> dict:
    """The interview's answers, projected into a lean-1 config.

    `backlog` is always written, even for `local` with no path override: the schema treats an
    ABSENT key as meaning local-default too (for a project that never asked, e.g. one `slim`
    migrated from a 1.x adapter with no such concept), but `init` just asked the question and
    got a real answer, so it records it. Writing it is also what makes the answer OBSERVABLE:
    `_backlog_norm` below only renders its "this is where the backlog lives, do not create a
    second one" line when `backlog` is present, so omitting it for the most common answer would
    make the whole question a no-op. `handoffs` left off and no rules typed still write no key --
    those defaults have no comparable render-path dependency on the key being present."""
    cfg: dict = {
        "$schema": "https://tautline.dev/schemas/adapter/lean-1.json",
        "schemaVersion": LEAN_SCHEMA_VERSION,
        "project": {"name": answers["name"] or "project"},
        "integrationBranch": answers["branch"] or DEFAULT_INTEGRATION_BRANCH,
        "commands": {"test": answers["test_cmd"] or DEFAULT_TEST_COMMAND},
    }
    if answers["repo"]:
        cfg["project"]["repo"] = answers["repo"]
    provider = answers["backlog_provider"] or "local"
    fields = dict(answers["backlog_fields"])
    cfg["backlog"] = {"provider": provider, **fields}
    cfg["workCoordination"] = answers.get("work_coordination", True)
    if answers["handoffs"]:
        cfg["handoffs"] = True
    if answers["rules"]:
        cfg["projectRules"] = list(answers["rules"])
    return cfg


def _backlog_source_of_truth_label(cfg: dict) -> str:
    backlog = cfg.get("backlog")
    provider = backlog["provider"] if isinstance(backlog, dict) else "local"
    if provider == "github":
        repo = backlog.get("repo") or ""
        return f"GitHub issues ({repo})" if repo else "GitHub issues"
    if provider == "jira":
        project = backlog.get("project") or ""
        return f"Jira ({project})" if project else "Jira"
    path = backlog.get("path") if isinstance(backlog, dict) else ""
    return f"the local queue ({path or DEFAULT_BACKLOG_PATH})"


def _what_next_lines(cfg: dict) -> list[str]:
    """The 6-line "what next". `tautline backlog add` stays first regardless of provider -- the
    backlog is the source of truth for what to work on next, whichever of the three it is.

    Track G: goal-advice salvage. Line 6 reuses PLUGIN_ENABLEMENT_HINT rather than a second
    hand-written string, so `init` and `slim` -- the two commands that leave a project without the
    plugin enabled -- point at the exact same next step and cannot drift apart."""
    return [
        "what next:",
        "  1. add your first one-page spec: tautline backlog add",
        f"  2. it lands in {_backlog_source_of_truth_label(cfg)} -- `tautline backlog list` "
        "shows what is next",
        "  3. the process: take the top backlog item; failing test first, small diffs; one "
        "adversarial review before merge; never commit secrets",
        "  4. the runbook: CLAUDE.md (Claude) / AGENTS.md (Codex) at the repo root -- re-run "
        "`tautline init --target . --force` anytime to reconfigure",
        "  5. validate anytime with: tautline validate-adapter " + ADAPTER_FILENAMES[0],
        f"  6. {PLUGIN_ENABLEMENT_HINT}",
    ]


# The suffix a `--force` run gives a stranded LEGACY-named adapter (`.minervit-ai-delivery.json`)
# once it writes `.tautline.json` beside it. Same family as `slim`'s own `.before-minervit` /
# `.before-tautline-slim` markers -- "moved aside, never deleted, name says by what and to what".
LEGACY_INIT_SUFFIX = ".before-tautline-init"


def init_command(args: argparse.Namespace) -> int:
    target = Path(getattr(args, "target", ".") or ".").expanduser().resolve()
    if not target.is_dir():
        raise SystemExit(f"init: {target} is not a directory")
    force = bool(getattr(args, "force", False))
    existing_path = next(
        (target / name for name in ADAPTER_FILENAMES if (target / name).is_file()), None
    )
    existing_cfg = load_lean_config(existing_path) if existing_path is not None else None
    # Only ever the LEGACY name: `.tautline.json` is where `init` writes, so a `--force` re-run
    # that found `.tautline.json` is overwriting the file it is about to rewrite anyway, not
    # stranding a second one beside it.
    legacy_to_archive = (
        existing_path
        if existing_path is not None and existing_path.name != ADAPTER_FILENAMES[0]
        else None
    )
    if existing_path is not None and not force:
        if existing_cfg is not None:
            hint = "your answers below will prefill from the current config"
        else:
            hint = (
                "it looks like a 1.x adapter -- `tautline slim --target "
                f"{target}` migrates it without losing your rules, and is almost certainly what "
                "you want instead"
            )
        raise SystemExit(
            f"init: {existing_path} already exists ({hint}). Pass --force to overwrite it anyway."
        )

    try:
        answers = _run_interview(target, args, existing_cfg)
    except (EOFError, KeyboardInterrupt):
        # Every `_ask*` helper calls the builtin `input()` directly, so a closed stdin (Ctrl-D,
        # or a scripted run that supplies fewer answers than questions asked) or an interrupt
        # (Ctrl-C) would otherwise surface as a raw traceback. Nothing is written before this
        # point -- `answers` does not exist yet -- so the abort is already clean; this only
        # makes it a clean MESSAGE too.
        raise SystemExit("init: aborted (no input; nothing was written)") from None
    cfg = lean_config_from_answers(answers)

    config_path = target / ADAPTER_FILENAMES[0]
    config_path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {config_path}")

    # Validate the file that now sits on disk -- not the in-memory dict -- on the SAME formatter
    # `validate-adapter` uses, so this is genuinely "the same path", not a lookalike. Should never
    # fire (the interview only ever produces schema-legal shapes); it is the fail-loud net the
    # spec asks for, not the primary defense.
    written = json.loads(config_path.read_text(encoding="utf-8"))
    errors = lean_config_errors(written)
    for line in lean_validation_report(str(config_path), errors):
        print(line, file=sys.stderr if errors else sys.stdout)
    if errors:
        raise SystemExit(1)

    if legacy_to_archive is not None:
        # Never silently strand it: `--force` just wrote `.tautline.json` beside a 1.x-named
        # adapter that `tautline slim` would have MIGRATED (carrying its rules across). Moving it
        # aside -- never deleting -- means both the new config and the old one's content survive,
        # and the note says exactly what to do if the old content still matters.
        archived_legacy = _unique_destination(
            legacy_to_archive.with_name(legacy_to_archive.name + LEGACY_INIT_SUFFIX)
        )
        legacy_to_archive.rename(archived_legacy)
        print(
            f"archived {legacy_to_archive} -> {archived_legacy} (superseded by {config_path}; "
            "if it had rules or settings worth keeping, `tautline slim` next time migrates them "
            "instead of starting fresh)"
        )

    try:
        written_adapters, proposed_adapters = write_lean_adapter_files(target, cfg)
    except LeanAdapterBudgetExceeded as exc:
        # `config_path` above is ALREADY written and schema-valid at this point -- only the
        # CLAUDE.md/AGENTS.md render is the problem, so the recovery is a re-render, not a redo of
        # the interview. Actionable, on the failed path (nonzero exit), never a written over-cap
        # file.
        print(f"init: {exc}", file=sys.stderr)
        print(
            f"{config_path} was written and is schema-valid; only the CLAUDE.md/AGENTS.md render "
            "failed. Shorten the field named above, then re-run `tautline init --target . "
            "--force` (or hand-edit the config and run `tautline slim --target .` to re-render).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    for rel in written_adapters:
        print(f"wrote {target / rel}")
    for rel, dest in proposed_adapters:
        print(
            f"proposed {target / dest} (kept {rel}: it is hand-authored, not generated -- "
            "review the proposal and move it into place yourself)"
        )

    for line in _what_next_lines(cfg):
        print(line)
    return 0
