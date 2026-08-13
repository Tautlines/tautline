"""Lane currency findings and reporting (`tautline-lane-status/v1`).

Pure computation over injected git facts: no subprocess, no filesystem, no network. The collector
(``cli.py``) owns all I/O and hands this module a facts dict, which is what makes the never-blocks
contract testable -- every failure mode is just a value in ``unverified``.

Item 27: session-start currency gate.
"""

from __future__ import annotations

import shlex

# Report sinks interpolate repository-controlled values (a committed VERSION, a branch name, a
# collector detail string). `0.21.0-\n  -> forged line` PARSES as a valid version, so without this
# a repository can forge extra SessionStart status or remedy lines into the report an agent is told
# to act on. Everything printed goes through `_safe` first.
LANE_STATUS_REPORT_VALUE_LIMIT = 200


def _safe(value: object, *, limit: int = LANE_STATUS_REPORT_VALUE_LIMIT) -> str:
    """Flatten control characters and truncate. Pure: the collector owns secret redaction."""
    flattened = " ".join(
        "".join(char if char.isprintable() else " " for char in str(value)).split()
    )
    return flattened[:limit]

LANE_STATUS_SCHEMA = "tautline-lane-status/v1"

# Ordered: the report leads with the most identity-destroying verdict first. A tuple, not a list --
# UPPER_CASE list-of-str constants are auto-collected into the policy-phrases SSOT (C15).
LANE_STATUS_FINDING_ORDER: tuple[str, ...] = (
    # FIRST: another session in this worktree destroys identity harder than anything below it.
    # Every other finding describes a state this lane can reason about; this one says the lane's
    # own edits may not be its own.
    "CONCURRENT",
    "DETACHED",
    "ORPHANED",
    "MERGED",
    "STALE",
    "SQUATTED",
    "DIRTY",
    "UNCLAIMED",
    "BASELINE-MOVED",
    "UNVERIFIED",
)

# Which findings a rerun can actually clear. The report ends with "rerun lane-status" only when at
# least one printed command can change the verdict. SQUATTED (another worktree holds the ref; a
# fetch cannot move it), UNCLAIMED (no command here creates a claim-source match) and UNVERIFIED
# (no mechanical remedy) cannot, so instructing a rerun on them alone loops forever.
LANE_STATUS_RESOLVING_FINDINGS = frozenset(
    {"DETACHED", "ORPHANED", "MERGED", "STALE", "BASELINE-MOVED"}
)

# Findings whose remedy is branch replacement -- but only when the lane has no unique commits to
# strand. See `_replacement_is_safe`.
_REPLACEMENT_FINDINGS = ("DETACHED", "ORPHANED", "MERGED")


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _version_tuple_or_none(text: object) -> tuple[int, ...] | None:
    """Local, dependency-free semantic parse. Returns None for anything non-numeric so an
    unparseable VERSION is skipped rather than guessed at (the collector reports the reason)."""
    if not text:
        return None
    parts = str(text).strip().split("-", 1)[0].split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def compute_lane_status_findings(facts: dict) -> list[dict]:
    """Findings for a lane, ordered by LANE_STATUS_FINDING_ORDER. Pure."""
    found: dict[str, dict] = {}

    def add(finding_id: str, severity: str, detail: str) -> None:
        found[finding_id] = {"id": finding_id, "severity": severity, "detail": detail}

    integration = facts.get("integration_branch") or "the integration branch"

    # DETACHED is a POSITIVE finding: it requires that the branch probe actually ran and returned
    # nothing. A failed probe contributes an `unverified` reason instead, so a wedged repository
    # reports UNVERIFIED rather than a fabricated detached HEAD with a branch-switch remedy.
    if facts.get("branch") is None and not facts.get("branch_probe_failed"):
        add("DETACHED", "drift", "detached HEAD - this lane has no branch identity")

    if facts.get("upstream_gone"):
        add(
            "ORPHANED",
            "drift",
            f"upstream {facts.get('upstream') or '<unknown>'} is GONE",
        )

    behind = _int_or_none(facts.get("behind"))
    ahead = _int_or_none(facts.get("ahead"))

    # MERGED requires ancestry AND no unique commits AND actually being behind. Ancestry alone is
    # satisfied by a brand-new branch sitting at the integration tip, which would report MERGED and
    # print a remedy creating another branch at that same tip -- forever. The detail describes what
    # was observed rather than asserting merge completion, because git cannot distinguish a merged
    # branch from one that never received a commit.
    if facts.get("merged_into_base") and ahead == 0 and behind:
        add(
            "MERGED",
            "drift",
            f"no unique commits and behind {integration} by {behind} commit(s) - "
            "this branch has either landed or was never used",
        )

    # STALE has two INDEPENDENT triggers: being behind at all, and carrying an older VERSION. A base
    # commit that touches only PM surfaces does not bump VERSION, so the behind trigger is what
    # catches that case; the version trigger is what reads instantly to a human.
    stale_bits: list[str] = []
    if behind:
        stale_bits.append(f"behind {integration} by {behind} commit(s)")
    local_v = _version_tuple_or_none(facts.get("local_version"))
    base_v = _version_tuple_or_none(facts.get("base_version"))
    # DIRECTIONAL: only OLDER is stale. A release branch is legitimately ahead -- the release task
    # itself bumps local VERSION while the base still reads the previous one.
    if local_v is not None and base_v is not None and local_v < base_v:
        stale_bits.append(
            f"VERSION {_safe(facts.get('local_version'), limit=40)} - "
            f"{_safe(integration, limit=80)} is at {_safe(facts.get('base_version'), limit=40)}"
        )
    if stale_bits:
        add("STALE", "drift", "; ".join(stale_bits))

    if facts.get("squatted_by"):
        # INFO, not drift: this lane compares against the remote ref, so a peer worktree holding the
        # local integration branch does not make this lane stale, and no command this lane can run
        # will clear it. Rendering it as drift would promise a remediation that does not exist.
        add(
            "SQUATTED",
            "info",
            f"{integration} is held by another worktree behind the remote: "
            f"{facts['squatted_by']} - do not trust the local ref; this lane compares against "
            f"{facts.get('remote')}/{integration}",
        )

    foreign = facts.get("foreign_lease")
    if foreign:
        # `drift`, not a blocking severity: this module has none, and it carries a never-blocks
        # contract because it runs as a session-start hook. The blocking teeth are PR2's
        # lane-start refusal, which a human ran on purpose and can answer. Deliberately NOT in
        # LANE_STATUS_RESOLVING_FINDINGS -- the SQUATTED precedent -- because a rerun cannot clear
        # a live peer, and promising one would loop forever.
        holder = str(foreign.get("session_id") or "another session")
        branch = str(foreign.get("branch") or "")
        where = f" on {branch}" if branch else ""
        add(
            "CONCURRENT",
            "drift",
            f"{holder} is working in this worktree{where} - your edits and theirs overwrite each "
            "other with no error; work in your own worktree instead",
        )

    if facts.get("dirty"):
        if foreign:
            # Reworded ONLY when there is a foreign lease. The no-lease line below is pinned
            # byte-identical by adapter greps and the policy-phrase SSOT, so a blanket rewording
            # would break callers that never see a peer at all.
            add(
                "DIRTY",
                "drift",
                "uncommitted changes, and another session is in this worktree - they may not be "
                "yours",
            )
        else:
            add("DIRTY", "info", "uncommitted changes inherited from a prior session")

    # Tri-state: only an actively-checked-and-unmatched claim is a finding. Adopters who configure
    # no claim source get "not-checked", which is silent.
    if facts.get("claim_state") == "unmatched":
        add(
            "UNCLAIMED",
            "info",
            f"no item under {facts.get('claim_source') or 'the configured claim source'} "
            "declares this branch",
        )

    if facts.get("baseline_moved"):
        add(
            "BASELINE-MOVED",
            "info",
            "the integration branch advanced since the latest-code baseline was written",
        )

    unverified = [str(reason) for reason in (facts.get("unverified") or []) if str(reason)]
    if unverified:
        # C5: never silent. An unrunnable check is reported, never guessed at.
        add("UNVERIFIED", "info", "; ".join(unverified))

    return [found[key] for key in LANE_STATUS_FINDING_ORDER if key in found]


def _replacement_is_safe(facts: dict) -> bool:
    """True when moving the lane to a fresh branch cannot strand unique commits.

    STALE fires whenever `behind > 0`, which includes a DIVERGENT lane that also has unique commits;
    replacing the branch there would move the agent off work that exists nowhere else.

    A detached HEAD is NOT automatically safe. The previous revision returned True for it
    unconditionally, so a detached HEAD carrying unique commits would be told to create a branch at
    the integration base and switch -- leaving those commits reachable only through the reflog,
    executed by an agent that policy tells to run the printed command. Unique commits are what
    matters, branch identity is not; `ahead == 0` is the only safe condition, and an `unknown`
    ahead count is treated as unsafe.
    """
    return _int_or_none(facts.get("ahead")) == 0


def _q(value: object) -> str:
    """Shell-quote a value for a RUNNABLE command, losslessly.

    `shlex.quote` protects an ARGUMENT, not a COMMENT: quoting `backlog\ntouch /tmp/pwned` yields
    a two-line string, and after a leading `#` the newline ends the comment so the second line
    executes -- under a banner telling the agent to run the block. Stripping control characters is
    what makes both positions safe.

    It strips ONLY control characters, and never collapses whitespace or truncates. The previous
    revision quoted `_safe(value)`, which meant a path containing two spaces, or longer than the
    display limit, produced a command that operated on a DIFFERENT path than the one reported --
    silently wrong, in text an agent is told to execute. Display truncation and lossless quoting
    are separate concerns and must stay separate.
    """
    cleaned = "".join(char for char in str(value) if char.isprintable())
    return shlex.quote(cleaned)


def _git(target: object, *args: str) -> str:
    """A git command pinned to the INSPECTED lane. `lane-status --target /other/lane` is supported,
    so a bare `git ...` would act on whatever repository the agent happens to be sitting in."""
    return "git -C " + _q(target) + " " + " ".join(args)


def _fresh_branch_program(
    target: object, fresh: str, base: str, remote: str, *, fetch_first: bool = True
) -> str:
    """Collision-safe branch replacement. `git switch -c` FAILS when the destination already exists
    -- from an earlier remediation attempt, or an unrelated lane using the same convention -- and
    `-C` would silently reset someone else's branch. Preflight a free name instead."""
    # Built by concatenation rather than nested-quote f-strings: reusing the outer quote character
    # inside an f-string is Python 3.12+ syntax, and CI runs 3.10 as well.
    q_fresh = _q(fresh)
    name_ref = '"$name"'
    fetch = _git(target, "fetch", shlex.quote(remote), "--prune")
    # `--verify` requires a FULL ref: `show-ref --verify experimental` exits 1 even when the branch
    # exists (verified), so the previous short-name probe never detected a collision and the
    # promised `-2` suffix was never chosen -- the switch just failed.
    probe = _git(target, "show-ref", "--verify", "--quiet", '"refs/heads/$name"')
    switch = _git(target, "switch", "--no-track", "-c", name_ref, _q(base))
    prefix = (fetch + " && ") if fetch_first else ""
    return (
        prefix
        + "name="
        + q_fresh
        + "; i=2; while "
        + probe
        + "; do name="
        + q_fresh
        + "-$i; i=$((i+1)); done; "
        + switch
    )


def lane_status_remedies(target: object, facts: dict, findings: list[dict]) -> list[str]:
    """Runnable remedies for a finding set, coalesced.

    MERGED and STALE overlap by construction (both need `behind > 0`), and ORPHANED pairs with STALE
    in the acceptance case -- so a per-finding remedy API would print two branch-replacement
    programs under a banner telling the agent to run them, and the second would execute against
    state the first had changed. At most ONE replacement program is emitted.
    """
    # Raw values: _q quotes losslessly, and the report lines that DISPLAY them apply _safe
    # separately. Pre-truncating here would corrupt the runnable commands.
    integration = str(facts.get("integration_branch") or "main")
    remote = str(facts.get("remote") or "origin")
    branch = facts.get("branch")
    base = f"{remote}/{integration}"
    q_remote = _q(remote)
    ids = {finding["id"] for finding in findings}
    lines: list[str] = []

    wants_replacement = bool(ids & set(_REPLACEMENT_FINDINGS))
    wants_rebase = "STALE" in ids or ("ORPHANED" in ids and not _replacement_is_safe(facts))

    if wants_replacement and _replacement_is_safe(facts):
        fresh = f"{branch}-current" if branch else f"lane-{integration}-current"
        lines.append(_fresh_branch_program(target, fresh, base, remote))
    elif wants_replacement or wants_rebase:
        # Unique commits exist (or the lane is only STALE): rebase, never replace. The fetch carries
        # the explicit integration refspec, or in a narrow-fetchspec clone the rebase would target a
        # stale base and the mandated rerun would report clean while the remote had advanced.
        refspec = _q(f"+refs/heads/{integration}:refs/remotes/{remote}/{integration}")
        # A rebase alone moves the commits but does NOT clear an identity finding: the upstream is
        # still gone, and a detached HEAD is still detached -- so the mandated rerun would report
        # the same verdict and print the same remedy forever, including on the deleted-upstream
        # case this feature exists for. Attach identity FIRST (which also preserves the commits),
        # then bring the work current.
        identity: list[str] = []
        if "DETACHED" in ids:
            fresh = f"lane-{integration}-current"
            identity.append(_fresh_branch_program(target, fresh, "HEAD", remote, fetch_first=False))
        elif "ORPHANED" in ids:
            # Local and non-destructive: clears the dangling tracking ref so ORPHANED stops firing
            # without pushing anything on the agent's behalf.
            identity.append(_git(target, "branch", "--unset-upstream"))
        lines.extend(identity)
        lines.append(
            f"{_git(target, 'fetch', q_remote, '--prune')} && "
            f"{_git(target, 'fetch', q_remote, refspec)} && "
            f"{_git(target, 'rebase', _q(base))}"
        )

    if "SQUATTED" in ids:
        squat_path = str(facts.get("squatted_path") or "")
        if squat_path:
            lines.append(
                f"# {_q(integration)} is checked out at {_q(squat_path)}; a "
                f"fetch cannot advance it from here. This lane is unaffected -- it "
                f"compares against "
                f"{_q(base)}. Coordinate with that lane; never remove a peer's worktree."
            )
    if "DIRTY" in ids:
        lines.append(
            f"{_git(target, 'status', '--short')}   # commit, stash, or discard before new work"
        )
    if "UNCLAIMED" in ids:
        lines.append(
            f"# no item under {_q(facts.get('claim_source') or 'the claim source')} "
            f"declares {_q(branch or 'this branch')}. Claim the item in the backlog "
            "(or rename this lane to match the claimed item) before recording work against it."
        )
    if "BASELINE-MOVED" in ids:
        lines.append(f"tautline latest-code-status --target {_q(target)} --write")

    return lines


def render_lane_status_report(
    target: object,
    facts: dict,
    findings: list[dict],
    *,
    abbreviated: bool = False,
) -> list[str]:
    """Verdict-first report. Clean is exactly ONE line -- silence must never be ambiguous with
    "the check did not run"."""
    header_branch = facts.get("branch") or "DETACHED"
    version = facts.get("local_version") or "unknown"
    if not findings:
        # Names the COMPARISON BASE, because "ahead=0 behind=0" is meaningless without saying
        # behind what.
        return [
            f"TAUTLINE LANE STATUS - {_safe(header_branch, limit=80)} @ {_safe(version, limit=40)} "
            f"vs {_safe(facts.get('integration_branch'), limit=80)}, "
            f"ahead={_safe(facts.get('ahead', '?'), limit=12)} "
            f"behind={_safe(facts.get('behind', '?'), limit=12)}, clean OK"
        ]

    lines = [
        f"TAUTLINE LANE STATUS - {_safe(target, limit=200)}          "
        "[report-only, never blocks]"
    ]
    for finding in findings:
        mark = "x" if finding["severity"] == "drift" else "-"
        if abbreviated:
            lines.append(f"  {mark} {finding['id']}")
        else:
            lines.append(f"  {mark} {finding['id']:<14} {_safe(finding['detail'], limit=400)}")

    remedies = lane_status_remedies(target, facts, findings)
    if remedies:
        lines.append("  -> THE AGENT RUNS THIS, NOT THE OPERATOR:")
        lines.extend(f"       {command}" for command in remedies)
        if any(finding["id"] in LANE_STATUS_RESOLVING_FINDINGS for finding in findings):
            lines.append(f"       tautline lane-status --target {_q(target)}")
    # 0.21.0 ships no Stop-seam re-assertion (that is item 28), so promising one would be this
    # item's own defect class: guidance text describing behaviour the release does not have.
    lines.append("  Not blocking. This report is the only notice; nothing re-checks it for you.")
    return lines
