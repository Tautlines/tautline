# Iteration Review Policy Reference

This reference keeps the detailed adapter status, `GoalReview` contract, rendering, hosting, publication, delivery-check, content, boundary, and media policy behind the concise `iteration-review` entrypoint. Read it in full before producing, validating, rendering, publishing, or deferring an iteration review.

## Iteration Review

Use this skill when the human operator asks for an iteration review, `/iteration-review`, goal review, or when the adapter has `iterationReview.enabled: true` and a goal has completed. Boundary announcements are non-blocking, but completed goal review delivery is required when the adapter enables the matching target granularity. Internal milestone-complete visibility belongs to the `milestone-update` skill and `publish-milestone-update`; do not turn routine milestone updates into customer-facing videos/pages unless the adapter explicitly opts `iterationReview.granularities` into `milestone`.

## Contract

1. Load the active project adapter and run:

   ```bash
   minervit-methodology iteration-review-status --target . --strict
   ```

   Use `--strict` so the check fails when delivery is enabled but its webhook env var is unset/missing in this environment (otherwise after-merge delivery silently never posts). Wire the webhook env before relying on delivery.

2. Continue only when `iterationReview.enabled` is true. If disabled, state that the project has not opted in and continue the normal authorized work. Do not ask whether to enable it unless the human operator explicitly asked to configure the project.

3. Select a completed goal from explicit human instruction or `.ai-work/GOAL_RUN.json`. Do not invent completion. A review is evidence and communication, not proof that the goal is complete.

4. Compose one `GoalReview` JSON record following `../DATA-CONTRACT.md`. Write it under adapter `iterationReview.recordDir`, usually:

   ```text
   docs/iteration-reviews/<goal-or-milestone-id>/goal-review.json
   ```

   Each review gets its own folder. The generated page is `index.html` beside
   `goal-review.json`; generated media remains outside git and is linked by URL.

5. Validate before rendering. Use adapter-aware validation when publishing or when checking a completed boundary:

   ```bash
   minervit-methodology validate-iteration-review --target . --file <record.json>
   ```

6. If `iterationReview.outputs.page` is true, generate the static page from the validated record:

   ```bash
   minervit-methodology generate-iteration-review-page --target . --record <record.json> --write
   ```

   This command also writes adapter media defaults, such as an approved default
   `musicUrl` and `musicVolume`, into the JSON record when those fields are
   missing. Render video from the updated record.

7. If `iterationReview.outputs.video` is true, prepare the bundled `renderer-kit` with `minervit-methodology iteration-review-renderer-setup`, then render from the user-state cache at `~/.local/state/minervit/renderer-kit/`. Do not install `node_modules` inside the plugin tree. Video, poster, screenshot, and page-media production is agent-owned delivery work, not a human handoff and not a reason to stop. Generated videos, thumbnails, screenshots, posters, clips, and render scratch output must stay out of git. Upload media output to adapter-approved S3/CloudFront hosting and place only the final URL in the JSON record. Use adapter-approved/licensed `musicUrl` or a renderer built-in music token with low `musicVolume`; do not fetch arbitrary audio.

8. After adding `videoUrl` or `posterUrl` to the record, validate and run `generate-iteration-review-page --write` again so the final `index.html` embeds the hosted recap. If `videoUrl` exists and `posterUrl` is absent, the generator adds a built-in SVG poster thumbnail to the video element so embeds are not blank. Prefer a real hosted `posterUrl` when available, but do not stop solely because a custom poster has not been produced. When `iterationReview.outputs.video` is true, the CLI must not publish the review without a hosted `videoUrl`; missing recap video is not a publishable partial stakeholder update.

9. Commit only text artifacts: the JSON record and generated HTML page. Never commit generated videos, screenshots, thumbnails, clips, posters, or other media binaries.

10. After the review PR lands on the base branch, publish stakeholder-facing artifacts through the CLI:

   ```bash
   minervit-methodology publish-iteration-review --target . --record <record.json>
   ```

   This uploads `goal-review.json` and `index.html` to adapter-approved
   S3/CloudFront and, when `iterationReview.delivery.enabled` is true, posts the
   CloudFront page URL to the configured Google Chat webhook. When an active
   goal ledger exists, the review folder slug must match the active `goal_id`
   before validate/publish/delivery-check; fix the folder name before posting,
   never after a Chat card has already been sent. `--skip-chat` is
   not allowed when delivery is enabled unless the human operator approved
   skipping Chat delivery and the command carries `--operator-approval-token
   OPERATOR_APPROVED_PARTIAL_ITERATION_REVIEW`. Do not post a GitHub URL as the
   primary stakeholder link.

   Iteration-review Chat delivery is the recap/link signal, not proof that a
   delayed dev/staging deploy has finished rolling forward. When the adapter
   enables deployment notifications, the deploy/build pipeline must call this
   only after deploy completion and live-site health checks:

   ```bash
   minervit-methodology publish-deploy-ready-update --target . --environment <env> --url <live-url> --iteration-review-url <page-url> --source pipeline
   ```

   If `deploymentNotification.pipeline.required` is true, prove the actual
   deploy workflow contains that command with:

   ```bash
   minervit-methodology deployment-notification-status --target . --strict
   ```

   Then run:

   ```bash
   minervit-methodology iteration-review-delivery-check --target . --record <record.json>
   ```

   A completed-goal close-out is not done until this check passes.

   If rendering or publishing fails because renderer dependencies, hosting, a webhook env var, or another adapter-declared delivery setting is missing, resolve the setup path or name the exact missing credential/config as the blocker after checking the adapter path. Do not say agents do not do videos or media production, do not ask whether the review should be produced, do not hand delivery to the human operator, and do not replace the required review with a note that it is "teed up" for later.

11. Log a boundary event:

   ```bash
   minervit-methodology log-event --target . --event iteration_review --severity ok --plain "<plain outcome>" --next "<next authorized work>"
   ```

## Content Rules

- Write for non-technical product readers first. Make the review feel like a concise product launch note: what is now easier, safer, faster, clearer, or possible; why that matters; what users/admins/operators can now do; why they can trust it; and what comes next.
- Keep technical detail in the optional `technical` block only. PR numbers, repository links, file paths, routes, schemas, database details, test tiers, review rounds, commits, CI mechanics, and implementation jargon must not appear in `why`, `highlight`, `milestones`, `quality`, `next`, `outro`, or top-level `links`.
- Keep customer-facing copy short. `validate-iteration-review` rejects overlong or technical non-technical fields; fix the story instead of bypassing the validator.
- Use real screenshots or screen recordings whenever the change has a visible product surface. If there is no visible surface, frame it as a foundation or trust improvement and say what future capability it unlocks.
- Honor adapter role vocabulary. Do not use forbidden product terms in on-screen copy.
- Use real proof from goal/milestone ledgers, PRs, tests, deploy checks, or delivery summaries. Omit unsupported metrics or claims.
- Generated media should show actual product behavior, not abstract filler. Any screenshot, poster, clip, embedded video, or other page-referenced generated media must use adapter-approved hosting.

## Boundary Behavior

- Boundary announcement is non-blocking. Say a review is available and continue authorized work; do not pause for permission.
- At completed goal boundaries covered by adapter `iterationReview.granularities`, produce the review as required evidence after the reviewed work lands. If an adapter explicitly enables `milestone` granularity for customer-facing milestone reviews, each milestone completion gets its own customer-facing review before the next milestone begins; otherwise use the internal `milestone-update` workflow for milestone completion. `iterationReview.boundary.autoRunAtBoundary` defaults to true and controls automatic generation timing, not whether the completed-boundary review requirement exists.
- Do not ask `Want me to generate the review?` at a normal PR, milestone, or goal boundary.
- Low context, fatigue, marathon-session length, or the desire for a "fresh context" is context-rotation work, not permission to defer a required goal review or its media. Refresh continuity and the session journal, compact/restart/resume when available, then produce and publish the review before goal completion.
- Delivery is also non-blocking. When enabled, publish and post after merge,
  then continue authorized work; do not wait for Chat acknowledgement.
- Iteration reviews are evidence only. They are not process authority, not continuity handoffs, not session journals, and not a substitute for validation or goal/milestone completion proof.

## Implementation Notes

- The renderer kit source lives beside this skill at `renderer-kit/`; dependencies install into `~/.local/state/minervit/renderer-kit/` through `iteration-review-renderer-setup`.
- The data contract lives beside this skill at `../DATA-CONTRACT.md`.
- The generated page command writes a static `index.html` page in the review folder for easy hosting or review.
- `iterationReview.outputs.video: false` disables recap-video rendering only. It is not approval to skip S3/CloudFront setup for page media.
- If S3/CloudFront hosting is not configured, page output may proceed only for a strictly text-only `GoalReview` record that omits `videoUrl`, `posterUrl`, `highlight.image`, and `usage[].src` media references. If the review needs screenshots, posters, clips, embedded video, or any other generated media, treat missing adapter-approved hosting as an adapter setup blocker before generating/publishing that media.
