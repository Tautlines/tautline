# Claude Code integration

This manifest installs the `tautline-core` skills and hooks. Install the Tautline CLI first;
see the root [README](../../../README.md).

- **SessionStart** reports advisory lane and shared-work context. It does not block startup.
- **PreToolUse / Bash** runs the specialized builder guard for explicitly configured builder
  lanes. See [builder lanes](../../../docs/builder-lanes.md) for role selection, the allowed
  operations, and GitHub App permissions.
- **Skills** help compose a goal prompt, prepare a handoff, and give clear operator instructions.

There is no Stop hook or review-evidence completion gate. The sibling `.codex-plugin` exposes
skills to Codex; it does not run Claude hooks. Project tests and CI remain separate from these
runtime integrations.
