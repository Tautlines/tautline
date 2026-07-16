# Tautline Roadmap

This is the public, directional roadmap for Tautline — the governor for AI
coding agents. It exists so product direction is developed in the open, under
community scrutiny.

It is directional, not a commitment: items can move, split, or be dropped as
we learn. The work items below are tracked as issues on the public repository
and backlinked here; **the issue is the source of truth for its status**, and
this file is the map, not the tracker.

## 0.9.x direction

- [ ] **Package split** — break the single-file CLI (`bin/tautline`) into an
  importable package. The design exists and the refactor is behavior-neutral;
  it is a maintainability item so contributors can navigate the codebase.
  (0.10.0 proved it is not a prerequisite for the packaged install story.)
  ([#11](https://github.com/Tautlines/tautline/issues/11))
- [x] **Installable package** — `pipx install tautline` via a real
  `[project.scripts]` entry point. Shipped in 0.10.0: a thin wrapper package
  embeds the released tree, so it did not need the package split after all.
  ([#13](https://github.com/Tautlines/tautline/issues/13))
- [ ] **Guided onboarding** — when a session starts in a repository with no
  adapter, offer to run the onboarding interview instead of requiring the
  operator to know about `tautline init`. Guide, don't force.
  ([#14](https://github.com/Tautlines/tautline/issues/14))
- [ ] **Update prompts** — when a newer framework release is available,
  surface it and offer the update path, rather than silently skipping under
  the pinned update policy.
  ([#15](https://github.com/Tautlines/tautline/issues/15))
- [ ] **Compatibility sunset** — the `minervit-methodology` launcher name,
  `MINERVIT_*` environment fallbacks, and the legacy
  `.minervit-ai-delivery.json` marker remain supported through 0.x and are
  removed in 1.0. New adopters should use the `tautline` names exclusively.
  ([#16](https://github.com/Tautlines/tautline/issues/16))

## Recently shipped

- **0.9.2–0.9.5** — config-surface rebrand (`~/.config/tautline/tautline.env`, with the
  legacy config path kept as a fallback), a brand-copy sweep across the reader-facing
  docs, a Claude Code plugin marketplace manifest (`/plugin marketplace add
  tautlines/tautline`), and a truth pass over the public documentation surface.
- **0.9.1** — no dead ends at launch: a trust-policy hold on an available update reports
  `held` and launch continues on the trusted retained checkout, with the repair command
  printed alongside; generated Claude launchers print an exact executable remedy with
  every gate failure. The checkout still never advances to unverified code.
- **0.9.0** — sanitized instrumentation replaces narrative session-journal publication:
  a closed-vocabulary instrumentation record with no product-information capacity is the
  only session evidence that can reach a remote.
- **0.8.0** — the Tautline rename: `tautline` CLI (with the legacy `minervit-methodology`
  compatibility shim), `TAUTLINE_*` environment variables (with `MINERVIT_*`
  fallback), `.tautline.json` marker (legacy marker still resolves), plugins
  renamed to `tautline-core`/`tautline-ops`.
- **0.7.0** — initial public (open-core) release.

## How to influence this roadmap

Open a discussion or an issue. Roadmap changes land as PRs to this file, so
the reasoning stays reviewable.
