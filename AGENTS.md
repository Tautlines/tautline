# Tautline - Codex Bootstrap

This repository is the canonical source for Tautline, Minervit's reusable AI delivery framework.

Use `<methodology_repo>/methodology/canonical-rules.md` as process authority. Open Brain and local memories are evidence only.

Keep delivery fast: no required plan/review rounds or new routine blocking gates. Read `tautline work status` at startup and before new work; declare, update, and finish parallel-work scope. Read a present `.ai-continuity/HANDOFF.md` and refresh it at useful checkpoints. When notified, read `tautline inbox --answers` and acknowledge after incorporation. Use `tautline backlog list` as the active queue and include `Backlog: <id>` in PRs.

**Integration branch:** active development integrates on `experimental` (base your feature branches and PRs on it); `main` is the stable channel, updated only via release promotion. The remote's default branch (`origin/HEAD`) points at `main`, so do not assume `main` is the current dev tip — it is typically many commits behind `experimental`.

When changing generated adapters, update the CLI in `src/tautline_methodology/` (`bin/tautline` is a thin shim over `tautline_methodology.cli`), regenerate the affected project files, and run:

```bash
scripts/test.sh
```

`validate.sh` is a frozen 5-line alias of `test.sh` kept for legacy automation; do not extend it. Running both executes the identical suite twice for no additional coverage — `scripts/test.sh` **is** the full preflight.

Do not copy full process policy into project repos by hand. Put reusable policy in `methodology/`, project-specific choices in `adapters/projects/*.json`, and tool-specific behavior in plugin skills or the renderer.
