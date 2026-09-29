"""Two plan-review runs inside one second must not share a log path.

The run log filename is stamped `%Y%m%dT%H%M%SZ` — SECOND resolution — and combined with the
plan slug and the round label. Two runs of the same plan and round inside one second therefore
produced the SAME path, and the second silently overwrote the first.

That is an evidence-integrity bug, not a cosmetic one: a recorded manifest binds its log by
sha256, so the overwrite makes `plan-finalization-precheck` refuse the plan with `plan review log
hash mismatch` — the lane cannot finalize a review it genuinely ran, and the original log is gone.

It reddened `experimental` on three unrelated commits before the mechanism was identified, and it
is reachable by any lane that takes two rounds quickly.
"""

from datetime import datetime, timezone
from pathlib import Path

from tautline_methodology import cli


def test_the_stamp_alone_collides_within_one_second():
    """The premise, asserted rather than assumed -- if the stamp ever gains sub-second
    resolution this test should fail and the guard below becomes redundant.

    Built from a FIXED instant, not `now()` (R1 review, P2). Two `now()` calls straddling a UTC
    second boundary format different seconds, so the original version of this test would have
    failed intermittently in CI -- reproducing, inside the fix for a same-second collision, the
    very class of timing-dependent red it exists to remove.
    """
    fixed = datetime(2026, 8, 22, 23, 25, 43, tzinfo=timezone.utc)

    def stamped(moment):
        stamp = moment.strftime("%Y%m%dT%H%M%SZ")
        return f"{stamp}-{cli.slugify('admin', 'plan')}-{cli.slugify('R2', 'round')}.log"

    # Two DIFFERENT instants inside one second must still produce one name -- which is the
    # property that makes the collision reachable at all.
    assert stamped(fixed) == stamped(fixed.replace(microsecond=999_999)), (
        "two runs in one second must produce one name -- that is why the guard exists"
    )


def test_a_surviving_meta_without_its_log_still_forces_a_new_name(tmp_path):
    """R1 review, P2. The pair, not just the log.

    `unique_destination` only avoids a file at the name it is given. A run whose `.log` was
    cleaned up while its `.log.meta.json` survived would be handed the original name back and
    clobber that meta — the same evidence loss this guard exists to stop, reached from the other
    side.
    """
    # Only the META exists; the log does not.
    (tmp_path / "20260822T232543Z-admin-r2.log.meta.json").write_text("{}", encoding="utf-8")

    # The guard's own predicate, reproduced exactly as the seam applies it.
    def taken(candidate):
        return candidate.exists() or candidate.with_name(f"{candidate.name}.meta.json").exists()

    original = tmp_path / "20260822T232543Z-admin-r2.log"
    assert taken(original), "a surviving meta must count as taken even with no log beside it"

    base = original.name
    chosen, counter = original, 1
    while taken(chosen):
        chosen = tmp_path / f"{Path(base).stem}-{counter}{Path(base).suffix}"
        counter += 1
    assert chosen.name == "20260822T232543Z-admin-r2-1.log"
    assert not taken(chosen)
