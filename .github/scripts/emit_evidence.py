#!/usr/bin/env python3
"""Compose a tautline-evidence/v1 document from GitHub Actions step outcomes.

CommandCenter reads the run artifact named `evidence`; this writes the evidence.json inside it.
Usage:
  emit_evidence.py --out evidence/evidence.json \
      --suite validate:eval \
      --result validate.methodology-suite=success \
      --result validate.compile-cli=failure
Every --result id must begin with the name of a declared --suite ("<suite>.<result>"); an id
whose prefix matches no suite is an error, never a silent reassignment. GitHub step outcomes
map: success -> pass, failure -> fail, skipped/cancelled -> skip. Any other value is an error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = "tautline-evidence/v1"
SUITE_KINDS = ("test", "eval", "smoke", "probe")
OUTCOME_STATUS = {
    "success": "pass",
    "failure": "fail",
    "skipped": "skip",
    "cancelled": "skip",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--suite", action="append", default=[], metavar="NAME:KIND")
    parser.add_argument("--result", action="append", default=[], metavar="ID=OUTCOME")
    return parser.parse_args(argv)


def build_document(suite_specs: list[str], result_specs: list[str]) -> dict:
    if not suite_specs:
        raise SystemExit("emit_evidence: at least one --suite is required")
    suites: list[dict] = []
    by_name: dict[str, dict] = {}
    for spec in suite_specs:
        name, _, kind = spec.partition(":")
        if not name or kind not in SUITE_KINDS:
            raise SystemExit(f"emit_evidence: bad --suite {spec!r} (want NAME:{'|'.join(SUITE_KINDS)})")
        suite = {"name": name, "kind": kind, "results": []}
        suites.append(suite)
        by_name[name] = suite
    for spec in result_specs:
        result_id, sep, outcome = spec.partition("=")
        if not result_id or not sep:
            raise SystemExit(f"emit_evidence: bad --result {spec!r} (want ID=OUTCOME)")
        status = OUTCOME_STATUS.get(outcome.strip().lower())
        if status is None:
            raise SystemExit(f"emit_evidence: unknown step outcome {outcome!r} for {result_id!r}")
        # Route by the LONGEST declared suite whose "<name>." prefixes the id, requiring a
        # nonempty result suffix. Splitting at the first dot would misroute a dotted suite
        # name ("api.contract") and would accept a bare id equal to a suite name; matching the
        # full "<name>." prefix handles both. A typo matches nothing and fails the job.
        target_name = None
        for name in by_name:
            if result_id.startswith(name + ".") and len(result_id) > len(name) + 1:
                if target_name is None or len(name) > len(target_name):
                    target_name = name
        if target_name is None:
            raise SystemExit(
                f"emit_evidence: result {result_id!r} has no matching --suite prefix "
                f"(declared suites: {', '.join(by_name) or 'none'})"
            )
        by_name[target_name]["results"].append({"id": result_id, "status": status})
    return {"schema": SCHEMA, "suites": suites}


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    document = build_document(args.suite, args.result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({sum(len(s['results']) for s in document['suites'])} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
