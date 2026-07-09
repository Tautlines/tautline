# Database Migration Collision Policy Reference

This reference keeps the detailed migration collision, Drizzle repair, snapshot
metadata, migration journal, prevention, and delivery-evidence policy behind the
concise `database-migration-collision` skill entrypoint.

## Core Rule

Use this policy when two lanes create database migrations from the same base,
when a merge conflict touches migration files, or when a migration system uses
monotonic indexes such as `0004_*.sql`, `meta/0004_snapshot.json`, and
`_journal.json`.

The project adapter owns exact database commands, test commands, and migration
generation commands. This policy owns the collision sequence. Do not invent
project-specific migration commands when the adapter or repo scripts define
them. A migration chain is code and data-shape authority: do not leave SQL
files, snapshot metadata, or migration journal entries guessed, partially
regenerated, or verified only by file rename.

## Prevention

Before generating a migration:

1. Fetch the latest base branch.
2. Bring the lane onto the latest base if that can be done safely.
3. Check whether another merged or queued PR has already consumed the next
   migration index.
4. Generate the migration from the current schema and current migration chain.
5. Before commit, push, or queue, run the adapter merge-conflict check and
   inspect migration-index collisions specifically.

During long push deferrals or multi-PR goals, repeat the migration collision
check at each PR boundary. If another lane lands a migration first, renumber and
rebuild the local migration before pushing.

Do not treat "I generated this earlier" as freshness proof. The relevant
question is whether the migration was generated against the current base,
current schema, and current migration journal at the point this branch is about
to leave the lane.

## Collision Signals

Treat any of these as a database migration collision until proven otherwise:

- two SQL migration files with the same numeric prefix;
- both sides modify the same `meta/<index>_snapshot.json`;
- both sides append a journal entry at the same index;
- a snapshot `prevId` points to a migration that is no longer the immediately
  previous journal entry;
- adapter merge-conflict output names migration SQL, migration metadata, or
  journal files.

## Drizzle Cure Playbook

For Drizzle-style migrations, repair the chain rather than taking either side
wholesale:

1. Identify the migration index already consumed by `main` or the merge base
   winner.
2. Identify the next free index after the winner's journal entry.
3. Rename the local SQL migration to the next free index.
4. Keep or restore the winner's snapshot at the contested index.
5. Rebuild the local snapshot as winner cumulative schema plus the local schema
   additions, with `prevId` pointing to the winner's snapshot id.
6. Append the local journal entry at the new index and preserve the winner's
   journal entry.
7. Regenerate any generated database artifacts required by the project.
8. Run the adapter database/package tests and the adapter merge-conflict check
   again.

If the project provides a migration generation command that can rebuild metadata
from schema and current migrations, prefer that command over hand-editing.
Hand-edit only when the repo's migration tool cannot express the merge repair,
and then verify with tests plus schema inspection. File renames alone are not
proof: the SQL, snapshot metadata, journal order, and generated database
artifacts must agree on the same chain.

The repair is complete only when a future lane can replay the journal in order
without guessing which snapshot belongs to which SQL file.

## Delivery Evidence

Before declaring the collision resolved, the summary must name:

- the contested index;
- the winner migration kept from base/main;
- the new index assigned to this lane's migration;
- the verification commands run;
- any remaining deploy or migration-run risk.

Do not ask the human operator to choose a migration number when the next free
index is derivable from the migration chain.
