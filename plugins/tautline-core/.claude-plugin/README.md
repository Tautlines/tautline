# Minervit AI Delivery — Claude Code package (`.claude-plugin/`)

This directory makes the methodology an **installable Claude Code plugin**. Claude
Code is the headline runtime, so this is the package most adopters install.

It ships the same components as the methodology repo — the full skill library under
`../skills/` and the hook wiring in `../hooks/hooks.json` — as a single
self-contained unit that Claude Code discovers when the plugin is installed.

## What this is (vs. the `.codex-plugin/`)

The repo ships two manifests for the same methodology, one per runtime, intentionally
at different enforcement tiers:

| Directory | Runtime | Enforcement tier | Behavior |
| :-- | :-- | :-- | :-- |
| `.claude-plugin/` (this dir) | Claude Code | **Tier A — blocking, in-session** | Hooks run on `PreToolUse` / `PostToolUseFailure` / `Stop` and can **block** an action mid-session (e.g. background-command guard, plan-finalization gate, response-guard). Skills are invokable in-session. |
| `.codex-plugin/` | Codex | Advisory | Surfaces the methodology and skills, but enforcement is advisory — it cannot block a Codex tool call the way a Claude `PreToolUse` hook can. |

This split is the honest statement of the enforcement-tier model the productization
audit asked for (`prod-portability-3/6`, `prod-portability-5`):

- **Tier A (Claude):** blocking in-session hooks — only Claude Code exposes the
  `PreToolUse`/`Stop` hook contract this package binds to.
- **Tier B (any runtime):** pre-push / CI / Git gates that bind at ship time (e.g.
  the branch-liveness Git hook, `scripts/test.sh`, review-before-push). Those are
  runtime-agnostic and are not part of this in-session manifest.

Do not assume "portable enforcement" means identical enforcement everywhere — the
in-session blocking power here is Claude-specific.

## Layout

```
plugins/tautline-core/   <- plugin root
├── .claude-plugin/
│   ├── plugin.json   <- this Claude Code manifest (Tier A)
│   └── README.md     <- this file
├── .codex-plugin/
│   └── plugin.json   <- the Codex manifest (advisory)
├── hooks/
│   └── hooks.json    <- shared hook wiring (referenced by both manifests)
└── skills/           <- the shared skill library (one dir per skill)
```

Component paths in `plugin.json` (`skills`, `hooks`) resolve **relative to the
plugin root** — the parent of `.claude-plugin/` — not relative to this directory.
Claude Code already scans `skills/` and `hooks/hooks.json` by default; the manifest
declares them explicitly so the package is self-describing.

## Hooks and the CLI dependency

`../hooks/hooks.json` invokes the `tautline` CLI from `PATH` rather than
bundling `${CLAUDE_PLUGIN_ROOT}`-relative scripts, because the CLI is installed and
kept in sync separately by the methodology launcher. The same `hooks.json` backs both
manifests; this package does not fork it.

## Versioning

`plugin.json` `version` is kept in lockstep with the repo `/VERSION` file and the
`.codex-plugin/plugin.json` version. Bump all three together so installers and the
release card report the same version.

## Validate

```bash
claude plugin validate ./plugins/tautline-core --strict
```

The manifest carries a `_notes` object documenting inline assumptions. It is an
unrecognized top-level field, so Claude Code ignores it at load time (a warning
under `--strict`, never a load error).
