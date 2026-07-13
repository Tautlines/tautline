# Release Engineering

This reference owns maintainer-only release commands, public contract checks,
public-release gates, and clean export workflow. Keep adopter onboarding in the
top-level `README.md`; keep release mechanics here.

## Release Gate Commands

Run the core repository checks before publishing a framework release:

```bash
scripts/test.sh
scripts/validate.sh
tautline public-contract --check
tautline canonical-policy --check
tautline public-release-check
```

The public contract manifest marks framework surfaces as `stable`,
`experimental`, `deprecated`, or `internal`:

```bash
tautline public-contract
tautline public-contract --check
```

Stable surfaces follow semver expectations even before 1.0: patch releases are
bugfix-only, minor releases are additive or deprecating, and removals wait for a
major release with a migration path.

## Public Release Export

`public-release-check` blocks publication while private adapters, private paths,
or private history remain in the repository. For same-repo publication, treat a
clean public-release check as a release prerequisite.

For clean-repo publication, export a candidate repository:

```bash
tautline public-release-export \
  --private-terms-file ~/.config/minervit/public-release-private-terms.txt \
  --destination ../tautline-dev-public \
  --write
```

`public-release-export` creates a fresh git repository candidate and runs the
same public-release gate against that clean history. Keep
`--private-terms-file` or `MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS` populated for
private release candidates after private adapters have moved out of the tree,
because adapter-derived names are no longer available to scan. The file accepts
newline-delimited terms, comma-delimited terms, comments beginning with `#`, or a
JSON string array. Keep it untracked and outside the public export destination.
`public-release-export` refuses the file when it resolves inside the framework
repository or inside the export destination. The export prints only the term
source and count; it must not print or write the private term values.

`public-release-check` accepts the same private-term file when validating a
candidate checkout directly:

```bash
tautline public-release-check \
  --private-terms-file ~/.config/minervit/public-release-private-terms.txt
```

Normal public release exports use tracked files from a committed tree.
`--include-working-tree` and `--include-untracked` are only for in-progress
validation before the release branch is committed.

### Public Export Preflight

Run this preflight against a scratch destination before any public push, so
the export boundary is verified rather than assumed. `public-release-export`
already fails closed on private terms, dirty/untracked files, and known
private-content patterns; this preflight additionally confirms the specific
boundary this repository promises (excluded directories, the two public
product docs, squashed changelogs, and no maintainer-identifying paths).

```bash
# 1. Export a clean candidate from a committed tree into a scratch destination.
tautline public-release-export \
  --destination /path/to/scratch/export \
  --write --allow-empty-private-terms
# (drop --allow-empty-private-terms and pass --private-terms-file once
# private product/client terms are configured; see above.)

# 2. Assert the export boundary.
EXPORT=/path/to/scratch/export
test ! -e "$EXPORT/docs/backlog"
test ! -e "$EXPORT/docs/productization"
test ! -e "$EXPORT/docs/superpowers"
[ "$(ls "$EXPORT/docs/product")" = "$(printf 'positioning.md\nsupport-sla-model.md')" ]
head -20 "$EXPORT/CHANGELOG.md"                                    # squashed, single launch entry
cat "$EXPORT/plugins/tautline-core/CHANGELOG.md" # pointer stub
```

For the maintainer-identifying-path check, reuse the exact blocked-token
tuple from `tests/test_public_boundary_scan.py` (`PERSON_REFERENCE_RE`) or
`test_repository_text_excludes_person_specific_machine_tokens` rather than
retyping the tokens here — that keeps this doc from becoming a second place
those tokens have to be redacted from. A broader ad hoc scan that widens the
same suite's `PERSON_REFERENCE_RE` (person and machine-path tokens) and
`INTERNAL_FINDING_REFERENCE_RE` (internal task and finding IDs) into a single
loose grep also surfaces benign noise (redaction-regex source, synthetic
example paths, internal task-ID code comments); treat those hits as leads to
triage against the precise checks above, not as automatic failures.

## Release Tracks And Client Safety

Existing products and clients stay on `stable` unless they explicitly opt in to
`experimental`. Stable lanes must use pinned or signed releases and must not
raw-pull a moving framework branch during active work.

Use the first-class channel command instead of hand-editing JSON. The default
writes a lane-local `.minervit/pin.json` override:

```bash
tautline set-framework-channel --target . stable
tautline set-framework-channel --target . experimental
```

To change the repo-local adapter contract itself, update `_framework.channel`
through the same command and let it validate and re-render the generated lane
config:

```bash
tautline set-framework-channel --target . --source adapter stable
tautline set-framework-channel --target . --source adapter experimental
```

Before promoting experimental work to stable, verify that migration reports,
release notes, generated adapters, and status gates are compatible with existing
client lanes. Patch updates may run during work in progress only when the
release declares `wipSafe: true`; minor and major upgrades wait for a safe lane
boundary.

## Release Announcements

Maintainer release announcements are optional and delivered through the ops
plugin's configured notification channel. Publish a concise plain-language
release update with:

```bash
tautline publish-release-update --version "$(cat VERSION)"
```

The ops plugin (typically `plugins/tautline-ops/`) can configure
announcement delivery via the `MINERVIT_METHODOLOGY_RELEASE_GOOGLE_CHAT_WEBHOOK`
environment variable for Google Chat integration, the fallback in
`$HOME/.config/tautline/tautline.env`, or an explicitly supplied webhook URL.
Framework release gates do not depend on successful announcement delivery;
announcement mechanisms are an ops-only concern.

`public-release-check` (part of `scripts/validate.sh` and the gate commands
above) still requires the current `VERSION` to be release-accounted: either
delivered (recorded automatically when `publish-release-update` succeeds) or
explicitly suspended. If a release skips the Chat post, record a suspension
entry for it in `docs/releases/release-update-delivery.json` under
`"suspended"`, keyed by version, with `at` (ISO timestamp), `via`
(`operator-instruction` or `maintainer-backfill`), `scope`, and `reason`
fields — otherwise the gate fails with `release-update-current-missing`.

## Release Notes Archive

Maintainers may maintain a permanent archive of narrative release notes by
manually appending version entries to the dedicated archive branch:
`methodology-release-notes-archive:docs/releases/minervit-ai-delivery-methodology.md`.
The main-branch copy of that path is a size-capped stub that only records the
current release identity — never append narrative entries there (validation
enforces the stub shape). No automated appending occurs during the release
flow; the maintainer is responsible for curating archive-branch entries after
a release is complete and public.

## Migration Inspection

Use migration and status commands to inspect drift before changing a lane:

```bash
tautline methodology-status --target .
tautline migrate-adapter .tautline/adapter.json --dry-run
tautline migrate-adapter .tautline/adapter.json --write
```

Migration writes must be explicit, deterministic, validated, and idempotent.
Never auto-run adapter migrations during active implementation work.
