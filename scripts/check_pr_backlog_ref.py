#!/usr/bin/env python3
"""Deterministic PR<->backlog reference check. Stdlib only, no network, exits in milliseconds.

Runs as a named step in `.github/workflows/validate.yml` on every `pull_request` event. Single
field, single condition -- this never calls a network API (not even to confirm an id is real,
which would need a live board), never reads `gh`, and never inspects anything but this repo's own
lean config and the PR's own title and body.

* When this repo's lean config (`.tautline.json` or `.minervit-ai-delivery.json`) names NO
  `backlog` key at all, there is nothing to check: exit 0, having done nothing.
* When one is configured, the PR title or body must carry a reference in that PROVIDER's grammar
  (`tautline_methodology.backlog.REFERENCE_GRAMMAR`) -- the generic `Backlog: <id>` form works for
  every provider; each provider also accepts its own native form (a GitHub closing keyword, a bare
  Jira key). `tautline backlog take` prints a ready-to-paste line with the real id filled in.

See docs/reference/backlog.md ("PR reference stamp") for the why.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tautline_methodology import backlog, lean  # noqa: E402


def _skip(reason: str) -> int:
    print(f"check_pr_backlog_ref: skipped ({reason})")
    return 0


def _configured_provider(root: Path) -> str | None:
    """The `backlog.provider` this project names, or None when its config carries no `backlog`
    key at all.

    Deliberately NOT `backlog.backlog_config`'s "absent means local-with-defaults" reading: that
    default is what makes `tautline backlog` useful out of the box with nothing configured, but
    gating every PR on a reference stamp is an opt-in policy decision a project makes by writing
    the key down, not one it should trip into by never having named a provider.
    """
    adapter = lean.find_lean_adapter(root)
    cfg = lean.load_lean_config(adapter) if adapter is not None else None
    if not isinstance(cfg, dict) or "backlog" not in cfg:
        return None
    block = cfg.get("backlog")
    provider = block.get("provider") if isinstance(block, dict) else None
    return str(provider).strip() if provider else "local"


def _pr_title_and_body() -> tuple[str, str]:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise SystemExit(
            "check_pr_backlog_ref: GITHUB_EVENT_PATH is not set; this must run inside a GitHub "
            "Actions pull_request job."
        )
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"check_pr_backlog_ref: could not read or parse the event payload at "
            f"{event_path!r}: {type(exc).__name__}: {exc}. GITHUB_EVENT_PATH must name the JSON "
            "file GitHub Actions itself writes for this run."
        ) from None
    pr = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pr, dict):
        raise SystemExit(
            "check_pr_backlog_ref: the event payload has no pull_request object; this must run "
            "on a pull_request event."
        )
    return str(pr.get("title") or ""), str(pr.get("body") or "")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Project root to read the lean config from (default: this repo).",
    )
    args = parser.parse_args(argv)

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name != "pull_request":
        return _skip(f"not a pull_request event (GITHUB_EVENT_NAME={event_name!r})")

    provider = _configured_provider(args.root)
    if provider is None:
        return _skip("no backlog configured")

    grammar = backlog.REFERENCE_GRAMMAR.get(provider)
    if grammar is None:
        # An unrecognised `backlog.provider` is a config-validation problem for
        # `validate-adapter`, not this check's to diagnose twice -- fail open rather than block
        # every PR on a typo this check did not cause and cannot name usefully.
        return _skip(f"unknown backlog provider {provider!r}; nothing to check")

    title, body = _pr_title_and_body()
    haystack = f"{title}\n{body}"
    if any(pattern.search(haystack) for pattern in grammar.patterns):
        print(f"check_pr_backlog_ref: OK (backlog provider: {provider})")
        return 0

    print(
        "check_pr_backlog_ref: FAILED -- no backlog reference found in the PR title or body.\n"
        f"This repo's backlog provider is {provider!r}. Add ONE of these to the PR TITLE or "
        "BODY:\n"
        f"  {grammar.describe}\n"
        "The generic form always works -- add a line reading exactly:\n"
        "  Backlog: <id>\n"
        "`tautline backlog take` prints a ready-to-paste line with the real id filled in.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
