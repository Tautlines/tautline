# GitHub Projects Reads — policy

The read-side complement to `board-item-updates`. That skill governs what an agent
WRITES to a board; this one governs what it believes after READING one.

Every rule here is a control from a recorded incident in which the agent was not
confused — it was confident, and wrong. The reads returned exactly what they were
asked for. The questions were wrong.

## Non-Negotiables

### 1. Operator evidence is ground truth

When an operator's screenshot or observed UI state contradicts an API or CLI result,
the observation wins. Acknowledge the contradiction, then debug the query — identity,
field-name semantics, pagination/truncation — instead of re-asserting the query result.
**Arguing with operator evidence is a stop-the-line defect.**

Recorded failure (`20260627T193516Z`): the agent argued against the operator's
screenshots, held the API result as authoritative, and was wrong on all three counts
below at once.

### 2. Org-identity guard before any `gh project` command

Confirm owner and project number from the adapter pin or the project URL. Never carry
an owner or number forward from prior work unverified, and never resolve a board by
display-name resemblance. A queried number that differs from the configured
`projectNumber` is **blocking drift, not a fallback candidate**.

Recorded failure (`20260702T202523Z`): a board was picked because its display name
resembled the expected one. Every read afterwards inherited that resolution.

Sanctioned path: `backlog-provider-board-check` compares the identity recorded in each
synced source against the adapter pin and blocks on a mismatch.

### 3. No exact field-name match does NOT mean the field is absent

Scan the returned field list for **semantically equivalent** names — same purpose,
overlapping option values — and confirm with the operator before declaring a field
missing. The recorded pair was the UI label `Priority` against the API name
`Goal Priority`; the agent reported the field as absent because the string did not match.

### 4. Count cross-check after every bulk read

Compare the returned count against `totalCount` or the visible board count. A mismatch
requires per-item verification before acting on the result.

**Surface trap:** `gh project item-list --format json` omits `fieldValues` on some `gh`
versions. A null there is not an empty field — it is an unanswered question.

## Required Follow-Through

- A read that cannot be count-verified is **unavailable, not empty**. Report it as
  unavailable and let the gate block: an unreadable authoritative board is not current.
- Record the board identity a sync read from, alongside the synced artifact, so a later
  run can tell which board produced it.
