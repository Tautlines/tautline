"""The durable per-round plan-review record: append-only writers (item 108 WS1).

Schema ``tautline-plan-review-round/v1``. One small committed JSON file per event, living
under ``<planning_source_root>/.plan-reviews/rounds/<manifest-identity>/`` -- beside the
manifests, riding the same evidence commit, never under gitignored ``.ai-runs/``. The
manifest identity is the collision-aware ``plan_review_manifest_identity`` slug, so two
plans sharing a basename cannot share a record directory.

Exactly FOUR record kinds (108-R4-P2-1: imports are a SUBTYPE, never a fifth kind):

- ``baseline`` -- one per member, at the deterministic ``000-baseline.json`` path, the
  durable cutover marker. Created with O_EXCL semantics: a concurrent second writer FAILS
  the create and re-reads instead of duplicating, and two uncommitted baselines born in
  different worktrees collide on the same path at merge time -- a surfaced conflict, never
  a silent double count. Content is deterministic from its inputs (identical inputs give
  identical bytes; no timestamp): the pre-record spend floor plus the SORTED enumeration of
  every pre-cutover meta ``log_sha256`` it absorbed. Membership in that enumerated set --
  never a timestamp -- is what "predates the cutover" means everywhere in item 108.
- ``reviewer-invocation`` -- one per reviewer invocation including failures, with
  ``source: "run"`` for a launch this CLI performed and ``source: "imported"`` for a round
  bound through ``record-plan-review``'s import path. ``charged`` is true iff
  ``wrapper_exit_code == 0`` for BOTH sources: a run that produced no usable review spends
  no budget, whichever door it came through.
- ``round-classification`` -- appended at finalize/record bind time, referencing the
  invocation by nonce + ``log_sha256``. Finalize appends; it never mutates the invocation
  record. ``origin: "pre-record"`` marks a classification of a round whose digest is in the
  baseline's enumerated set (no nonce exists for it); ``origin: "imported-unverified"``
  marks an import that matched neither a recorded invocation nor the baseline set and
  therefore rode a freshly charged ``source: "imported"`` invocation record. Neither origin
  can ever satisfy a verified carried-findings basis -- pre-record history never verifies.
- ``correction`` -- the only sanctioned amendment: a NEW record referencing the original
  (an invocation nonce, or the literal ``baseline``). A correction may RAISE the baseline's
  pre-record count; nothing lowers anything, and no verb modifies, renames, or deletes a
  record file. The reader applies corrections raise-only (WS2's contract to consume).

This module is a deliberate leaf: pure path/dict helpers with no adapter, lane, or CLI
knowledge, so every writer invariant is unit-testable without a fixture lane.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

PLAN_REVIEW_ROUND_SCHEMA = "tautline-plan-review-round/v1"
ROUND_BASELINE_BASENAME = "000-baseline.json"
ROUND_RECORD_KINDS = ("baseline", "reviewer-invocation", "round-classification", "correction")
REVIEWER_INVOCATION_SOURCES = ("run", "imported")
CLASSIFICATION_ORIGINS = ("pre-record", "imported-unverified")
CORRECTION_BASELINE_TARGET = "baseline"

# A work item declared as a FIELD, never inferred from prose (item 36: no English parsing).
# Ported from the read-only prior art (1e90a294) because the record carries the declaration
# forward for the lineage resolver (WS3) to consume; the failed accounting seam is NOT ported.
WORK_ITEM_PATTERN = re.compile(
    r"^[ \t]*(?:[-*+][ \t]*)?(?:\*\*|__)?[ \t]*"
    r"(?:work[ \-]?item|backlog[ \-]?item|packet[ \-]?id|item[ \-]?reference)"
    r"[ \t]*(?:\*\*|__)?[ \t]*:[ \t]*(?P<ref>\S[^\n]*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
WORK_ITEM_LINK_PATTERN = re.compile(r"^\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)$")


def rounds_dir(reviews_root: Path, manifest_identity: str) -> Path:
    """A member's record directory under the committed reviews root."""
    return reviews_root / "rounds" / manifest_identity


def baseline_path(rounds: Path) -> Path:
    """The deterministic baseline path: no timestamp, so concurrent writers must collide."""
    return rounds / ROUND_BASELINE_BASENAME


def record_bytes(record: dict) -> str:
    """Canonical serialization: identical inputs give identical bytes."""
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def render_baseline(
    *,
    plan_identity: str,
    plan_path: str,
    prerecord_count: int,
    prerecord_log_sha256s: list[str],
) -> dict:
    return {
        "schema": PLAN_REVIEW_ROUND_SCHEMA,
        "kind": "baseline",
        "plan_identity": plan_identity,
        "plan_path": plan_path,
        "prerecord_count": int(prerecord_count),
        "prerecord_log_sha256s": sorted(
            {str(digest) for digest in prerecord_log_sha256s if digest}
        ),
    }


def render_reviewer_invocation(
    *,
    plan_identity: str,
    plan_path: str,
    plan_content_sha256: str,
    declared_round: str,
    wrapper_exit_code: int,
    reviewer: str,
    reviewer_model: str,
    started_at: str,
    finished_at: str,
    nonce: str,
    log_sha256: str,
    declared_predecessor: str,
    work_items: list[str],
    source: str,
) -> dict:
    if source not in REVIEWER_INVOCATION_SOURCES:
        raise ValueError(f"reviewer-invocation source must be one of {REVIEWER_INVOCATION_SOURCES}")
    return {
        "schema": PLAN_REVIEW_ROUND_SCHEMA,
        "kind": "reviewer-invocation",
        "plan_identity": plan_identity,
        "plan_path": plan_path,
        "plan_content_sha256": plan_content_sha256,
        "declared_round": declared_round,
        "wrapper_exit_code": int(wrapper_exit_code),
        # Charged iff the wrapper succeeded, for BOTH sources: an infrastructure failure is an
        # audit fact, never a spent round.
        "charged": int(wrapper_exit_code) == 0,
        "reviewer": reviewer,
        "reviewer_model": reviewer_model,
        "started_at": started_at,
        "finished_at": finished_at,
        "nonce": nonce,
        "log_sha256": log_sha256,
        "declared_predecessor": declared_predecessor,
        "work_items": list(work_items),
        "source": source,
    }


def render_round_classification(
    *,
    plan_identity: str,
    plan_path: str,
    plan_content_sha256: str,
    declared_round: str,
    verdict: str,
    unresolved_critical_count: int,
    unresolved_p1_count: int,
    classified_findings_count: int,
    nonce: str,
    log_sha256: str,
    origin: str,
    recorded_by: str,
    recorded_at: str,
) -> dict:
    if origin and origin not in CLASSIFICATION_ORIGINS:
        raise ValueError(
            f"round-classification origin must be empty or one of {CLASSIFICATION_ORIGINS}"
        )
    record = {
        "schema": PLAN_REVIEW_ROUND_SCHEMA,
        "kind": "round-classification",
        "plan_identity": plan_identity,
        "plan_path": plan_path,
        "plan_content_sha256": plan_content_sha256,
        "declared_round": declared_round,
        "verdict": verdict,
        "unresolved_critical_count": int(unresolved_critical_count),
        "unresolved_p1_count": int(unresolved_p1_count),
        "classified_findings_count": int(classified_findings_count),
        "log_sha256": log_sha256,
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
    }
    # A pre-record round has no nonce to reference (the plan's Design section: log_sha256 alone
    # identifies it, valid only through baseline-set membership); everything recorded binds by
    # nonce + log_sha256.
    if nonce:
        record["nonce"] = nonce
    if origin:
        record["origin"] = origin
    return record


def render_correction(
    *,
    plan_identity: str,
    plan_path: str,
    corrects: str,
    note: str,
    raise_prerecord_count_to: int | None,
    recorded_by: str,
    recorded_at: str,
) -> dict:
    record = {
        "schema": PLAN_REVIEW_ROUND_SCHEMA,
        "kind": "correction",
        "plan_identity": plan_identity,
        "plan_path": plan_path,
        "corrects": corrects,
        "note": note,
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
    }
    if raise_prerecord_count_to is not None:
        record["raise_prerecord_count_to"] = int(raise_prerecord_count_to)
    return record


def write_baseline_once(rounds: Path, baseline: dict) -> tuple[dict, bool]:
    """Create the baseline with O_EXCL, or re-read the one that already exists.

    Returns ``(baseline_in_effect, created)``. A second writer's create FAILS and the existing
    record is returned unchanged -- refuse-and-reread, never rewrite. An existing-but-unreadable
    baseline (a merge conflict in progress, for example) is still never overwritten: the caller
    gets its attempted content back for membership checks while the file on disk stays whatever
    the conflict resolution makes of it.
    """
    rounds.mkdir(parents=True, exist_ok=True)
    path = baseline_path(rounds)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return load_baseline(rounds) or dict(baseline), False
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(record_bytes(baseline))
    return dict(baseline), True


def load_baseline(rounds: Path) -> dict | None:
    try:
        data = json.loads(baseline_path(rounds).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def append_record(rounds: Path, record: dict) -> Path:
    """Append one record as a NEW file; never touches an existing one (O_EXCL, fresh name)."""
    rounds.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = record_bytes(record)
    while True:
        path = rounds / f"{stamp}-{secrets.token_hex(4)}.json"
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


def current_prerecord_floor(rounds: Path, baseline: dict | None) -> int:
    """The member's pre-record floor as of NOW: the baseline count raised by every prior
    baseline correction (Codex R2 P2 -- comparing a new raise against the ORIGINAL count let a
    later, lower correction slip under an earlier raise, contradicting raise-only)."""
    floor = int((baseline or {}).get("prerecord_count") or 0)
    for _path, record in load_round_records(rounds):
        if record.get("kind") != "correction":
            continue
        if record.get("corrects") != CORRECTION_BASELINE_TARGET:
            continue
        try:
            raised = int(record.get("raise_prerecord_count_to"))
        except (TypeError, ValueError):
            continue
        floor = max(floor, raised)
    return floor


def load_round_records(rounds: Path) -> list[tuple[Path, dict]]:
    """Every appended record (baseline excluded), oldest filename first."""
    records: list[tuple[Path, dict]] = []
    if not rounds.is_dir():
        return records
    for path in sorted(rounds.glob("*.json")):
        if path.name == ROUND_BASELINE_BASENAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("schema") == PLAN_REVIEW_ROUND_SCHEMA:
            records.append((path, data))
    return records


def charged_invocation_count(records: list[tuple[Path, dict]]) -> int:
    """How many recorded invocations spent budget -- BOTH sources, run and imported alike.

    Only charged records spend: a failed wrapper run appends an uncharged audit record and
    consumes nothing, matching the pre-record `observed_successful_runs` semantics where a round
    that produced no usable review costs no budget.
    """
    return sum(
        1
        for _path, record in records
        if record.get("kind") == "reviewer-invocation" and record.get("charged") is True
    )


def reviewer_invocation_log_sha256s(records: list[tuple[Path, dict]]) -> set[str]:
    """Every log digest an invocation record already accounts for, charged or not.

    Deliberately invocation records ONLY: a classification referencing a digest whose invocation
    record is missing proves the round was classified, not that it was ever counted -- treating
    it as accounted-for would hide exactly the write-path gap the spend reader must surface.
    """
    return {
        str(record.get("log_sha256") or "")
        for _path, record in records
        if record.get("kind") == "reviewer-invocation" and record.get("log_sha256")
    }


def effective_prerecord_count(baseline: dict, records: list[tuple[Path, dict]]) -> int:
    """The baseline's pre-record floor with corrections applied RAISE-ONLY (item 108 WS2).

    A correction targeting the baseline may raise the floor; one that would lower it changes
    nothing (the writer refuses to append those, but a hand-written or merged record must not
    become a way to walk the floor down either).
    """
    try:
        count = int(baseline.get("prerecord_count") or 0)
    except (TypeError, ValueError):
        count = 0
    for _path, record in records:
        if record.get("kind") != "correction":
            continue
        if record.get("corrects") != CORRECTION_BASELINE_TARGET:
            continue
        try:
            raised = int(record["raise_prerecord_count_to"])
        except (KeyError, TypeError, ValueError):
            continue
        count = max(count, raised)
    return count


def find_reviewer_invocation(
    rounds: Path, *, log_sha256: str | None = None, nonce: str | None = None
) -> dict | None:
    """The first invocation record matching the given digest or nonce, or None.

    Callers pass exactly one selector; a digest match and a nonce match are each sufficient.
    """
    for _path, record in load_round_records(rounds):
        if record.get("kind") != "reviewer-invocation":
            continue
        if log_sha256 is not None and record.get("log_sha256") == log_sha256:
            return record
        if nonce is not None and record.get("nonce") == nonce:
            return record
    return None


def declared_work_items(text: str) -> list[str]:
    """The work item a plan declares as a field, normalized, or [] when it declares none.

    Fenced code blocks are examples, not declarations. Normalized (whitespace-collapsed,
    casefolded, link target over label) because the comparison is the point: a lineage that
    binds on one spelling and not another is a budget with a typo-shaped escape hatch.
    """
    outside_fences = []
    fenced = False
    for line in (text or "").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            outside_fences.append(line)
    match = WORK_ITEM_PATTERN.search("\n".join(outside_fences))
    if not match:
        return []
    raw = match.group("ref").strip().strip("`*_ ")
    link = WORK_ITEM_LINK_PATTERN.match(raw)
    if link:
        raw = link.group("url").strip()
    normalized = " ".join(raw.split()).casefold()[:200]
    return [normalized] if normalized else []
