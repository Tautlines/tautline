# examples/

- `example-saas-order-catalog-taxonomy.goal-review.json` — a worked, schema-valid
  `GoalReview` record (the Order Catalog Taxonomy goal for the fictional Example SaaS app).

## Where's the example media?

**Not in git — on purpose.** This capability's core rule is that generated media
never lives in git; videos, posters, screenshots, clips, and thumbnails go to
S3 + CloudFront and are referenced by URL. The package models that rule, so no
media binary is committed here.

To produce the example video from the record above:

```bash
tautline iteration-review-renderer-setup
cd ~/.local/state/minervit/renderer-kit
npx remotion render src/index.ts IterationReview /tmp/example-saas-order-catalog-taxonomy.mp4 \
  --props=<methodology-repo>/plugins/tautline-ops/skills/iteration-review/examples/example-saas-order-catalog-taxonomy.goal-review.json
```

In production the rendered file and any page screenshots/posters/clips are
uploaded to object storage and the `/iteration-review` page references them via
CloudFront URLs (`videoUrl`, `posterUrl`, `highlight.image`, `usage[].src`).
