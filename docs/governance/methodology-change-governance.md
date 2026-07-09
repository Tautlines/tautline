# Methodology Repository Governance

The methodology repository is the product surface for reusable AI delivery process. Project lanes may propose changes, but changes to `main` are centrally governed.

## Required Path

- Create a branch for each methodology proposal.
- Open a pull request into `main`.
- Include the problem/evidence, proposed change, adapter/project impact, migration impact, validation, and review status.
- Resolve Critical/P1 review findings before merge.

## Main Branch

`main` contains canonical policy, adapters, skills, CLI code, validation, and concise backlog. Do not add raw methodology regression RCA artifacts or normal session journals to `main`.

## RCA Evidence

Methodology regression RCAs are evidence, not product docs. Publish them with:

```bash
minervit-methodology publish-rca-artifact --file <path> --commit --push
```

The default target is the `methodology-rca-archive` branch under `docs/backlog/methodology-regressions/`.

## Session Journal Evidence

Normal session journals are compact evidence for methodology improvement, not product docs or process authority. Publish them with:

```bash
minervit-methodology publish-session-journal --file <path> --commit --push
```

The default target is the `methodology-session-archive` branch under `docs/backlog/session-journals/`. Fetch or inspect that branch only for methodology audits, RCA pattern review, or explicit process-improvement work.

## Break Glass

Direct pushes to `main` are allowed only from the methodology-owner lane while bootstrapping protections or repairing a broken protection path. The commit or follow-up PR must state the break-glass reason.
