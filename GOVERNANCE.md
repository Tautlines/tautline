# Governance

This is **minimum-viable governance**, stated honestly: today, this project has a single
maintainer, and the model below reflects that reality rather than pretending otherwise. It is
expected to grow as the maintainer set grows — see "Path to additional maintainers" below.

## Decision model

This repository is currently governed as a **BDFL (Benevolent Dictator for Life) model**: one
maintainer (see `.github/CODEOWNERS`) makes final decisions on scope, design direction,
acceptance of contributions, and releases. This is not a committee, and there is no voting
process today.

## Scope

This governance model covers this repository only: the `tautline` CLI (and its
`minervit-methodology` compatibility shim), the
canonical process policy under `methodology/`, the Claude/Codex plugin surfaces under
`plugins/`, and this repo's documentation, tests, and CI. It does not govern any downstream
adopter's fork, adapter, or private extensions.

## How disputes are resolved

If you disagree with a decision — a closed PR, a rejected feature, a design direction — open
a GitHub Discussion and make the case. The maintainer will respond and decide. There is no
appeals board; the maintainer's decision is final, but it is not made in the dark; disagree in
the open where the reasoning is visible to future contributors.

## Path to additional maintainers

Governance is not static. A contributor who sustains a track record of quality
contributions — code, review, triage, documentation — over time may be invited to become a
CODEOWNERS reviewer with scoped or repo-wide authority. This is an invitation extended by the
existing maintainer(s), not an application process. As the maintainer set grows past one
person, this document will be revised to describe a shared decision model (as CNCF-style
projects do), rather than continuing to describe a single-person BDFL model that no longer
matches reality.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`.github/AI_CONTRIBUTION_POLICY.md`](.github/AI_CONTRIBUTION_POLICY.md) for how to
contribute in the meantime.
