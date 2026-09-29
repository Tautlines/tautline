"""The carve tooling must be provable, not described.

The monolith split is only safe if relocation is byte-identical and the resulting
package still imports and behaves the same. These tests are that proof; the split
plan derives from `analyze`, so its numbers are reproducible rather than asserted.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from carve.apply import (  # noqa: E402
    ALIAS_MARKER,
    CarveError,
    carve,
    dependencies,
    free_names,
    environment_derived_state,
    main as carve_main,
    module_scope_refs,
    mutable_module_state,
    prune_unused_imports,
    relative_import_users,
    resolve,
    self_referential_users,
)
from carve.model import parse_module  # noqa: E402

CLI = Path(__file__).resolve().parents[1] / "src" / "tautline_methodology" / "cli.py"

SAMPLE = textwrap.dedent(
    '''
    """Module docstring."""
    import os

    SHARED = "shared"

    def helper():
        return SHARED


    # A comment attached to alpha.
    def alpha():
        version = "local"
        return version + helper()


    def beta():
        return os.sep
    '''
).lstrip()


def test_spans_are_exact_and_reconstruct_the_source():
    """Concatenating spans and gap bytes must rebuild the file byte-for-byte.

    The old name-in-chunk form could not fail: a span one byte short survived the
    whole suite, and parse_module returning [] would have passed vacuously. Every
    span must also end on a line boundary -- a mid-line end is exactly the
    off-by-one that silently corrupts the reverse splice.
    """
    symbols = parse_module(SAMPLE)
    assert symbols, "parse_module must find the sample's symbols"
    data = SAMPLE.encode("utf-8")
    lines = SAMPLE.split("\n")
    ordered = sorted(symbols, key=lambda s: s.start_byte)
    rebuilt = bytearray()
    cursor = 0
    for sym in ordered:
        # Overlap would delete bytes twice on the reverse splice.
        assert cursor <= sym.start_byte, f"{sym.name} overlaps its predecessor"
        rebuilt += data[cursor : sym.start_byte]  # unowned gap bytes
        chunk = data[sym.start_byte : sym.end_byte]
        assert lines[sym.def_line - 1].encode("utf-8") in chunk, (
            f"{sym.name}'s span must contain its own defining line"
        )
        assert chunk.endswith(b"\n") or sym.end_byte == len(data), (
            f"{sym.name}'s span must end on a line boundary"
        )
        rebuilt += chunk
        cursor = sym.end_byte
    rebuilt += data[cursor:]
    assert bytes(rebuilt) == data, "spans plus gaps must reconstruct the source exactly"


def test_attached_comment_travels_with_its_symbol():
    alpha = next(s for s in parse_module(SAMPLE) if s.name == "alpha")
    assert SAMPLE.splitlines()[alpha.start_line - 1].strip().startswith("#")


def test_free_names_uses_scope_not_string_matching():
    """`version` is a local here; treating it as a dependency would block the batch."""
    symbols = parse_module(SAMPLE)
    alpha = next(s for s in symbols if s.name == "alpha")
    names = free_names(SAMPLE, alpha)
    assert "helper" in names
    assert "version" not in names


def test_resolve_refuses_absent_and_ambiguous_symbols():
    symbols = parse_module(SAMPLE)
    with pytest.raises(CarveError, match="absent"):
        resolve(symbols, ["nope"])
    dupe = SAMPLE + "\n\ndef alpha():\n    return 2\n"
    with pytest.raises(CarveError, match="ambiguous"):
        resolve(parse_module(dupe), ["alpha"])


def test_dependencies_reports_the_back_edge():
    symbols = parse_module(SAMPLE)
    moving = resolve(symbols, ["alpha"])
    assert dependencies(SAMPLE, moving, symbols) == ["helper"]
    # Dependencies are transitive: helper() closes over the module constant SHARED,
    # so pulling helper in exposes the next back-edge rather than hiding it.
    partial = resolve(symbols, ["alpha", "helper"])
    assert dependencies(SAMPLE, partial, symbols) == ["SHARED"]
    # Moving the whole closure along is what actually closes the batch.
    whole = resolve(symbols, ["alpha", "helper", "SHARED"])
    assert dependencies(SAMPLE, whole, symbols) == []


def test_carved_bodies_are_byte_identical():
    symbols = parse_module(SAMPLE)
    moving = resolve(symbols, ["alpha", "helper"])
    original = {s.name: SAMPLE.encode()[s.start_byte : s.end_byte] for s in moving}
    _, dest = carve(SAMPLE, moving, "carved", "sample")
    for name, body in original.items():
        assert body.decode().strip() in dest, f"{name} was not relocated verbatim"


def test_carve_round_trips_through_a_real_import(tmp_path):
    """The end-to-end proof: carve, import the result, behaviour is unchanged."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "sample.py").write_text(SAMPLE)

    symbols = parse_module(SAMPLE)
    moving = resolve(symbols, ["alpha", "helper", "SHARED"])
    assert dependencies(SAMPLE, moving, symbols) == []
    new_origin, dest = carve(SAMPLE, moving, "carved", "sample")
    (pkg / "carved.py").write_text(dest)
    (pkg / "sample.py").write_text(new_origin)

    script = "import pkg.sample as s; print(s.alpha()); print(s.beta())"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    # The `cli.<attr>` surface survives the move via the re-export alias.
    assert proc.stdout.split() == ["localshared", "/"]


MODULE_SCOPE_SAMPLE = textwrap.dedent(
    '''
    ROOT = "/tmp"


    def helper():
        return 1


    CONFIG = {"root": ROOT}


    def uses_helper():
        return helper()
    '''
).lstrip()


def test_symbol_used_at_module_scope_is_refused():
    """`ROOT` is read by a top-level assignment, so it cannot be carved.

    On the SUCCESS path the deletion-site alias would cover this. On the fail-open path it
    binds a guided stub instead of the value, and the consuming statement raises while the
    module is still importing -- so the tool refuses rather than relying on the happy path.
    `helper` is only ever called from inside a function body, so it is safe.
    """
    symbols = parse_module(MODULE_SCOPE_SAMPLE)

    unsafe = {s.name for s in resolve(symbols, ["ROOT"])}
    assert "ROOT" in unsafe & module_scope_refs(MODULE_SCOPE_SAMPLE, unsafe)

    safe = {s.name for s in resolve(symbols, ["helper"])}
    assert not (safe & module_scope_refs(MODULE_SCOPE_SAMPLE, safe))


def test_moving_the_referencing_statement_too_makes_it_safe():
    """CONFIG is what reads ROOT; carrying both removes the import-time reference."""
    both = {"ROOT", "CONFIG"}
    assert not (both & module_scope_refs(MODULE_SCOPE_SAMPLE, both))


@pytest.mark.skipif(not CLI.exists(), reason="monolith not present")
def test_the_binding_floor_is_refused_by_the_tool():
    """_MissingFrameworkPackage is the campaign's known import-order landmine."""
    source = CLI.read_text(encoding="utf-8")
    refs = module_scope_refs(source, {"_MissingFrameworkPackage", "REPO_ROOT"})
    assert "_MissingFrameworkPackage" in refs
    assert "REPO_ROOT" in refs


GUARDED_SAMPLE = textwrap.dedent(
    '''
    """Origin with the fail-open guard."""


    class _MissingFrameworkPackage:
        def __init__(self, exc, subject):
            self._subject = subject

        def __getattr__(self, name):
            raise SystemExit(self._subject)


    def carved_one():
        return "one"


    def carved_two():
        return carved_one() + "two"
    '''
).lstrip()


def test_dotted_dest_generates_importable_alias(tmp_path):
    """`from pkg import a.b` is a SyntaxError, so a dotted dest must split package/leaf.

    This is the guarded, in-place alias form the real monolith uses -- the round trip
    proves the generated block both parses AND resolves through a real import.
    """
    symbols = parse_module(GUARDED_SAMPLE)
    moving = resolve(symbols, ["carved_one", "carved_two"])
    assert dependencies(GUARDED_SAMPLE, moving, symbols) == []

    new_origin, dest = carve(GUARDED_SAMPLE, moving, "core.runtime", "origin", "helpers")

    pkg = tmp_path / "tautline_methodology"
    (pkg / "core").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "core" / "runtime.py").write_text(dest)
    (pkg / "origin.py").write_text(new_origin)

    proc = subprocess.run(
        [sys.executable, "-c", "import tautline_methodology.origin as o; print(o.carved_two())"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "onetwo"


def test_alias_lands_at_the_deletion_site_not_eof():
    """Placement is what makes module-scope readers safe; assert it rather than trust it.

    Moving only `carved_one` leaves `carved_two` as a survivor BELOW the deletion
    site, so an alias appended at EOF -- the mutation this test previously could not
    see -- now lands on the wrong side of it and fails.
    """
    symbols = parse_module(GUARDED_SAMPLE)
    moving = resolve(symbols, ["carved_one"])
    new_origin, _ = carve(GUARDED_SAMPLE, moving, "core.runtime", "origin", "helpers")

    lines = new_origin.splitlines()
    alias_at = next(i for i, line in enumerate(lines) if ALIAS_MARKER in line)
    floor_at = next(i for i, line in enumerate(lines) if "class _MissingFrameworkPackage" in line)
    survivor_at = next(i for i, line in enumerate(lines) if line.startswith("def carved_two"))
    assert floor_at < alias_at, "the alias must sit below the fail-open guard it references"
    assert alias_at < survivor_at, (
        "the alias must land at the deletion site, above the surviving def that "
        "followed it -- an EOF alias binds too late for module-scope readers"
    )


def test_a_generated_syntax_error_is_refused_before_anything_is_written():
    # A hyphenated dest yields an invalid handle identifier; the subject vector this test
    # previously used is now closed by json.dumps escaping (see the escaping test below).
    symbols = parse_module(GUARDED_SAMPLE)
    moving = resolve(symbols, ["carved_one"])
    with pytest.raises(CarveError, match="does not parse"):
        carve(GUARDED_SAMPLE, moving, "core.run-time", "origin", "helpers")


SELF_REF_SAMPLE = textwrap.dedent(
    '''
    from pathlib import Path


    def scans_its_own_file():
        return Path(__file__).read_text()


    def reads_globals():
        return sorted(globals())


    def honest_leaf():
        return 42
    '''
).lstrip()


def test_module_introspecting_symbols_are_refused():
    """Byte-identical relocation is NOT behaviour-preserving for these.

    `registered_subcommand_names()` in the real monolith reads `Path(__file__)` and regexes
    for `.add_parser(...)`. Carved into core/runtime.py the same bytes read a file with no
    parsers and returned an empty list, which silently emptied the public-contract
    manifest's entire command list. Nothing in a byte diff can show that, so it is refused
    by name.
    """
    symbols = parse_module(SELF_REF_SAMPLE)
    moving = resolve(symbols, ["scans_its_own_file", "reads_globals", "honest_leaf"])
    assert self_referential_users(SELF_REF_SAMPLE, moving) == [
        "reads_globals",
        "scans_its_own_file",
    ]

    safe = resolve(symbols, ["honest_leaf"])
    assert self_referential_users(SELF_REF_SAMPLE, safe) == []


@pytest.mark.skipif(not CLI.exists(), reason="monolith not present")
def test_the_real_command_enumerator_is_refused():
    """The specific symbol that proved this class of defect."""
    source = CLI.read_text(encoding="utf-8")
    symbols = parse_module(source)
    target = [s for s in symbols if s.name == "registered_subcommand_names"]
    if not target:  # already carved into core/runtime.py in a prior wave
        pytest.skip("registered_subcommand_names no longer lives in cli.py")
    assert self_referential_users(source, target) == ["registered_subcommand_names"]


RELATIVE_SAMPLE = textwrap.dedent(
    '''
    def loads_sibling():
        from . import helper as mod
        return mod
    '''
).lstrip()


def test_relative_imports_in_moved_bodies_are_refused():
    """`.` means the DESTINATION package once the body moves."""
    symbols = parse_module(RELATIVE_SAMPLE)
    moving = resolve(symbols, ["loads_sibling"])
    assert relative_import_users(RELATIVE_SAMPLE, moving) == ["loads_sibling"]


PRUNE_SAMPLE = textwrap.dedent(
    '''
    import json
    import signal
    from pathlib import Path


    def uses_json(p: Path):
        return json.dumps(str(p))


    def brings_its_own():
        import signal
        return signal.SIGTERM
    '''
).lstrip()


def test_pruning_is_scope_aware_and_respects_protection():
    """A function with its own `import signal` is not a user of the module-level one."""
    pruned, removed = prune_unused_imports(PRUNE_SAMPLE)
    assert removed == ["signal"]
    assert "import json" in pruned
    assert "from pathlib import Path" in pruned, "annotation-only use must keep the import"

    # The re-export alias publishes names nothing local uses; pruning it would delete the
    # very line a carve just added.
    protected, removed = prune_unused_imports(PRUNE_SAMPLE, protect=frozenset({"signal"}))
    assert removed == []
    assert "import signal" in protected


def test_closure_tolerates_edges_to_names_that_own_no_symbol():
    """An edge may point at a module-scope binding with no top-level symbol of its own.

    Imports, and handles bound inside a try/except guard, are real module-scope names but
    they are not graph keys. `closure` must treat a missing key as "no further edges"
    rather than blowing up -- it did blow up, on the first such name, as soon as the
    dependency graph learned about non-symbol bindings.
    """
    from carve.analyze import closure

    graph = {"a": {"b", "json"}, "b": set()}  # `json` is an import, not a graph key
    assert closure(graph, {"a"}) == {"a", "b", "json"}


@pytest.mark.skipif(not CLI.exists(), reason="monolith not present")
def test_the_package_still_fails_open_when_the_carved_module_is_missing(tmp_path):
    """The arch-errors-1 contract, exercised against the REAL carved package.

    Adversarial review found this broken and no test could see it. The existing round-trip
    tests always write a real destination module, so the guarded import always succeeds and
    the fallback branch never runs. Two defects hid behind that:

    * the alias binds `_MissingFrameworkPackage.__getattr__`'s stub -- a *function* -- so a
      module-scope CONSUMER of a moved name (`frozenset((*MOVED, ...))`) raised TypeError at
      import, wedging every hook. That is what `module_scope_refs` now refuses.
    * a missing SUBMODULE of a package that IS importable raises ImportError, not
      ModuleNotFoundError, so the generated `except` never even fired.

    So this deletes the carved module from a copy of the real package and asserts the two
    things the contract actually promises: the import survives, and touching a moved symbol
    fails with a guided message rather than an opaque crash.
    """
    pkg_src = CLI.parent
    if not (pkg_src / "core" / "runtime.py").exists():
        pytest.skip("core/runtime.py not present; nothing carved in this tree")

    staged = tmp_path / "tautline_methodology"
    shutil.copytree(pkg_src, staged, ignore=shutil.ignore_patterns("__pycache__"))
    (staged / "core" / "runtime.py").unlink()

    probe = (
        "import tautline_methodology.cli as c\n"
        "print('IMPORT_OK')\n"
        "try:\n"
        "    c.utc_event_timestamp()\n"
        "except SystemExit as exc:\n"
        "    print('GUIDED' if 'framework checkout' in str(exc) else 'UNGUIDED')\n"
        "    print('CAUSE=' + type(exc.__cause__).__name__)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe], cwd=tmp_path, capture_output=True, text=True
    )
    assert "IMPORT_OK" in proc.stdout, (
        "importing the package without its carved module must not raise -- "
        f"stdout={proc.stdout!r} stderr={proc.stderr[-2000:]!r}"
    )
    assert "GUIDED" in proc.stdout, proc.stdout + proc.stderr[-2000:]

    # The contract is not "import survives" -- it is that a HOOK still exits 0, and
    # dispatch_command decides that by checking `isinstance(exc.__cause__, ModuleNotFoundError)`
    # (cli.py). A missing SUBMODULE of an importable package raises PLAIN ImportError, so
    # widening the generated `except` to ImportError without normalising the cause makes every
    # hook that touches a moved symbol block the lane instead of failing open. Asserting only
    # the two lines above missed exactly that, and the round after introduced it.
    assert "CAUSE=ModuleNotFoundError" in proc.stdout, (
        "the guided SystemExit's __cause__ must be a ModuleNotFoundError or dispatch_command "
        f"will not fail hooks open -- got {proc.stdout!r}"
    )


def test_future_annotations_follow_the_origin_even_with_no_other_imports():
    """The future flag is a property of the ORIGIN, not of whether imports are needed.

    An import-free batch that dropped `from __future__ import annotations` would leave
    forward annotations to be evaluated eagerly, and the resulting NameError happens when
    the destination is imported -- after ast.parse has already pronounced it valid.
    """
    src = textwrap.dedent(
        '''
        from __future__ import annotations


        def later(value: Unresolved) -> Unresolved:
            return value


        class Unresolved:
            pass
        '''
    ).lstrip()
    symbols = parse_module(src)
    moving = resolve(symbols, ["later"])
    _, dest = carve(src, moving, "carved", "origin")
    assert "from __future__ import annotations" in dest


def test_destination_collision_is_refused(tmp_path):
    """A second batch must not erase the module an earlier batch produced.

    The first batch's aliases in cli.py still point at those symbols, so overwriting the
    destination breaks the next import on the missing attributes. Families split across
    batches hit this immediately.
    """
    origin = tmp_path / "origin.py"
    origin.write_text(SAMPLE)
    (tmp_path / "carved.py").write_text('"""an earlier batch already wrote this"""\n')
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["alpha", "helper", "SHARED"]}))

    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 9, f"expected the collision refusal, got {rc}"
    assert "an earlier batch" in (tmp_path / "carved.py").read_text()


def test_mutable_module_state_is_held_back():
    """Per-load dedup state must not become a cross-engine singleton.

    cli.py is loaded more than once in-process by the SourceFileLoader fixtures, so each
    load used to get its own warning-dedup sets. Moved into a destination module, every
    engine imports the same object and one engine's warning suppresses another's.
    """
    src = textwrap.dedent(
        '''
        _WARNED: set[str] = set()
        _CACHE = {}
        _ITEMS = []
        LIMIT = 5
        NAMES = ("a", "b")
        '''
    ).lstrip()
    assert mutable_module_state(src) == ["_CACHE", "_ITEMS", "_WARNED"]


def test_duplicate_manifest_entries_are_refused():
    """A repeated name would make the reverse splice delete the same span twice.

    The second deletion lands on whatever followed it, so `["alpha", "alpha"]` also eats the
    next definition -- silent source corruption of the file being carved, not a harmless
    duplicate.
    """
    symbols = parse_module(SAMPLE)
    with pytest.raises(CarveError, match="duplicated in the batch"):
        resolve(symbols, ["alpha", "alpha"])


def test_environment_derived_module_state_is_held_back():
    """A value computed from the environment at import time is per-load, not a constant.

    `METHODOLOGY_UPDATE_PINS_FILE = Path.home() / ...` is immutable, so the mutable-container
    check cannot see it -- but the SourceFileLoader fixtures load cli.py more than once with
    different HOMEs. Shared, it binds to whichever load came first and a later engine reads
    the wrong profile's update-pin allowlist.
    """
    src = textwrap.dedent(
        '''
        from pathlib import Path
        import os

        PINS = Path.home() / ".config" / "pins"
        CWD = os.getcwd()
        TOKEN = os.getenv("SOME_TOKEN")
        STATIC = "/etc/hosts"
        '''
    ).lstrip()
    assert environment_derived_state(src) == ["CWD", "PINS", "TOKEN"]


def test_apply_enforces_per_load_state_for_hand_authored_manifests(tmp_path):
    """The refusal lives in apply, not only in the batch generator.

    plan_core filters these names, but a hand-authored or stale manifest goes straight
    through apply.py -- so the guarantee has to hold wherever a batch enters.
    """
    src = textwrap.dedent(
        '''
        from pathlib import Path

        _SEEN: set[str] = set()
        PINS = Path.home() / "pins"


        def warn_once(name):
            if name not in _SEEN:
                _SEEN.add(name)
        '''
    ).lstrip()
    origin = tmp_path / "origin.py"
    origin.write_text(src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["_SEEN", "warn_once"]}))

    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 10, f"expected the per-load-state refusal, got {rc}"
    assert not (tmp_path / "carved.py").exists()


BATCH = Path(__file__).resolve().parents[1] / "carve" / "batches" / "core.json"


@pytest.mark.skipif(not BATCH.exists(), reason="no committed batch")
def test_no_committed_batch_moves_a_monkeypatched_symbol():
    """An eager alias is a snapshot, not a forwarder.

    If a batch moves both a patched symbol and something that calls it, the caller resolves
    the destination's own global and `setattr(cli, name, fake)` never reaches it -- the test
    keeps passing while exercising nothing. That is what happened to test_merge_gate.py's
    malformed-content case: moved `read_version_at` called moved `gh_content`, so the injected
    failure was never invoked and a merge fail-open path silently lost its protection.

    This is the durable guard: no committed batch may contain a name the suite rebinds on
    `cli`. It is an invariant over the real manifest, so it protects every future wave rather
    than the one symbol that happened to break first.
    """
    sys.path.insert(0, str(TOOLS))
    from carve.plan_core import monkeypatched_symbols

    root = Path(__file__).resolve().parents[1]
    moved = set(json.loads(BATCH.read_text())["symbols"])
    collisions = sorted(moved & monkeypatched_symbols(root))
    assert not collisions, (
        "these symbols are rebound on `cli` by the suite and must stay in cli.py, or the "
        f"monkeypatch seam silently stops biting: {collisions}"
    )


def _mini_repo(tmp_path, origin_src, test_src=""):
    """A checkout-shaped tree: <root>/src/pkg/origin.py plus <root>/tests/."""
    root = tmp_path / "repo"
    pkg = root / "src" / "pkg"
    pkg.mkdir(parents=True)
    (root / "tests").mkdir()
    if test_src:
        (root / "tests" / "test_thing.py").write_text(test_src)
    origin = pkg / "origin.py"
    origin.write_text(origin_src)
    return root, origin


def test_apply_refuses_a_monkeypatched_symbol_for_any_manifest(tmp_path):
    """The exclusion must hold wherever a batch enters, not only in the derived planner.

    A hand-authored or stale manifest goes straight through apply.py. If it moves both a
    patched name and its caller, the caller resolves the destination's global and
    `setattr(cli, name, fake)` silently stops biting.
    """
    root, origin = _mini_repo(
        tmp_path,
        'def gh_content():\n    return "real"\n\n\n'
        "def read_version_at():\n    return gh_content()\n",
        'monkeypatch.setattr(cli, "gh_content", fake)\n',
    )
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["gh_content", "read_version_at"]}))

    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 11, f"expected the monkeypatch refusal, got {rc}"
    assert not (origin.parent / "carved.py").exists()


def test_a_patched_import_is_not_treated_as_freely_reimportable(tmp_path):
    """Re-importing a patched name hands the moved body the REAL object.

    Tests stub `cli.urlopen`; a destination that imports `urlopen` for itself would make a
    real network call inside a test that believes it stubbed one.
    """
    src = "from urllib.request import urlopen\n\n\ndef probe():\n    return urlopen('http://x')\n"
    symbols = parse_module(src)
    moving = resolve(symbols, ["probe"])

    assert dependencies(src, moving, symbols) == [], "unpatched import is safely re-importable"
    assert dependencies(src, moving, symbols, frozenset({"urlopen"})) == ["urlopen"]


def test_plan_core_creates_the_manifest_directory(tmp_path):
    """The documented command must work on a fresh checkout.

    Failing on a missing `carve/batches/` would waste the whole planning pass on a
    FileNotFoundError raised after it.
    """
    sys.path.insert(0, str(TOOLS))
    from carve.plan_core import main as plan_main

    root, origin = _mini_repo(tmp_path, 'VALUE = 1\n\n\ndef helper():\n    return VALUE\n')
    out = tmp_path / "nowhere" / "batches" / "core.json"
    assert plan_main([str(origin), str(out)]) == 0
    assert out.exists()


def test_a_failed_origin_write_leaves_no_destination(tmp_path, monkeypatch):
    """Both files or neither.

    A destination committed beside an unchanged origin is not self-healing: the collision
    refusal then blocks the retry.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    before = origin.read_text()
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["alpha", "helper", "SHARED"]}))

    real_replace = os.replace

    def explode(src, dst):
        if str(dst).endswith("origin.py"):
            raise OSError("simulated failure between the two writes")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="simulated failure"):
        carve_main(["--batch", str(batch), "--origin", str(origin)])

    assert not (origin.parent / "carved.py").exists(), "the destination must be rolled back"
    assert origin.read_text() == before, "the origin must be untouched"
    assert not list(origin.parent.glob("*.carve-tmp")), "temporaries must be cleaned up"


def test_class_bases_count_as_import_time_consumers():
    """A base class and a metaclass are evaluated when the class statement runs.

    Two consequences of omitting them, both live: a batch could move a base out from under a
    surviving subclass (its alias is a guided stub on the fail-open path, so the class
    statement raises during import), and `prune_unused_imports` could not see the CLI's only
    `NamedTuple` use -- deleting an import the origin still needs.
    """
    src = textwrap.dedent(
        '''
        class Base:
            pass


        class Meta(type):
            pass


        class Child(Base, metaclass=Meta):
            pass
        '''
    ).lstrip()
    assert "Base" in module_scope_refs(src, {"Base"})
    assert "Meta" in module_scope_refs(src, {"Meta"})
    assert "Base" not in module_scope_refs(src, {"Base", "Child"})


def test_an_import_used_only_by_a_class_base_survives_pruning():
    """The regression Codex found in the real CLI: NamedTuple, used only as a base."""
    src = textwrap.dedent(
        '''
        from typing import NamedTuple


        class Mark(NamedTuple):
            name: str
        '''
    ).lstrip()
    pruned, removed = prune_unused_imports(src)
    assert removed == [], f"an import used as a class base must survive, dropped {removed}"
    assert "from typing import NamedTuple" in pruned


def test_environment_reads_through_os_environ_are_detected():
    """`os.environ.get(...)` hides behind an undistinctive method name; `os.environ[...]` is
    not a call at all. Both are per-load environment reads."""
    src = textwrap.dedent(
        '''
        import os

        VIA_GET = os.environ.get("TOKEN")
        VIA_SUBSCRIPT = os.environ["OTHER"]
        STATIC = "constant"
        '''
    ).lstrip()
    assert environment_derived_state(src) == ["VIA_GET", "VIA_SUBSCRIPT"]


def test_a_deliberately_unused_import_is_preserved():
    """An import carrying a lint suppression is unused ON PURPOSE.

    It exists for a registration side effect and has no lexical user by design, so the usage
    analysis cannot tell it from a dead import. Pruning it silently kills the side effect.
    """
    src = (
        "import json\nimport plugin  # noqa: F401\n\n\n"
        "def uses_json():\n    return json.dumps({})\n"
    )
    pruned, removed = prune_unused_imports(src)
    assert removed == [], f"a noqa-marked import must survive, dropped {removed}"
    assert "import plugin" in pruned


def test_method_bodies_are_not_import_time_consumers():
    """A method's BODY does not run when the class is created; its defaults do.

    Walking the whole class body made a surviving method's call to a moved helper look like
    an import-time consumer, so the tool refused batches that were perfectly safe.
    """
    src = textwrap.dedent(
        '''
        def helper():
            return 1


        def default_maker():
            return 2


        class Survivor:
            def method(self, value=default_maker()):
                return helper()
        '''
    ).lstrip()
    refs = module_scope_refs(src, set())
    assert "default_maker" in refs, "an argument default DOES run at class creation"
    assert "helper" not in refs, "a method body does NOT run at class creation"


def test_a_producer_is_carvable_when_its_consumer_moves_too():
    """The planner must judge module-scope consumption against the evolving candidate set.

    Asking "who is consumed if nothing moves" permanently excluded producers that are safe
    once the consuming statement moves with them.
    """
    sys.path.insert(0, str(TOOLS))
    from carve.plan_core import plan

    src = textwrap.dedent(
        '''
        class _MissingFrameworkPackage:
            def __init__(self, exc, subject):
                pass


        ROOT = "/tmp"
        CONFIG_PATH = ROOT + "/config"
        '''
    ).lstrip()
    # CONFIG_PATH is a plain str, deliberately: a dict/set/list consumer would be excluded
    # as per-load mutable state and the cascade would hide what this test is checking.
    moved = set(plan(src)["symbols"])
    assert {"ROOT", "CONFIG_PATH"} <= moved, (
        f"ROOT is safe to move once CONFIG_PATH moves with it, got {sorted(moved)}"
    )


def test_a_rebound_import_is_not_a_safe_provider():
    """An import whose name is replaced later no longer provides that name.

    Re-importing it in the destination silently restores the ORIGINAL object: a moved body
    reading `VALUE` would get the `math` module instead of 42.
    """
    src = "import math as VALUE\n\nVALUE = 42\n\n\ndef reads():\n    return VALUE\n"
    from carve.apply import importable_names

    assert "VALUE" not in importable_names(src)

    plain = "import math\n\n\ndef reads():\n    return math.pi\n"
    assert "math" in importable_names(plain)


def test_top_level_annotations_are_import_time_when_pep563_is_absent():
    """Without `from __future__ import annotations`, a def's annotations are evaluated."""
    eager = "class Marker:\n    pass\n\n\ndef survivor(x: Marker) -> Marker:\n    return x\n"
    assert "Marker" in module_scope_refs(eager, {"Marker"})

    lazy = "from __future__ import annotations\n\n\n" + eager
    assert "Marker" not in module_scope_refs(lazy, {"Marker"})


def test_a_nested_class_decorator_is_import_time():
    """A nested class's decorators run while the OUTER class body executes."""
    src = textwrap.dedent(
        '''
        def register(cls):
            return cls


        class Outer:
            @register
            class Inner:
                pass
        '''
    ).lstrip()
    assert "register" in module_scope_refs(src, {"register"})


def test_direct_attribute_assignment_counts_as_a_test_seam(tmp_path):
    """`cli.foo = fake` patches the origin alias only, exactly like setattr does."""
    from carve.apply import monkeypatched_symbols

    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text(
        "def t():\n    cli.direct_rebind = fake\n\n"
        'monkeypatch.setattr(cli, "via_setattr", fake)\n'
    )
    assert monkeypatched_symbols(root) == {"direct_rebind", "via_setattr"}


def test_annotation_only_declarations_are_not_relocatable():
    """`TOKEN: str` binds nothing at runtime.

    Treating it as a movable symbol gives the destination no attribute while the origin's
    eager alias reads it back -- an AttributeError at import that passes every syntax check.
    """
    src = "TOKEN: str\nREAL: int = 5\n"
    names = {s.name for s in parse_module(src) if s.kind == "assign"}
    assert "REAL" in names
    assert "TOKEN" not in names


def test_class_body_annotations_respect_pep563():
    """With `from __future__ import annotations`, a method's annotations are strings.

    Reporting them as import-time references falsely refuses safe candidates -- and cli.py
    has the future import, so this over-refusal applied to the real target.
    """
    body = textwrap.dedent(
        '''
        class Marker:
            pass


        class Survivor:
            def method(self, value: Marker) -> Marker:
                return value
        '''
    ).lstrip()
    assert "Marker" in module_scope_refs(body, {"Marker"}), "eager annotations DO run"
    lazy = "from __future__ import annotations\n\n\n" + body
    assert "Marker" not in module_scope_refs(lazy, {"Marker"}), "PEP 563 defers them"


def test_a_failed_carve_leaves_no_package_scaffolding(tmp_path, monkeypatch):
    """A reported failure must not mutate the tree.

    Creating the destination directory and its __init__.py outside the transaction meant a
    failed carve still changed the checkout -- and an __init__.py can convert a namespace
    package into a regular one.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "sub.carved", "symbols": ["alpha", "helper", "SHARED"]}))

    real_replace = os.replace

    def explode(src, dst):
        if str(dst).endswith("origin.py"):
            raise OSError("simulated failure between the two writes")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="simulated failure"):
        carve_main(["--batch", str(batch), "--origin", str(origin)])

    assert not (origin.parent / "sub").exists(), "the created package must be rolled back"


def test_a_broken_existing_destination_package_is_not_treated_as_absent(tmp_path):
    """Absent fails open; broken must fail LOUDLY.

    When the destination's parent package exists but raises while initialising, find_spec
    re-raises that failure. Catching it as "unlocatable" converted a real implementation
    failure into a ModuleNotFoundError and activated the fail-open stub -- every hook then
    swallowed the broken package instead of surfacing it.
    """
    symbols = parse_module(GUARDED_SAMPLE)
    moving = resolve(symbols, ["carved_one", "carved_two"])
    new_origin, dest = carve(GUARDED_SAMPLE, moving, "core.runtime", "origin", "helpers")

    pkg = tmp_path / "tautline_methodology"
    (pkg / "core").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core" / "__init__.py").write_text(
        "raise ImportError('core package is broken, not absent')\n"
    )
    (pkg / "core" / "runtime.py").write_text(dest)
    (pkg / "origin.py").write_text(new_origin)

    proc = subprocess.run(
        [sys.executable, "-c", "import tautline_methodology.origin"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "a broken parent package must surface, not fail open"
    assert "core package is broken" in proc.stderr, proc.stderr[-2000:]

    # The genuinely-absent case must still take the fail-open branch: same tree, carved
    # module removed and the parent init repaired. This fixture's toy guard raises the
    # guided SystemExit("helpers") the moment an eager alias touches the stub, so seeing
    # that subject -- and NOT the ImportError -- proves the absent path chose fail-open.
    # (The import-survives half of the contract is asserted against the REAL package by
    # test_the_package_still_fails_open_when_the_carved_module_is_missing.)
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "core" / "runtime.py").unlink()
    proc = subprocess.run(
        [sys.executable, "-c", "import tautline_methodology.origin"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "helpers" in proc.stderr, proc.stdout + proc.stderr[-2000:]
    assert "core package is broken" not in proc.stderr


def test_an_import_rebound_inside_a_compound_statement_is_not_a_provider():
    """`if enabled: VALUE = 42` after `import math as VALUE` breaks the provider claim.

    The rebinding scan only read direct top-level assignments, so a moved body reading
    VALUE would re-import `math` in the destination and get the module instead of the
    effective value.
    """
    from carve.apply import importable_names

    conditional = (
        "import math as VALUE\n\nif True:\n    VALUE = 42\n\n\ndef reads():\n    return VALUE\n"
    )
    assert "VALUE" not in importable_names(conditional)

    augmented = "import tally as TALLY\n\nTALLY += 1\n"
    assert "TALLY" not in importable_names(augmented)

    deleted = "import math\n\ndel math\n"
    assert "math" not in importable_names(deleted)

    untouched = "import math\n\nif True:\n    OTHER = 42\n"
    assert "math" in importable_names(untouched)


def test_reordered_import_time_effects_are_refused(tmp_path):
    """The alias executes every moved statement at the FIRST moved symbol's offset.

    A later moved assignment that calls into imported external state originally ran after
    the surviving statements between them; the reorder is invisible to the dependency and
    consumer gates, so it must be refused outright.
    """
    from carve.apply import import_order_hazards

    src = textwrap.dedent(
        '''
        import registry


        def first():
            return 1


        registry.configure("prod")

        LATER = registry.STATE
        '''
    ).lstrip()
    symbols = parse_module(src)
    moving = resolve(symbols, ["first", "LATER"])
    assert import_order_hazards(src, moving) == ["LATER"]

    # A pure def displaced past the same survivor is not a hazard, and neither is an
    # effectful symbol with only pure survivors in between.
    assert import_order_hazards(src, resolve(symbols, ["first"])) == []
    pure_between = src.replace('registry.configure("prod")', "MARK = 3")
    pure_moving = resolve(parse_module(pure_between), ["first", "LATER"])
    assert import_order_hazards(pure_between, pure_moving) == []

    # And the refusal is enforced at the tool boundary, not only in the planner.
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["first", "LATER"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 12, f"expected the ordering refusal, got {rc}"
    assert not (origin.parent / "carved.py").exists()


def test_conditional_definitions_count_as_module_bindings():
    """A def inside a top-level `if` binds its name with no ast.Name node to see.

    Missing it meant a moved caller showed no back-edge and was emitted into a
    destination where the name is undefined.
    """
    from carve.apply import module_bound_names

    src = (
        "if True:\n    def guarded():\n        return 1\n\n\n"
        "def caller():\n    return guarded()\n"
    )
    assert "guarded" in module_bound_names(src)

    symbols = parse_module(src)
    moving = resolve(symbols, ["caller"])
    assert dependencies(src, moving, symbols) == ["guarded"]


def test_augmented_assignment_is_a_module_scope_read():
    """`VALUE += 1` reads VALUE, but its target's ctx is Store, not Load.

    The load-only scan accepted the carve; the origin then updated its eager alias while
    moved callers kept reading the destination's stale value.
    """
    src = "VALUE = 1\nVALUE += 1\n"
    assert "VALUE" in module_scope_refs(src, {"VALUE"})


def test_environment_derived_function_defaults_are_held_back():
    """`def load(path=Path.home())` evaluates its default ONCE, at definition time.

    In a shared destination that is once per process, not once per SourceFileLoader
    engine -- the same cross-engine leak the assignment form has. A body-level
    environment read is runtime behaviour and stays movable.
    """
    default = "from pathlib import Path\n\n\ndef load(path=Path.home()):\n    return path\n"
    assert environment_derived_state(default) == ["load"]

    method_default = (
        "import os\n\n\nclass Config:\n"
        "    def read(self, key=os.environ.get('HOME')):\n        return key\n"
    )
    assert environment_derived_state(method_default) == ["Config"]

    body_read = "import os\n\n\ndef read():\n    return os.environ.get('X')\n"
    assert environment_derived_state(body_read) == []


def test_future_import_detection_is_structural():
    """A future directive mentioned in a string is prose, not a compiler flag.

    The substring test switched every annotation gate to lazy mode and injected the
    future header into destinations whose origin never enabled it -- silently deferring
    annotations that used to run at definition time.
    """
    src = (
        'NOTE = "from __future__ import annotations"\n\n\n'
        "class Marker:\n    pass\n\n\n"
        "def survivor(x: Marker) -> Marker:\n    return x\n"
    )
    # Annotations here are EAGER, so Marker IS an import-time consumer.
    assert "Marker" in module_scope_refs(src, {"Marker"})

    symbols = parse_module(src)
    moving = resolve(symbols, ["survivor"])
    _, dest = carve(src, moving, "carved", "origin")
    assert "from __future__ import annotations" not in dest.splitlines(), (
        "the origin never enabled PEP 563; the destination must not either"
    )


def test_a_failed_scaffolding_write_is_rolled_back(tmp_path, monkeypatch):
    """Creating the package scaffolding is part of the transaction, not a preamble.

    An __init__.py write that raises after the directories were created used to skip the
    cleanup entirely, leaving directories behind despite the all-or-nothing guarantee.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "sub.carved", "symbols": ["alpha", "helper", "SHARED"]}))

    real_write = Path.write_text

    def explode(self, *args, **kwargs):
        if self.name == "__init__.py":
            raise OSError("simulated scaffolding failure")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", explode)
    with pytest.raises(OSError, match="simulated scaffolding failure"):
        carve_main(["--batch", str(batch), "--origin", str(origin)])

    assert not (origin.parent / "sub").exists(), "the created directories must be rolled back"
    assert not list(origin.parent.glob("*.carve-tmp")), "temporaries must be cleaned up"


def test_generated_alias_lines_respect_the_line_limit():
    """The FIRST committed carve must not grow the frozen E501 ratchet.

    With plan_core's real subject ("shared CLI runtime helpers") the flat handle line
    reached 111 characters, so the first real carve was unmergeable without a hand edit
    -- breaking the promise that a batch's diff is a pure function of (base, batch).
    """
    from carve.apply import LINE_LIMIT

    symbols = parse_module(GUARDED_SAMPLE)
    moving = resolve(symbols, ["carved_one", "carved_two"])
    new_origin, _ = carve(
        GUARDED_SAMPLE, moving, "core.runtime", "origin", "shared CLI runtime helpers"
    )
    long_lines = [
        (i + 1, len(line))
        for i, line in enumerate(new_origin.splitlines())
        if len(line) > LINE_LIMIT
    ]
    assert not long_lines, f"generated origin breaches the ratchet: {long_lines}"


def test_a_quoted_subject_is_escaped_not_spliced():
    """The subject lands inside generated source; it must be a string, never code."""
    symbols = parse_module(GUARDED_SAMPLE)
    moving = resolve(symbols, ["carved_one"])
    subject = 'say "hi" \\ there'
    new_origin, _ = carve(GUARDED_SAMPLE, moving, "core.runtime", "origin", subject)
    assert json.dumps(subject) in new_origin, "the subject must appear as one escaped literal"


def test_a_non_identifier_dest_is_refused(tmp_path):
    """`../evil` as a dest would escape the package directory via joinpath."""
    root, origin = _mini_repo(tmp_path, SAMPLE)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "../evil", "symbols": ["alpha", "helper", "SHARED"]}))

    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 13, f"expected the dest refusal, got {rc}"
    assert not (tmp_path / "evil.py").exists()
    assert not (origin.parent.parent / "evil.py").exists()


def test_env_derived_class_attributes_behind_a_conditional_are_held_back():
    """The platform-switch idiom binds a class attribute from the environment.

    An `if` in a class body runs at class-creation time, but the def-time walk skipped
    compound statements -- so `Config.ROOT` became a process singleton bound to
    whichever HOME the first SourceFileLoader load saw.
    """
    src = textwrap.dedent(
        '''
        import sys
        from pathlib import Path


        class Config:
            if sys.platform == "win32":
                ROOT = Path.home() / "AppData"
            else:
                ROOT = Path.home() / ".config"
        '''
    ).lstrip()
    assert environment_derived_state(src) == ["Config"]


def test_nondeterministic_import_time_calls_are_per_load_state():
    """The gate is an allowlist: an unknown import-time call is per-load, not proven safe.

    The denylist form silently admitted uuid4/time/mkdtemp/gethostname -- exactly the
    per-load values the gate exists to hold back.
    """
    src = textwrap.dedent(
        '''
        import socket
        import tempfile
        import time
        import uuid

        RUN_ID = uuid.uuid4().hex
        LOADED_AT = time.time()
        SCRATCH = tempfile.mkdtemp()
        HOSTNAME = socket.gethostname()
        '''
    ).lstrip()
    assert environment_derived_state(src) == ["HOSTNAME", "LOADED_AT", "RUN_ID", "SCRATCH"]

    deterministic = textwrap.dedent(
        '''
        import re

        PATTERN = re.compile(r"x+")
        NAMES = frozenset(("a", "b"))
        LABEL = str(42)
        '''
    ).lstrip()
    assert environment_derived_state(deterministic) == []

    # Deterministic is not sufficient: sorted()/list()/map() RESULTS are mutable or
    # stateful, so sharing them across engine loads is the same singleton leak.
    mutable_results = "BASE = (2, 1)\nORDERED = sorted(BASE)\nLAZY = map(str, BASE)\n"
    assert environment_derived_state(mutable_results) == ["LAZY", "ORDERED"]


def test_scaffolding_rollback_survives_a_missing_inner_directory(tmp_path, monkeypatch):
    """A vanished inner directory must not abandon the outer cleanup.

    FileNotFoundError is an OSError, and `break` on it left every outer created
    directory behind -- contradicting the all-or-nothing promise.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    batch = tmp_path / "b.json"
    batch.write_text(
        json.dumps({"dest": "sub.deep.carved", "symbols": ["alpha", "helper", "SHARED"]})
    )

    real_write = Path.write_text

    def explode(self, *args, **kwargs):
        if self.name == "__init__.py":
            # Simulate a concurrent sweep taking the innermost directory first.
            self.parent.rmdir()
            raise OSError("simulated scaffolding failure")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", explode)
    with pytest.raises(OSError, match="simulated scaffolding failure"):
        carve_main(["--batch", str(batch), "--origin", str(origin)])

    assert not (origin.parent / "sub").exists(), "outer directories must still be removed"


def test_a_displaced_last_user_import_is_an_ordering_hazard():
    """Pruning an import from the origin re-runs its side effects at the alias site.

    When a moved symbol was the import's LAST user, the origin loses the import and the
    destination header re-creates it -- so the module's import-time effects execute at
    the alias line instead of the original import line, past every survivor in between.
    """
    from carve.apply import import_order_hazards

    src = textwrap.dedent(
        '''
        import plugin

        print("ready")


        def moved():
            return plugin
        '''
    ).lstrip()
    symbols = parse_module(src)
    assert import_order_hazards(src, resolve(symbols, ["moved"])) == ["moved"]

    # A surviving user keeps the import at its original line: nothing is displaced.
    kept = src + "\n\ndef keeps():\n    return plugin\n"
    kept_symbols = parse_module(kept)
    assert import_order_hazards(kept, resolve(kept_symbols, ["moved"])) == []

    # Only pure survivors in between: the reorder is unobservable.
    quiet = src.replace('print("ready")', "MARK = 3")
    assert import_order_hazards(quiet, resolve(parse_module(quiet), ["moved"])) == []


def test_a_global_writing_body_is_refused(tmp_path):
    """`global COUNT; COUNT += 1` in a moved body forks module state.

    The dependency analysis correctly reports the batch as closed (COUNT moves too),
    but the origin's eager alias is a snapshot: cli.COUNT stays 0 while the destination
    counts -- so the tool must refuse, not the reviewer notice.
    """
    from carve.apply import global_writing_symbols

    src = textwrap.dedent(
        '''
        COUNT = 0


        def bump():
            global COUNT
            COUNT += 1
            return COUNT
        '''
    ).lstrip()
    symbols = parse_module(src)
    assert global_writing_symbols(src, resolve(symbols, ["bump", "COUNT"])) == ["bump"]

    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["COUNT", "bump"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 15, f"expected the global-statement refusal, got {rc}"
    assert not (origin.parent / "carved.py").exists()


def test_a_mutable_default_is_per_load_state():
    """`def collect(items=[])` evaluates its default once per LOAD, not per call.

    In a shared destination that is once per process, so every SourceFileLoader engine
    shares one list. Assignment-based gates never see it; the def-time walk must.
    """
    from carve.apply import mutable_default_symbols

    src = "def collect(items=[]):\n    return items\n"
    assert mutable_default_symbols(src) == ["collect"]

    class_attr = "class Registry:\n    ENTRIES = {}\n"
    assert mutable_default_symbols(class_attr) == ["Registry"]

    clean = "def collect(items=None):\n    return items or ()\n"
    assert mutable_default_symbols(clean) == []


def test_an_empty_batch_is_refused_not_crashed(tmp_path):
    """plan_core can legitimately emit zero symbols; apply must refuse, not ValueError."""
    root, origin = _mini_repo(tmp_path, SAMPLE)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": []}))

    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 14, f"expected the empty-batch refusal, got {rc}"
    rc = carve_main(["--batch", str(batch), "--origin", str(origin), "--plan"])
    assert rc == 14, "--plan must take the same structured refusal"
    assert not (origin.parent / "carved.py").exists()


# --- Stage-1 hardening round: every gate hole below was demonstrated live before the
# --- fix, by a hand-built origin or manifest that applied with exit 0 and changed
# --- behaviour. Each test re-runs that demonstration against the closed gate.


def test_co_lined_statements_are_refused_not_silently_deleted(tmp_path):
    """`X = 1; Y = 2` gives both statements the same span; carving one deleted both.

    model.py owns the span math, so resolve() must enforce the non-overlap invariant
    rather than trust it -- the silent form corrupted the survivor with exit 0.
    """
    src = "X = 1; Y = 2\n\n\ndef keeper():\n    return Y\n"
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["X"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 2, f"expected the overlap refusal, got {rc}"
    assert origin.read_text() == src, "a refusal must leave the origin untouched"


def test_formfeed_in_a_string_cannot_desync_the_global_gate(tmp_path, capsys):
    """splitlines() breaks on FF/VT/NEL inside string literals; ast's linenos do not.

    Before the split(\"\\n\") fix the desync made _parse_span slice the wrong lines, so
    the exit-15 gate judged the WRONG body and a global-writing move applied with
    exit 0 -- a forked-module-state miscompile hidden behind one control character.
    """
    src = 'BANNER = "a\x0cb"\n\n\ndef writer():\n    global FLAG\n    FLAG = 1\n\n\nFLAG = None\n'
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["writer"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 15, f"the FF-desynced gate bypass must refuse, got {rc}"
    assert "global" in capsys.readouterr().err


def test_nested_mutables_are_per_load_state(tmp_path):
    """`X = ([], {})` is the same cross-engine singleton as `X = []`, one node deeper."""
    from carve.apply import mutable_module_state

    nested = (
        "PAIR = ([], {})\nSCALED = [0] * 4\nPICKED = [] if True else None\n"
        "OR_FALLBACK = 0 or {}\n"
    )
    assert mutable_module_state(nested) == ["OR_FALLBACK", "PAIR", "PICKED", "SCALED"]
    # frozenset CONSUMES its literal argument into an immutable result; over-refusing it
    # would pin every constant table in cli.py and shrink the real batch for nothing.
    assert mutable_module_state("CONST = frozenset({1, 2})\n") == []

    root, origin = _mini_repo(tmp_path, "PAIR = ([], {})\n")
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["PAIR"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 10, f"expected the per-load refusal, got {rc}"


def test_a_surviving_global_writer_refuses_the_moved_name(tmp_path, capsys):
    """The exit-15 gate was one-sided: it scanned MOVING bodies only.

    `_CACHE = None` moves while `def warm(): global _CACHE` stays -- every dependency
    gate sees a closed batch, but the survivor rebinds the origin's alias while
    co-moved readers resolve the destination's stale copy.
    """
    src = "_CACHE = None\n\n\ndef warm():\n    global _CACHE\n    _CACHE = 1\n"
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["_CACHE"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 15, f"expected the surviving-writer refusal, got {rc}"
    assert "surviving" in capsys.readouterr().err


def test_a_surviving_compound_rebind_is_a_consumer(tmp_path):
    """`if FAST: greet = _fast` in a survivor stores to a moved name invisibly.

    A plain top-level duplicate is already ambiguous at resolve(); the compound form
    was uncounted by every gate, and the origin's conditional then rebound the alias
    while co-moved callers kept the destination's original.
    """
    src = (
        "FAST = False\n\n\ndef greet():\n    return 'hi'\n\n\n"
        "def _fast():\n    return 'HI'\n\n\nif FAST:\n    greet = _fast\n"
    )
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["greet"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 7, f"expected the consumer refusal, got {rc}"


def test_env_name_constants_are_refused_by_apply_not_only_plan(tmp_path, capsys):
    """apply's own comment promised this class was enforced there; it was not.

    A hand-authored manifest moving `K = \"MINERVIT_X\"` away from its reader applied
    with exit 0 and turned a provable env read into an unprovable-key finding.
    """
    src = 'K = "MINERVIT_THING"\n\n\ndef reader(env):\n    return env.get(K)\n'
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["K"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 10, f"expected the env-name-constant refusal, got {rc}"
    assert "env-name" in capsys.readouterr().err


def test_plan_core_never_emits_a_name_apply_would_refuse_to_resolve():
    """One legal tuple assignment must not kill the whole derived batch.

    `a, b = 1, 2` gets the placeholder name `<assign@LINE>` with kind \"assign\";
    emitting it refused the ENTIRE manifest at resolve() -- so the planner must
    mirror resolve()'s preconditions instead of discovering them at apply time.
    """
    from carve.plan_core import plan

    src = (
        "a, b = 1, 2\n\n\ndef carvable():\n    return 1\n\n\n"
        "def carvable_too():\n    return carvable()\n"
    )
    result = plan(src)
    assert all(name.isidentifier() for name in result["symbols"])
    assert "carvable" in result["symbols"]


def test_keyword_and_confusable_dest_segments_are_refused(tmp_path):
    """`'import'.isidentifier()` is True; NFKC confusables are identifier-valid too.

    A keyword segment generated an unparseable import (raw traceback, exit 1); a
    fullwidth segment compiled NFKC-normalized while the file kept the raw name, so
    the origin ImportErrored on its next load AFTER a successful exit 0.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    for dest in ("import.stuff", "True", "ｒｕｎｔｉｍｅ"):
        batch = tmp_path / "b.json"
        batch.write_text(json.dumps({"dest": dest, "symbols": ["alpha"]}))
        rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
        assert rc == 13, f"dest {dest!r} must take the dest refusal, got {rc}"


def test_dest_shadowing_is_refused_in_both_directions(tmp_path, capsys):
    """exists() on the exact .py file missed both shadowing directions.

    Writing carved.py beside an existing carved/ package produces a dead file the
    alias points at; scaffolding paths/ beside an existing paths.py shadows that
    module for every importer. Both applied with exit 0 and broke the next import.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    (origin.parent / "carved").mkdir()
    (origin.parent / "carved" / "__init__.py").write_text("")
    batch = tmp_path / "b.json"
    # beta, not alpha: alpha's helper() back-edge would refuse at exit 3 first.
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["beta"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 9, f"expected the package-shadow refusal, got {rc}"
    assert "existing package" in capsys.readouterr().err

    (origin.parent / "paths.py").write_text("MARKER = 1\n")
    batch.write_text(json.dumps({"dest": "paths.extra", "symbols": ["beta"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 9, f"expected the module-shadow refusal, got {rc}"
    assert "beside the existing module" in capsys.readouterr().err
    assert not (origin.parent / "paths").exists(), "the refusal must scaffold nothing"

    rc = carve_main(["--batch", str(batch), "--origin", str(origin), "--plan"])
    assert rc == 0, "--plan reports collisions without refusing"
    assert "destination collisions" in capsys.readouterr().out


def test_a_symlinked_origin_is_refused_not_silently_ungated(tmp_path, capsys):
    """resolve() follows a symlink out of the lexical tree, so every root-relative
    gate -- the monkeypatch scan above all -- judged a DIFFERENT repository, and an
    empty tests/ scan looked exactly like \"nothing is patched\"."""
    root, real_origin = _mini_repo(tmp_path, SAMPLE)
    elsewhere = tmp_path / "elsewhere" / "src" / "pkg"
    elsewhere.mkdir(parents=True)
    link = elsewhere / "origin.py"
    link.symlink_to(real_origin)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["alpha"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(link)])
    assert rc == 11, f"expected the symlink refusal, got {rc}"
    assert "symlink" in capsys.readouterr().err


def test_a_late_carve_error_is_a_structured_refusal_not_a_traceback(tmp_path, capsys):
    """CarveErrors raised past resolve() -- a span a gate cannot parse, a generated
    file that does not parse -- used to escape as raw tracebacks with exit 1."""
    src = "@(\n    staticmethod\n)\ndef odd():\n    return 1\n\n\ndef plain():\n    return 2\n"
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["odd"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 2, f"a late CarveError must become a structured refusal, got {rc}"
    assert "REFUSED" in capsys.readouterr().err
    assert origin.read_text() == src


def test_vararg_annotations_are_import_time_consumers(tmp_path):
    """`def survivor(*args: Marker())` evaluates its annotation at def time.

    The eager-annotation scan covered positional and keyword-only parameters but
    not `*args`/`**kwargs`, so moving Marker was accepted -- and on the fail-open
    path the alias stub was CALLED while defining the survivor, exiting the module
    mid-import (codex R5). Both the module-level and the class-body method form
    must count; PEP 563 mode must still defer them.
    """
    src = (
        "class Marker:\n    pass\n\n\n"
        "def survivor(*args: Marker(), **kwargs: Marker()):\n    return args, kwargs\n"
    )
    assert "Marker" in module_scope_refs(src, {"Marker"}), "vararg annotations DO run"

    method = (
        "class Marker:\n    pass\n\n\n"
        "class Survivor:\n    def m(self, *args: Marker()):\n        return args\n"
    )
    assert "Marker" in module_scope_refs(method, {"Marker"}), (
        "a method's vararg annotation runs at class-creation time"
    )

    lazy = "from __future__ import annotations\n\n\n" + src
    assert "Marker" not in module_scope_refs(lazy, {"Marker"}), "PEP 563 defers them"

    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["Marker"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 7, f"expected the consumer refusal, got {rc}"


GUARDED_HANDLE = (
    "class _MissingFrameworkPackage:\n"
    "    def __init__(self, exc, subject):\n"
    "        self._subject = subject\n\n"
    "    def __getattr__(self, name):\n"
    "        raise SystemExit(self._subject)\n\n\n"
    "try:\n"
    "    from tautline_methodology.core import runtime as _core_runtime_mod\n"
    "except ImportError:\n"
    "    _core_runtime_mod = _MissingFrameworkPackage(None, 'core')\n\n\n"
)


def test_alias_importable_names_recognizes_only_pure_reexports():
    """`helper = _core_runtime_mod.helper` is importable from core.runtime; noise is not.

    The alias IS the destination's object (eager identity), so a later family carve
    may import it directly -- but only when the alias assign is the name's SOLE
    module-scope binding and nothing global-writes it, or the identity claim breaks.
    """
    from carve.apply import alias_importable_names

    src = GUARDED_HANDLE + (
        "helper = _core_runtime_mod.helper\n"
        "renamed = _core_runtime_mod.other\n"  # attr != target: not a re-export
        "twice = _core_runtime_mod.twice\n"
        "twice = None\n"  # second binding disqualifies
        "written = _core_runtime_mod.written\n\n\n"
        "def w():\n    global written\n    written = 1\n"
    )
    provides = alias_importable_names(src)
    assert set(provides) == {"helper"}
    assert provides["helper"] == "from tautline_methodology.core.runtime import helper"

    # A LOCAL of the same name inside a surviving function is not a module-scope
    # rebinding and must not disqualify the alias (codex R1: the ast.walk form
    # dropped otherwise-movable family members from restricted plans).
    with_local = src + "\n\ndef survivor():\n    helper = 'local'\n    return helper\n"
    assert "helper" in alias_importable_names(with_local)


def test_alias_provider_handle_position_is_the_ordering_boundary():
    """The provider module's import-time effects run at its HANDLE import.

    A moved user above the handle import pulls the provider's import up past
    effectful survivors (hazard); a moved user below it is a sys.modules no-op no
    matter where the per-name alias assign sits -- the assign is a pure attribute
    read, and treating IT as the boundary over-refused 13 of 17 real batch members
    whose providers were imported thousands of lines earlier (codex R1).
    """
    from carve.apply import import_order_hazards

    floor_block = (
        "class _MissingFrameworkPackage:\n"
        "    def __init__(self, exc, subject):\n"
        "        self._subject = subject\n\n"
        "    def __getattr__(self, name):\n"
        "        raise SystemExit(self._subject)\n\n\n"
    )
    handle = (
        "try:\n"
        "    from tautline_methodology.core import runtime as _core_runtime_mod\n"
        "except ImportError:\n"
        "    _core_runtime_mod = _MissingFrameworkPackage(None, 'core')\n\n\n"
    )
    hazard = floor_block + (
        "def mover():\n    return helper()\n\n\n"
        'MARK = print("effect")\n\n\n'
    ) + handle + "helper = _core_runtime_mod.helper\n"
    symbols = parse_module(hazard)
    assert import_order_hazards(hazard, resolve(symbols, ["mover"])) == ["mover"]

    # Handle ABOVE the mover: provider already imported; the alias assign sitting
    # BELOW the mover with an effectful survivor between must NOT refuse.
    quiet = floor_block + handle + (
        "def mover():\n    return helper()\n\n\n"
        'MARK = print("effect")\n\n\n'
        "helper = _core_runtime_mod.helper\n"
    )
    assert import_order_hazards(quiet, resolve(parse_module(quiet), ["mover"])) == []


def test_plan_restrict_limits_candidates_to_a_family():
    """plan(restrict=...) derives the largest safe SUBSET of a family."""
    from carve.plan_core import plan

    src = "def a_one():\n    return 1\n\n\ndef b_one():\n    return 2\n"
    assert set(plan(src)["symbols"]) == {"a_one", "b_one"}
    assert plan(src, restrict={"a_one"})["symbols"] == ["a_one"]


def test_two_stage_carve_imports_core_helpers_directly(tmp_path):
    """Stage 2 of the split: a family member calling a stage-1-moved helper carves.

    Without alias-aware importability the helper read back-edges into the origin and
    the post-W1 family yield is ZERO (measured on the real monolith). With it, the
    family destination imports the helper straight from core.runtime -- the same
    object the origin's eager alias binds -- and behaviour is identical end to end.
    """
    root = tmp_path / "repo"
    pkg = root / "src" / "tautline_methodology"
    pkg.mkdir(parents=True)
    (root / "tests").mkdir()
    (pkg / "__init__.py").write_text("")
    origin = pkg / "cli.py"
    origin.write_text(GUARDED_HANDLE.replace(
        "    from tautline_methodology.core import runtime as _core_runtime_mod\n"
        "except ImportError:\n"
        "    _core_runtime_mod = _MissingFrameworkPackage(None, 'core')\n",
        "    import tautline_methodology as _tm_probe  # noqa: F401 # side-effect\n"
        "except ImportError:\n"
        "    pass\n",
    ) + (
        "def helper():\n    return 'from-core'\n\n\n"
        "def family_verb():\n    return helper() + '!'\n"
    ))

    stage1 = tmp_path / "s1.json"
    stage1.write_text(json.dumps({"dest": "core.runtime", "symbols": ["helper"]}))
    rc = carve_main(["--batch", str(stage1), "--origin", str(origin)])
    assert rc == 0, f"stage 1 must carve, got {rc}"
    assert "helper = _core_runtime_mod.helper" in origin.read_text()

    stage2 = tmp_path / "s2.json"
    stage2.write_text(json.dumps({"dest": "core.family", "symbols": ["family_verb"]}))
    rc = carve_main(["--batch", str(stage2), "--origin", str(origin)])
    assert rc == 0, f"stage 2 must carve through the alias, got {rc}"
    family_src = (pkg / "core" / "family.py").read_text()
    assert "from tautline_methodology.core.runtime import helper" in family_src

    proc = subprocess.run(
        [sys.executable, "-c",
         "import tautline_methodology.cli as cli\n"
         "import tautline_methodology.core.runtime as rt\n"
         "import tautline_methodology.core.family as fam\n"
         "assert cli.family_verb() == 'from-core!'\n"
         "assert fam.helper is rt.helper is cli.helper\n"
         "print('two-stage ok')"],
        cwd=root / "src", capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "two-stage ok" in proc.stdout


def test_quoted_annotation_names_are_real_dependencies(tmp_path):
    """`def f(x: "Path")` depends on Path even though symtable cannot see it.

    The name still resolves against module globals when anything evaluates the
    annotations later (typing.get_type_hints), but the destination header omitted
    the import and the carve exited 0 (codex R5). An origin-DEFINED quoted name is
    an open back-edge for the same reason.
    """
    imported = 'from pathlib import Path\n\n\ndef f(x: "Path"):\n    return x\n'
    symbols = parse_module(imported)
    moving = resolve(symbols, ["f"])
    _, dest_source = carve(imported, moving, "carved", "origin")
    assert "from pathlib import Path" in dest_source

    origin_defined = (
        "class Marker:\n    pass\n\n\ndef f(x: \"Marker\"):\n    return x\n"
    )
    root, origin = _mini_repo(tmp_path, origin_defined)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["f"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 3, f"expected the back-edge refusal, got {rc}"


def test_a_file_occupying_a_dest_parent_is_a_collision(tmp_path, capsys):
    """A bare file named `core` blocks dest core.runtime; refuse, do not traceback.

    The collision scan only looked for .py siblings and directories, so mkdir
    raised mid-apply and --plan reported clean (codex R5).
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    (origin.parent / "core").write_text("not a directory")
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "core.runtime", "symbols": ["beta"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 9, f"expected the file-parent collision refusal, got {rc}"
    assert "not a directory" in capsys.readouterr().err

    rc = carve_main(["--batch", str(batch), "--origin", str(origin), "--plan"])
    assert rc == 0
    assert "destination collisions" in capsys.readouterr().out


def test_annotated_env_name_constants_are_refused_too(tmp_path):
    """`K: str = "MINERVIT_THING"` is the same env-name constant with an annotation.

    The gate matched only plain Assign nodes, so the annotated spelling moved away
    from its reader and broke same-file env-key provability (codex R5).
    """
    src = 'K: str = "MINERVIT_THING"\n\n\ndef reader(env):\n    return env.get(K)\n'
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["K"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 10, f"expected the env-name-constant refusal, got {rc}"


def test_module_and_engine_direct_rebinds_are_monkeypatch_seams(tmp_path):
    """`module.foo = fake` and `engine.bar = fake` patch the loaded CLI engine.

    The SourceFileLoader fixtures name the loaded module `module` or `engine`; the
    direct-assignment seam matched only cli/_cli, so those patches were invisible
    and a carve could move the patched target while the test kept passing against
    nothing (codex R5).
    """
    from carve.apply import monkeypatched_symbols

    root, origin = _mini_repo(
        tmp_path,
        SAMPLE,
        test_src="module.foo = fake\nengine.bar = other\ncli.baz = third\n",
    )
    assert monkeypatched_symbols(root) >= {"foo", "bar", "baz"}

    # Nested test modules are collected by pytest and must be scanned too.
    nested = root / "tests" / "unit"
    nested.mkdir()
    (nested / "test_nested.py").write_text('cli.qux = fake\n')
    assert "qux" in monkeypatched_symbols(root)


def test_match_captures_are_module_bindings(tmp_path):
    """A top-level `case {"x": captured}` binds `captured` with no Name node.

    module_bound_names missed it, so a moved reader of the capture showed zero
    origin needs, applied with exit 0, and NameErrored in the destination
    (codex R5). The rebound scan in importable_names needs the same treatment for
    captures that overwrite imported names.
    """
    from carve.apply import importable_names, module_bound_names

    src = (
        'DATA = {"x": 1}\n\n\nmatch DATA:\n    case {"x": captured}:\n        pass\n\n\n'
        "def reader():\n    return captured\n"
    )
    assert "captured" in module_bound_names(src)

    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["reader"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 3, f"expected the back-edge refusal, got {rc}"

    rebinding = "import captured\n\n\nmatch [1]:\n    case [captured]:\n        pass\n"
    assert "captured" not in importable_names(rebinding)


def test_a_self_reading_binding_is_refused(tmp_path, capsys):
    """`VALUE = VALUE + 1` reads the origin's prior binding; the destination has none.

    symtable scopes the sliced snippet, so free_names marks VALUE local and the
    dependency gate saw nothing -- the carved module opened with a NameError
    (codex R5). A binding that reads OTHER names stays carvable with its producers.
    """
    src = "from math import pi as VALUE\n\n\nVALUE = VALUE + 1\n"
    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["VALUE"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    # The surviving import that supplies the prior VALUE is itself a rebinder of the
    # moved name, so the consumer gate fires first; either refusal keeps the tree safe.
    assert rc == 7, f"expected a refusal for the import-backed self-read, got {rc}"

    # A BUILTIN-shadowing self-read has no module-level prior binding, so it reaches
    # the self-read gate itself.
    shadow = "enumerate = enumerate\n"
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    _, origin2 = _mini_repo(shadow_dir, shadow)
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["enumerate"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin2)])
    assert rc == 3, f"expected the self-read refusal, got {rc}"
    assert "read the name they are binding" in capsys.readouterr().err

    from carve.plan_core import plan

    assert "VALUE" not in plan(src)["symbols"]
    # Control: a binding that reads a DIFFERENT co-moving name is not a self-read.
    healthy = 'BASE = "b"\nDERIVED = BASE + "x"\n'
    assert set(plan(healthy)["symbols"]) == {"BASE", "DERIVED"}


def test_deterministic_call_allowlist_is_owner_qualified(tmp_path):
    """`maker.compile()` is not `re.compile`.

    The allowlist matched bare attribute names, so ANY object's .compile()/.escape()
    passed as deterministic and became a cross-engine singleton (codex R5). Only the
    literal re.compile/re.escape stay carvable.
    """
    factory = (
        "from factories import maker\n\n\nTOKEN = maker.compile()\n\n\n"
        "def user():\n    return TOKEN\n"
    )
    assert "TOKEN" in environment_derived_state(factory)

    real_re = "import re\n\n\nPATTERN = re.compile('x')\n"
    assert environment_derived_state(real_re) == []

    root, origin = _mini_repo(tmp_path, factory)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["TOKEN"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 10, f"expected the per-load refusal, got {rc}"


def test_a_namespace_dir_beside_a_module_is_a_shadowing_collision(tmp_path, capsys):
    """An existing paths/ WITHOUT __init__.py beside paths.py must refuse too.

    The module wins over the namespace directory today, but the write path drops an
    __init__.py into the destination's parent, flipping it into a regular package
    that shadows paths.py for every importer (codex R5). Only a pre-existing regular
    package -- which already owned the name -- may accept new carved files.
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    (origin.parent / "paths.py").write_text("MARKER = 1\n")
    (origin.parent / "paths").mkdir()  # namespace dir: no __init__.py
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "paths.extra", "symbols": ["beta"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 9, f"expected the namespace-shadow refusal, got {rc}"
    assert not (origin.parent / "paths" / "__init__.py").exists()

    # Control: a pre-existing REGULAR package already owned the name; adding a carved
    # file to it changes no import resolution.
    sub = tmp_path / "two"
    sub.mkdir()
    _, origin2 = _mini_repo(sub, SAMPLE)
    (origin2.parent / "paths.py").write_text("MARKER = 1\n")
    (origin2.parent / "paths").mkdir()
    (origin2.parent / "paths" / "__init__.py").write_text("")
    rc = carve_main(["--batch", str(batch), "--origin", str(origin2)])
    assert rc == 0, f"a pre-existing regular package must stay writable, got {rc}"
    assert (origin2.parent / "paths" / "extra.py").exists()


def test_star_imports_are_never_pruned_and_refuse_the_origin(tmp_path, capsys):
    """`from constants import *` provides names the pruner cannot enumerate.

    The keep-test compared the literal '*' against real used names and deleted the
    import on every carve -- a NameError for any survivor relying on a star-provided
    name (codex R5). The pruner now keeps every star import, and the applier refuses
    a star-importing origin outright: module_bound_names, importable_names and
    dependencies are all blind to what `*` binds, so no downstream judgement is sound.
    """
    src = "from constants import *\n\n\ndef f():\n    return TOKEN\n"
    pruned, removed = prune_unused_imports(src)
    assert "from constants import *" in pruned
    assert removed == []

    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["f"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 2, f"a star-importing origin must refuse, got {rc}"
    assert "star import" in capsys.readouterr().err

    # A star inside a module-scope guard binds its names just the same.
    guarded = (
        "try:\n    from constants import *\nexcept ImportError:\n    pass\n\n\n"
        "def f():\n    return TOKEN\n"
    )
    sub_dir = tmp_path / "guarded"
    sub_dir.mkdir()
    _, origin2 = _mini_repo(sub_dir, guarded)
    rc = carve_main(["--batch", str(batch), "--origin", str(origin2)])
    assert rc == 2, f"a guarded star import must refuse too, got {rc}"


def test_surviving_import_and_nested_def_rebinds_are_refused(tmp_path):
    """Rebinding shapes with no ast.Name node must still refuse the move.

    A surviving `from replacement import greet` (in a try/except guard) and a
    surviving `if FAST:` block defining greet both overwrite the moved name from
    module-level code -- with no Store node anywhere, the consumer gate never saw
    them (codex R5), so cli.greet diverged from the destination's original.
    """
    imp = (
        "def greet():\n    return 'hi'\n\n\n"
        "try:\n    from replacement import greet\nexcept ImportError:\n    pass\n"
    )
    root, origin = _mini_repo(tmp_path, imp)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["greet"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 7, f"expected the rebind refusal for the import form, got {rc}"

    # The BARE top-level import form too: scan() inspects children, and an import's
    # children are alias nodes, so `from m import B` at top level slipped past while
    # the try-wrapped form was caught -- which is how the forward-read pattern
    # `from m import B; A = B; B = ...` carved with exit 0 (codex R5): the moved
    # A = B read the import the destination never gets.
    fwd = 'from m import B\n\n\nA = B\n\n\nB = "later"\n\n\ndef keeper():\n    return A\n'
    fwd_dir = tmp_path / "fwd"
    fwd_dir.mkdir()
    _, origin_fwd = _mini_repo(fwd_dir, fwd)
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["A", "B"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin_fwd)])
    assert rc == 7, f"expected the rebind refusal for the bare-import form, got {rc}"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["greet"]}))

    nested = (
        "FAST = False\n\n\ndef greet():\n    return 'hi'\n\n\n"
        "if FAST:\n    def greet():\n        return 'HI'\n"
    )
    sub = tmp_path / "two"
    sub.mkdir()
    _, origin2 = _mini_repo(sub, nested)
    rc = carve_main(["--batch", str(batch), "--origin", str(origin2)])
    assert rc == 7, f"expected the rebind refusal for the nested-def form, got {rc}"

    from carve.plan_core import plan

    assert "greet" not in plan(imp)["symbols"]
    assert "greet" not in plan(nested)["symbols"]

    # Control: a LOCAL of the same name inside a surviving function is not a module
    # binding. The first cut of this gate used ast.walk and dropped three safe
    # symbols from the real W1 batch exactly this way.
    from carve.apply import surviving_rebinders

    local = (
        "def greet():\n    return 'hi'\n\n\n"
        "def keeper():\n    greet = 'local'\n    return greet\n"
    )
    local_syms = parse_module(local)
    assert surviving_rebinders(local, resolve(local_syms, ["greet"])) == []
    assert "greet" in plan(local)["symbols"]


def test_destination_header_preserves_origin_import_order():
    """`import zebra, apple` must initialise zebra first in the destination too.

    The header was built with sorted(), so modules imported for their side-effect
    ORDER ran reversed in the carved module while the carve exited 0 (codex R5) --
    a behaviour change the byte-identity contract exists to prevent.
    """
    src = (
        "import zebra, apple\n\n\ndef moved():\n    return zebra.Z + apple.A\n\n\n"
        "def keeper():\n    return 1\n"
    )
    symbols = parse_module(src)
    moving = resolve(symbols, ["moved"])
    _, dest_source = carve(src, moving, "carved", "origin")
    z = dest_source.index("import zebra")
    a = dest_source.index("import apple")
    assert z < a, f"origin import order must survive the carve:\n{dest_source}"


def test_a_globally_rebound_import_is_not_a_safe_reimport(tmp_path):
    """`import math` plus a surviving `global math` writer: the dest must not re-import.

    The destination's own `import math` keeps the ORIGINAL module object while the
    surviving writer rebinds only the origin's binding -- post-switch, origin readers
    and carved readers see different objects (codex R5, reproduced live). Counting the
    name as rebound turns the moved reader into an open back-edge, which refuses, and
    plan_core's fixed point drops such readers instead of emitting them.
    """
    from carve.apply import importable_names
    from carve.plan_core import plan

    src = (
        "import math\n\n\ndef reader():\n    return math.pi\n\n\n"
        "def switch():\n    global math\n    math = None\n"
    )
    assert "math" not in importable_names(src)
    assert "reader" not in plan(src)["symbols"]

    root, origin = _mini_repo(tmp_path, src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["reader"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 3, f"expected the back-edge refusal, got {rc}"


def test_dunder_init_dest_segments_are_refused(tmp_path):
    """dest 'core.__init__' writes a real file the alias can never import.

    `from tautline_methodology.core import __init__` binds the package's own
    initializer attribute -- a method-wrapper, not the carved module -- so every
    eager alias AttributeErrors at import while the carve reports success
    (codex R5, reproduced live).
    """
    root, origin = _mini_repo(tmp_path, SAMPLE)
    for dest in ("core.__init__", "__init__"):
        batch = tmp_path / "b.json"
        batch.write_text(json.dumps({"dest": dest, "symbols": ["beta"]}))
        rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
        assert rc == 13, f"dest {dest!r} must take the dest refusal, got {rc}"


def test_eager_annotations_are_per_load_state(tmp_path):
    """Without PEP 563, an annotation evaluates at def time AND is retained.

    `def f(x: Path.home())` keeps the first load's HOME in __annotations__ forever in
    a shared destination; `def f(x: [])` retains one shared list. _def_time_exprs
    collected only decorators and defaults, so both escaped the per-load gates
    (codex R5). Every retention slot must count -- parameter (vararg included),
    return, class-body and top-level annotations -- and PEP 563 must still defer all
    of them.
    """
    from carve.apply import mutable_default_symbols

    env_src = "from pathlib import Path\n\n\ndef f(x: Path.home()):\n    return x\n"
    assert environment_derived_state(env_src) == ["f"]

    mut_src = "def g(*args: []):\n    return args\n"
    assert mutable_default_symbols(mut_src) == ["g"]

    method = "class Registry:\n    def m(self, x: {}):\n        return x\n"
    assert mutable_default_symbols(method) == ["Registry"]

    class_attr = "class Holder:\n    SLOT: [] = ()\n"
    assert mutable_default_symbols(class_attr) == ["Holder"]

    top_level = "CACHE: [] = ()\n"
    assert mutable_module_state(top_level) == ["CACHE"]

    for src in (env_src, mut_src, method, class_attr):
        lazy = "from __future__ import annotations\n\n\n" + src
        assert environment_derived_state(lazy) == []
        assert mutable_default_symbols(lazy) == []

    root, origin = _mini_repo(tmp_path, mut_src)
    batch = tmp_path / "b.json"
    batch.write_text(json.dumps({"dest": "carved", "symbols": ["g"]}))
    rc = carve_main(["--batch", str(batch), "--origin", str(origin)])
    assert rc == 10, f"expected the per-load refusal, got {rc}"


def test_a_reimported_survivor_import_below_the_alias_is_an_ordering_hazard():
    """The destination header re-creates survivor-kept imports too.

    When the origin's import line sat BELOW the alias site, the re-import at the
    alias runs the module's import-time side effects ahead of every effectful
    survivor between the two positions -- the pruned-import direction's blind spot.
    """
    from carve.apply import import_order_hazards

    src = (
        "def moved_user():\n    return helper_mod.thing\n\n\n"
        'MARK = print("effect")\n\n\nimport helper_mod\n\n\n'
        "def survivor_user():\n    return helper_mod.other\n"
    )
    symbols = parse_module(src)
    moving = resolve(symbols, ["moved_user"])
    assert import_order_hazards(src, moving) == ["moved_user"]

    # With the import ABOVE the alias site the re-import is a sys.modules no-op.
    quiet = (
        "import helper_mod\n\n\ndef moved_user():\n    return helper_mod.thing\n\n\n"
        'MARK = print("effect")\n\n\ndef survivor_user():\n    return helper_mod.other\n'
    )
    assert import_order_hazards(quiet, resolve(parse_module(quiet), ["moved_user"])) == []
