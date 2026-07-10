import { z } from "zod";

const MilestoneSchema = z.object({
  id: z.string(), // "W0"
  title: z.string().max(120),
  pr: z.string(), // "PR #50"
  status: z.literal("complete"),
});

// A screenshot or short clip of the real system in use. `src` is either a local
// dev path in the renderer kit's `public/` folder or a production CloudFront URL.
// Generated production media is hosted, not committed to git.
// `.mp4`/`.webm`/`.mov` render as video; anything else renders as an image.
const MediaShotSchema = z.object({
  src: z.string(),
  caption: z.string().max(150).optional(), // plain-language: what the user is doing/seeing
});

export const GoalReviewSchema = z.object({
  product: z.string().max(48), // "Example SaaS"
  goalTitle: z.string().max(86), // "Order Catalog Taxonomy"
  kicker: z.string().max(72), // "Example SaaS · Iteration Review"
  why: z.string().max(520), // plain-language, non-technical reason this matters to users
  milestones: z.array(MilestoneSchema), // what shipped
  highlight: z.object({
    heading: z.string().max(90), // one plain-language line — the user-facing capability
    items: z.array(z.string().max(150)).max(8), // short, non-technical value points
    image: z.string().optional(), // optional hero screenshot; CloudFront URL in production
  }),
  // Optional "see it in action" scene. Prefer real screenshots/clips of system
  // usage. Omit entirely (or empty) to skip the scene.
  usage: z.array(MediaShotSchema).max(4).optional(),
  quality: z.object({
    // Keep these as brief, plain-language trust signals (not jargon).
    tests: z.string().max(140),
    types: z.string().max(140),
    review: z.string().max(140),
    discipline: z.string().max(140),
  }),
  next: z.array(z.object({ title: z.string().max(86), blurb: z.string().max(220) })), // what's next
  nextWhy: z.string().max(360), // why these are next (plain language)
  outro: z.object({ headline: z.string().max(90), subhead: z.string().max(190) }),

  // ── Fields below are consumed by the release-notes PAGE, not the video. ──
  // The video renderer ignores them; including them here keeps a single
  // "one record → two outputs" contract (video + /iteration-review page).
  date: z.string().optional(), // ISO date the goal/milestone completed
  status: z.string().optional(), // e.g. "Completed"
  videoUrl: z.string().optional(), // page's <video> src — a CloudFront URL in prod
  posterUrl: z.string().optional(), // page's <video> poster image src — a CloudFront URL in prod
  musicUrl: z.string().optional(), // optional adapter-approved music URL/local public asset for recap video
  musicCredit: z.string().optional(), // optional human-readable credit for the chosen track
  musicVolume: z.number().min(0).max(1).optional(), // defaults low so narration/visual rhythm stays primary
  links: z.array(z.object({ label: z.string(), url: z.string() })).optional(),
  // Technical release notes — shown in the page's collapsible "under the hood"
  // section, kept OUT of the video. Source from the goal artifact + GOAL_RUN.
  technical: z
    .object({
      summary: z.string(),
      changes: z.array(z.string()),
      evidence: z.array(z.string()),
      prs: z.array(z.object({ id: z.string(), title: z.string() })),
    })
    .optional(),
});

export type Milestone = z.infer<typeof MilestoneSchema>;
export type MediaShot = z.infer<typeof MediaShotSchema>;
export type GoalReview = z.infer<typeof GoalReviewSchema>;
