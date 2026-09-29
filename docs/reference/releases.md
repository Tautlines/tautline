# Public release procedure

Tautline develops on `experimental`. `main` is the stable development channel. The public
repository, `Tautlines/tautline`, receives a sanitized export with separate history. Never push
the private development history to the public repository.

## Prepare one release

- Merge the tested changes after the fresh-context self-review and different-model review. Run `scripts/test.sh` on Python 3.12,
  and verify the upgrade from the previous public version, not just the latest development tip.
- Update `VERSION`, both plugin packages' manifests, the marketplace version, and release notes
  together. The newest `CHANGELOG.md` section must match the version and describe the actual
  public upgrade, including removed behavior and migration steps.
- Keep private scan terms in an untracked file outside the public export destination. Review
  current product promises and package metadata. No private backlog content belongs in the export.
- Commit the complete release tree. Promote that reviewed tree to the development `main`
  branch through the normal repository flow. Run the publishing command from that committed
  checkout; the CLI does not itself promote development branches or run the test suite.

## Preview and publish

Use the checked-out CLI so the release does not accidentally execute an older installed copy:

```bash
python3.12 bin/tautline cut-release --dry-run
python3.12 bin/tautline public-release-export \
  --destination /tmp/tautline-public-candidate \
  --private-terms-file /path/to/private-release-terms.txt --write
python3.12 bin/tautline release-tail --dry-run
python3.12 bin/tautline release-tail \
  --private-terms-file /path/to/private-release-terms.txt
```

Choose a fresh export destination. The export prints sanitization findings; resolve them before
publishing. `release-tail --dry-run` prints the publishing plan and checks release-note/version
consistency; it does **not** execute the export or prove that remote credentials work.

`release-tail` exports and checks the committed tree, clones the public mirror, overlays the
export, and pushes a normal fast-forward commit. It creates an annotated `vVERSION` tag and a
GitHub release. The release event triggers `publish-pypi.yml` and `publish-npm.yml`; the command
waits for publishing runs at the exact mirror commit and checks registry versions afterward.
It refuses to move an existing tag to another commit. It does not produce a signed public tag
or attach a complete signed artifact bundle.

Prerequisites are GitHub `gh` and Git push authentication with access to the public repository,
and the existing PyPI/npm Trusted Publishing configuration for that repository and those
workflow filenames. The registry workflows use GitHub OIDC, not a local registry token. PyPI
ships the Python runtime; npm ships a pointer package.

`cut-release` is a separate local checksum/tag helper. `--create-tag` creates a local tag;
it does not push a tag or publish packages. It is not a substitute for `release-tail`.

## Verify or resume

```bash
python3.12 bin/tautline release-drift-check
gh release view --repo Tautlines/tautline
gh run list --repo Tautlines/tautline --workflow publish-pypi.yml --limit 3
gh run list --repo Tautlines/tautline --workflow publish-npm.yml --limit 3
```

Also install the published PyPI version in a clean environment and exercise its quickstart.
Check that the public GitHub release, repository `VERSION`, PyPI, and npm agree. Remote CI
still needs to pass; a successful publishing run alone is not application validation.

If a registry step fails, correct the cause and rerun the same `release-tail` command from the
same release tree. It recognizes existing tags/releases and dispatches a missing registry's
workflow for the pinned version. Never retag a published version or alter its contents.
`--skip-registry` is a bootstrap option that leaves a draft release; it is not a completed
public release.
