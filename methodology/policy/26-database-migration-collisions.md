## Database Migration Collisions

- Parallel lanes that generate database migrations must check for monotonic migration-index collisions before commit, push, merge queue, and after rebasing onto main.
- If migration SQL, snapshot metadata, or migration journal files conflict, do not resolve by choosing one side wholesale. Preserve the already-landed migration, assign this lane the next free migration index, rebuild metadata/journal ordering, and verify with adapter database tests plus the merge-conflict check.
- Use the ops-owned `database-migration-collision` skill for stack-specific migration index, snapshot, journal, and delivery-evidence repair steps.
