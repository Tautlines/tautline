# Two reviews before merge

Every implementation gets two bounded review passes:

1. **Fresh-context adversarial self-review.** Start a separate session or subagent using the
   implementation model. Supply the requirements, diff, and relevant code/tests without the
   implementation conversation. Ask it to find concrete defects, not defend the implementation.
2. **Different-model review.** Then have a different model family independently review the
   resulting change, also with fresh context. Another agent running the same model does not
   satisfy this review. For example, a Codex implementation can use Claude for this pass;
   a Claude implementation can use Codex. Changing effort alone is not changing models.

Fix Critical/P1 findings and run the relevant checks. Verify fixes directly; do not restart
both reviews after every correction. A materially different implementation needs review of
the changed scope. Record useful lower-priority follow-ups in the existing backlog.

Name each reviewer/model, configured effort when known, reviewed scope, findings, and fixes
in the existing PR summary. Report an unavailable reviewer or unknown model honestly; do not
silently substitute a same-model reviewer, waive the missing pass, or claim both reviews ran.
No separate review ledger, mandatory plan, review-round counter, or blocking hook is required.

The lean adapter's `review` string adds project-specific focus. It cannot replace these two
core reviews. Generated instructions include both even when a project retains the old
one-review default. After upgrading, use `tautline slim --target .` to refresh generated
instructions. For handwritten files, manually add the two-review requirement described above;
`slim` preserves them and does not produce proposals for already-lean projects. Reword custom
`review` strings that describe a replacement process as additional review focus.

Provider and model choices remain portable. A project may name preferred reviewers; Tautline
does not require a particular vendor subscription. Reviewers must actually be available:
record the model reported by the runtime, not merely the model requested in a prompt.
