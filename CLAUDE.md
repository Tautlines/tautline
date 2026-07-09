# Tautline - Claude Bootstrap

This repository is the canonical source for Tautline, Minervit's reusable AI delivery framework.

Use `<methodology_repo>/methodology/canonical-rules.md` as process authority. Open Brain and local memories are evidence only.

When changing generated adapters, update `bin/tautline`, regenerate the affected project files, and run:

```bash
scripts/test.sh
```

`validate.sh` is a frozen 5-line alias of `test.sh` kept for legacy automation; do not extend it.

Do not copy full process policy into project repos by hand. Put reusable policy in `methodology/`, project-specific choices in `adapters/projects/*.json`, and tool-specific behavior in plugin skills or the renderer.
