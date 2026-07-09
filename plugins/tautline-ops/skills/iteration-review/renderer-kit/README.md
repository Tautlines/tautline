# Minervit Iteration-Review Video — Renderer Kit

A small, self-contained [Remotion](https://remotion.dev) project that renders a
~45-second iteration-review video for a completed **goal** (or an explicitly customer-facing milestone review). It is
**data-driven**: the entire video is produced from one `GoalReview` JSON object,
so the same code works for any project. This kit is the proven reference
implementation (the bundled worked example is the fictional Example SaaS "Order Catalog Taxonomy" goal).

## How it works

- The composition `IterationReview` takes a `GoalReview` as its props.
- `GoalReview` is defined as a **Zod schema** (`src/data/schema.ts`) and set as
  the composition `schema`, so props are validated at render time and editable
  in Remotion Studio.
- Optional recap music accepts remote URLs, local `public/` assets, or the
  built-in `builtin:minervit-midnight-pulse` procedural soundtrack.
- Six scenes are arranged with `@remotion/transitions` (`TransitionSeries` +
  `fade()`); total duration is computed by `calculateMetadata` from the scene
  list (`src/data/scenes.ts`), so it stays in sync automatically.
- All motion is `useCurrentFrame()`-derived (Bézier easing / springs) — **no CSS
  transitions/animations** (they don't render). Fonts load via
  `@remotion/google-fonts` for deterministic output.

Scenes, in order: **Intro (goal + why)** → **What users get** → **Highlight grid
(hero)** → **Delivered with quality** → **What's next + why** → **Outro**.

## Install

```bash
minervit-methodology iteration-review-renderer-setup
```

The setup command syncs this source kit to `~/.local/state/minervit/renderer-kit/`
and runs `npm ci` there. Do not install dependencies inside the plugin tree.
First render downloads a headless Chrome shell automatically.

## Render a real video (the normal path)

Pass a project's `GoalReview` JSON with `--props`; it overrides the bundled
sample and is validated against the schema:

```bash
cd ~/.local/state/minervit/renderer-kit
npx remotion render src/index.ts IterationReview out/<goal-id>.mp4 \
  --props=path/to/<goal-id>.goal-review.json
```

See `../examples/example-saas-order-catalog-taxonomy.goal-review.json` for the
shape and `../DATA-CONTRACT.md` for how to build it from run-state.

## Preview / iterate

```bash
cd ~/.local/state/minervit/renderer-kit
npm run studio          # opens Remotion Studio; edit props live in the sidebar
npm run render:sample   # renders the bundled sample to out/sample-iteration-review.mp4
```

## Verify the kit

```bash
cd ~/.local/state/minervit/renderer-kit
npm run typecheck       # tsc --noEmit
npm test                # vitest: schema + duration-math tests
```

Cheap per-scene layout checks before a full render:

```bash
cd ~/.local/state/minervit/renderer-kit
npx remotion still src/index.ts IterationReview out/check.png --frame=120 --scale=0.5 \
  --props=path/to/<goal-id>.goal-review.json
```

## Files

```
src/
  index.ts                  registerRoot
  Root.tsx                  <Composition> schema + defaultProps(sample) + calculateMetadata
  IterationReview.tsx          TransitionSeries of the 6 scenes
  builtinMusic.ts              built-in procedural soundtrack + music URL resolver
  fonts.ts                  @remotion/google-fonts (Inter + JetBrains Mono)
  theme.ts                  palette + font families
  ui.tsx                    Rise / Chip / Kicker / Panel (frame-based, Bézier)
  data/
    schema.ts               GoalReviewSchema (Zod) + GoalReview type  ← the contract
    sample-goal-review.ts   bundled sample (overridden by --props)
    scenes.ts               scene list + transition-aware duration helper
  scenes/                   one file per scene
```

## Known limitations (room for improvement)

- Fixed 6-scene structure and per-scene durations; very long strings can
  overflow. Keep titles short; future work could auto-fit text
  (`@remotion/measuring-text`) or scale durations to content length.
- Single theme/palette; per-product branding (logo, colors) is not yet wired.
- No voiceover/captions yet; the current audio path is background music only.
