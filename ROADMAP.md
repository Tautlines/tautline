# Tautline Roadmap

This is the public, directional roadmap for Tautline — the governor for AI
coding agents. It exists so product direction is developed in the open, under
community scrutiny.

It is directional, not a commitment: items can move, split, or be dropped as
we learn. Once an item has a GitHub issue, **the issue is the source of truth
for its status**; this file is the map, not the tracker. After the public
repository is live, each item below gets an issue (and release-sized items a
milestone), backlinked here.

## 0.9.0 direction

- [ ] **Package split** — break the single-file CLI (`bin/tautline`) into an
  importable package. The design exists and the refactor is behavior-neutral;
  it is the prerequisite for a standard `pip`/`pipx` install story and for
  contributors to navigate the codebase. Target: 0.9.0.
- [ ] **Installable package** — `pipx install tautline` via a real
  `[project.scripts]` entry point. Follows the package split.
- [ ] **Guided onboarding** — when a session starts in a repository with no
  adapter, offer to run the onboarding interview instead of requiring the
  operator to know about `tautline init`. Guide, don't force.
- [ ] **Update prompts** — when a newer framework release is available,
  surface it and offer the update path, rather than silently skipping under
  the pinned update policy.

## Recently shipped

- **0.8.0** — the Tautline rename: `tautline` CLI (with `minervit-methodology`
  compatibility shim), `TAUTLINE_*` environment variables (with `MINERVIT_*`
  fallback), `.tautline.json` marker (legacy marker still resolves), plugins
  renamed to `tautline-core`/`tautline-ops`.
- **0.7.0** — initial public (open-core) release.

## How to influence this roadmap

Open a discussion or an issue. Roadmap changes land as PRs to this file, so
the reasoning stays reviewable.
