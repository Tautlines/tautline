# Documentation Index

This is the map for the Tautline docs tree. The top-level [`README.md`](../README.md) is
the public entrypoint — pitch, quickstart, comparison, FAQ. Everything here goes deeper for
maintainers, advanced adopters, and anyone auditing how the framework's enforcement
actually works.

## Reading path

1. **Quickstart** — start at the root [`README.md`](../README.md#quickstart) to clone,
   install the CLI, and run `init --target` against a project.
2. **Operating manual** — [`reference/operating-manual.md`](reference/operating-manual.md)
   is the full reference for onboarding projects, running lanes, and the day-to-day
   maintainer workflow.
3. **Concepts** — [`product/positioning.md`](product/positioning.md) covers the
   three-layer authority model (canonical policy, adapter, tool behavior), the
   differentiated mechanisms, and the honest enforcement-tier split between Claude and
   other runtimes.
4. **Capability reference** —
   [`reference/plugin-capability-catalog.md`](reference/plugin-capability-catalog.md)
   lists what the plugin does end to end, and
   [`reference/policy-module-index.md`](reference/policy-module-index.md) is the human
   map of the modular canonical policy source.
5. **Operations** — [`reference/operations/release-engineering.md`](reference/operations/release-engineering.md)
   covers release gates, the public contract manifest, and how adopters pin the stable
   or experimental framework channel.

## Migrations

[`releases/migrations/`](releases/migrations/) is machine-consumed deprecation tracking,
not narrative documentation — one JSON file per release, read by the update tooling to
decide whether a pinned channel needs an operator-visible migration note.
