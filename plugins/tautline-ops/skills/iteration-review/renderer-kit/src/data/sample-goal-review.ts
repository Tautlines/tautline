import { GoalReview } from "./schema";

// Bundled SAMPLE so the composition renders out-of-the-box and is editable in
// Remotion Studio. Real renders override this by passing a project's own
// GoalReview JSON at render time:
//
//   minervit-methodology iteration-review-renderer-setup
//   cd ~/.local/state/minervit/renderer-kit
//   npx remotion render src/index.ts IterationReview out/review.mp4 \
//     --props=path/to/<goal-id>.goal-review.json
//
// The content below is a fictional worked example (the Example SaaS "Order
// Catalog Taxonomy" goal) and doubles as the reference for the agent-composed narrative.
export const sampleGoalReview: GoalReview = {
  product: "Example SaaS",
  goalTitle: "Order Catalog Taxonomy",
  kicker: "Example SaaS · Iteration Review",
  why:
    "Teach the system every way a customer can order an item — by quantity, by weight, by configurable options — so the upcoming ordering experience is built on a correct foundation.",
  milestones: [
    { id: "W0", title: "Simpler path for placing an order", pr: "PR #50", status: "complete" },
    { id: "W1", title: "Every product gets the right order style", pr: "PR #51", status: "complete" },
  ],
  highlight: {
    heading: "Seven ways customers order an item — now in the data model",
    items: [
      "Standard pack",
      "Counted per-unit",
      "Custom option",
      "Target-quantity range",
      "Fixed-each prepared",
      "Measured-prepared container",
      "Made-to-order item",
    ],
  },
  quality: {
    tests: "Tested against the ordering scenarios",
    types: "Checked for errors",
    review: "Independently reviewed",
    discipline: "Delivered in a focused slice",
  },
  next: [
    { title: "Catalog Browse", blurb: "Customers see the full catalog — including the featured items." },
    { title: "Mixed-Request Switch", blurb: "The ordering flow: switch a request across the customer order and staff fulfillment." },
  ],
  nextWhy:
    "Foundation first: with the data model settled, each next goal changes a smaller surface and stays easy to review.",
  outro: {
    headline: "Foundation laid.",
    subhead:
      "The data model now describes every way customers order an item — the ordering experience is next.",
  },
  musicUrl: "builtin:minervit-midnight-pulse",
  musicCredit: "Minervit Midnight Pulse",
  musicVolume: 0.12,
};
