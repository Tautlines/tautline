"""The refusal ladder must be wired, not just written.

test_carve_tooling.py proves the gate PREDICATES and the refusal exits 9-15. This file
closes the remaining gaps: exits 2 through 8 exercised through the real `carve_main`
entry point, the multi-binding detector's own contract, the analyzer's dependency graph
and its entangled-families warning, and the lint-suppression policy that keeps carved
destinations from inheriting the monolith's baggage. Each refusal fixture is built to
trip ONLY its intended gate, so a ladder reordering that changes an exit code fails here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from carve.analyze import analyze, build_graph  # noqa: E402
from carve.apply import (  # noqa: E402
    main as carve_main,
    multi_binding_symbols,
    resolve,
)
from carve.model import parse_module  # noqa: E402


def _refused(tmp_path, capsys, origin_src, symbols, dest="carved"):
    """Run carve_main against a checkout-shaped tree and return (rc, stderr).

    The origin sits at <root>/src/pkg/origin.py so that `origin.resolve().parents[2]` --
    the repo root apply.py scans for monkeypatched test seams -- lands on the fixture
    root rather than a pytest temp directory shared with unrelated files. The empty
    tests/ directory keeps the monkeypatch gate (exit 11) quiet, so every fixture below
    reaches the gate it aims at instead of being intercepted higher up the ladder.
    """
    root = tmp_path / "repo"
    pkg = root / "src" / "pkg"
    pkg.mkdir(parents=True)
    (root / "tests").mkdir()
    origin = pkg / "origin.py"
    origin.write_text(origin_src)
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"dest": dest, "symbols": symbols}))

    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    err = capsys.readouterr().err
    assert "REFUSED" in err, f"rc={rc} but no refusal reached stderr: {err!r}"
    dest_path = origin.parent.joinpath(*dest.split(".")).with_suffix(".py")
    assert not dest_path.exists(), "a refused batch must write nothing"
    return rc, err


@pytest.mark.parametrize(
    ("origin_src", "symbols", "reason"),
    [
        pytest.param(
            "def helper():\n    return 1\n",
            ["nope"],
            "absent",
            id="absent-symbol",
        ),
        pytest.param(
            "def helper():\n    return 1\n",
            ["helper", "helper"],
            "duplicated in the batch",
            id="duplicate-in-batch",
        ),
        pytest.param(
            "def helper():\n    return 1\n\n\ndef helper():\n    return 2\n",
            ["helper"],
            "ambiguous",
            id="ambiguous-duplicate-def",
        ),
    ],
)
def test_an_unresolvable_batch_exits_2(tmp_path, capsys, origin_src, symbols, reason):
    """Resolution failures are the first rung of the ladder: exit 2, reason on stderr.

    Absent: a stale manifest naming a symbol a prior wave already moved must refuse, not
    KeyError. Duplicated: the reverse splice would delete the same span twice, and the
    second deletion eats whatever followed it. Ambiguous: carving the wrong one of two
    same-named defs silently changes behaviour. All three funnel through one CarveError;
    this pins that the funnel is wired to exit 2 rather than escaping as a traceback.
    """
    rc, err = _refused(tmp_path, capsys, origin_src, symbols)
    assert rc == 2, f"expected the resolution refusal, got {rc}"
    assert reason in err, f"the refusal must name its reason: {err!r}"


def test_an_open_back_edge_exits_3(tmp_path, capsys):
    """A moved body still needing an origin-defined helper cannot be carved.

    The destination would need an import back-edge into the origin, which the byte-slice
    model never generates -- the moved body would NameError at first call. Fixture care:
    `helper` stays behind and is only called from inside `mover`'s BODY, so the surviving
    module-level code evaluates nothing moved and the consumer gate (exit 7) stays quiet;
    the dependency gate is the first to fire.
    """
    src = textwrap.dedent(
        '''
        def helper():
            return 1


        def mover():
            return helper()
        '''
    ).lstrip()
    rc, _ = _refused(tmp_path, capsys, src, ["mover"])
    assert rc == 3, f"expected the back-edge refusal, got {rc}"


def test_an_alias_above_the_binding_floor_exits_4(tmp_path, capsys):
    """The alias block names _MissingFrameworkPackage, so it must land BELOW that class.

    The alias is emitted at the first moved symbol's deletion site; a symbol defined
    above the fail-open guard would put the generated `except` handler ahead of the class
    it instantiates -- a NameError at import that takes every hook down. Fixture care:
    `moved_above` is a pure leaf (no deps, no consumers, no relative imports, nothing
    self-referential), so nothing on the ladder above the floor check can fire first.
    """
    src = textwrap.dedent(
        '''
        def moved_above():
            return "safe"


        class _MissingFrameworkPackage:
            def __init__(self, exc, subject):
                self._subject = subject
        '''
    ).lstrip()
    rc, _ = _refused(tmp_path, capsys, src, ["moved_above"])
    assert rc == 4, f"expected the binding-floor refusal, got {rc}"


def test_a_relative_import_bound_for_a_dotted_dest_exits_5(tmp_path, capsys):
    """Bodies move byte-identically, so `from . import x` moves too -- and `.` rebinds.

    In the origin `.` is the origin's package; inside a dotted dest like core.runtime it
    resolves against `core` and raises ImportError at call time. Rewriting the line would
    break the byte-identity guarantee, so the batch must be refused instead. Fixture
    care: the import is INSIDE the function body, so it is not an import symbol of the
    module, has no free names, and trips no gate above the relative-import check.
    """
    src = textwrap.dedent(
        '''
        def loads_sibling():
            from . import sibling as mod
            return mod
        '''
    ).lstrip()
    rc, _ = _refused(tmp_path, capsys, src, ["loads_sibling"], dest="core.runtime")
    assert rc == 5, f"expected the relative-import refusal, got {rc}"


def test_a_module_introspecting_body_exits_6(tmp_path, capsys):
    """A body reading __file__ changes behaviour when its module changes.

    Byte-identical relocation is not behaviour-preserving here: the same bytes in the
    destination read a DIFFERENT file, which is exactly how the real command enumerator
    silently emptied the public-contract manifest. Fixture care: `Path` is provided by a
    plain import (re-importable in the destination, so no back-edge), the import sits
    directly above the only symbol (no effectful survivor between them, so the ordering
    gate stays quiet), and nothing else consumes the moved name.
    """
    src = textwrap.dedent(
        '''
        from pathlib import Path


        def reads_own_file():
            return Path(__file__).read_text()
        '''
    ).lstrip()
    rc, _ = _refused(tmp_path, capsys, src, ["reads_own_file"])
    assert rc == 6, f"expected the self-reference refusal, got {rc}"


def test_a_surviving_import_time_consumer_exits_7(tmp_path, capsys):
    """`TOTAL = helper()` stays behind while `helper` moves: refused, not aliased.

    On the success path the deletion-site alias would cover the read, but on the
    fail-open path the alias binds a guided stub instead of the function, and the
    surviving assignment CALLS it while the module is still importing -- wedging every
    hook, which is the exact failure the fail-open contract exists to prevent. Fixture
    care: TOTAL itself is not in the batch, so the per-load gate (exit 10) never sees
    the environment-derived assignment; only the moved name's consumption is at issue.
    """
    src = textwrap.dedent(
        '''
        def helper():
            return 3


        TOTAL = helper()
        '''
    ).lstrip()
    rc, _ = _refused(tmp_path, capsys, src, ["helper"])
    assert rc == 7, f"expected the module-scope-consumer refusal, got {rc}"


def test_a_statement_binding_two_names_exits_8(tmp_path, capsys):
    """`ALPHA = BETA = (...)` moves as one span but the alias re-exports one name.

    BETA would vanish from the origin with nothing re-exporting it, and the dependency
    analysis cannot see that: it inspects the moved bodies, not what survivors still
    read. Fixture care: the value is an immutable tuple of constants, so neither the
    mutable-state nor the environment-derived arm of the per-load gate (exit 10) fires
    ahead of the multi-binding check.
    """
    src = 'ALPHA = BETA = ("x",)\n'
    rc, _ = _refused(tmp_path, capsys, src, ["ALPHA"])
    assert rc == 8, f"expected the multi-binding refusal, got {rc}"


def test_multi_binding_symbols_sees_every_second_binding():
    """The detector must catch bindings the target scan cannot see, and only those.

    A chained assignment is one statement with two bindings, so moving ALPHA strands
    BETA. A walrus in the VALUE (`X = (y := 1)`) leaks `y` at module scope even though
    it is no assignment target. A single-target assignment binds exactly its own name
    and must stay carvable, or every module constant would be pinned in place.
    """
    chained = 'ALPHA = BETA = ("x",)\n'
    moving = resolve(parse_module(chained), ["ALPHA"])
    assert multi_binding_symbols(chained, moving) == ["ALPHA"]

    walrus = "X = (y := 1)\n"
    moving = resolve(parse_module(walrus), ["X"])
    assert multi_binding_symbols(walrus, moving) == ["X"]

    single = "SOLO = (1,)\n"
    moving = resolve(parse_module(single), ["SOLO"])
    assert multi_binding_symbols(single, moving) == []


ANALYZE_SAMPLE = textwrap.dedent(
    '''
    SHARED = "shared"


    def helper():
        return SHARED


    def alpha():
        return helper()


    def beta():
        return alpha() + helper()
    '''
).lstrip()


def test_build_graph_reports_the_edges_the_bodies_actually_have():
    """The wave order derives from this graph, so a missing edge is a wrong plan.

    Every reference class matters: def -> def (`alpha` calls `helper`), def -> constant
    (`helper` closes over SHARED -- assignments are NOT dependency-free leaves), fan-in
    (`beta` reaches both), and a constant with no references at all. An edge that
    silently drops out here surfaces later as a batch that "looked closed" but carried
    a back-edge into the origin.
    """
    _, graph = build_graph(ANALYZE_SAMPLE)
    assert graph["alpha"] == {"helper"}
    assert graph["helper"] == {"SHARED"}
    assert graph["beta"] == {"alpha", "helper"}
    assert graph["SHARED"] == set()


def _entangled_families_source() -> str:
    """Two 5-member families whose closures share one large worker.

    The sizing is load-bearing. `entangled` requires the SHARED closure to exceed 100
    LOC, while CARVABLE_DRAG (2.0) requires each family's OWN lines to outweigh the
    drag: the worker is 112 lines and each family owns 5 x 25 = 125, so drag is
    (125 + 112) / 125 ~= 1.9 -- both families carvable, and entangled. The worker's 10
    dependents stay under HUB_THRESHOLD (20), so it joins neither the core nor a family
    of its own (one member is below the 5-member floor).
    """
    filler = "\n".join(f"    v{i} = {i}" for i in range(110))
    parts = [f"def shared_worker():\n{filler}\n    return v0\n"]
    pad = "\n".join(f"    w{i} = {i}" for i in range(23))
    for family in ("alpha", "beta"):
        for n in range(5):
            parts.append(f"def {family}_{n}():\n{pad}\n    return shared_worker() + w0\n")
    return "\n\n".join(parts)


def test_the_entangled_families_warning_fires_and_names_the_contest(tmp_path):
    """The lane-merge advice must measure the RAW closure overlap.

    The warning used to subtract `contested` from the overlap before sizing it -- but
    every shared symbol is claimed by at least two families, so it is ALWAYS contested
    and the difference is always empty: the advice had never fired, however entangled
    two families were (analyze.py documents the fix at the `entangled` computation).
    This is the regression net: reintroduce the subtraction and `entangled` empties,
    the CLI output loses the warning, and both halves of this test fail.
    """
    src = _entangled_families_source()

    r = analyze(src)
    assert "shared_worker" in r["contested"], "both families must contest the shared worker"
    pairs = [(a, b) for a, b, _, _ in r["entangled"]]
    assert ("alpha", "beta") in pairs, f"entangled families not reported: {r['entangled']}"

    origin = tmp_path / "entangled.py"
    origin.write_text(src)
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "carve" / "analyze.py"), str(origin)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "merge these into single lanes" in proc.stdout, proc.stdout
    assert "alpha + beta" in proc.stdout, proc.stdout


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_carved_destinations_never_inherit_the_monolith_suppressions():
    """The per-file-ignores baseline is a ratchet on cli.py, not a dowry for its pieces.

    (a) No ignore key may reach inside src/tautline_methodology/core/: a carved
    destination starts clean, and granting it the monolith's suppressions would let the
    exact violations the carve strands in cli.py ride along invisibly. (b) The cli.py
    entry may only ever SHRINK from the day-one baseline {F541, F841, B904}: a new code
    appearing there grandfathers a new class of violation, which is the ratchet moving
    backwards.
    """
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    per_file = config.get("tool", {}).get("ruff", {}).get("lint", {}).get("per-file-ignores", {})

    core_keys = [key for key in per_file if "src/tautline_methodology/core" in key]
    assert not core_keys, (
        f"per-file-ignores must never cover carved destination files, found: {core_keys}"
    )

    baseline = {"F541", "F841", "B904"}
    cli_codes = set(per_file.get("src/tautline_methodology/cli.py", ()))
    assert cli_codes <= baseline, (
        "codes may only be DELETED from the cli.py baseline, never added: "
        f"{sorted(cli_codes - baseline)}"
    )
