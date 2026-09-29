# Product direction

**Tautline helps capable AI agents work together without slowing them down.** It is for
builders who want to put several agents on a product and still understand who is doing what,
what has been checked, and which decisions need attention.

The product's value is coordination, continuity, and useful evidence. A work manifest should
save another agent from duplicating work. A handoff should make a restart cheap. An inbox
answer should reach the agent that needs it. Measure these features by the effort they save.

## The working model

- Keep project instructions small. The lean canonical rules and `.tautline.json` render the
  instructions each runtime reads; project-specific choices belong in the project config.
- Let agents publish their scope and check peer work at startup and work boundaries. Local
  sibling worktrees share those declarations without coordination commits or remote calls.
- Record the tests already being run. Show their code identity and freshness instead of
  adding another test run or turning a receipt into permission to continue.
- Collect operator questions and persist answers until consumed. Resume through a short
  handoff when useful.
- Use the project's tests and CI for verification. Tautline's development process has one
  adversarial review before merge, not an accumulating sequence of approval rounds.

## Current boundaries

Coordination is local to worktrees sharing a Git common directory. It is advisory: overlapping,
stale, or blocked work remains visible but does not lock edits or reserve a backlog item.
Remote fleet synchronization and a hosted dashboard are future work.

Evidence is a record of a command and its result. Health reports separate local observations
from explicitly requested remote facts. Neither should imply successful deployment,
acceptance, or human approval that was not observed.

Claude Code's startup hook reports context. Its separate builder hook can restrict selected
GitHub actions for a configured builder lane; GitHub App permissions provide the server-side
boundary. Codex receives instructions and CLI access, not Claude's hook enforcement. See
[builder lanes](../builder-lanes.md).

## What stays out

Mandatory planning rounds, review-round accounting, completion-claim blocking, compulsory
journals, and duplicate backlog mirrors are not the product direction. A new blocking control
needs a concrete defect to prevent and evidence that it saves more time than it costs.
Coordination utilities earn their place through easier teamwork, not through refusing actions.

The [roadmap](../../ROADMAP.md) separates the working foundation from proposed additions.
No speed multiplier, cost saving, autonomy score, or hosted-service SLA is claimed without
supporting measurements.
