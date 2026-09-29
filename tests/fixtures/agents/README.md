# Conformance fixture agents

Real subprocesses, driven through the real review seam. **No vendor CLI is required to run
them, and none may ever be.** A suite that needs a real `codex` or `claude` binary can only
prove agnosticism for agents the operator already owns, which reproduces the coupling one layer
up.

Each script implements the whole agent output contract:

1. be invoked with the review inputs the framework passes;
2. write `review-result.json` to `$TAUTLINE_REVIEW_RESULT_PATH`;
3. exit non-zero only on transport failure, never to signal findings.

`clean` is the reference implementation and is deliberately about twenty lines. It is the
standing proof that the contract stayed small: **if a twenty-line script can no longer pass
`tautline agent-conformance`, the framework has re-coupled to something.**

The same battery ships as `tautline agent-conformance --agent <id>` so an adopter can certify
an agent this repo has never run.

Most of these are *conforming* agents that differ in what they report. `wrong-identity`,
`malformed-output`, `nonzero-exit` and `no-structured-output` are **failure** fixtures: each
breaks one clause above so the seam's refusal can be proven against a real subprocess rather
than a mock. `prose-clean-structured-findings` is a **divergence** fixture — it satisfies the
contract but makes its prose and its structured result disagree, which is the only way to
exercise a seam that reads one and classifies the other.
