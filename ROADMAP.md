# Tautline roadmap

Tautline's direction is fast, coordinated AI development. Every addition should reduce the
operator's or agents' total effort. Features are useful when they make work easier to pick up,
share, verify, and finish; they do not need to block an action to justify their existence.

This page describes the current source and direction. Public package availability is recorded
in [GitHub releases](https://github.com/Tautlines/tautline/releases) and [CHANGELOG.md](CHANGELOG.md).
Future items are proposals, not delivery commitments.

## Current foundation

- Small project setup and generated Claude Code / Codex instructions.
- Local queue, GitHub issues, and Jira backlog providers; optional continuity handoffs.
- Shared work manifests and a fleet view for sibling worktrees, with an optional Git metadata branch across clones and computers, scope, dependencies,
  blockers, stale records, and overlap advisories.
- Optional command evidence tied to code identity; local health and explicitly requested
  GitHub facts, including PR outcomes and exact-head CI in the work view.
- Operator decisions with persisted answers and acknowledgement.
- Specialized builder GitHub controls, diagnostics, security checks, and batched releases.

Coordination is advisory, local by default and optionally shared through Git. Evidence and health do not certify acceptance or deployment.
The inbox does not execute answers. These boundaries matter more than an expansive feature list.

## Next: improve the complete workflow

1. **Use and polish the shared fleet workflow.** Measure duplicate work, collisions, stale
   declarations, and time spent finding context. Improve startup, scope updates, and handoffs
   from actual use before adding enforcement.
2. **Make outcomes easier to inspect.** Build a compact visual fleet view over the existing work and PR observations. Connect
   deployment observations where an integration can report them accurately. Keep unknown and stale distinct from passed.
3. **Make operator decisions easy to resume.** Improve answer routing and clarity without
   automatic execution of untrusted answer text.
4. **Validate a focused next feature.** Choose between optional usage/cost attribution and a
   scenario harness that exercises real coordination and recovery failures. Show limitations
   and measured results before presenting scores.

## Later, subject to evidence

- A richer fleet UI after the compact view proves useful.
- Optional conflict reservations for teams with demonstrated collision problems.
- Delivery economics with explicit exact, estimated, and unknown attribution.
- Review-quality experiments and earned-autonomy suggestions grounded in reliable observations.
- Opt-in delivery updates and recap publishing when there is demonstrated demand.

These do not imply a return to required plans, repeated reviews, or a policy gate for every
agent action. Keep one backlog authority and batch releases when there is something to ship.

Open a [public issue](https://github.com/Tautlines/tautline/issues) with a concrete workflow,
its current cost, and what would make it easier. The smallest useful improvement is a good
starting point.
