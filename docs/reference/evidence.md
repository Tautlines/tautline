# Execution receipts

`tautline evidence` records a command you choose to run and reports whether its result still
matches this checkout. It adds no hook, approval, required plan, completion gate, or automatic
rerun. Nothing is fingerprinted until you explicitly run or inspect evidence.

```sh
tautline evidence run -- scripts/test.sh
tautline evidence run --target ../worktrees/change -- python -m pytest tests/test_feature.py
tautline evidence status
tautline evidence status --json
```

`run` executes the argv after `--` **once**, in the target repository root. It does not interpret
shell syntax; use an explicit shell if you need it. Output streams directly to your terminal.
The command's exit code is returned, with signal exits represented as `128 + signal`. If a
receipt cannot be created, the command is not started and the CLI reports that with exit 2.
`status` is always advisory and exits 0, including when the result is failed, stale, or unknown.

Each receipt records the start and finish times, elapsed time, actual exit code, interruption
state, HEAD, index identity, and content fingerprints before and after execution. Fingerprints
include dirty tracked files, deleted tracked files, file modes, symlinks, and nonignored untracked
files. Ignored files are excluded unless tracked. A test report created inside the checkout must
be ignored if you want it excluded from freshness checks.

The latest **started** run is authoritative for this worktree. Its running receipt is published
before execution and completed atomically. A newer failed or interrupted run cannot reveal an
older green result; concurrent runs keep separate records. Sibling worktrees share Git's common
storage directory, with separate per-worktree receipt directories at
`<git-common-dir>/tautline/evidence/<worktree-key>/`.

States are:

- `fresh_pass`: the recorded command exited 0, and HEAD, index, and repository fingerprints
  matched before execution, after execution, and at inspection.
- `failed`: the matching run exited nonzero.
- `stale`: repository identity changed during or after the run.
- `running`: the latest run has no completion record. It may still be running, or its recorder
  may have been killed.
- `interrupted`: signal interruption was observed.
- `unknown`: no usable receipt, unreadable files, or an unsupported content boundary.

The receipt stores **no raw arguments, shell snippets, environment values, filenames, or command
output**. It retains only an allowlisted executable name (otherwise “custom command”) and argument
count. Keep command output itself appropriate for your terminal or CI: the recorder does not
redact a child process's live output.

A receipt establishes what happened for the command you selected. It does not assert that the
command was a sufficient test, that a review occurred, or that anything was merged or deployed.
It is a local observation, not tamper-proof attestation. Environment and external dependencies
are outside its fingerprint. Symlinks are recorded as links; their external targets are not read.
Submodules, nested repositories, and special files currently produce unknown freshness. Endpoint
fingerprints cannot detect a change that was made and then fully reverted while the command ran.

See [health observations](health.md) for integration and CI state.
