"""Derive the split plan from the monolith's reference graph.

The wave order is not a judgement call. A family is carvable when its dependency
closure is closed; the waves fall out of measuring that. Re-run this at any base to
regenerate the plan -- it is the plan's source, and it is why the plan does not need
to be re-argued in prose every time `cli.py` grows.

    python tools/carve/analyze.py src/tautline_methodology/cli.py
"""

from __future__ import annotations

import argparse
import collections
import itertools

try:
    from .apply import free_names, module_bound_names
    from .model import parse_module
except ImportError:  # pragma: no cover - direct-script path
    from apply import free_names, module_bound_names  # type: ignore[no-redef,import-not-found]
    from model import parse_module  # type: ignore[no-redef,import-not-found]

HUB_THRESHOLD = 20  # dependents above which a symbol belongs to the shared core
CARVABLE_DRAG = 2.0  # closure LOC / own LOC below which a family is independent


def build_graph(source: str):
    """symbol -> the origin-module names its body references."""
    symbols = parse_module(source)
    lines = source.split("\n")
    origin = module_bound_names(source) | {
        s.name for s in symbols if s.kind in ("def", "class", "assign")
    }
    graph: dict[str, set[str]] = {}
    for sym in symbols:
        if sym.kind in ("def", "class", "assign"):
            # Assignments are NOT dependency-free: `FOO = bar()` needs bar, and treating
            # constants as leaves silently under-reports the closure, which is how a batch
            # that looked closed still carried back-edges into the origin module.
            graph[sym.name] = (free_names(source, sym, lines) & origin) - {sym.name}
        else:
            graph.setdefault(sym.name, set())
    return symbols, graph


def closure(graph: dict[str, set[str]], seeds: set[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        # frozenset, not (): edges may name a module-scope binding that owns no top-level
        # symbol (an import, or a handle bound inside a try/except guard), so the default
        # has to support set difference rather than blowing up on the first such name.
        stack.extend(graph.get(name, frozenset()) - seen)
    return seen


def dependents(graph: dict[str, set[str]]) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for dsts in graph.values():
        for dst in dsts:
            counts[dst] += 1
    return counts


def families(symbols) -> dict[str, set[str]]:
    """Group verbs by their leading token -- the CLI's own naming convention."""
    groups = collections.defaultdict(set)
    for sym in symbols:
        if sym.kind == "def" and not sym.name.startswith("_"):
            groups[sym.name.split("_")[0]].add(sym.name)
    return {k: v for k, v in groups.items() if len(v) >= 5}


def analyze(source: str) -> dict:
    symbols, graph = build_graph(source)
    lines = {s.name: s.n_lines for s in symbols}
    loc = lambda names: sum(lines.get(n, 0) for n in names)  # noqa: E731

    hubs = {n for n, c in dependents(graph).items() if c >= HUB_THRESHOLD}
    core = closure(graph, hubs)
    pruned = {k: (v - core) for k, v in graph.items()}

    groups = families(symbols)
    clos = {f: closure(pruned, seeds - core) for f, seeds in groups.items()}

    carvable = {
        f: seeds
        for f, seeds in groups.items()
        if (seeds - core) and loc(clos[f]) / max(loc(seeds - core), 1) < CARVABLE_DRAG
    }

    # A symbol two families both reach belongs in core, or their lanes collide.
    claims: collections.Counter = collections.Counter()
    for f in carvable:
        for n in clos[f]:
            claims[n] += 1
    contested = {n for n, c in claims.items() if c > 1}

    # Measure the RAW overlap. Subtracting `contested` here made the warning unreachable:
    # every shared symbol is counted by at least two families in the claims loop above, so it
    # is always in `contested` and the difference is always empty. The lane-merge advice this
    # is supposed to emit has therefore never fired, however entangled two families were.
    entangled = [
        (a, b, len(clos[a] & clos[b]), loc(clos[a] & clos[b]))
        for a, b in itertools.combinations(sorted(carvable), 2)
        if loc(clos[a] & clos[b]) > 100
    ]

    return {
        "symbols": symbols,
        "lines": lines,
        "core": core,
        "core_loc": loc(core),
        "contested": contested,
        "contested_loc": loc(contested),
        "carvable": {f: loc(groups[f] - core) for f in carvable},
        "closures": {f: loc(clos[f]) for f in carvable},
        "entangled": entangled,
        "total": len(source.splitlines()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("origin")
    args = ap.parse_args(argv)
    r = analyze(open(args.origin, encoding="utf-8").read())

    print(f"monolith: {r['total']:,} lines")
    print(
        f"core batch: {len(r['core']):,} symbols / {r['core_loc']:,} LOC"
        f"  (+{len(r['contested']):,} contested / {r['contested_loc']:,} LOC)"
    )
    print(f"\n{'family':<20}{'own LOC':>10}{'closure':>10}{'drag':>8}")
    unlocked = 0
    for f, own in sorted(r["carvable"].items(), key=lambda kv: -kv[1]):
        unlocked += own
        print(f"{f:<20}{own:>10,}{r['closures'][f]:>10,}{r['closures'][f]/max(own,1):>7.1f}x")
    print(f"\nparallel-carvable after core: {unlocked:,} LOC ({unlocked/r['total']:.0%})")
    if r["entangled"]:
        print("\nmerge these into single lanes (shared closure > 100 LOC):")
        for a, b, n_syms, n_loc in r["entangled"]:
            print(f"  {a} + {b}: {n_syms} symbols / {n_loc:,} LOC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
