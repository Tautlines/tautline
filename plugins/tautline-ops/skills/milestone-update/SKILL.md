---
name: milestone-update
description: Publish internal, professional, text-only milestone-complete updates to the adapter-configured Product Milestones Google Chat webhook without generating customer-facing pages or videos.
---

# Milestone Update

Use this skill when a milestone completes, when the human operator asks for a
milestone update/review, or when adapter `milestoneUpdate.enabled` is true and a
milestone-complete boundary is reached.

Read `references/milestone-update-policy.md` in full before composing, posting,
or treating a milestone update as delivered.

Milestone updates are internal operator visibility artifacts for the Product
Milestones space. They are not customer-facing iteration reviews.

## Fast Path

Check the active configuration:

```bash
minervit-methodology milestone-update-status --target . --strict
```

If disabled, continue normal authorized work and do not ask whether to enable it
unless the human operator explicitly asked to configure the project. If enabled
but the webhook env is missing, that is a setup blocker for milestone
completion; do not mark the milestone complete until the env is configured and
the update is posted.

Compose a concise internal milestone summary with these headings exactly:

```markdown
## Plain English
## Progress
## What Changed
## Validation
## Next
## Technical Details
```

Post through the CLI:

```bash
minervit-methodology publish-milestone-update --target . --milestone <milestone-id-or-title> --stdin
```

When an active goal ledger exists, short milestone keys such as `M3` are
canonicalized to the active milestone title before the delivery marker is
written. Do not re-post under a different milestone spelling to satisfy the
completion gate; use the same canonical identity.

Delivery is non-blocking after a successful post. Continue the next authorized
milestone/goal action; do not wait for Chat acknowledgement.

## Completion Gate

When `milestoneUpdate.enabled` is true, `goal-advance --event milestone-complete` is not allowed until the Product Milestones delivery marker exists.
Publish the update first, then advance the goal milestone.

## Boundaries

Do not include secrets, webhook URLs, raw terminal dumps, or customer-private
data. Do not write directly to Google Chat or store webhook URLs in repo files.

Do not generate a video or S3 review page for the internal milestone update. Customer-facing page/video reviews remain the `iteration-review` skill at goal completion.
