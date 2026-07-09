# AI Contribution Policy

This project exists because AI coding agents need enforcement: guardrails plus a test-backed
self-correction loop that make agents finish work, report status honestly, and ship through
real gates. We build that discipline into our own agents every day. We ask contributors to
hold their agents to the same bar — **we enforce discipline on our own agents; we ask the
same of yours.**

AI-assisted pull requests are welcome. Agent-authored contributions are expected here, not
tolerated. What matters is not whether an agent wrote the diff, but whether a human stands
behind it.

## Non-negotiables

Before you open a pull request that includes AI-generated or AI-assisted changes:

1. **You ran `scripts/test.sh` locally and it passed.** Not "it looked right" — the gate ran
   green on your machine, on the exact diff you are submitting.
2. **You can explain every changed line without re-running the tool.** If a maintainer asks
   "why this line, why this way," you answer from your own understanding, not by re-prompting
   an agent and pasting its answer back. If you can't explain it, you aren't ready to submit
   it.
3. **Substantially AI-generated commits carry an `Assisted-by: <tool>` trailer** (for example
   `Assisted-by: Claude Code`, `Assisted-by: Codex`). Use `Assisted-by`, not `Co-Authored-By`
   — the tool assisted; it did not co-author accountability for the change. You are the
   author of record and the person we hold responsible for the contribution.

## The bar

Credit where it's due: we borrow this framing directly from LLVM's AI tool policy, because it
is the right test and we're not going to reword it just to sound original:

> A contribution must be worth more to the project than the time it takes to review it.

Volume is not a substitute for judgment. A large, mechanically-generated diff that a
maintainer has to reverse-engineer costs more than it gives back, no matter how confidently
it was produced.

## What gets closed, and what gets blocked

- **Drive-by or unexplained agent output** — a PR the submitter can't walk a maintainer
  through, or that reads like an unreviewed model transcript — is closed without discussion.
  Re-open it once you can explain and defend every line.
- **Repeat low-effort submissions** from the same contributor are blocked. This is not about
  punishing agent use; it's about protecting maintainer time from a pattern that has already
  shown it won't improve.
- **AI tools may not be used to pad `good-first-issue` work.** Those issues exist to give
  first-time human contributors a real, hands-on entry point into the codebase. Submitting an
  agent-generated solution to a `good-first-issue` defeats its purpose and will be closed.

## Why this exists

An agent that can generate a plausible-looking diff in seconds can also generate ten
plausible-looking diffs in seconds. Review time is the scarce resource in any open-source
project, and this project's entire reason for existing is teaching agents (and the humans who
run them) to respect that constraint. We apply the same standard to contributions that we
build into the tool itself.

If you're unsure whether your change clears this bar, open an issue first and ask. See
[`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`GOVERNANCE.md`](../GOVERNANCE.md) for the rest
of the contribution and decision-making model.
