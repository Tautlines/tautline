# Delivery Communications

This reference keeps detailed stakeholder-facing and operator-facing delivery
communication procedures out of the main operating manual.

## Iteration Reviews

Iteration reviews are customer-facing communication artifacts for completed goals. Project opt-in is optional, but when adapter `iterationReview.enabled` is true, completed goal boundaries covered by `iterationReview.granularities` require a review. They translate run evidence into plain language: what changed, why it matters, what users/admins/operators can now do, what proof exists, and what comes next. Keep internal process/meta details out of the customer-facing sections.

Adapters control the capability through `iterationReview`. Existing projects default to disabled:

```json
{
  "iterationReview": {
    "enabled": false,
    "granularities": ["goal"],
    "outputs": { "page": true, "video": true },
    "boundary": { "announce": true, "autoRunAtBoundary": true },
    "recordDir": "docs/iteration-reviews",
    "hosting": {
      "store": "s3",
      "bucket": "",
      "keyPattern": "<project>/iteration-reviews/<target-id>/<media-file>",
      "cdn": "cloudfront",
      "access": "private-cdn",
      "baseUrl": ""
    },
    "delivery": {
      "enabled": false,
      "trigger": "after-merge",
      "provider": "google-chat-webhook",
      "webhookEnv": "",
      "chatSpace": "",
      "primaryUrl": "cloudfront-page",
      "dedupe": true,
      "sentStateDir": ".ai-work/iteration-review-delivery"
    },
    "video": {
      "music": {
        "enabled": true,
        "source": "adapter-approved",
        "defaultUrl": "",
        "volume": 0.18
      }
    },
    "rendererVersion": "0.2.1"
  }
}
```

Check the active lane configuration with:

```bash
tautline iteration-review-status --target .
```

The workflow is text-first. Compose a `GoalReview` JSON record in its own review folder under `iterationReview.recordDir`, validate it, and generate the static page:

```bash
tautline validate-iteration-review --target . --file docs/iteration-reviews/<id>/goal-review.json
tautline generate-iteration-review-page --target . --record docs/iteration-reviews/<id>/goal-review.json --write
```

Iteration reviews are customer-facing product communication. The main record fields must read like a short product launch note: what changed for users, why it matters, what capability it unlocks, why the reader can trust it, and what comes next. Keep PR numbers, repository links, file paths, routes, schemas, databases, behavior contracts, specs, Gherkin, test tiers, review rounds, commits, CI mechanics, and implementation jargon out of `why`, `highlight`, `milestones`, `quality`, `next`, `outro`, and top-level `links`; put that detail only in the optional collapsed `technical` appendix. `validate-iteration-review` enforces length limits and rejects technical/process jargon in customer-facing fields.

Generated pages and videos use a light, modern product-report style by default. When a review record has `videoUrl` but no `posterUrl`, the page generator writes a built-in SVG poster into the video element so embedded recaps are never blank by default. A project can still provide a hosted `posterUrl` for a real branded thumbnail. Video output uses the bundled renderer kit in the `iteration-review` skill directory. Generated videos, thumbnails, screenshots, posters, clips, and render scratch output are not product source. Do not commit them. Upload media only through adapter-approved hosting, currently S3 plus CloudFront by default, and store the resulting URL in the JSON record. When video output is enabled, use adapter-approved/licensed `musicUrl` and a low `musicVolume` for a more engaging recap when the project has approved audio available; do not fetch random audio or commit music/video binaries.

When `iterationReview.outputs.video` is true, adapter-aware validation and publish require a hosted `videoUrl` that uses the configured S3/CloudFront `baseUrl`, and the generated `index.html` must embed that hosted recap. A missing hosted recap is not a publishable partial stakeholder update. The approval token is still required for `--skip-chat` when `iterationReview.delivery.enabled` is true.

After the review lands on the base branch, publish the stakeholder-facing page:

```bash
tautline publish-iteration-review --target . --record docs/iteration-reviews/<id>/goal-review.json
```

`publish-iteration-review` uploads `goal-review.json` and `index.html` to the adapter's S3/CloudFront path and prints the CloudFront page URL. When an active goal ledger exists, validate/publish/delivery-check reject review folders whose slug does not match the active `goal_id` before any Chat post, so recovery cannot create duplicate cards under a wrong key. When `iterationReview.delivery.enabled` is true, it posts that CloudFront page URL to the configured Google Chat webhook and dedupes repeated sends. The primary stakeholder link is the S3/CloudFront page, not GitHub, because customers, operators, and business reviewers may not have repository access.

At goal close-out, run:

```bash
tautline iteration-review-delivery-check --target . --record docs/iteration-reviews/<id>/goal-review.json
```

This verifies the required page/video outputs and the Google Chat delivery marker when delivery is enabled. Do not declare the completed-goal review done until this check passes.

The same check is enforced by `goal-advance --event goal-complete --iteration-review-record <record>` for adapters that enable goal iteration reviews.

`iterationReview.outputs.video: false` disables rendering a recap video. It does not mean S3/CloudFront is unnecessary. Page output can proceed without media hosting only when the review is strictly text-only and the `GoalReview` record omits `videoUrl`, `posterUrl`, `highlight.image`, and `usage[].src` media references. Any screenshot, poster, clip, embedded video, or other generated media used by the page belongs in adapter-approved S3/CloudFront hosting, not git.

Boundary notices are non-blocking. If `iterationReview.boundary.announce` is true, the agent may say an iteration review is available and continue authorized work. It must not ask whether to pause. `iterationReview.boundary.autoRunAtBoundary` defaults to true and controls automatic generation timing; it does not waive the completed-boundary review requirement for opted-in projects. Delivery is also non-blocking: after merge, publish/post and continue; do not wait for Chat acknowledgement.

Iteration reviews are evidence and communication only. They are not process authority, not continuity handoffs, not session journals, and not proof that a goal or milestone is complete.

## Deployment Ready Notifications

Iteration review delivery tells stakeholders what changed and where to read/watch the recap. It does not prove the deployed dev/staging site has finished rolling forward. When the deploy itself completes later, the deploy closeout path should send a separate ready-to-review Chat note.

Adapters control this through `deploymentNotification`. For existing projects that already enable `iterationReview.delivery`, deployment notification auto-enables and reuses the iteration-review Google Chat webhook unless the adapter sets its own `webhookEnv`:

```json
{
  "deploymentNotification": {
    "enabled": true,
    "trigger": "deploy-ready",
    "provider": "google-chat-webhook",
    "webhookEnv": "",
    "reuseIterationReviewWebhook": true,
    "chatSpace": "Product",
    "dedupe": true,
    "sentStateDir": ".ai-work/deployment-notification-delivery",
    "maxChars": 3000,
    "pipeline": {
      "required": true,
      "mode": "ci-post-deploy",
      "evidencePaths": [".github/workflows/deploy.yml"],
      "requiredCommand": "tautline publish-deploy-ready-update",
      "healthCheckBeforeNotify": true
    }
  }
}
```

Auto-inherited support is intentionally advisory for existing projects: strict pipeline enforcement starts when the project adapter explicitly configures `deploymentNotification.pipeline.required: true` with evidence paths. That lets existing lanes keep starting while each product lane installs the real deploy workflow hook.

Check configuration with:

```bash
tautline deployment-notification-status --target .
```

The reliable path is the build/deploy pipeline itself. The notification step belongs after deploy completion and live-site health checks in the real CI/deploy workflow. Generate a copy/paste shell step with:

```bash
tautline deployment-notification-pipeline-snippet --target .
```

The pipeline step should run:

```bash
tautline publish-deploy-ready-update \
  --target . \
  --environment dev \
  --url <live-dev-url> \
  --iteration-review-url <published-review-url> \
  --source pipeline \
  --summary "The latest reviewed change is live and ready for product review."
```

The command posts a Google Chat card with the live URL, optional iteration-review URL, deployed commit/ref, source (`pipeline` or `agent`), and short summary. It dedupes repeated deploy notifications by source, environment, URL, commit, review URL, and summary within the same persisted workspace or deploy job state; fresh ephemeral CI runners should still call it only after their own health checks pass. Store webhook URLs only in the environment variable reported by `deployment-notification-status`; never commit webhook URLs.

`deployment-notification-status --strict` treats pipeline evidence as the enforcement surface. If `deploymentNotification.pipeline.required` is true, the adapter must name one or more project-relative `evidencePaths`, and each file must contain the configured `requiredCommand` on a non-comment line. Agent-session posting is a manual fallback only; it does not satisfy reliable deploy-ready notification unless the deploy pipeline also contains the hook. Projects with truly manual deploys may set `pipeline.required: false`, but then status reports the notification path as not pipeline-integrated. The status command proves the pipeline hook exists; workflow authors must still place it after deploy health checks.

## Deploy Health Gate

When an adapter deployment target declares `deployHealth`, startup and status
must treat deployment history as current work health, not as optional
background context. Run:

```bash
tautline deploy-health --target .
```

A latest failed deploy, repeated deploy failures, no recent successful deploy,
missing GitHub Actions access, or unreadable deploy run history is a
highest-priority blocker until investigated and surfaced. Branch status,
local tests, and an iteration-review Chat card do not prove that the live
target is healthy.

## Milestone Updates

Milestone updates are internal operator visibility artifacts. They are meant for the product owner/operator to understand what just completed, how it was built, what validation happened, what risks remain, and what happens next. They are not customer-facing release notes and they do not require a video or S3 review page.

Adapters control the capability through `milestoneUpdate`. Current project adapters can opt in by setting `enabled: true`; unmanaged or future projects stay disabled until their adapter enables it:

```json
{
  "milestoneUpdate": {
    "enabled": false,
    "trigger": "milestone-complete",
    "provider": "google-chat-webhook",
    "webhookEnv": "",
    "chatSpace": "Product Milestones",
    "dedupe": true,
    "sentStateDir": ".ai-work/milestone-update-delivery",
    "maxChars": 4000
  }
}
```

Check the active lane configuration with:

```bash
tautline milestone-update-status --target .
```

At a completed milestone boundary, compose a concise internal update with these headings and publish it:

```bash
tautline publish-milestone-update --target . --milestone <milestone-id-or-title> --stdin
```

Required headings:

```markdown
## Plain English
## Progress
## What Changed
## Validation
## Next
## Technical Details
```

`publish-milestone-update` posts a professional Google Chat card to the configured webhook and dedupes repeated sends by milestone/content hash. When an active goal ledger exists, short milestone keys such as `M3` are canonicalized to the active milestone title before the delivery marker is written, so the completion gate and publisher share one identity. Store the webhook URL in the environment variable named by `milestoneUpdate.webhookEnv`; never commit webhook URLs. For Minervit product lanes that use the shared Product Milestones space, use `MINERVIT_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK`.

`milestone-update-status --strict` and `methodology-status --fail-on-drift` fail when `milestoneUpdate.enabled` is true and the configured webhook env value is missing. `goal-advance --event milestone-complete` also refuses to mark a milestone complete until the Product Milestones update delivery marker exists. Install the webhook once per machine as a local export; `install-cli` preserves non-managed local exports in `~/.config/tautline/tautline.env` so this value survives normal methodology updates.

## Product Chat Notes

Product Chat notes are quick, human-requested messages to a project's product Google Chat space. Use them when the operator wants to drop a short summary, reminder, decision, question, or heads-up into the product room without creating a milestone update, iteration review, RCA, or session journal.

Adapters control the capability through `productChat`. Existing projects default to disabled unless their adapter opts in:

```json
{
  "productChat": {
    "enabled": false,
    "provider": "google-chat-webhook",
    "webhookEnv": "",
    "chatSpace": "Product",
    "maxChars": 6000
  }
}
```

Publish a note with:

```bash
tautline publish-product-note --target . --title "Short title" --stdin
```

The command also supports `--summary "..."` and `--content-file <path>`. It validates that the note is non-empty, below the configured size limit, and does not contain webhook URLs or secret-looking values. Store the webhook URL in the environment variable named by `productChat.webhookEnv`; never commit webhook URLs.
