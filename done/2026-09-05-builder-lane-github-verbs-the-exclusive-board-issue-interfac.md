# Builder-lane GitHub verbs: the exclusive board/issue interface for build agents

# Builder-lane GitHub verbs

Build agents keep taking liberties with a product's GitHub issues and Project board (relabelling, closing, filing feature issues, moving cards). Prose rules do not hold. Replace them with a deterministic, allowed-actions-only layer: if a verb does not exist, a builder cannot do it.

## Verbs (the whole builder surface)
- `tautline board list|show|fields` -- read the ProjectV2 board (filters: status, type, label, text).
- `tautline issue show|comments|find` -- read repo issues.
- `tautline issue comment` -- write ONE stamped comment.
- `tautline debt file` -- create an issue carrying exactly the configured debt label, off-board, dedup-checked, read back.

## Enforcement (build-only; humans are never bound)
- A lane is a builder only when `TAUTLINE_ROLE=builder` or `.ai-work/lane-role` says so (`src/tautline_methodology/builder.py`). Default is human.
- `builder-guard`: a Claude PreToolUse Bash hook plus a `gh` PATH shim for non-Claude lanes; both are no-ops for humans and deny raw `gh issue|project|label|api` (issues/projects/graphql) for builders.
- `builder-token`: mint a GitHub App installation token so builders act as `<app>[bot]` with Projects read-only, making board writes impossible at the token layer and attributing every write.
- Lean adapter opt-in block: `builderGithub` (methodology/adapter-schema-lean.json).

## Done when
Verbs, guard, and token ship with socket-level tests; `scripts/test.sh` green; the adopter repo can opt in with one config block.
