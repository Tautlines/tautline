# Iteration-Review Release-Notes Page — prototype

A standalone, self-contained `/iteration-review` release-notes page for a
completed goal/iteration. Built around the fictional Example SaaS **Order Catalog
Taxonomy** goal to show the shape before we host it or generalize it.

## Open it

Open `iteration-review.html` in any browser (double-click it). No build, no
server. When the record includes hosted media URLs, the recap video or images
play inline.

## What's here

| File | What it is |
|---|---|
| `iteration-review.html` | The self-contained page (inline CSS, no external deps except a Google Fonts link). |
| `data/counter-product-taxonomy.json` | The `IterationReview` record that drives it — note the new **`technical`** section alongside the non-technical content. |
| `example-saas-order-catalog-taxonomy-iteration-review.mp4` | Local-dev embedded recap only; production media is hosted and linked by URL. |
| `poster.png` | Local-dev video poster frame only; production media is hosted and linked by URL. |

## Page structure

Hero → embedded video → **What's new** (non-technical, user-facing value) →
**Technical appendix** (collapsible technical detail) → **What's next** → outro.

## Notes / design intent

- **One record → two outputs.** The same `IterationReview` record drives the
  video (non-technical) and this page (non-technical + technical). For the
  prototype the content is inlined in the HTML; production would template the
  page from the JSON.
- **No generated media in git.** Videos, screenshots, posters, clips, and
  thumbnails are git-ignored on purpose. In production they live in **S3 +
  CloudFront** and the page points at CloudFront URLs (`videoUrl`, `posterUrl`,
  `highlight.image`, `usage[].src`); git holds only the record + page source.
- **Left existing living-docs alone.** This is a *new, separate* surface; the
  Gherkin `/behavior` + `/behavior/changelog` pages are untouched. How/whether
  to combine is a later decision.
- **CSS animation here is fine** (this is a real web page) — unlike the Remotion
  video, where CSS animation is forbidden.

## Next decisions (after you've seen it)

Hosting (in-app `/iteration-review` route vs S3 static site), provisioning
S3/CloudFront for all page media, generalizing into the methodology, and whether
to combine with the existing living-docs.

Design notes live in this README and the adjacent `../DATA-CONTRACT.md`.
