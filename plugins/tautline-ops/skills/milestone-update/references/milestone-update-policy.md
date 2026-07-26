# Milestone Update Policy Reference

This reference keeps detailed internal milestone-update policy behind the
concise `milestone-update` skill entrypoint.

## Purpose

Use this policy when a milestone completes, when the human operator asks for a
milestone update or review, or when adapter `milestoneUpdate.enabled` is true
and a milestone-complete boundary is reached.

Milestone updates are internal, professional, text-only Google Chat cards for
the adapter-configured Product Milestones space. They may include technical and
meta detail when that helps the operator understand what was built, how it was
validated, what risk changed, and what comes next. They are not customer-facing
iteration reviews, generated pages, recap videos, or release-marketing assets.

## Contract

1. Check the active configuration:

   ```bash
   tautline milestone-update-status --target . --strict
   ```

2. If disabled, continue normal authorized work and do not ask whether to enable
   it unless the human operator explicitly asked to configure the project.

3. If enabled but the webhook env is missing, that is a setup blocker for
   milestone completion. Do not mark the milestone complete until the env is
   configured and the update is posted.

4. Compose a concise internal milestone summary for the Product Milestones
   space, not customers.

5. Include these headings exactly:

   ```markdown
   ## Plain English
   ## Progress
   ## What Changed
   ## Validation
   ## Next
   ## Technical Details
   ```

6. Post through the CLI, not by writing directly to Google Chat or storing
   webhook URLs in repo files:

   ```bash
   tautline publish-milestone-update --target . --milestone <milestone-id-or-title> --stdin
   ```

7. When an active goal ledger exists, short milestone keys such as `M3` are
   canonicalized to the active milestone title before the delivery marker is
   written. Do not re-post under a different milestone spelling to satisfy the
   completion gate; use the same canonical identity.

8. Delivery is non-blocking after a successful post. Continue the next
   authorized milestone or goal action; do not wait for Chat acknowledgement.

9. When `milestoneUpdate.enabled` is true,
   `goal-advance --event milestone-complete` is not allowed until the Product
   Milestones delivery marker exists. Publish the update first, then advance the
   goal milestone.

`methodology-status --fail-on-drift` fails when the configured Product
Milestones webhook env is missing. `goal-advance --event milestone-complete`
also refuses completion until the delivery marker exists, so the update is part
of milestone closeout evidence rather than optional commentary.

## Content Rules

- Keep `Plain English` first and useful: what happened, why it matters, and
  what capability or risk reduction was unlocked.
- `Progress` must name the goal, milestone, grounded percent/position when
  known, and whether the milestone is complete.
- `What Changed` should summarize the product, code, process, or delivery work
  completed.
- `Validation` should name real checks, reviews, deploy proof, or why
  validation is deferred.
- `Next` should state the next authorized action and whether work continues
  immediately.
- `Technical Details` may include branches, PRs, commits, test commands, logs,
  blockers, risks, review rounds, and implementation notes.
- Do not include secrets, webhook URLs, raw terminal dumps, or customer-private
  data.

## Boundaries

Do not generate a video or S3 review page for the internal milestone update.
Customer-facing page/video reviews remain the `iteration-review` skill at goal
completion.

These updates may include implementation approach, risks, validation, PRs,
review rounds, and next work because they are operator-facing. They are not a
substitute for a customer-facing goal-complete iteration review when
`iterationReview.enabled` covers the goal boundary.

Do not treat a successful milestone-update post as permission to stop. Continue
the next authorized milestone or goal action unless the source-of-truth plan,
goal ledger, or adapter says no authorized work remains.
