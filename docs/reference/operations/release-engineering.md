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

## The Release Tail

Everything after a promotion lands — export, mirror, tag, GitHub Release,
registry publish, drift verification — is one command:

```bash
tautline release-tail
```

It runs these steps in order, printing `key: value` evidence for each, and
fails closed and loudly at the first one that does not hold:

1. **Preflight.** The public-release export gate must report `ok`; `VERSION`
   must agree with the newest section of `CHANGELOG.md`; and the release notes
   are scanned for leak terms (internal task IDs, private doc paths, absolute
   home-directory paths). Release notes are a permanent public surface, so a
   leak term refuses the release rather than publishing and retracting it.
2. **Export.** `public-release-export` builds the clean public tree.
3. **Mirror.** The public mirror is cloned, the export tree is overlaid onto it
   while its `.git/` is preserved, and the result is committed **on top of the
   mirror's current HEAD**. The push is always a plain fast-forward. The tail
   never force-pushes and never rewrites the mirror's history — existing clones
   stay valid. (The export alone is a fresh repository with a root commit and
   shares no ancestor with the mirror, which is why the overlay exists.)
4. **Tag.** `vX.Y.Z` is created at the pushed commit and pushed. If the tag
   already exists but points somewhere else, the tail refuses rather than
   moving it.
5. **Release.** A GitHub Release is created against the public repo, targeting
   the exact SHA just pushed, with notes taken from the CHANGELOG section.
6. **Publish.** Publishing the Release fires `publish-npm.yml` and
   `publish-pypi.yml` on the mirror. The tail waits for the runs **at that
   exact commit SHA** to reach a terminal state. A stale successful run from an
   earlier release is never mistaken for this one, and "no matching run yet"
   means still waiting, never success.
7. **Drift check.** `release-drift-check` must report repo, npm, and PyPI all
   holding the same version.

### No credentials

**Publishing requires no credentials at all.** Both publish workflows
authenticate with **OIDC Trusted Publishing**: GitHub Actions mints a
short-lived identity token, and the registry exchanges it for a
single-use credential. There is no npm token, no PyPI token, nothing to paste,
store, or rotate — and nothing to leak. A publish workflow that needs a secret
is a bug, and a test fails if one is ever reintroduced.

Because a registry publish is **irreversible** — a version can never be
re-published — each workflow first asks the registry whether the target version
already exists. If it does, the workflow no-ops. If the registry cannot be read
at all, the workflow fails closed rather than publishing blind.

### Flags

```bash
tautline release-tail --dry-run        # print the full plan, change nothing
tautline release-tail --skip-registry  # stop at a DRAFT Release; fire no publish
tautline release-tail                  # run (or resume) the tail to completion
```

- **`--dry-run`** is completely offline: it reads files, prints every step it
  would take, and makes no network calls and no changes. Use it first.
- **`--skip-registry`** creates the GitHub Release as a **draft**. A draft
  Release emits no `release: published` event, so neither publish workflow
  fires. This is what makes the one-time bootstrap below safe.
- **Resuming is the default and needs no flag.** A plain `release-tail` run
  re-derives progress from the world rather than from a journal:
  mirror already up to date, tag already present, Release already drafted or
  created, registry already holding the version. It continues the remaining
  steps without repeating the completed ones, so a tail that failed partway —
  after the tag, say, or after one of the two registries — is restarted by simply
  running it again. It never double-publishes.

### Drift check

```bash
tautline release-drift-check
```

Reports the version held by the repository, npm, and PyPI, then a verdict; it
exits non-zero if they disagree. `release-tail` runs it after publishing, and
`.github/workflows/release-drift-check.yml` runs it on a schedule against the
public mirror, so a stale registry surfaces within a day instead of being
discovered months later.

### One-time bootstrap: configuring Trusted Publishing

Trusted Publishing can only be configured **after** the publish workflows exist
on the mirror's default branch, and it must be configured **before** any
Release is published — otherwise the publish workflows have no trust to
exchange their OIDC token for.

**Until Trusted Publishing is configured, the publish workflows fail closed.
That is by design, not a bug.** They will not fall back to a token, because
there is no token to fall back to.

Run these four steps **in this exact order**. The order is load-bearing: doing
step 4 before step 3 publishes into a registry that will reject the exchange,
and skipping the draft in step 2 either leaves the release with no GitHub
Release at all, or publishes a Release later that double-publishes a version
the registries already hold.

**1. Merge and promote**, so `publish-npm.yml` and `publish-pypi.yml` exist on
the mirror's default branch. (A workflow that is not on the default branch of
the public repo cannot be bound as a trusted publisher.)

**2. Push the mirror and cut a draft Release:**

```bash
tautline release-tail --skip-registry
```

This pushes the mirror, creates and pushes the tag, and creates the GitHub
Release **as a draft**. No `release: published` event fires, so no publish
workflow runs and nothing reaches a registry yet.

**3. Configure Trusted Publishing on npm and PyPI** (below). Both bind to the
owner, the repository, and the workflow **filename**.

**4. Publish the draft** — rerun the tail, this time without `--skip-registry`:

```bash
tautline release-tail
```

This publishes the *existing* draft Release rather than creating a second one.
That fires `release: published` exactly once, the publish workflows run, both
registries authenticate over OIDC, and the drift check confirms all three
surfaces agree.

### Workflow filenames are load-bearing

Trusted Publishing binds to **owner + repository + workflow filename**. The
filename is part of the trust relationship, not an incidental detail.

**Renaming `publish-npm.yml` or `publish-pypi.yml` silently breaks the trust
link** and every subsequent publish fails. If a workflow ever must be renamed,
the trusted publisher entry on the registry must be updated in the same change.

### Registry configuration

Both registries must be configured by hand, once. The forms cannot be driven by
an API. `tautline` already exists on both registries, so both use the
*existing-project* flow.

Verified against vendor documentation on 2026-07-13. If these screens have
moved, trust the vendor's page, not this one.

**npm** — source:
[docs.npmjs.com/trusted-publishers](https://docs.npmjs.com/trusted-publishers/)

Navigate to **npmjs.com → Packages → `tautline` → Settings → Trusted
publishing**, then under **"Select your publisher"** choose **GitHub Actions**
and fill in:

| Field | Value |
| --- | --- |
| Organization or user | `tautlines` |
| Repository | `tautline` |
| Workflow filename | `publish-npm.yml` |
| Environment name | *leave empty* |
| Allowed actions | `npm publish` |

- **Workflow filename** is the bare filename **including the extension** — not
  a path. Do not enter `.github/workflows/publish-npm.yml`.
- **Environment name is optional and must be left empty here.** `publish-npm.yml`
  declares no GitHub deployment `environment:`. Naming one on the registry that
  the workflow does not enter will not match, and the publish will fail.
- **Allowed actions** is required and at least one must be selected. Select
  `npm publish`. (`npm stage publish` is for staged publishing, which this
  workflow does not use.)
- npm's Trusted Publishing requires **npm CLI ≥ 11.5.1 and Node ≥ 22.14.0**;
  `publish-npm.yml` pins both. Note that npm **automatically generates and
  publishes provenance attestations** when publishing this way — no
  `--provenance` flag is needed, and none is passed.
- Once a trusted publish has succeeded, npm recommends tightening the package's
  Publishing access setting to **"Require two-factor authentication and
  disallow tokens"**, which closes off token-based publishing entirely.

**PyPI** — source:
[docs.pypi.org/trusted-publishers/adding-a-publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)

Navigate to **pypi.org → Your projects → `tautline` → Manage → Publishing**,
then add a **GitHub** publisher:

| Field | Value |
| --- | --- |
| Owner | `tautlines` |
| Repository name | `tautline` |
| Workflow name | `publish-pypi.yml` |
| Environment name | *leave empty* |

- **Workflow name** is the bare filename, e.g. `publish-pypi.yml` — not
  `.github/workflows/publish-pypi.yml`. The file must exist under
  `.github/workflows/` in the repository named above.
- **Environment name is optional, and must be left empty here.** PyPI's
  documentation *strongly recommends* binding to a GitHub environment, and the
  PyPA guide's example uses one named `pypi` — but `publish-pypi.yml` declares
  no `environment:`, so entering `pypi` would not match the OIDC claim and the
  publish would fail. Leave it blank unless the workflow is changed to declare
  an environment, in which case both must change together.

**A note on PyPI "pending" publishers.** PyPI also offers a *pending* publisher,
configured from the account sidebar rather than a project
([docs.pypi.org/trusted-publishers/creating-a-project-through-oidc](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)).
That flow exists only for a project that **does not exist on PyPI yet**: it
reserves nothing, and converts into a normal publisher the first time it is
used to publish. **`tautline` already exists on PyPI, so the pending-publisher
flow does not apply** — use the project's own Publishing page as above.

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
