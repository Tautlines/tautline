## Autonomy

- Execute known safe work without asking the human operator to repeat adapter decisions.
- Use risk tiers: T0 mechanical no-behavior changes use self-review/focused checks; T1 backlog work uses brief plan plus implementation review; T2 architecture/security/schema/cross-system behavior requires source-of-truth planning/review; T3 destructive, production-impacting, external-side-effect, or cost-bearing work requires explicit or standing approval.
- Routine deploy-to-close work is agent-owned when adapter/plan/packet/closure criteria require it; production presence alone is not a human gate. Before production deploy exists, break-glass/destructive-path tests may proceed after full gates with a documented reason.
- Standing approval recorded in a source-of-truth plan, execution packet, backlog/follow-up row, PR body/comment, project adapter, or human-approved closure criterion counts once conditions match. Do not ask again just because the next action is T2/T3, break-glass, or admin merge.
- If approval conditions conflict, are missing, or no longer match risk/scope, ask one exact blocker question and do not invent approval; otherwise execute.
- Do not stop at arbitrary "good stopping points" or "clean checkpoints." Continue until the approved queue is exhausted, a true blocker occurs, or the operator changes direction.
- True blockers are decisions that change approved scope, unresolved explicit approval, unavailable credentials/external access after checking adapter paths, a failing required gate with no safe fix, or lack of safe parallel work. Credential or served-origin access is not a true blocker until the agent has checked adapter-declared env, secret, cloud identity, seeded-account, deploy/status, and local-lane evidence paths. For a missing `MINERVIT_*`/`TAUTLINE_*`/webhook secret that means `tautline secret-status --name <VAR>` and one retry through the lane environment before any operator question; re-asking for a value already in the secrets store is permission theater.
- Multi-step but fully executable actions are not true blockers: a methodology release (version bump, changelog, release notes, validation, PR), cross-model review, branch push, or documented multi-command sequence must complete when it gates the active goal, not justify deferral or descoping.

## Unattended Operation

- The standing autonomy directive is default operating policy for every lane type
  (planning, building, remediation, maintenance). Assume the operator is AFK unless
  the adapter disables `autonomy.standingDirective`.
- Non-obvious decisions taken under the directive require a durable record with
  rationale and reversibility: `decision-record` in adapter-bearing lanes; session
  notes or working artifacts where no adapter (and therefore no ledger) exists. The
  record, not chat prose, is the operator's review surface.
- Operator-owned forks (per the existing true-blocker and approval categories above -
  this section narrows none of them) are queued asynchronously - through the
  stakeholder-question flow where the adapter enables it and no startup-remediation
  marker is active, falling back to a hard-to-reverse decision entry carrying the
  question whenever that flow is unavailable or fails at ask time - and do not stop
  the run while safe authorized goal work remains. When such a fork is queued and no
  safe authorized work remains, the existing true-blocker rules apply unchanged -
  never invent approval.
- Guard and review-gate mechanics are unchanged by this section; enforcement
  tightening lands separately.
- Lane currency is the agent's job, not the operator's. At session start the agent
  reads the `TAUTLINE LANE STATUS` line. On any drift verdict the agent itself
  attempts the printed remedy; it does not hand the drift back to the operator as
  the operator's task, which is the failure this rule exists to prevent. When a
  remedy cannot complete, the agent states the unresolved drift and its effect in
  its own output and continues - currency is never a precondition for responding.
