"""RCA: derived-artifact freshness was a published HARD Stage-1 gate (canonical-rules: "regenerate
or prove those artifacts are current") enforced only by agent self-report -- no machine check.

`derived_artifact_staleness` is the machine check: within the reviewed base..HEAD diff, if a declared
artifact's source globs matched a changed file but the committed artifact itself was not changed in
that same diff, the mirror is stale (sources moved, the derived output did not). Hermetic -- it
inspects the changed-file set only, never runs a build, and cannot be silenced without actually
changing the artifact.
"""


import subprocess

import pytest


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _entry(artifact, sources, regenerate=""):
    return {"artifact": artifact, "sources": sources, "regenerate": regenerate}


# --- adapter config normalization (fail-closed on malformed declarations) ----------------------


def test_normalize_accepts_valid_entries(cli):
    raw = [{"artifact": "a.lock", "sources": ["a/*", "b/*"], "regenerate": "make a"}]
    assert cli.normalize_derived_artifacts(raw) == [
        {"artifact": "a.lock", "sources": ["a/*", "b/*"], "regenerate": "make a"}
    ]


def test_normalize_defaults_and_trims(cli):
    assert cli.normalize_derived_artifacts([{"artifact": "  a.lock  ", "sources": [" a/* "]}]) == [
        {"artifact": "a.lock", "sources": ["a/*"], "regenerate": ""}
    ]


def test_normalize_missing_is_empty_list(cli):
    assert cli.normalize_derived_artifacts(None) == []
    assert cli.normalize_derived_artifacts([]) == []


def test_normalize_rejects_malformed(cli):
    for bad in [
        {"artifact": "x", "sources": ["y"]},  # not a list
        [{"sources": ["a/*"]}],  # missing artifact
        [{"artifact": "a", "sources": []}],  # empty sources
        [{"artifact": "a", "sources": "a/*"}],  # sources not a list
        [{"artifact": "a", "sources": [""]}],  # blank source glob
        ["not-an-object"],
    ]:
        with pytest.raises(SystemExit):
            cli.normalize_derived_artifacts(bad)


# --- gate errors with the narrow recorded override --------------------------------------------


# --- review-fix hardening: path normalization, ** rejection, non-ASCII paths ------------------


def test_normalize_strips_leading_dot_slash(cli):
    # './gen/out.json' must line up with git's 'gen/out.json' or a regenerated artifact false-flags.
    assert cli.normalize_derived_artifacts([{"artifact": "./gen/out.json", "sources": ["./src/*"]}]) == [
        {"artifact": "gen/out.json", "sources": ["src/*"], "regenerate": ""}
    ]


def test_normalize_rejects_double_star_glob(cli):
    # fnmatch has no recursive '**'; 'proto/**/*.proto' would silently miss shallow sources.
    with pytest.raises(SystemExit):
        cli.normalize_derived_artifacts([{"artifact": "a", "sources": ["proto/**/*.proto"]}])
