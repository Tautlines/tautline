# public/ — screenshot & clip assets

Place screenshots and short screen-recording clips of the system here. Reference
them from a `GoalReview` JSON by **filename relative to this folder**:

```json
{
  "highlight": { "heading": "...", "items": ["..."], "image": "order-flow.png" },
  "usage": [
    { "src": "order-flow.png", "caption": "A customer placing a counter order" },
    { "src": "staff-queue.mp4", "caption": "Staff working the prep queue" }
  ]
}
```

- `.mp4` / `.webm` / `.mov` render as video; other files render as images.
- Remote `https://…` URLs are also accepted in `src` / `image` and used directly.
- The renderer resolves non-URL values with Remotion's `staticFile()`.
