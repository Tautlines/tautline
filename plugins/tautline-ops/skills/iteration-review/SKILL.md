---
name: iteration-review
description: Generate adapter-enabled customer-facing plain-language iteration reviews for completed goals using adapter iterationReview config, validated GoalReview records, text pages, and adapter-approved S3/CloudFront media hosting without committing generated binaries.
---

# Iteration Review

Use this skill when the operator asks for an iteration review, `/iteration-review`, goal review, or when `iterationReview.enabled` and a goal has completed. Routine milestone visibility belongs to `milestone-update` unless the adapter opts `iterationReview.granularities` into `milestone`.

Read `references/iteration-review-policy.md` in full before status checks, `GoalReview` authoring, media work, hosting/webhook setup, publishing, delivery checks, boundary decisions, or disabled-output decisions. Do not proceed from this entrypoint alone; the fast path is a summary.

## Fast Path

1. Load the adapter and run strict status:

   ```bash
   minervit-methodology iteration-review-status --target . --strict
   ```

   Continue only when enabled. If disabled, state that the project has not opted in and continue normal authorized work.

2. Select a completed goal from instruction or `.ai-work/GOAL_RUN.json`. Do not invent completion; a review communicates completion, it does not prove it.

3. Compose the `GoalReview` JSON using `DATA-CONTRACT.md`, normally at:

   ```text
   docs/iteration-reviews/<goal-or-milestone-id>/goal-review.json
   ```

   Validate before rendering:

   ```bash
   minervit-methodology validate-iteration-review --target . --file <record.json>
   ```

4. If page output is enabled, generate the page:

   ```bash
   minervit-methodology generate-iteration-review-page --target . --record <record.json> --write
   ```

   Render any video from the updated record.

5. If video output is enabled, run `minervit-methodology iteration-review-renderer-setup`, produce the recap from `~/.local/state/minervit/renderer-kit/`, upload media to adapter-approved S3/CloudFront, add hosted URLs, validate again, and regenerate the page. Video, poster, screenshot, and page-media production is agent-owned delivery work. Do not install dependencies inside the plugin tree. Do not say agents do not do videos or media production. When video output is required, missing recap video is not a publishable partial stakeholder update.

6. Commit only text artifacts: the review JSON and generated `index.html`. Never commit generated videos, screenshots, thumbnails, clips, posters, or other media binaries.

7. After the review PR lands, publish stakeholder-facing artifacts:

   ```bash
   minervit-methodology publish-iteration-review --target . --record <record.json>
   ```

   The review folder slug must match the active `goal_id` before validation, publish, or delivery-check. Do not post a GitHub URL as the primary stakeholder link. Skipping Chat requires the approved operator token. If deployment notifications are required, use `publish-deploy-ready-update` and `deployment-notification-status --target . --strict`; the recap link is not proof a delayed deploy finished.

8. Run the close-out delivery check:

   ```bash
   minervit-methodology iteration-review-delivery-check --target . --record <record.json>
   ```

   Goal close-out is not done until this check passes.

## Content And Media

- Write for non-technical product readers first; it should read like a concise launch note.
- Keep PR numbers, repository links, file paths, routes, schemas, database details, test tiers, review rounds, commits, CI mechanics, and implementation jargon out of customer-facing fields.
- Put technical detail only in the optional `technical` block.
- Use real screenshots or recordings for visible product surfaces; generated media must show product behavior and use adapter-approved hosting.
- `iterationReview.outputs.video: false` disables recap-video rendering only; it does not waive hosting for page media.
- Without S3/CloudFront, page output is text-only: no `videoUrl`, `posterUrl`, `highlight.image`, or `usage[].src`.

## Boundary Rules

- Boundary announcement is non-blocking. Say a review is available and continue authorized work.
- At covered completed-goal boundaries, produce the review after reviewed work lands. If `milestone` granularity is enabled, each milestone gets its own customer-facing review; otherwise use `milestone-update`.
- Do not ask `Want me to generate the review?` at a normal PR, milestone, or goal boundary.
- Low context, fatigue, or wanting fresh context is rotation work, not permission to defer the review or media.
- Iteration reviews are evidence only. They are not process authority, continuity handoffs, session journals, or substitutes for validation or goal/milestone completion proof.
