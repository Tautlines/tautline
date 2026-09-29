# Operator inbox

Record a real blocker once, continue other work, and incorporate the answer on resume.
The inbox does not stop sessions, execute answers, poll a service, or add a review step.

```sh
tautline decision-record --summary "Which API should remain supported?" \
  --rationale "The compatibility choice needs the operator" --awaiting-operator
tautline inbox --target /path/to/lane
tautline inbox --target /path/to/lane --answer <id> --text "Keep v1 for this release"
```

The source lane reads the answer and acknowledges it **after** incorporating it:

```sh
tautline inbox --answers
tautline inbox --ack <id>
```

Startup reports unacknowledged answers. Reading one does not consume it: a crashed or compacted
session sees it again. An answered question leaves the pending list immediately; acknowledgement
marks that the lane incorporated the answer. Repeating the same answer or acknowledgement is safe.
A different answer to the same question is refused; record a new decision to revise the choice.

Repeat `--target` to aggregate the lanes you want to inspect, including lanes in other repos.
Omitting it means the current lane, not every worktree on the machine. Each pending row includes a
stable id. Answers are scoped to the source lane, so another lane's acknowledgement cannot hide
your answer. `--json` works with every operation.

Replies are small owner-only files in an `answers/` directory beside the project's existing
machine-local event log (`tautline event-log-path`). They survive log rotation. Startup reads only
this reply state, not the historical log, and makes no network call. Corrupt or inaccessible state
is reported as unknown; it does not silently resolve a pending question. This is local delivery
within one user's machine, not a cross-machine message service.

Do not put credentials in questions or answers. The writer rejects secret-shaped values. Answering
is an explicit operator workflow, not permission for an agent to invent the operator's response.
