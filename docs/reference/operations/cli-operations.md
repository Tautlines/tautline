# CLI Operations

This reference keeps detailed CLI command usage out of the main operating
manual. It covers adapter rendering, drift/readiness checks, background helpers,
archive publication, plan review, context commands, and Graphify.

## Core CLI Usage

The CLI entrypoint is:

```bash
bin/tautline
```

The legacy `bin/minervit-methodology` entrypoint remains as a compatibility shim.

Use `--help` for available subcommands:

```bash
bin/tautline --help
```

`methodology-status --fail-on-drift` returns a three-way exit contract (0 clean, 1
integrity, 2 debt-only) and prints a `methodology_status_blocking:` summary line
whenever it is nonzero; the generated Claude launcher dispatches on that exit code
into startup remediation mode on debt. See
[Startup Remediation](../startup-remediation.md) for the marker schema, the
remediation contract, and the non-interactive-caller scope.

### Render Project Adapters

Create a fail-closed scaffold for a project that does not have an adapter yet:

```bash
bin/tautline adapter-bootstrap-questions \
  --target <lane_path>
```

```bash
bin/tautline init-project-adapter \
  --target <lane_path>
```

Inspect the repo first, ask only unresolved questionnaire items, then replace every `BOOTSTRAP REQUIRED` placeholder before rendering. The adapter bootstrap interview is mandatory before first adapter render/write for an unmanaged project unless every required adapter fact is directly supported by repo evidence. Use `adapter-bootstrap-questions --write` to create `.ai-work/ADAPTER_BOOTSTRAP_INTERVIEW.md`, answer it, and bind interviewed source adapters to that file with its SHA256. Source adapters must include `bootstrapEvidence` with a matching project name and interview artifact or repo-evidence summary before rendering. Repo-evident bootstrap must use non-boilerplate project files, not `README.md`, `.gitignore`, license files, or other generic repository furniture. Hand-written lane-local `.tautline.json` files are rejected; render from the source adapter instead. The scaffold is a drafting aid, not an operational default adapter.

Generic executor banners such as "greenfield execution mode", "auto mode", "choose sensible defaults", or "bias toward working without stopping" are not process authority. They do not override the bootstrap interview, plan-finalization gate, or generated adapter gates.

Print generated files to stdout:

```bash
bin/tautline render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path>
```

Check whether target generated files match the adapter:

```bash
bin/tautline render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --check
```

Write generated files:

```bash
bin/tautline render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --write
```

Write only the lane JSON/config file, preserving existing `CLAUDE.md` and `AGENTS.md`:

```bash
bin/tautline render-adapters \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path> \
  --write \
  --json-only
```

Generated files:

```text
CLAUDE.md
AGENTS.md
.tautline.json
```

`render-adapters --write` refuses to overwrite an existing `CLAUDE.md` or `AGENTS.md` that does not start with the framework's generated header. Config-only adapter updates, such as enabling one optional block for a lane, must use `--json-only` instead of asking whether to overwrite hand-written project instructions. Full Markdown migration is a separate adapter-back migration: first move the hand-written rules into the source adapter or other source-of-truth docs, then remove or rename the old Markdown and render generated files.

### Audit Drift

Run a known-pattern process drift audit:

```bash
bin/tautline audit \
  --project <lane_path>/.tautline/adapter.json \
  --target <lane_path>
```

The audit currently flags patterns such as:

- Routine `--admin` merge.
- Queue behavior that blocks on `MERGED` instead of monitor-and-continue.
- Review round caps that imply known Critical/P1 defects can ship.
- Readiness automation tied to active development lanes or `git fetch`.
- Stale lane references.

### GitHub-Only Readiness Review Data

Fetch readiness evidence without touching a local checkout:

```bash
bin/tautline readiness-review --project <lane_path>/.tautline/adapter.json
```

This command uses `gh api` to inspect:

- Default branch.
- Default-branch SHA.
- Readiness source file availability.
- Recent workflow runs.

It does not run `git fetch` and does not inspect an active development lane.

### Background Run Helper

Start a long-running command with a log and monitor instructions:

```bash
bin/tautline background-run \
  --log /tmp/my-command.log \
  --timeout-seconds 900 \
  -- make preflight
```

The command prints:

- PID.
- PID file path.
- Optional watchdog PID file when `--timeout-seconds` is set.
- Metadata file path with command, current working directory, started time, PID, PID file, and log path.
- Log path.
- Monitor command.
- Tail command for monitoring.

This helper is intentionally small. It does not replace project-specific monitors, but it enforces the minimum evidence shape for background work. Use `--timeout-seconds` for detached work that is expected to finish in a bounded window; a tool launch timeout is not enough after a command is detached.

Check whether a log-backed command is actually healthy before reporting it active:

```bash
bin/tautline monitor-status \
  --target <lane_path> \
  --log /tmp/my-command.log \
  --pid <pid-if-known> \
  --strict
```

`monitor-status` reports PID state, process-identity verification, watchdog state when configured, log size, last log update time, seconds since progress, stale threshold, and the next action. In strict mode it exits non-zero for missing, failed, unverified, or stale/hung monitors. A fresh log without verified PID liveness is not proof the command is still running. A log that has not grown beyond the stale threshold is not proof of progress; recover or rerun the command instead of waiting.

Transient provider outages are recovery-loop work. Anthropic/Claude/Codex/GitHub/API overloads, API errors, 429/500/502/503/504/529 responses, rate limits, websocket/network failures, service-degraded messages, and "try again" failures require `ScheduleWakeup` or host self-wakeup at an initial cadence no longer than 5 minutes, with backoff capped at 15 minutes. Lanes should retry until the provider responds or the failure becomes a real credential/access/scope/risk blocker; they should not stop for the night because Anthropic or another provider is temporarily down. Do not cancel the recovery loop, scheduled retry, wakeup, or autonomous goal loop merely because the human operator is angry or uses profanity; cancellation requires an explicit stop, cancel, pause, abort, or `/goal clear` instruction.

Short form for status checks: `tautline monitor-status --target <lane_path> --log <log> --pid <pid-if-known> --strict`.

### RCA Archive Publishing

Validate a methodology regression RCA and publish it to the dedicated RCA archive branch for other machines:

```bash
bin/tautline publish-rca-artifact \
  --file <lane_path>/.ai-runs/<utc>-methodology-regression-rca.md \
  --commit \
  --push
```

The command rejects archive paths outside the framework repository, and it resolves the archive directory against the canonical methodology checkout (the mutable checkout `sync-methodology` manages), never against a runtime snapshot. With `--commit --push`, the CLI publishes through an isolated temporary clone to `methodology-rca-archive` by default instead of committing RCA Markdown to `main` or mutating the active release checkout used by project lanes. Local archive writes into an ACTIVE methodology release checkout -- one on a release branch under a `pinned`/`signed` update policy, which sync advances and rescue repairs -- are refused, because a dirty canonical checkout routes every lane on the machine into the local-changes rescue path; they require explicit `--allow-release-checkout-write`; that mode is validation/preview-only and is not cross-machine durable publication. A maintainer's dev checkout (non-release branch, or an update policy that does not auto-advance it) stages the archive copy normally. RCA artifacts are evidence that shapes the framework; they are not part of the primary product context surface.

Methodology RCA artifacts use compact substance sections:

- `## What happened`
- `## Evidence`
- `## Root cause`
- `## Proposed control`
- `## Validation`

Record `tautline version --no-remote` and
`tautline methodology-status --target . --fail-on-drift` output in
`Evidence` when stale methodology, adapter drift, missing hooks, or locked lanes
may have contributed.

### Session Journals (Local-Only)

Session journals are compact summaries of normal AI delivery sessions. They are evidence for framework improvement, not product documentation, continuity handoffs, or process authority. As of 0.9.0 they are **local-only**: a journal narrates the adopter's product work, so it can never be proven safe to publish. `publish-session-journal` and `publish-pending-session-journals` are disabled and refuse in every mode; there is no session-archive branch.

The CLI-generated `Session Runtime` block includes Graphify freshness evidence: whether Graphify is enabled, the output path, the freshness state, latest graph timestamp/path, newer files, gate pass/fail, and any Graphify issues. This makes a journal useful for the adopter's own audit of whether lanes kept their code graph current, without loading lane-local `graphify-out/` artifacts.

Prepare a journal from an agent-written summary and validate it in place:

```bash
tautline prepare-session-journal --target <lane_path> --stdin
tautline validate-session-journal --file <lane_path>/.ai-runs/session-journals/<utc>-session-journal.md
```

Both commands write only under the lane's gitignored `.ai-runs/`; nothing leaves the lane.

To contribute sanitized signal upstream, enable `"instrumentation": {"enabled": true}` in the source adapter and publish an instrumentation record, a closed-vocabulary record with zero product-information capacity:

```bash
tautline publish-instrumentation-record --target .
```

See [Instrumentation](../instrumentation.md) for the record schema and vocabulary.

Journal validation rejects raw terminal dumps, secret-looking values, person-specific absolute paths, oversized content, missing Graphify evidence, and wording that presents the journal as current process authority. Required sections are `Session Runtime`, `Starting Context`, `Work Delivered Or Advanced`, `Planning And Review Gates`, `Human Interruptions Or Questions`, `Delays, Waits, Or Autonomy Breakdowns`, `Validation And PR State`, `Continuity Outcome`, and `Methodology Improvement Signals`.

### Methodology Repository Governance

The framework repository is centrally governed. Lanes may suggest changes by branch and pull request, but they must not push directly to `main`. `main` contains reusable policy, adapters, skills, CLI code, validation, and concise backlog. RCA evidence belongs on the dedicated `methodology-rca-archive` branch unless a specific summary is promoted into reusable policy. Normal session journals are local-only as of 0.9.0 and are never published; sanitized upstream signal comes from instrumentation records instead.

Every framework PR should include:

- Problem or evidence.
- Proposed canonical, adapter, skill, CLI, or validation change.
- Migration impact for existing machines/projects.
- Validation run.
- Review status.

### Plan-Finalization Gate

For T2/T3 or explicitly review-required plans, run one authoring-model native/self-check before R1. Claude-authored plans should use Superpowers review where available. If the native review surface is unavailable, run a structured self-review checklist, state the fallback in round status, and fix native-review blockers before spending R1. T0/T1 plans do not use this cross-model plan-review path.

Run the configured cross-model review through the methodology CLI. `run-plan-review` starts exactly one plan-only Codex review round and writes the trusted log plus sidecar metadata:

```bash
bin/tautline run-plan-review \
  --target <lane_path> \
  --plan <source-of-truth-plan> \
  --round R1
```

Plan-review convergence is a ladder. Rounds 1-2 are the target. Rounds 3-4 are self-authorized: pass `--exception-note "<reason>"` to `run-plan-review`/`finalize-plan-review` and proceed — never stop to ask the operator to authorize a round. The note is required to write the manifest for any round past the target, on every writer (`finalize-plan-review`, `run-plan-review` inline finalization, and `record-plan-review`). `run-plan-review` also self-authorizes a round 3-4 without a note when it detects a convergence state (blockers fixed since the bound round, or a run voided by a plan edit that no manifest binds), and prints a `plan_review_exception:` line naming the round, the cap, and the reason. Past round 4 refusal is unconditional, and the remedy is chosen by whether the bound evidence can actually be finalized: finalize the existing evidence only when it is clean AND still bound to the current plan; in every other state — including evidence that is clean but STALE, which `plan-finalization-precheck` rejects as a stale manifest — the split into smaller source-of-truth plans is mandatory. Findings that do not justify another round transfer into implementation review focus.

The round budget is counted per plan path, so a successor plan starts a fresh one — declare the succession with `run-plan-review --predecessor <superseded-plan>` on the successor's first round, and the tooling records the link and reports the chain's cumulative review spend at both ceremonies (`plan_review_chain_ledger:` at run time, `plan_review_chain_status:` at finalize). The flag is optional and append-once: omitting it behaves exactly as before, a repeat matching value is a no-op, and nothing about chain accounting can ever refuse a succession — the successor path is the round cap's sanctioned exit and stays unconditionally reachable. Past 8 cumulative recorded rounds or a chain depth of 3, one `plan_review_chain_advisory:` line prints, says plainly that nothing is blocked, and names the two remedies that work from there (decompose the scope, or carry non-blocking findings into implementation review focus); a total the tooling could only establish as a floor is reported as `>=` rather than as an exact count.

`run-plan-review` has a no-output watchdog so a wedged Codex/review process cannot be mistaken for active work. The default threshold is 720 seconds without log growth; override only for a known slow reviewer:

```bash
bin/tautline run-plan-review \
  --target <lane_path> \
  --plan <source-of-truth-plan> \
  --round R1 \
  --no-output-timeout-seconds 1200
```

Shortcut form: `run-plan-review --no-output-timeout-seconds <seconds>`.

When the watchdog fires, the CLI terminates the review process group, returns exit code `124`, writes `<review-log>.stale.json`, and prints `plan_review_stale_marker`. Treat that as a stale review: rerun the configured review round after any needed recovery instead of polling a frozen log.

After reading the log and classifying findings, bind that existing trusted run into the tracked manifest and in-plan evidence section:

```bash
bin/tautline finalize-plan-review \
  --target <lane_path> \
  --plan <source-of-truth-plan> \
  --log <printed-plan-review-log> \
  --round R1 \
  --verdict <clean|clean-with-deferrals|blocked> \
  --unresolved-critical-count <n> \
  --unresolved-p1-count <n> \
  --classified-findings-json <file>
```

The captured review command must start with the adapter `review.codexPlanWrapper`, include a structured `--plan <source-of-truth-plan>` binding appended by `run-plan-review`, appear verbatim in the captured log, and match the CLI-written `<review-log>.meta.json`. Run metadata must say `review_scope: plan-only` and `code_diff_review: false`. The wrapper output itself must reference the reviewed plan path or plan hash; the CLI header alone is not enough. Shell/mock commands such as `echo`, `printf`, `cat`, `true`, pipes, redirects, and command chaining are rejected. `record-plan-review` remains available for diagnostics/imports only; it writes `.imported.json` evidence and `plan-finalization-precheck` trusts only the canonical manifest recorded by `run-plan-review` or `finalize-plan-review`. Do not run Codex manually and then run `run-plan-review` again just to bind manifest evidence.

Block every plan-finalization path until the manifest matches the current plan and review log:

```bash
bin/tautline plan-finalization-precheck \
  --target <lane_path> \
  --plan <source-of-truth-plan>
```

Once the precheck passes, planning is finalized and the plan is ready for a builder lane. Emit the goal the operator assigns rather than authoring one by hand — the Claude Code harness refuses a goal prompt over 4000 characters, so an over-long goal fails at paste time, after the planning session that wrote it has ended:

```bash
bin/tautline goal-assignment \
  --target <lane_path> \
  --plan <finalized-plan>
```

The emitted goal carries the plan reference, the scope, the completion condition, the autonomy contract, and the proof command, and prints its exact character count and headroom. It is printed between `goal_assignment_begin` and `goal_assignment_end`: hand over exactly the text between those markers and never the marker lines, because `char_count` certifies the goal text alone and any prefix pasted with it spends the same budget. `--raw` prints those bytes and nothing else, so `--raw > goal.txt` round-trips through `--check`. The irreducible core is never trimmed: if it alone cannot fit the limit, composition refuses rather than emit a goal that cannot tell a builder when to stop. Only the milestone list flexes, and anything dropped or shortened is reported on `goal_assignment_milestones:` and marked in the goal itself as `(+N more in the plan)`; when the budget admits no full entry the goal still states `Milestones: all N are in the plan`, so omitted work is never invisible. Composition is gated on the finalization precheck, so an unfinalized plan is refused with the plan-review recovery path; `--allow-unfinalized` dry-runs the wording and labels its own output as not-yet-assignable. To vet a goal that was written by hand instead, pass `--check <file|->` — it exits 1 over the limit and names the exact count and overage. Use `--char-limit` only for a host whose limit genuinely differs, never to make an over-long goal fit.

Install the Claude Code `ExitPlanMode` hook, Claude `Task` branch-liveness hook, Claude `Bash` background-command hook, Claude `Stop` response guard, Claude tool-rejection hook, and lane-local Git branch-liveness hooks. `lane-start` installs these automatically, and `methodology-status --fail-on-drift` fails if required hooks are missing:

```bash
bin/tautline install-hooks --target <lane_path>
```

### Classified-Findings Contract

`--classified-findings-json` carries the review's classification into the tracked evidence. One shape serves both review paths:

```json
{
  "id": "R1",
  "severity": "critical",
  "summary": "the export retry loop is unbounded",
  "status": "deferred",
  "ac_ref": null,
  "disposition": "routed",
  "routed_to": "BACKLOG-482",
  "deferral_rationale": "the retry path is unreachable until the throttle flag ships",
  "acceptance_criterion": "AC4: the export completes within the throttle ceiling"
}
```

**Note the flag takes different forms on the two verbs.** `finalize-implementation-review --classified-findings-json` takes a **path to a JSON file**; `finalize-plan-review`, `run-plan-review` and `record-plan-review` take **inline JSON**. A retry line copied from one verb to the other will not run.

`status` and `disposition` are **separate axes**, not two spellings of one field:

- `status` is the review-round vocabulary and includes `deferred`. It answers *what happened to this finding in this round*.
- `disposition` is `fixed`, `routed` or `refuted`. It answers *how this finding leaves the item*. It never takes a `deferred` value — a deferred blocker records `disposition: routed` with a `routed_to`, or is `fixed`/`refuted`.

Requiredness, on the **implementation** path with a push-eligible verdict (`clean`, `clean-with-deferrals`):

- A **blocker-severity** finding (`critical`/`c1`/`p0`/`p1`/`important`/`high`) requires `ac_ref` and `disposition`. `ac_ref` names the acceptance criterion the finding is open against, or is `null` when the finding is out of scope for this item.
- `disposition: routed` requires `routed_to`, the backlog row the finding was carried into.
- A finding with a non-null `ac_ref` is **never routable** — it is fixed or refuted with cited evidence, regardless of severity. Severity is never downgraded to make routing legal.
- Any routed finding forces `--verdict clean-with-deferrals`; `--verdict clean` is refused.
- `--verdict clean-with-deferrals` requires the flag, with at least one finding.
- `--verdict blocked` requires none of this. Recording what review actually found is always the cheapest verdict.

Requiredness on **both** paths:

- A finding with `status: "deferred"` whose severity is Critical/P1-origin requires `deferral_rationale` (at least 12 characters, why it is non-blocking) and `acceptance_criterion` (what it was judged non-blocking against). A deferred P2/P3 requires neither.

The recorded counts are reconciled against the review log the manifest pinned: a push-eligible verdict with zero unresolved counts is refused when the log names blocker findings that the classification does not account for. One resolved finding does not account for the rest — every blocker class the log mentions must be covered, and every recorded blocker must be fixed, refuted, or routed to a row.

Manifests recorded by a plugin older than the version that introduced this contract are exempt, so a mid-flight lane is not stranded. A manifest with **no** recorded `plugin_version` is strict by design: omission is not a migration.

`methodology-status` prints one `critical_deferral:` line per recorded Critical/P1-origin deferral. It is a ledger surface and never changes an exit code.

### Document Context Commands

Bootstrap context indexes without moving project docs:

```bash
bin/tautline context-bootstrap --target <lane_path> --write
```

Classify existing Markdown candidates into the generated index for human/agent review:

```bash
bin/tautline context-bootstrap --target <lane_path> --classify --write
```

Add historical headers to archived Markdown after the index is reviewed:

```bash
bin/tautline context-bootstrap --target <lane_path> --add-archive-headers --write
```

Inspect budget state:

```bash
bin/tautline context-status --target <lane_path>
bin/tautline context-status --target <lane_path> --strict
```

Warn mode reports issues and exits zero. Strict mode exits non-zero for missing indexes, oversized indexes, unclassified tracked Markdown, missing archive headers, or generated adapter drift.

### Graphify Commands

Graphify is adapter-backed, optional per project, and enabled by default. It gives agents a graph-first navigation path so they can answer architecture and code-flow questions without dumping broad source scans into context.

Inspect Graphify state:

```bash
bin/tautline graphify-status --target <lane_path>
```

Install Graphify CLI support when asked:

```bash
bin/tautline graphify-install --target <lane_path>
```

Build or refresh the graph from the project root:

```bash
graphify update .
```

Semantic enrichment is separate and never blocking:

```bash
GRAPHIFY_CLAUDE_CLI_MODEL=haiku graphify label . --backend=claude-cli
```

When `graphify-out/GRAPH_REPORT.md` or `graphify-out/graph.json` exists, agents should use Graphify report/query/path/explain before broad `rg` or grep for architecture, dependency, call-flow, and navigation questions. Use `rg` for exact text or symbol lookups, missing graph state, or while rebuilding after a failed refresh. Do not use stale Graphify output.

After every code, docs, schema, route, test, architecture, or other system change, run `graphify update .` before relying on existing Graphify output, committing, or pushing. If any tracked or unignored project file is newer than the latest Graphify artifact, `graphify-out/` is stale and `methodology-status --fail-on-drift` plus installed Git hooks block until it is refreshed.

The blocking gate names the no-LLM refresh only. `graphify update .` needs no API key, backend, or external model, and it cold-builds when no graph output exists; semantic labeling (`graphify label . --backend=<name>`) is a separate step whose failure never blocks. `graphify-status` and `methodology-status` print the adapter's CONFIGURED `graphify.updateCommand` and `graphify.buildCommand`, so a project override and the gate can never prescribe different commands.

Do not run `graphify claude install`, `graphify codex install`, or other Graphify assistant project installers unless the project adapter explicitly allows Graphify to manage assistant files and the human asks for that exact installer. Tautline owns generated `CLAUDE.md` and `AGENTS.md`.

`graphify-out/` is generated local output. `lane-start` keeps it ignored, and `methodology-status --fail-on-drift` fails if Graphify output is tracked in git or stale.
