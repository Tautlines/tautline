---
name: database-migration-collision
description: Use when parallel lanes generate database migrations with monotonic indexes, especially Drizzle SQL snapshots and journal entries, or when merge conflicts involve migration numbering, snapshots, or journals.
---

# Database Migration Collision

Use this skill when parallel lanes or merge conflicts touch database migrations with monotonic indexes such as `0004_*.sql`, `meta/0004_snapshot.json`, and `_journal.json`.

Read `references/database-migration-collision-policy.md` in full before repairing migration numbering, snapshot metadata, migration journal entries, Drizzle snapshots, or generated database artifacts.

## Authority

- The project adapter owns exact database, test, and migration generation commands; do not invent them.
- A migration chain is code and data-shape authority. Do not leave SQL files, snapshot metadata, or migration journal entries guessed, partially regenerated, or verified only by file rename.

## Fast Path

Before generating, committing, pushing, or queueing, fetch the latest base, bring the lane current when safe, check whether another merged or queued PR consumed the next index, generate from the current schema/chain, run the adapter merge-conflict check, and inspect migration-index collisions specifically. Repeat at PR boundaries; if another lane landed first, renumber and rebuild before pushing.

## Collision Signals

Treat these as collisions until proven otherwise:

- duplicate SQL numeric prefixes;
- both sides modify `meta/<index>_snapshot.json` or append the same journal index;
- snapshot `prevId` no longer points to the immediately previous journal entry;
- adapter merge-conflict output names migration SQL, migration metadata, or journal files.

## Cure Rule

Repair the chain rather than taking either side wholesale. Use the reference playbook to identify the winner, assign the next free index, rebuild snapshot metadata and the migration journal, regenerate required artifacts, and rerun adapter database/package tests plus the merge-conflict check.

Prefer the project migration generation command over hand-editing whenever it can rebuild metadata from schema and current migrations.

## Delivery Evidence

Before declaring the collision resolved, name the contested index, winner migration kept from base/main, new index assigned to this lane's migration, verification commands run, and any remaining deploy or migration-run risk.

Do not ask the human operator to choose a migration number when the next free index is derivable from the migration chain.

## Required Follow-Through

When a collision is possible, load `references/database-migration-collision-policy.md`, apply the preventive/cure playbook, and preserve the contested-index/winner/new-index evidence in the delivery summary.
