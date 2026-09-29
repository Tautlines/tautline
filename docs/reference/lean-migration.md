# Migrating a project to the lean profile

`tautline slim` moves one adapted project off the heavyweight process and onto the lean profile.
It archives, it never deletes, and running it twice is a no-op.

## What it does

| | Before | After |
|---|---|---|
| `CLAUDE.md` / `AGENTS.md` | ~16KB of rendered process | under 2KB: project facts, six process norms, and a standing working-style block (autonomy, blocked-handling, subagent fan-out, evidence-before-done) |
| `.tautline.json` | ~25KB, ~57 keys | under 1KB, `schemaVersion: "lean-1"` |
| `~/.claude/settings.json` | 18 framework hook entries across 5 events | your own hooks only |
| `.git/hooks/` | framework `pre-commit` + `pre-push` | your own hooks only |
| plans, review ledgers, lane state | scattered, load-bearing | `docs/archive-prebankruptcy/`, read-only reference |

## Steps

1. **Update the framework checkout.** `slim` ships with the framework; run it from a checkout that
   has it, not from a pinned installed shim that predates it.

   ```bash
   cd <your framework checkout>          # e.g. ~/Projects/Tautline
   git fetch origin --prune
   git switch experimental && git pull --ff-only
   ```

2. **Make sure the project has no uncommitted work.** `slim` uses `git mv`, and reviewing the
   migration is much easier against a clean tree.

   ```bash
   git -C <project> status --short       # commit, stash, or discard first
   ```

3. **Dry run.** Nothing is changed; every action is printed with a `would` prefix.

   ```bash
   python3 bin/tautline slim --target <project> --dry-run
   ```

   Read the `archive` and `back up` lines. Anything you did not expect to move is worth
   understanding before step 4.

4. **Run it.**

   ```bash
   python3 bin/tautline slim --target <project>
   ```

5. **Review and commit, in the project.**

   ```bash
   cd <project>
   git status --short
   git add -A && git commit -m "chore: migrate to the Tautline lean profile"
   ```

6. **Confirm it is a no-op now.** A second run must report `already lean - no changes`.

   ```bash
   python3 <framework checkout>/bin/tautline slim --target <project>
   ```

   That holds only while neither your config nor the framework's own adapter template has
   changed. When the framework ships a template change (a new standing working-style line, say),
   update the checkout and re-run this same command: it re-renders `CLAUDE.md`/`AGENTS.md` from
   your existing config and rewrites them (backing up the old copy first) -- no hand-editing, and
   no `--project` flag to work out, unlike `render-adapters`, which is for 1.x adapter sources.

## Flags

- `--dry-run` — print every change without making one.
- `--keep-agent-hooks` — leave `~/.claude/settings.json` alone. The framework's Claude hooks are
  installed **there**, not in the project, so this opts out of removing the ones you actually
  feel at session start. Use it when several projects share the machine and only one is migrating.

## When it cannot finish

`slim` exits **non-zero** and prints a `FAILED - these were NOT migrated:` section if any part was
left undone — most often a `settings.json` it could not parse (a trailing comma or a comment is the
usual cause; a byte-order mark is tolerated). The hooks in that file are still installed and still
firing until you fix it and re-run. A partial migration never exits 0.

## Rollback

Two independent paths, and you have both:

- **git** — the migration is one commit in the project. `git revert` it, or `git checkout` the
  files, and the project is exactly as it was.
- **the archive** — `docs/archive-prebankruptcy/` holds the old `CLAUDE.md`, `AGENTS.md` and
  `.tautline.json`, the plan directories and review ledgers, and a copy of every git hook that was
  removed. Nothing is deleted, so a project that was never committed can still be reassembled by
  hand.

`~/.claude/settings.json` is backed up beside itself as `settings.json.before-tautline-slim` —
deliberately not in the project, because that file carries machine-wide environment values and
permission grants and does not belong in a repository.

## Things it deliberately does not do

- **It does not restore the hook the installer displaced.** If `.git/hooks/pre-commit.before-minervit`
  exists, that is your original hook. `slim` prints the exact `mv` to put it back; it will not
  re-arm an executable that runs on every commit without you asking.
- **It does not move gitignored lane scratch.** `.ai-work/`, `.ai-runs/` and `.ai-continuity/` stay
  where they are and are reported. Moving them under `docs/` would un-ignore them and stage
  whatever was on disk. Nothing writes them after the migration; delete them when you feel like it.
  Review ledgers and plan directories are different — they are process *history*, so they are
  archived whether or not git tracks them.
- **It does not overwrite a hand-authored `CLAUDE.md`.** A file without the `<!-- GENERATED -->`
  header is prose a person wrote. `slim` writes the lean adapter to `CLAUDE.md.lean-proposed`
  instead and says so; move it into place yourself once you have read it.
- **It does not archive a path that contains the archive.** A config naming `docs` as its plan
  directory would move that directory into a destination inside itself. `slim` skips it with a
  note rather than crashing half-way through.
- **It does not touch your product documents.** Only the paths the framework created or that the
  project's own config named as process artifacts are archived.
- **It does not follow a config path out of the project.** An absolute or `../` path in the old
  adapter is ignored.

## The lean contract

`.tautline.json` after the migration:

```json
{
  "schemaVersion": "lean-1",
  "project": {"name": "Example SaaS", "repo": "example-org/example-saas"},
  "integrationBranch": "main",
  "commands": {"test": "make preflight"},
  "review": "One adversarial review before merge; fix Critical/P1; merge.",
  "security": {"secretScan": true, "customerDataScan": true},
  "release": {"batched": true},
  "laneStatus": "advisory",
  "projectRules": ["Every tenant-scoped endpoint must enforce tenant isolation."]
}
```

Required: `schemaVersion`, `project`, `integrationBranch`, `commands.test`. Everything else is
optional. The full contract is `methodology/adapter-schema-lean.json`.

Process is prose in the generated adapter, not configuration — there is no key that turns a norm
off, because turning one off is a conversation, not a toggle. `projectRules` is for facts about
**this** project that an agent would otherwise get wrong, one line each; they are migrated from the
old `knownProjectRules` and `technologyStack.nonNegotiable`.

## Enable the Claude Code plugin

`slim` migrates a project's files. It cannot enable the Claude Code plugin that makes `/goal`,
`/handoff`, and the advisory `lane-status` SessionStart hook show up in a session -- that is a
Claude Code client setting, not something a file migration can write for you.

From a framework checkout, with Claude Code's working directory set to that checkout:

```
/plugin marketplace add ./
/plugin install tautline-core@tautline
```

The first command registers the checkout's own `.claude-plugin/marketplace.json` as a local
marketplace named `tautline` (its `name` field); the second installs the `tautline-core` plugin
from it -- the same plugin the published install in the root `README.md` pulls from GitHub,
except sourced from your local checkout so edits under `plugins/tautline-core/` take effect
without waiting on a release. `/goal` and `/handoff` become available as slash commands, and the
`SessionStart` hook starts printing the advisory `lane-status` line at the top of each session.

Not working from a framework checkout, or want the released version instead? Use the published
marketplace from the root `README.md` (`/plugin marketplace add tautlines/tautline`).
