# Verify before trusting

A check's exit code and a check's output can disagree about what was actually learned. The
shapes below are where trusting the exit code, or trusting output that looks like proof, has
been wrong before.

## A health check that reports the pre-deploy SHA is a failed deploy

Regardless of exit code. Printing a value back is not the same operation as comparing that
value against what the deploy was supposed to produce, and a check that only does the first can
exit 0 on every run, including the one where the new code never actually started. A deploy is
proven by a fresh probe that disagrees with the pre-deploy state in the expected way — the
pre-deploy SHA, echoed back unchanged, is the specific shape of a check that learned nothing.

## A skipped, pending, or quarantined test proves nothing about the behavior it names

Its name still appears in a green run either way. The suite passing is a fact about which tests
executed; it is a different fact from whether the behavior a skipped test names still works,
and the two facts look identical in a summary line that only counts passed and failed. A
quarantined test and a deleted test currently provide the same coverage — the quarantined one
is just still on the file listing, where it can be mistaken for evidence.

## "Indeterminate" is not "absent"

A check that could not run — no credentials, no network, the tool it shells out to is missing
from this machine — learned nothing about the thing it was checking. Reporting that outcome as
a pass asserts a fact the check never observed; reporting it as a finding asserts the opposite
fact, equally ungrounded. The honest third state names what actually happened — unknown, and
here is why — which is a different answer from both "yes" and "no," and the only one of the
three the check is entitled to give.

## GitHub closing keywords fire only against the repository's default branch

A commit message or pull request body that says `Fixes #123` closes the issue only when the
pull request merges into the repository's own default branch; on any other branch the keyword
is inert — no link, no close, nothing. This repository's default branch is `main`; day-to-day
development integrates on `experimental`, which runs many commits ahead of it. A closing
keyword in a PR merged to `experimental` does not close its issue — the issue stays open until
`main` is promoted from `experimental` and carries that commit across the branch the keyword
actually needed. An issue tracked as closed by keyword alone, before that promotion, is still
open on GitHub.
