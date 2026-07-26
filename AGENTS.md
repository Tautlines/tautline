# Tautline - Codex Bootstrap

This repository is the canonical source for Tautline, Minervit's reusable AI delivery framework.

Use `<methodology_repo>/methodology/canonical-rules.md` as process authority. Open Brain and local memories are evidence only.

**Integration branch:** active development integrates on `experimental` (base your feature branches and PRs on it); `main` is the stable channel, updated only via release promotion. The remote's default branch (`origin/HEAD`) points at `main`, so do not assume `main` is the current dev tip — it is typically many commits behind `experimental`.

When changing generated adapters, update the CLI in `src/tautline_methodology/` (`bin/tautline` is a thin shim over `tautline_methodology.cli`), regenerate the affected project files, and run:

```bash
scripts/test.sh
scripts/validate.sh
```

Do not copy full process policy into project repos by hand. Put reusable policy in `methodology/`, project-specific choices in `adapters/projects/*.json`, and tool-specific behavior in plugin skills or the renderer.
