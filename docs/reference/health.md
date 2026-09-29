# Integration and CI health

`tautline health` gives an on-demand snapshot. It adds no startup work or merge gate and always
exits 0. Unknown is a result to investigate, not a green signal.

```sh
tautline health
tautline health --target ../worktrees/change --json
tautline health --remote
```

The default is entirely local. It reads the checkout's HEAD, branch, configured integration
branch, and cached `origin/<integration>` ref. Ahead/behind counts refer to that **cached** ref;
they are not a claim that the remote is current. A missing configuration or cached ref is shown
as unknown. The lean `integrationBranch` setting and existing legacy integration settings are
recognized.

`--remote` explicitly uses `gh api` against the repository's GitHub.com `origin`. It reads the
live integration SHA, then queries all pages of its latest check runs and combined commit
statuses for that exact SHA. Each subprocess has an eight-second timeout. It does not fetch or
modify branches, request a CI rerun, or write to GitHub.

CI is `passed` only when there is at least one observation, every observed check completed
successfully, and all observed commit statuses succeeded. Failed checks are `failed`; cancelled
checks are `cancelled`; active checks are `pending`. Skipped, neutral, absent, malformed,
mismatched-SHA, timed-out queries, and inaccessible observations cannot produce a pass.
GitHub access errors are reported without copying raw credential-bearing subprocess output.

The report always identifies deployment as **unknown** because this command has not observed a
deployment. GitHub CI success does not imply deployment success or completeness of a repository's
test coverage. A live observation is timestamped and can become old as soon as another commit
lands; the exact SHA remains visible for that reason.

For proof you ran locally and its relationship to current repository files, see
[execution receipts](evidence.md).
