---
name: bug-intake-triage
description: Use when a lane finds, files, classifies, or plans a product bug and must follow adapter bugBacklog policy for severity, source-of-truth artifact, tracker mirrors, and board placement without asking the operator to choose the tracker.
---

# Bug Intake Triage

Use this skill when a lane discovers, investigates, files, plans, defers, or closes a product bug. The active project adapter is the authority: read `bugBacklog`, `backlogAdapter`, and `backlogProvider` before creating a source-of-truth artifact, GitHub issue, board item, Jira/Linear item, or backlog note.

Methodology skills are file-backed policy. If host skill tooling returns `Unknown skill`, resolve the methodology checkout via `$MINERVIT_METHODOLOGY_REPO`, `$HOME/.config/minervit/methodology.env`, or `minervit-methodology version --no-remote` (`methodology_repo`), then read this skill and continue.

## Triage Order

1. Classify severity before planning or filing. Use the adapter `severityTaxonomy`; if it is generic, preserve project-local labels and do not invent a new taxonomy.
2. Default auth, email, tenant data, security, deploy, billing, data-loss, and customer-blocking failures to at least `P1` unless evidence proves lower severity. Adapter `autoP0Categories` and `autoP1Categories` override the generic list.
3. Write the adapter-declared source of truth. If `bugBacklog.sourceOfTruth` is still a `BOOTSTRAP REQUIRED` placeholder, the tracker is unresolved; ask one exact setup question instead of inventing policy. If it is `backlogAdapter`, use the project's existing backlog/source-of-truth planning path. If it names a path, write there. If it names GitHub Issues, Jira, Linear, or another tracker, use that tracker as the authoritative record.
4. Create mirrors only when `bugBacklog.issueMirrors` or adapter policy asks for them. Do not ask "specs or GitHub?" when the adapter already resolves the tracker of record.
5. If the bug is customer-facing and `backlogProvider` is enabled, ensure the issue/item is on the stakeholder board with an Item Type and current `Status`. `gh issue create` alone is not done.

## Required Bug Fields

Every bug artifact or tracker entry must include the adapter `requiredFields`. When the adapter does not specialize them, include at least: symptom or observed behavior, user/admin/operator impact, reproduction or observed trigger, suspected root cause or known unknown, file/line/log evidence, risk, proposed fix, tests/validation, rollout/backfill/ops needs, and deferral reason when not fixed immediately.

## Routing Rules

- `P0`/`P1`: stop unrelated feature work, create or update the authoritative bug record immediately, and keep board/status current while investigating.
- `P2`/`P3`/`Nit`: route through adapter policy. Defer only with evidence, owner, and a concrete follow-up location.
- Internal/non-customer-facing bugs stay out of customer boards unless the adapter records a concrete customer impact.
- Customer-facing bugs are not complete until the source-of-truth record, mirrors required by adapter policy, board status, verification evidence, and closure state agree.

## Commands

```bash
minervit-methodology methodology-status --target .
minervit-methodology backlog-provider-export --target . --item-path <bug-artifact.md> --type bug [--customer-facing] --write
minervit-methodology backlog-provider-update --target . --item <item-or-url> --status "<status>" --verification-evidence "<proof>"
minervit-methodology backlog-provider-board-check --target .
```

Use the sanctioned board/status commands. Do not mutate board structure, rewrite stakeholder-authored fields, or use raw GraphQL to route a bug.
