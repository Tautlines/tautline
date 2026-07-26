"""Release-machinery leaves: the registry-package MIT license text, the registry-JSON HTTP
fetch (404 -> None, every other failure propagates), the release-notes leak-term scan, the
public-mirror export overlay, and annotated-tag commit peeling. The stateful release verbs
(cut_release, registry_package, release_tail, release_migration_report, ...) stay in
bin/tautline; they reach VERSION/run_git/run_command/REPO_ROOT state and delegate here."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def registry_package_license() -> str:
    return (
        "MIT License\n\nCopyright (c) 2026 Minervit\n\n"
        "See https://github.com/tautlines/tautline/blob/main/LICENSE\n"
    )


RELEASE_TAIL_LEAK_TERMS = ("METH-FU", "docs/backlog/", "docs/productization/", "/Users/")


def release_http_json(url: str, timeout: int = 20) -> dict | None:
    """GET a registry JSON document. None means 'absent' (404).

    Any other failure propagates: an unreadable registry is NOT evidence that a
    version is absent, and the caller must fail closed rather than guess.
    """
    request = Request(url, headers={"User-Agent": "tautline-release-tail"})
    try:
        # Fixed https registry URLs only; never user-supplied.
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def release_tail_leaks(text: str) -> list[str]:
    return sorted({term for term in RELEASE_TAIL_LEAK_TERMS if term in text})


def release_tail_overlay(export_dir: Path, clone: Path) -> None:
    """Overlay the export tree onto the mirror clone, preserving the mirror's `.git/`.

    Clearing the clone first is what makes export-EXCLUDED paths become real
    deletions on the mirror instead of lingering forever. Skipping the export's own
    `.git/` is what keeps the mirror's history intact: the export carries a fresh
    root commit that shares no ancestor with the mirror, and letting it overwrite
    the mirror's history is precisely the force-push this design refuses to do.
    """
    for entry in clone.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in sorted(export_dir.iterdir()):
        if entry.name == ".git":
            continue
        target = clone / entry.name
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target, follow_symlinks=False)


def release_tail_tag_commit(out: str, tag: str) -> str:
    """The COMMIT a tag ref resolves to, peeling an annotated tag if it is one.

    `git tag -a` (what this command creates below) makes an ANNOTATED tag, whose
    ref points at a tag OBJECT, not at a commit. Comparing that object's sha to a
    commit sha never matches, so the "is this tag already where we want it?" check
    would refuse every tag the tail itself pushed -- breaking the documented resume
    path. Asking for the peeled ref (`refs/tags/<tag>^{}`) yields the commit; a
    lightweight tag has no peeled entry and already points at the commit.
    """
    refs = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            refs[parts[1].strip()] = parts[0].strip()
    peeled = refs.get(f"refs/tags/{tag}^{{}}", "")
    return peeled or refs.get(f"refs/tags/{tag}", "")
