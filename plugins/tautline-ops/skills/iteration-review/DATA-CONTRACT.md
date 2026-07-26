# Data Contract: `GoalReview`

The renderer kit consumes exactly one object, `GoalReview` (defined as a Zod
schema in `renderer-kit/src/data/schema.ts`). The capability's job, per project,
is to **produce a valid `GoalReview` JSON from the project's run-state and goal
artifact**, then render it. This document is the bridge.

## The shape

```ts
GoalReview = {
  product: string,        // "Example SaaS"
  goalTitle: string,      // "Order Catalog Taxonomy"
  kicker: string,         // "Example SaaS · Iteration Review"  (or "… · Milestone Review")
  why: string,            // 1–2 short sentences, plain-language business reason
  milestones: {           // what shipped — one row each (≤ ~5 reads well)
    id: string,           // "W0", "W1", "M1.3" …
    title: string,        // short user/business value, not implementation detail
    pr: string,           // short plain proof label; no PR numbers/repo links in customer-facing rows
    status: "complete",
  }[],
  highlight: {            // the hero — the user-facing capability this enables
    heading: string,      // one plain-language line: what users can now do
    items: string[],      // 1–5 short, non-technical value points
    image?: string,       // optional hero screenshot; CloudFront URL in production
  },
  usage?: {               // OPTIONAL "see it in action" scene — prefer real media
    src: string,          // screenshot/clip; CloudFront URL in production; .mp4/.webm/.mov = video
    caption?: string,     // plain-language: what the user is doing/seeing
  }[],                    // up to 4; omit to skip the scene entirely
  quality: {              // brief, PLAIN-LANGUAGE trust signals (not jargon)
    tests: string,        // e.g. "Tested against real customer paths"
    types: string,        // e.g. "Checked for errors"
    review: string,       // e.g. "Independently reviewed"
    discipline: string,   // e.g. "Delivered in small, reviewable steps"
  },
  next: {                 // what's next + why (1–3 cards)
    title: string,
    blurb: string,        // ≤ ~220 chars
  }[],
  nextWhy: string,        // why these are next / why deferred
  outro: { headline: string, subhead: string },

  // ── PAGE-ONLY fields (ignored by the video; used by the /iteration-review
  //    release-notes page). This is the "one record → two outputs" seam. ──
  date?: string,          // ISO date completed
  status?: string,        // "Completed"
  videoUrl?: string,      // page <video> src — CloudFront URL in production
  posterUrl?: string,     // page <video> poster image src — CloudFront URL in production; if omitted, the page generator creates a built-in SVG poster
  musicUrl?: string,      // optional adapter-approved music URL/local public asset for recap video
  musicCredit?: string,   // optional credit for the chosen track
  musicVolume?: number,   // optional 0..1 volume; defaults low for background music
  links?: { label: string, url: string }[], // customer-accessible links only; repo/PR links belong in technical.prs
  technical?: {           // collapsible "under the hood" — kept OUT of the video
    summary: string,
    changes: string[],    // notable technical changes
    evidence: string[],   // tests / typecheck / review / discipline (verbatim)
    prs: { id: string, title: string }[],
  },
}
```

Examples:
- video props: `examples/example-saas-order-catalog-taxonomy.goal-review.json`
- full record incl. page fields: `release-notes-page/data/counter-product-taxonomy.json`

## Two outputs from one record

The same `GoalReview` drives both deliverables:
- **The video** (the renderer kit) uses the non-technical fields and ignores
  `technical`/`videoUrl`/etc.
- **The `/iteration-review` page** uses everything: the non-technical sections
  *plus* the `technical` block (in a collapsible "under the hood" section) and
  the embedded video at `videoUrl`.

`outputs.video: false` disables rendering the recap video; it does not make
media hosting unnecessary. A page-only review may be strictly text-only, but
any page record that uses `videoUrl`, `posterUrl`, `highlight.image`, or
`usage[].src` must point at adapter-approved hosting such as S3 + CloudFront in
production. Generated screenshots, posters, clips, and videos are never git
artifacts.

If `videoUrl` is present and `posterUrl` is omitted, `generate-iteration-review-page`
adds a built-in SVG poster directly to the video element so the embedded recap
is inviting instead of blank. A hosted `posterUrl` is still preferred when the
project has a real branded thumbnail or captured poster frame.

When `outputs.video` is true, a recap video should not be silent by default.
Use `musicUrl` only for adapter-approved/licensed music, local renderer-kit
assets deliberately provided by the project, or the renderer built-in token
`builtin:minervit-midnight-pulse`. Keep `musicVolume` low enough that the
visuals and plain-language story remain primary. Do not fetch random audio or
commit generated music/video binaries to git.

`technical` is the one place technical language is expected — it is optional,
visually separated, collapsed by default on the generated page, and never
appears in the video or the page's non-technical sections. Source it from the
goal artifact + `GOAL_RUN.json` (PRs, tests, type/review evidence, the concrete
changes). The page prototype proving this shape lives in `release-notes-page/`
(open `iteration-review.html`).

## Source → field mapping

Inputs available in every subscribing lane:

- `.ai-work/GOAL_RUN.json` (`schema: minervit-goal-run/v1`) — goal-level run-state.
- `.ai-work/MILESTONE_RUN.json` (`schema: minervit-milestone-run/v1`) — milestone-level.
- The goal artifact under `goalArtifacts.sourceOfTruth` (e.g.
  `docs/product/specs/goals/<goal>.goal.md`).
- Optionally the `delivery-summary` skill output (already plain-English).

### For a GOAL review (from `GOAL_RUN.json` + goal artifact)

| `GoalReview` field | Source | Notes |
|---|---|---|
| `product` | `GOAL_RUN.project` | — |
| `goalTitle` | goal artifact H1 / `goalId` | Humanize; drop the "Goal Plan:" prefix. |
| `kicker` | `"${product} · Iteration Review"` | — |
| `why` | artifact `## Desired Outcome` + `## User, Business, Operator, Or Delivery Benefit` | **Agent-composed**, plain language, honest (see guardrails). |
| `milestones[]` | `GOAL_RUN.milestones[]` where `status == "complete"` | `id` = title prefix (e.g. "W0"); `pr` = a short plain proof label such as `"Live proof"` or `"Ready for pilot"`; put PR refs in `technical.prs`, not customer-facing rows; shorten the verbose `title`. |
| `highlight.items` | artifact / `validationProof` | The concrete things built (e.g. the 7 fulfillment shapes). ≤ 8. |
| `highlight.heading` | agent one-liner | Plain summary of the user-facing capability. |
| `highlight.image` | preview screenshot (optional) | Hero screenshot of the system; put the file in the kit `public/` (or use a URL). |
| `usage[]` | screenshots/clips (optional) | Real captures of the system in use, with plain-language captions. Source from the project's preview/deploy or existing screenshot tooling. Strongly preferred when available. |
| `quality.*` | `validationProof` / `milestones[].validationEvidence` / `review` config | Pull real numbers/verdicts only (tests, typecheck, cross-model review, scope discipline). |
| `next[]` | artifact `## Deferred Followon Goals` (fallback: `GOAL_RUN.nextAction`) | Title + short blurb per follow-on goal. |
| `nextWhy` | artifact deferral rationale | Why these are next / foundation-first reasoning. |
| `outro` | agent-composed | Honest one-line headline + subhead. |

### For a MILESTONE review (from `MILESTONE_RUN.json`)

Same shape; map `MILESTONE_RUN.items[]` (completed) onto `milestones[]` (use
`item.pr`, `item.title`), set `kicker` to `"… · Milestone Review"`, and source
`next`/`nextWhy` from `nextAction` and the parent goal's remaining milestones.

## Content philosophy (most important)

The audience is **purely non-technical product readers**. Compose for them.
The review should feel like a concise product launch note, not an engineering
status dump.

- **Make it desirable.** Lead with what is now easier, safer, faster, clearer,
  or possible. Use confident product language and concrete user outcomes. Do
  not narrate the implementation.
- **Plain, non-technical language wherever possible.** Avoid jargon at all costs.
  Technical wording is acceptable *only* when a goal is purely technical in
  nature with no user-facing framing available — and even then, translate the
  benefit first and move the technical detail to `technical`.
- **Lead with user-facing system behavior and value.** Describe what the system
  now *does for users* and **what functionality the change enables** — not how it
  was built. Accentuate the highest-value changes; don't recite a changelog.
- **Never put planning or build-process artifacts in "what users get".** Phrases
  like "wrote the behavior contract", "authored specs", "reviewed Gherkin",
  "validated tests", or "implemented the route" describe how the team worked, not
  what users receive. Translate them into user capabilities, or move them to
  `technical.evidence`.
- **Show the system in use.** Use real screenshots or short screen-recording clips
  (`highlight.image`, `usage[]`) **wherever possible** — seeing the product beats
  describing it. Capture from the project's preview/deploy or existing screenshot
  tooling.
- **`milestones` / `quality` are supporting, not the story.** Milestones should
  read as outcomes ("Recovery time appears in the dashboard"), not tasks
  ("GET /insights route wired"). Keep `quality` as brief, plain-language trust
  signals ("tested against real customer paths", "independently reviewed"), not
  engineering jargon.
- **Use the technical appendix deliberately.** PR numbers, file paths, routes,
  schemas, database details, test tiers, review rounds, commits, and CI mechanics
  belong only in `technical`, never in `why`, `highlight`, `milestones`,
  `quality`, `next`, or `outro`.

## Guardrails (mandatory)

1. **Honesty over polish.** If the goal made no customer-visible change (schema,
   infra, refactor), frame it as *"groundwork laid"* / *"foundation"* — never
   imply a shipped end-user feature. The Example SaaS example does this deliberately
   (it is the rare purely-technical case where some technical framing is
   unavoidable — most goals should read entirely in user-facing terms).
2. **Evidence only.** Every number/claim must trace to run-state or the artifact.
   No invented metrics, no rounding up. Omit a `quality` line rather than fake it.
3. **Respect the adapter's role vocabulary.** Honor
   `behaviorSpecs.roleVocabulary` (`allowed` / `forbidden`) in all on-screen copy.
   (E.g. an adapter may forbid "stakeholder/stakeholders" in product text — use
   `customer` / `owner` / `staff` even though the *audience* is stakeholders.)
4. **Keep strings short.** Hard validation rejects long or technical
   customer-facing copy. Current limits: `goalTitle` ≤ 86 chars, `why` ≤ 520,
   `milestones[].title` ≤ 120, `highlight.heading` ≤ 90,
   `highlight.items[]` ≤ 150, `quality.*` ≤ 140, `next[].title` ≤ 86,
   `next[].blurb` ≤ 220, `nextWhy` ≤ 360, `outro.headline` ≤ 90, and
   `outro.subhead` ≤ 190. Prefer shorter than the maximum.
5. **Validate before render.** The produced JSON MUST pass
   `GoalReviewSchema.parse(...)` and `minervit-methodology
   validate-iteration-review`. The CLI validator also rejects technical/process
   jargon in customer-facing fields. Fix and re-validate on failure; never
   render unvalidated content.

## Producing the JSON (agent-composed, validated)

The chosen flow is: an agent (Claude, via the `/iteration-review` skill) reads the
run-state + goal artifact (+ existing `delivery-summary`), composes the
`GoalReview` honoring the guardrails above, writes it to
`<recordDir>/<goal-id>/goal-review.json`, validates it against the schema, and
runs `generate-iteration-review-page --write`. That generator writes
adapter-approved defaults such as `musicUrl` and `musicVolume` into the record
when the project adapter provides them and the record omitted them. The agent
then invokes the renderer with `--props` when video is enabled, uploads the
generated media, updates the record with `videoUrl` and, when available, a
hosted `posterUrl`, validates again, and regenerates
`<recordDir>/<goal-id>/index.html`. If no custom `posterUrl` exists, the page
generator supplies a built-in SVG poster automatically. The deterministic parts of
the mapping table can be pre-filled mechanically; the `why`,
`highlight.heading`, `nextWhy`, and `outro` are the agent's narrative judgment.

## Publishing and stakeholder delivery

After the review PR is merged, publish from the merged mainline checkout:

```bash
tautline publish-iteration-review --target . --record docs/iteration-reviews/<goal-id>/goal-review.json
```

`publish-iteration-review` uploads both `goal-review.json` and `index.html` to
the adapter's S3/CloudFront path and, when `iterationReview.delivery.enabled` is
true, posts the CloudFront page URL to the configured Google Chat webhook. The
Chat message links to the public/stakeholder-facing S3/CloudFront page, not to
GitHub, because stakeholders may not have repository access.

When adapter `iterationReview.outputs.video` is true, adapter-aware validation
and publish require `videoUrl` to point at the adapter's hosted S3/CloudFront
base URL. Missing recap video is not a publishable partial stakeholder update.
When adapter delivery is enabled, skipping Google Chat requires an explicit
operator approval token. Full completed-goal close-out should pass
`iteration-review-delivery-check`.
