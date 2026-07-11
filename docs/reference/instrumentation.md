# Sanitized Instrumentation Records

The instrumentation record is the **only** session evidence Tautline can ever publish to a
remote. Where a narrative session journal describes your product work (and so can never be
proven safe to publish — see [session-journals.md](session-journals.md)), an instrumentation
record is a **closed-vocabulary record of enumerated event codes plus numbers** with **zero
product-information capacity** by construction. Leakage is impossible not by discipline but
by structure: there is no field a product name, path, branch, or freeform note could occupy.

It is **opt-in, default off**. Enable it per lane with `"instrumentation": {"enabled": true}`
in your source adapter; publishing is off until you do.

## What a record contains

A single JSON object conforming to the committed schema
`methodology/instrumentation-schema.json` (schema id `tautline-instrumentation/v1`). Every
object level is `additionalProperties: false`, and every string-typed field is constrained
to a constant, a regex, or a closed enum:

```json
{
  "schema": "tautline-instrumentation/v1",
  "emitted_at": "2026-07-10T12:00:00+00:00",
  "lane_id": "9f2c4a1b0e7d5c3a",
  "plugin_version": "0.9.0",
  "window_seconds": 5400,
  "window_gap": false,
  "end_seq": 12,
  "events": [
    {"code": "plan_review_round", "count": 3, "total_seconds": 1820.5},
    {"code": "gate_block", "count": 1}
  ]
}
```

The only string fields are `schema` (constant), `emitted_at` (UTC timestamp, regex-checked),
`lane_id` (16 hex chars), `plugin_version` (semver), and `events[].code` (a value from the
closed event vocabulary). Everything else is a number or boolean. There is deliberately **no**
repo slug, branch, project name, goal/milestone/task title, path, or freeform notes field —
and no way to add one without changing the committed schema, the in-code enum, and the public
contract together.

The record is an **aggregation over the local observability event log** (`events.jsonl`), so
enabling instrumentation requires `observabilityEvents.enabled: true` (the loader rejects the
incoherent combination). The aggregator maps known local event names to closed codes and drops
everything unmapped — this is the sanitization boundary between the freeform local log and the
closed vocabulary.

## Lane identity

`lane_id = sha256(salt + resolved lane path)[:16]`. The salt is 32 random bytes at
`$HOME/.local/state/tautline/telemetry-salt` (0600, created on first use), **never published and
never logged**. The lane id is stable per machine+lane for longitudinal analysis and unlinkable
to any product without the salt.

## Where it goes, and what git metadata is exposed

Remote metadata is a fixed constant, not configurable — there are no `branch`/`archiveDir`
adapter knobs. Records publish to the constant `tautline-telemetry-archive` branch of the
framework checkout's origin, at `telemetry/<lane_id>/<UTC-stamp>-<end_seq>.json`. The commit is
made under a **pinned, adopter-neutral identity and date** (`tautline-telemetry
<telemetry@tautline.invalid>`, date derived from the record, `+0000`), with signing, hooks, and
attribute filters disabled, so your git config leaks no company/project string or timezone into
the commit object. The publisher reads the committed blob back and byte-compares it to the
validated record before pushing.

## Guarantees

- **Zero freeform capacity.** No inadvertent narrative or product leakage is representable in a
  conforming record.
- **No tamper path through prepared artifacts.** `publish-instrumentation-record` recomputes the
  record directly from the local event log at publish time and publishes only the recomputed
  record; the prepared preview file is never read by the publisher, so editing it (even into a
  schema-valid but different record) cannot influence what publishes.
- **Fail-closed hygiene.** Before trusting the archive branch the publisher validates the whole
  branch: every path matches the grammar, every blob is a known-version conforming record bound
  to its own path, and every reachable commit carries only pinned metadata. Unknown schema
  versions are rejected (upgrade your framework), and a branch-tip ancestry guard refuses to
  publish onto a force-pushed/rewound history.

## Threat model (stated honestly)

This design guarantees (a) zero freeform capacity and (b) no tamper path through prepared
artifacts. What it **cannot** prevent is a *deliberately malicious local actor* steganographically
encoding bits into legitimate event counts by synthesizing local events. That channel is
low-bandwidth, requires intent, and remains auditable against the local event log; it is an
explicit **non-goal**. The salt is a machine secret readable by same-user processes, so a
deliberately malicious same-user actor is likewise out of scope. The design targets **inadvertent
leakage and blunt tampering**, which it eliminates by construction.

## Commands

- `prepare-instrumentation-record --target .` — write and validate a current-window preview under
  the lane's gitignored `.ai-runs/instrumentation/` (a human-inspection artifact; never read at
  publish time).
- `validate-instrumentation-record --file <path>` — standalone fail-closed validator.
- `publish-instrumentation-record --target .` — recompute from the event log and publish via the
  hardened push path. Gated on `instrumentation.enabled`.

## Adapter key

```json
"instrumentation": { "enabled": false, "cadence": "milestone" }
```

`enabled` (default false) alone permits publishing. `cadence` (`milestone` | `session` | `off`)
gates only whether boundary guidance prompts for emission; a disabled lane is never prompted.
There are no other keys — remote metadata is constant.
