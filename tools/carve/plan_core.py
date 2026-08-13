"""Generate the shared-core batch: the largest set that is provably safe to carve today.

Run it to regenerate `carve/batches/core.json` at any base:

    python tools/carve/plan_core.py src/tautline_methodology/cli.py carve/batches/core.json

The batch is a derived artifact, not a hand-written list. Everything it excludes, it
excludes for a reason the tool can check, so the same base always yields the same batch
and a reviewer can re-derive it instead of trusting it.
"""

from __future__ import annotations

import argparse
import json
import pathlib

try:
    from .analyze import build_graph
    from .apply import (
        binding_floor,
        importable_names,
        env_name_constants,
        environment_derived_state,
        global_writing_symbols,
        global_written_names,
        import_order_hazards,
        module_scope_refs,
        monkeypatched_symbols,
        mutable_default_symbols,
        mutable_module_state,
        multi_binding_symbols,
        relative_import_users,
        self_referential_users,
        self_reading_bindings,
        surviving_rebinders,
    )
except ImportError:  # pragma: no cover - direct-script path
    from analyze import build_graph  # type: ignore[no-redef,import-not-found]
    from apply import (  # type: ignore[no-redef,import-not-found]
        binding_floor,
        importable_names,
        env_name_constants,
        environment_derived_state,
        global_writing_symbols,
        global_written_names,
        import_order_hazards,
        module_scope_refs,
        monkeypatched_symbols,
        mutable_default_symbols,
        mutable_module_state,
        multi_binding_symbols,
        relative_import_users,
        self_referential_users,
        self_reading_bindings,
        surviving_rebinders,
    )


def plan(
    source: str,
    root: pathlib.Path | None = None,
    restrict: set[str] | None = None,
) -> dict:
    """The largest provably-safe batch; `restrict` limits candidates to a family.

    With `restrict=None` this derives the shared-core batch (W1). A W2 family lane
    passes the family's dependency closure instead: every gate and the fixed point
    run identically, so the result is the largest safe SUBSET of that family --
    members whose deps close inside the batch (or are importable) survive, and
    monolith-state reachers drop out instead of refusing the whole manifest.
    """
    symbols, graph = build_graph(source)
    lines = {s.name: s.n_lines for s in symbols}
    start = {s.name: s.start_line for s in symbols}
    floor = binding_floor(source)

    patched = monkeypatched_symbols(root) if root is not None else set()
    # Mirror resolve()'s preconditions, or one legal cli.py statement kills the whole
    # derived batch at apply time: a tuple- or attribute-target assignment gets the
    # placeholder name `<assign@LINE>` yet keeps kind "assign", and a duplicated
    # top-level name resolves as ambiguous -- both refuse the ENTIRE manifest.
    counts: dict[str, int] = {}
    for s in symbols:
        counts[s.name] = counts.get(s.name, 0) + 1
    relocatable = {
        s.name
        for s in symbols
        if s.kind in ("def", "class", "assign")
        and s.name.isidentifier()
        and counts[s.name] == 1
    }
    relocatable -= set(relative_import_users(source, symbols))
    relocatable -= set(self_referential_users(source, symbols))
    # A binding-time self-read (`VALUE = VALUE + 1`) resolves against the origin's
    # prior binding, which the destination does not have; symtable scopes the sliced
    # snippet so the dependency walk cannot see it.
    relocatable -= set(self_reading_bindings(source, symbols))
    relocatable -= env_name_constants(source)
    relocatable -= set(multi_binding_symbols(source, symbols))
    # NOTE: module-scope consumers are handled inside the fixed point below, not here.
    # Subtracting `module_scope_refs(source, set())` up front asked "who is consumed if
    # NOTHING moves", which permanently excluded producers that are safe once their
    # consuming statement moves too -- `ROOT = "/tmp"` with `CONFIG = {"root": ROOT}` is a
    # legal batch, but the up-front form dropped ROOT and the closure then dropped CONFIG.
    # Per-load mutable state must not become a cross-engine singleton.
    relocatable -= set(mutable_module_state(source))
    relocatable -= set(environment_derived_state(source))
    relocatable -= set(mutable_default_symbols(source))
    # A `global`-writing body forks module state between origin alias and destination;
    # batch-independent, so excluded up front like the other per-symbol properties.
    relocatable -= set(global_writing_symbols(source, symbols))
    # And the NAMES those writers rebind: the writer either moves (refused above) or
    # survives (the survivor would rebind the origin's alias while co-moved readers see
    # the destination's stale copy), so a globally-written name can never move either.
    relocatable -= global_written_names(source)
    relocatable -= patched
    if restrict is not None:
        relocatable &= restrict

    # Above the floor the guarded alias cannot be emitted at all -- it names
    # _MissingFrameworkPackage, which is not defined yet up there.
    below = {n for n in relocatable if start.get(n, 0) > floor}

    # Fixed point: keep only symbols whose every dependency is also kept. An importable
    # name is not a dependency; the destination imports it exactly as the origin does.
    # Same exclusion apply.py uses: a name the suite patches on `cli` is NOT freely
    # re-importable, so treating it as one here would emit a manifest apply then refuses.
    importable = set(importable_names(source)) - patched
    sym_by_name = {s.name: s for s in symbols if s.kind in ("def", "class", "assign")}
    keep = set(below)
    while True:
        # Three conditions, re-evaluated against the CURRENT candidate set each pass:
        #   1. every dependency is also moving,
        #   2. nothing left behind evaluates this name at import time, and
        #   3. the alias would not execute its import-time effects ahead of an effectful
        #      survivor it originally ran after.
        # The candidate set only shrinks, so the loop terminates; the hazard set is
        # re-derived from the current candidates each pass because dropping a symbol
        # changes both who survives and where the first moved symbol sits.
        keep_syms = [sym_by_name[n] for n in keep]
        consumed = module_scope_refs(source, keep)
        rebound = set(surviving_rebinders(source, keep_syms))
        hazards = set(import_order_hazards(source, keep_syms))
        drop = {
            n
            for n in keep
            if not ((graph.get(n, set()) - importable) <= keep)
            or n in consumed
            or n in rebound
            or n in hazards
        }
        if not drop:
            break
        keep -= drop

    ordered = sorted(keep, key=lambda n: start.get(n, 0))
    return {
        "floor": floor,
        "symbols": ordered,
        "loc": sum(lines.get(n, 0) for n in ordered),
        "alias_line": min((start[n] for n in ordered), default=0),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("origin")
    ap.add_argument("out")
    args = ap.parse_args(argv)

    out = pathlib.Path(args.out)
    # A fresh checkout has no carve/batches/, and failing here would waste the whole
    # planning pass on a FileNotFoundError the documented command should not produce.
    out.parent.mkdir(parents=True, exist_ok=True)
    source = open(args.origin, encoding="utf-8").read()
    result = plan(source, pathlib.Path(args.origin).resolve().parents[2])
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "dest": "core.runtime",
                "subject": "shared CLI runtime helpers",
                "symbols": result["symbols"],
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    print(
        f"binding floor line {result['floor']:,}; "
        f"{len(result['symbols']):,} symbols / {result['loc']:,} LOC; "
        f"alias at line {result['alias_line']:,} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
