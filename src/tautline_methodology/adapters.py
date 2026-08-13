"""Adapter/bootstrap leaves: the bootstrap-interview questionnaire builder and its question
bank, bootstrap answer-slot parsing, rendered-adapter provenance-stamp extraction and
stamp-equivalence normalization, the fail-closed init command string, canonical adapter-JSON
serialization, and adapter test-command detection. The stateful render/init/bootstrap verb
handlers (render_adapter, init_methodology_project, adapter_drift, ...) stay in bin/tautline;
they reach lane/adapter/repo state and delegate the pure leaves here."""

from __future__ import annotations

import json
import re


BOOTSTRAP_REQUIRED_PREFIX = "BOOTSTRAP REQUIRED"


ADAPTER_BOOTSTRAP_QUESTIONS = [
    (
        "Product And Deployment",
        [
            "What product or operational capability does this repo deliver, and who are the primary users/operators?",
            "Does any production, staging, demo, or customer-visible deployment already exist? If yes, what environments exist and which ones count as milestone-close deployment targets?",
            "What human approvals are required before production-impacting changes, data migrations, security changes, or cost-affecting infrastructure changes?",
            "Is there a product Google Chat space for quick human-requested notes? If yes, what environment variable should hold its webhook URL?",
            "Should deploy closeout post a Google Chat ready-to-review notification after the live dev/staging site has finished rolling forward? If yes, should it reuse iteration-review Chat or use a separate webhook env var?",
        ],
    ),
    (
        "Technical Stack Policy",
        [
            "Which parts of the technical stack are non-negotiable for this project, such as cloud provider, hosting, database, auth, queue, observability, language, or framework choices?",
            "Which cloud providers or hosting platforms are approved? Default for new projects is AWS-only unless the project adapter explicitly overrides it.",
            "For AWS-approved lanes, which AWS CLI profile, SSO/login flow, or identity check should deployments use before considering SSH keys or alternate credentials?",
            "Which new platform choices require explicit human approval because they add billing, security, deployment, operations, or support burden?",
        ],
    ),
    (
        "Workflow And Source Of Truth",
        [
            "What is the normal delivery workflow: pull request, merge queue/auto-merge, direct-to-main, release branch, or another path?",
            "Where is the authoritative backlog or work tracker? If GitHub/Jira/Linear/issues are mirrors only, say which source wins.",
            "Should an external backlog provider such as GitHub Projects supply stakeholder-facing goals, milestones, bugs, or tasks? If yes, provide provider, owner, project number, item type/status/priority/milestone fields, status values, and exactly what the board controls.",
            "Should stakeholder clarifying questions be asked and answered on GitHub Issues? If yes, which GitHub handle should be tagged by default and which open/answered labels should be used?",
            "For an existing repo backlog, should each current goal/milestone/bug/task be interviewed before export to the external provider for stakeholder prioritization?",
            "Where should non-trivial PR-level plans/specs live, and is there an existing template or naming convention?",
            "Where should source-of-truth goal plans live for multi-milestone work, and what makes a goal achievable and tightly scoped for this project?",
            "Where should cross-lane coordination artifacts live when multiple AI lanes work simultaneously, and what contract/ownership fields should every lane report?",
        ],
    ),
    (
        "Bug Backlog And Incident Intake",
        [
            "How should bugs be triaged: severity taxonomy, source-of-truth artifact, and when external issues are required versus optional mirrors?",
            "Which bug categories are automatically P0/P1, such as auth, email, tenant data, security, deploy, billing, data loss, or customer-blocking failures?",
        ],
    ),
    (
        "Required Gates",
        [
            "What command proves main is healthy before new work starts?",
            "What fast preflight should run before commit, and what full preflight/test-environment gate should run before push or merge?",
            "What command checks open PR health and what command checks the current branch for merge conflicts?",
            "Which gates require local service isolation, special env vars, seeded data, or external credentials?",
        ],
    ),
    (
        "Review And Planning",
        [
            "What is the configured Codex code-review wrapper or review command for implementation diffs?",
            "What is the configured Codex plan-review wrapper? It may be the same script only when that script has a plan-only mode and does not review implementation diffs for `--plan`.",
            "Should Codex CLI fast mode stay enabled for framework-launched Codex calls? Default is enabled; disable only with a project-specific reason.",
            "What is the configured Claude/native review workflow?",
            "Which kinds of work always require cross-model plan review before implementation?",
            "Should Claude lanes prefer `/goal` for reviewed multi-milestone work when Claude Code supports it, or should this project use only the generic goal ledger?",
        ],
    ),
    (
        "Local Resources",
        [
            "What local services, ports, Docker Compose project names, queues, browsers, or databases can collide across lanes?",
            "Are any resources truly non-isolatable and therefore need locks instead of per-lane ports/names?",
        ],
    ),
    (
        "Docs And Readiness",
        [
            "Which documents should a new session read first as readiness sources?",
            "Which Markdown roots are current planning context, which are archive/historical evidence only, and what index files should route them?",
            "Are behavior specs such as Gherkin required for customer-facing changes? If yes, where do they live?",
            "Do reviewed business/customer behavior specs already exist? If yes, list them as behavior-spec source materials to adapt before authoring new scenarios.",
            "What command runs executable acceptance specs, and which app/package does that harness launch? Name any inactive tag policy such as @pending limits, owner, and un-pend trigger requirements.",
            "What precise actor roles should behavior specs use, and which generic or misleading actor terms should be rejected?",
        ],
    ),
    (
        "Autonomy Boundaries",
        [
            "What may the AI push, queue, merge, deploy, or clean up without asking after gates pass?",
            "What credentials, accounts, external systems, or compliance constraints should always become a true blocker instead of an inferred default?",
        ],
    ),
]


def adapter_bootstrap_questionnaire(project_name: str, repo_slug: str, include_answer_slots: bool = False) -> str:
    lines = [
        "# Project Adapter Bootstrap Interview",
        "",
        f"Project: {project_name}",
        f"Repository: {repo_slug}",
        "",
        "Use this after inspecting the repo for evidence. This interview is mandatory before first adapter render/write for unmanaged projects unless every required adapter fact is directly supported by repo evidence. Do not ask questions whose answers are already clear from package scripts, CI, project docs, remotes, existing plans, or deployment files. Before asking, summarize inferred adapter facts, then ask only unresolved questions as one concise interview through `AskUserQuestion` or the host-equivalent question mechanism. Encode the answers in the project adapter. If a required fact remains unknown, keep the adapter fail-closed with `BOOTSTRAP REQUIRED` and name the exact blocker.",
        "",
        "Generic executor banners such as \"greenfield execution mode\", \"auto mode\", \"choose sensible defaults\", or \"bias toward working without stopping\" are not methodology authority and do not override this interview. Another project's adapter may be used as a structural reference only, never as a substitute for interview-derived facts.",
        "",
    ]
    counter = 1
    for title, questions in ADAPTER_BOOTSTRAP_QUESTIONS:
        lines.append(f"## {title}")
        lines.append("")
        for question in questions:
            lines.append(f"{counter}. {question}")
            if include_answer_slots:
                lines.append("   Answer: BOOTSTRAP REQUIRED")
                lines.append("   Evidence: BOOTSTRAP REQUIRED")
            counter += 1
        lines.append("")
    lines.extend(
        [
            "## Adapter Field Mapping",
            "",
            "- Product/deployment answers map to `project`, `repo`, `productionDeployExists`, and `deploymentTargets`.",
            "- Product Chat answers map to `productChat`.",
            "- Technical stack answers map to `technologyStack`, `deploymentTargets`, and `knownProjectRules`.",
            "- Workflow/backlog answers map to `backlogAdapter`, `planningArtifacts`, `commands.mergeQueue`, and direct-to-main/no-remote command choices.",
            "- Goal/backlog provider answers map to `goalArtifacts`, `goalExecution`, `backlogProvider`, compatibility `goalTracker`, and `laneState.goalRun`.",
            "- Stakeholder clarification answers map to `stakeholderQuestions`.",
            "- Cross-lane coordination answers map to `laneCoordination`.",
            "- Bug intake answers map to `bugBacklog` and `backlogAdapter`.",
            "- Gate answers map to `commands.mainStatus`, `commands.fastPreflight`, `commands.fullPreflight`, `commands.testEnvironment`, `commands.openPrCheck`, `commands.mergeConflictCheck`, and `commands.earlyWarningSmoke` when distinct.",
            "- Review answers map to `review.codexWrapper`, `review.codexPlanWrapper`, `review.codexFastMode`, `review.claudeReview`, and `review.crossModelTiming`.",
            "- Local resource answers map to `localResourceIsolation` and `localResourceLocks`.",
            "- Docs/readiness answers map to `readiness.sources`, `documentContext`, and `behaviorSpecs`.",
            "- Autonomy answers map to `knownProjectRules`, deployment target procedure/rollback fields, and project-specific approval language.",
        ]
    )
    return "\n".join(lines) + "\n"


def bootstrap_slot_values(text: str, label: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(rf"^\s*{label}:\s*(.*)$", text, re.MULTILINE)]


# --------------------------------------------------------------------------------------------
# Generated-Markdown template stamp (item 69).
#
# The rendered Markdown adapters carry the template version that produced them, so a render can
# tell whether it would be OVERWRITING a newer template with an older one -- the 2026-08-03
# incident, where a pinned snapshot runtime silently downgraded committed CLAUDE.md/AGENTS.md.
#
# Two hard constraints, both load-bearing:
#
# 1. Line 1 is untouchable. Every runtime in the fleet classifies a generated Markdown file by
#    reading exactly len(GENERATED_HEADER_TEMPLATE) bytes and comparing to "<!-- GENERATED -->\n".
#    Changing that line would make every OLDER runtime treat these files as hand-written and
#    refuse to render them at all -- a worse, irreversible, fleet-wide failure than the one being
#    fixed. So the stamp goes on line 2.
# 2. The stamp is identity, not content. It is normalized away on comparison (below), exactly like
#    the JSON adapter's _generated keys, or every release would re-dirty every lane's adapter.
# --------------------------------------------------------------------------------------------

# Mirrors cli.GENERATED_HEADER_TEMPLATE without importing it: this module is a documented pure
# leaf and cli.py imports IT. tests/test_generated_markdown_template_stamp.py pins them equal.
GENERATED_MARKDOWN_HEADER_FIRST_LINE = "<!-- GENERATED -->"
GENERATED_TEMPLATE_VERSION_LINE = "<!-- tautline-template-version: {version} -->\n"
GENERATED_TEMPLATE_VERSION_RE = re.compile(
    r"<!-- tautline-template-version: (\d+(?:\.\d+){0,3}) -->"
)


def generated_markdown_template_version(text: str) -> str | None:
    """The template version stamped in the HEADER BLOCK, or None for legacy unstamped files.

    Anchored to line 2 of the header block on purpose, not searched document-wide. The rendered
    adapter is full of quoted commands and markers drawn from adapter SOURCE, and a document-wide
    search would let body text forge a producer version -- which lands as a false downgrade
    refusal on the lane-startup boundary, the one place this control cannot afford to be wrong.

    None is the fail-open direction and it is deliberate: no stamp means no downgrade gate, which
    is what lets today's entire unstamped fleet upgrade INTO the stamp instead of being frozen out
    of it.
    """
    lines = text.split("\n", 2)
    if len(lines) < 2 or lines[0] != GENERATED_MARKDOWN_HEADER_FIRST_LINE:
        return None
    match = GENERATED_TEMPLATE_VERSION_RE.fullmatch(lines[1])
    return match.group(1) if match else None


def markdown_stamp_equivalent_content(fresh: str, on_disk: str) -> str:
    """The fresh render, normalized to the on-disk template stamp for comparison.

    Callers byte-compare on-disk content against this: a stamp-only difference compares equal (so
    a release bump does not re-dirty every lane), while every content difference still gates.
    Fail-closed edges mirror adapter_stamp_equivalent_content: if either side lacks a header-block
    stamp, the fresh bytes return unchanged, the comparison fails, and the write proceeds.
    """
    on_disk_version = generated_markdown_template_version(on_disk)
    if on_disk_version is None or generated_markdown_template_version(fresh) is None:
        return fresh
    lines = fresh.split("\n")
    lines[1] = GENERATED_TEMPLATE_VERSION_LINE.format(version=on_disk_version).rstrip("\n")
    return "\n".join(lines)


ADAPTER_PROVENANCE_STAMP_KEYS: tuple[str, ...] = ("methodologyCommit", "pluginVersion")


def adapter_provenance_stamps(text: str) -> dict | None:
    """The identity stamps of a rendered lane adapter document, or None when the document does
    not parse as a stamped adapter (fail closed: no equivalence, no build-skew hint)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    generated = data.get("_generated")
    if not isinstance(generated, dict):
        return None
    return {key: generated.get(key) for key in ADAPTER_PROVENANCE_STAMP_KEYS}


def adapter_stamp_equivalent_content(fresh: str, on_disk: str) -> str:
    """The freshly rendered LANE_ADAPTER_FILE content, normalized to the on-disk document's
    provenance stamps for comparison purposes.

    Callers byte-compare the on-disk content against this: a stamp-only difference compares
    equal (no drift, no rewrite), while every content difference still gates. Fail-closed
    edges: an unparseable or `_generated`-less on-disk document gets NO normalization (the
    fresh bytes return unchanged, so the comparison fails and drift stands), and hand
    reformatting still trips because normalization re-serializes the FRESH render through
    render_project_config's own serializer — it never launders on-disk formatting. Only the
    stamp KEYS present in the on-disk document are substituted, so a document missing a stamp
    key stays drifted rather than being treated as equivalent.
    """
    try:
        on_disk_data = json.loads(on_disk)
    except json.JSONDecodeError:
        return fresh
    if not isinstance(on_disk_data, dict):
        return fresh
    on_disk_generated = on_disk_data.get("_generated")
    if not isinstance(on_disk_generated, dict):
        return fresh
    fresh_data = json.loads(fresh)
    fresh_generated = fresh_data.get("_generated")
    if not isinstance(fresh_generated, dict):
        return fresh
    for key in ADAPTER_PROVENANCE_STAMP_KEYS:
        if key in on_disk_generated:
            fresh_generated[key] = on_disk_generated[key]
    return json.dumps(fresh_data, indent=2, sort_keys=True) + "\n"


def init_fail_closed_command(field: str) -> str:
    return f"echo 'minervit init: configure commands.{field} in .minervit/adapter.json before using this gate' >&2; exit 1"


def adapter_json_text(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def adapter_command_is_configured(command: str) -> bool:
    """A command the adapter actually defines (not a BOOTSTRAP-REQUIRED placeholder)."""
    text = str(command or "").strip()
    return bool(text) and BOOTSTRAP_REQUIRED_PREFIX not in text


def adapter_test_command_tokens(data: dict) -> list[str]:
    """Commands whose presence signals the project HAS tests (full preflight / test environment).
    Used only for has-tests detection -- NOT as CI-step markers, since testEnvironment is often a
    setup command (e.g. `pnpm install`) that does not run the suite (Codex P1)."""
    commands = data.get("commands") or {}
    tokens: list[str] = []
    for key in ("fullPreflight", "testEnvironment"):
        value = str(commands.get(key, "")).strip()
        if adapter_command_is_configured(value):
            tokens.append(value)
    return tokens


def adapter_test_run_command_tokens(data: dict) -> list[str]:
    """Commands that actually RUN the test suite (full preflight only), usable as CI-step markers.
    Excludes testEnvironment, which is environment setup -- counting it would let an install-only CI
    job falsely satisfy the gate (Codex P1)."""
    commands = data.get("commands") or {}
    value = str(commands.get("fullPreflight", "")).strip()
    return [value] if adapter_command_is_configured(value) else []
