# Contributing

Tautline helps AI agents coordinate and deliver work with little overhead. Contributions should
solve a concrete problem and preserve that speed. Keep changes small; prefer a working example
and meaningful tests over new process requirements.

## Repository layout

| Path | Purpose |
| --- | --- |
| `methodology/canonical-rules.md` | Lean reusable rules rendered into project instructions |
| `src/tautline_methodology/` | Python CLI implementation and modules |
| `bin/tautline` | Thin executable shim; `bin/minervit-methodology` is the compatibility entry point |
| `.tautline.json` | Lean project configuration; full adapters remain under `adapters/projects/` |
| `plugins/` | Runtime-specific skills, hooks, and manifests |
| `tests/`, `scripts/test.sh` | Behavior tests and the single local test gate |

Reusable rules belong in `methodology/`; project-specific choices belong in project config;
runtime-specific behavior belongs in the CLI or plugins. Use the fictional
`adapters/projects/example-saas.json` in examples and tests, never a private adopter's data.

## Development

Use Python 3.12+ (3.12 is the declared floor, and CI proves it on every merge).
CI currently exercises 3.12. Install the pinned developer tools into a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
bin/tautline --help
scripts/test.sh
```

`scripts/test.sh` runs Ruff, mypy, and pytest. `scripts/validate.sh` is a frozen five-line alias
of the same gate: running both repeats the suite. Do not add checks to the alias. PyPI packages
are assembled by `registry-package`; the root `pyproject.toml` holds developer tool settings.

Add a failing behavior test for a bug or new behavior, then implement the smallest useful fix.
Do not add prose-matching tests for copy edits. Keep existing lint/type suppressions from
growing; fix the underlying problem when a new diagnostic appears.

## Pull requests

1. Branch from `experimental`, the integration branch, and target it with your PR. `main` is
   the stable channel, advanced during release promotion.
2. Explain the problem, resulting behavior, and validation. A one-page spec is enough when a
   spec is useful. Small fixes can go directly to a PR.
3. Run `scripts/test.sh` and get one adversarial review. Fix Critical/P1 findings before merge;
   record useful follow-ups without starting a review-round ritual.
4. Sign off your commits with `git commit -s` under the Developer Certificate of Origin.
5. Merge through the repository's configured checks. Releases are batched, not required for
   every PR; see [the release procedure](docs/reference/releases.md).

Coordinate larger changes in an issue before investing heavily. Avoid unrelated refactoring or
formatting in a functional change. Changes to generated adapters should update the renderer,
regenerate affected files, and verify the result.

Never commit credentials or customer data. [SECURITY.md](SECURITY.md) describes private
vulnerability reporting; [GOVERNANCE.md](GOVERNANCE.md) describes project decisions, and the
[AI contribution policy](.github/AI_CONTRIBUTION_POLICY.md) covers AI-assisted changes.
