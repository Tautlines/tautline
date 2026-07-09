# Policy Module Index

This index is the human map for the modular canonical policy. The machine
ordering lives in `methodology/policy/manifest.json`; the generated compatibility
artifact is `methodology/canonical-rules.md`.

Edit policy in the module that owns the behavior, then regenerate the
compatibility artifact:

```bash
minervit-methodology canonical-policy --write
minervit-methodology canonical-policy --check
```

Do not hand-edit `methodology/canonical-rules.md`. It remains a generated
single-file surface for existing consumers while the source policy stays modular.

## Module Ownership

| Module | Owns |
| --- | --- |
| [00-introduction](../../methodology/policy/00-introduction.md) | Generated artifact warning, canonical title, and top-level source-of-authority statement. |
| [01-authority](../../methodology/policy/01-authority.md) | Canonical-vs-adapter authority, generated-file ownership, memory boundaries, and public documentation language. |
| [02-methodology-repository-governance](../../methodology/policy/02-methodology-repository-governance.md) | Methodology repo governance, release surface, archive branches, delivery communication requirements, deployment ownership, and product-isolated CLI resolution. |
| [03-autonomy](../../methodology/policy/03-autonomy.md) | Risk tiers, standing approval, true-blocker boundaries, and autonomous forward-motion defaults. |
| [04-autonomy-and-status](../../methodology/policy/04-autonomy-and-status.md) | Forward motion, work-evasion boundaries, exact blocker questions, RCA obligations, and operator-facing status language. |
| [04a-rejected-tool-call-recovery](../../methodology/policy/04a-rejected-tool-call-recovery.md) | Recovery rules for rejected, denied, cancelled, or blocked tool calls, including non-conflicting work and targeted verification fallback. |
| [05-current-status-truth](../../methodology/policy/05-current-status-truth.md) | Latest-code baseline, remote/base evidence, stale-lane handling, and freshness-guard escape behavior. |
| [06a-stop-and-deferral-red-flags](../../methodology/policy/06a-stop-and-deferral-red-flags.md) | Stop, pause, standby, deferral, review-supervision, and forbidden-example red-flag wording. |
| [08-verified-human-instructions](../../methodology/policy/08-verified-human-instructions.md) | Same-turn verification requirements for external-system instructions and authoritative source links. |
| [09-delivery-summaries](../../methodology/policy/09-delivery-summaries.md) | Executive-summary shape, progress visibility, delivery/queue closeout, and continuity refresh at handoff boundaries. |
| [10-goal-orchestration](../../methodology/policy/10-goal-orchestration.md) | Goal/milestone/PR hierarchy, goal ledgers, provider-item integration points, Claude `/goal`, completion proof, and operator-input dependencies. |
| [10a-backlog-provider](../../methodology/policy/10a-backlog-provider.md) | Backlog provider intake, board schema boundaries, stakeholder questions, exports, ordering, epics, item framing, provider-item completion authority, and grooming. |
| [10b-board-currency](../../methodology/policy/10b-board-currency.md) | Board status currency, current-lane scope, native subtask status, active-status claiming, done evidence, and customer-facing bug placement. |
| [11-cross-lane-coordination](../../methodology/policy/11-cross-lane-coordination.md) | Repo-tracked lane coordination, shared-contract protection, lane notes, and strict enforcement. |
| [12-context-rotation](../../methodology/policy/12-context-rotation.md) | Context thresholds, Claude auto-compact settings, rotation boundaries, and context-exhaustion anti-patterns. |
| [13-planning](../../methodology/policy/13-planning.md) | Plan-review loops, native/cross-model review order, plan finalization, execution-packet creation, and implementation-start gates. |
| [14-technical-stack-and-platform-defaults](../../methodology/policy/14-technical-stack-and-platform-defaults.md) | Adapter-owned stack policy, cloud-provider defaults, AWS credential path, and deployment platform boundaries. |
| [15-tdd-and-behavior-specs](../../methodology/policy/15-tdd-and-behavior-specs.md) | TDD requirements, behavior-spec source materials, acceptance coverage, and user-facing behavior tests. |
| [16-early-warning-smoke](../../methodology/policy/16-early-warning-smoke.md) | Early main-health smoke timing, monitor reuse, failure response, and post-merge smoke boundaries. |
| [17-review-before-push](../../methodology/policy/17-review-before-push.md) | Stage 1/Stage 2 review sequence, review evidence, round budgets, blocker handling, and review-tool supervision. |
| [18-merge-and-ci](../../methodology/policy/18-merge-and-ci.md) | Main health, branch liveness, pre-push/pre-merge validation, merge queue, auto-merge, and admin-merge boundaries. |
| [19-demo-and-staging-deployment](../../methodology/policy/19-demo-and-staging-deployment.md) | Adapter-owned deploy targets, standing approval for deploy closeout, and credential/setup blockers. |
| [20-background-work](../../methodology/policy/20-background-work.md) | Background command supervision, monitor status, stale process recovery, wakeup cadence, and terminal monitor states. |
| [21-lane-lifecycle](../../methodology/policy/21-lane-lifecycle.md) | Lane startup, methodology sync, stable/experimental pins, generated adapter protection, work profiles, WIP update blockers, and GitHub API budget. |
| [22-unmanaged-project-bootstrap](../../methodology/policy/22-unmanaged-project-bootstrap.md) | Required bootstrap flow when a repo has no adapter and no generic operational adapter can safely apply. |
| [23-local-resource-isolation](../../methodology/policy/23-local-resource-isolation.md) | Lane-local ports, compose names, service env, `lane-run`, and port-contention recovery. |
| [24-document-context-budget](../../methodology/policy/24-document-context-budget.md) | Markdown context indexes, archive headers, strict/warn enforcement, and bounded document audits. |
| [25-graphify-navigation](../../methodology/policy/25-graphify-navigation.md) | Graphify status, install, freshness, generated output protection, and graph-first navigation. |
| [26-database-migration-collisions](../../methodology/policy/26-database-migration-collisions.md) | Monotonic migration index, snapshot, and journal collision repair. |
| [27-execution-packet-work-loop](../../methodology/policy/27-execution-packet-work-loop.md) | Execution packet ownership boundary and milestone-plan-to-tactical-work loop. |
| [28-memory](../../methodology/policy/28-memory.md) | Open Brain memory capture, memory-as-evidence boundaries, and RCA/memory ordering. |
| [29-context-continuity](../../methodology/policy/29-context-continuity.md) | Filesystem continuity handoffs, startup consumption, post-merge next-work resolution, and final-response checks. |
| [30-session-journals](../../methodology/policy/30-session-journals.md) | Session journal purpose, publication branch, validation, and archive hygiene. |
| [31-automation](../../methodology/policy/31-automation.md) | Automation scratch-space boundaries, dedicated clone use, and safe automation targets. |

## Editing Rules

- Put reusable behavior in exactly one owning policy module when practical.
- Keep compatibility-only text out of source modules unless existing consumers
  need it in the generated `canonical-rules.md` artifact.
- Update plugin skills or reference docs only when the procedural surface also
  changes; do not copy full canonical policy into skills.
- Run `minervit-methodology canonical-policy --write` after policy module edits.
- Run `scripts/test.sh` and `scripts/validate.sh` before publishing policy
  changes.
