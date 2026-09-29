## What changed and why

Describe the problem, resulting behavior, and any migration impact.

Backlog: <item-id>

## Validation

- [ ] `scripts/test.sh` passed on this change (it already includes lint and types).
- [ ] `git diff --check` passed.
- [ ] Fresh-context adversarial self-review completed; reviewer/model and outcome noted below.
- [ ] Different-model-family review completed; reviewer/model and outcome noted below.
- [ ] Critical/P1 findings resolved and fixes verified.

Reviewers/models (effort when known), reviewed scope, findings and fixes:

`scripts/validate.sh` aliases the same suite; do not run both for duplicate evidence.
Note material limitations or useful follow-ups here.

## Contribution

- [ ] Commits are DCO signed off (`git commit -s`).
- [ ] AI assistance is disclosed with an `Assisted-by:` trailer where applicable.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the development and release workflow.
