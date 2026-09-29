# Documentation

Start with the [quickstart](../README.md#quickstart). Then use the reference for the workflow
you need; `tautline --help` is the current command inventory.

| Need | Reference |
| --- | --- |
| Understand the product | [Direction](product/positioning.md), [roadmap](../ROADMAP.md) |
| Coordinate agents in sibling worktrees | [Shared work](reference/work.md) |
| Select and finish backlog work | [Backlog](reference/backlog.md) |
| Resume a session | [Handoffs](reference/handoffs.md) |
| Inspect available plugins and commands | [Capability catalog](reference/plugin-capability-catalog.md) |
| Migrate older project instructions | [Lean migration](reference/lean-migration.md) |
| Configure restricted builder credentials | [Builder lanes](builder-lanes.md) |
| Install, get support, or uninstall | [Support and removal](product/support-sla-model.md) |
| Contribute or release | [Contributing](../CONTRIBUTING.md), [release procedure](reference/releases.md) |
| Understand data and security | [Privacy](../PRIVACY.md), [security](../SECURITY.md) |

The repository's development process is in [CLAUDE.md](../CLAUDE.md). The lean reusable rules
live in [methodology/canonical-rules.md](../methodology/canonical-rules.md).

`docs/archive/`, `docs/archive-prebankruptcy/`, and older productization designs are historical
reference. They include removed commands and proposed behavior; they are not current process
requirements. Release migration JSON under `releases/migrations/` is consumed by update tooling.
