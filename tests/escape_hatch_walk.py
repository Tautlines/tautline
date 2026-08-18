"""Who actually reads an escape-hatch setting, derived from source rather than declared by hand.

An escape hatch disables a subsystem. `METHODOLOGY_DISABLE_AUTO_RESCUE` stands the sync rescue
down; `METHODOLOGY_MAINTAINER_MODE` hands a whole checkout to the operator. When an *undeclared*
function starts reading one of those, a subsystem acquires a second off switch nobody reviewed --
which is how 23 tests once silently stood themselves down.

So the reader set is measured here and declared in `ESCAPE_HATCH_READERS`, and the test beside this
module fails when the two disagree.

Why this is not a grep for `resolve_env("THE_NAME")`
----------------------------------------------------
Because measuring that way finds nothing, and reports success while finding nothing. Measured over
`POLICED_SOURCES`, a direct call-site scan attributes **zero** readers to
`METHODOLOGY_MAINTAINER_MODE` and **zero** to `METHODOLOGY_DISABLE_SNAPSHOT_EXEC`. Both are read,
constantly. Two indirections hide them, and both are deliberate designs this walk must follow
rather than ask the codebase to abandon:

* **The key is a parameter.** `methodology_snapshot_exec_disabled` calls
  `_managed_config_value(METHODOLOGY_DISABLE_SNAPSHOT_EXEC_ENV)`, and inside that helper the key is
  just `name`. The read site names no setting at all, so a call-site scan credits the read to the
  generic helper -- collapsing every managed key in the codebase onto one row.
* **The key is computed.** `maintainer_mode_config_value` iterates
  `_maintainer_mode_export_names()`, which builds both alias spellings by slicing the constant
  (`"TAUTLINE_" + NAME[len("MINERVIT_"):]`). No string literal for either spelling exists anywhere.

A registry blind to both would carry two rows whose measured set is empty and stay green forever.
That is the failure this program exists to close, so the walk resolves both:

1. **Accessors, by fixed point.** A function that reads a setting keyed by *its own parameter* is an
   accessor (`resolve_env`, `_managed_config_value`, `user_config_env_value`). A caller that passes
   a provable key to an accessor is reading that key. Iterated, so a chain of wrappers resolves.
2. **Name taint, forward.** The module constant holding a hatch's name is a *source*. A function
   returning an expression built from a source is a *supplier*; a local bound from a source or a
   supplier call is *tainted*; and a read keyed by anything tainted is a read of that hatch.

Both directions are deliberately **over**-approximate. The test asserts `derived ⊆ declared`, so
guessing wide costs a declaration and guessing narrow costs the whole point of the registry.

Known residual — and the gap list itself is NOT exhaustive
---------------------------------------------------------
Read this before trusting the coverage, because the honest statement is stronger than the
comfortable one: **this walk under-detects by an unknown margin.**

Measured evidence, not intuition. Three consecutive review rounds each found reader forms this walk
missed -- two, then five, then four -- and every one was a form the walk was believed to
handle. The
first attempt at this very section enumerated four *exotic* gaps (runtime-assembled keys, callables
in dicts, runtime shell substitution, subprocesses) and the next round immediately found four
*mundane* ones: an alias bound before its target was discovered, an annotated local, a fixed key
inside an accessor wrapper, and two whole switches nobody had registered. **Enumerating the gaps by
introspection failed twice, so this section no longer claims to be a list of them.**

What is actually warranted:

* every form listed as covered is pinned by a test that reproduces it, and four are proven by
  injecting a reader and watching the guard turn red — those specific claims hold;
* the registry is a **floor**. A green suite means "no undeclared reader in a form this walk sees",
  which is strictly weaker than "no undeclared reader";
* every gap is a false NEGATIVE. The guard never blocks legitimate work, which is the deliberate
  direction and the opposite trade from a default-deny control.

Named, deliberate gaps, so nobody mistakes them for oversights. For a **derived wrapper** -- any
accessor discovered from its body rather than seeded in `ACCESSOR_ROOTS` -- only its **first
positional argument** is read as the key. A hatch passed to a wrapper **by keyword**, or in **any
slot after the first**, is not covered.

Keyword resolution is exact for the ROOTS, whose `def` lives in `POLICED_SOURCES` and can therefore
be read rather than guessed. For wrappers it was attempted twice and deleted twice: keyword
resolution produced nine P1s, per-wrapper index tracking four more. Both contributed **zero measured
readers** -- this codebase has exactly one derived accessor and it forwards position 0 -- so each
was machinery for a case that does not occur, and each grew surface that became its own finding.

This paragraph and the code are pinned together by a test. The failure mode being avoided is not the
gap; it is a documented claim that outruns what the code does.

**Do not close this by widening the matching further.** Each widening here bought one form and one
class of false positive; one attempt made a migration *description* count as a reader, which turns
the registry from "reads it" into "mentions it" and is worth nothing. The closing move is runtime
instrumentation — have `resolve_env` and the config readers record key and caller under test, then
reconcile observed against declared. That measures instead of approximating and needs no syntax
coverage at all. Filed as `ready/2026-08-14-escape-hatch-walk-completeness/`.

Attribution is to the enclosing **top-level** function, module-qualified
(`tautline_methodology.cli:maintainer_mode_config_value`). Bare names are fragile against exactly
the byte-slice relocation the carve campaign performs, and a nested closure's own name resolves to
nothing -- the declaration has to name something a test can still `getattr`.
"""

import ast
import re
from pathlib import Path

from test_env_reads_use_resolver import POLICED_SOURCES, ROOT, _EnvReadScanner

# Functions whose FIRST argument is the name of a setting to read. The walk derives the rest of the
# accessor set from these by fixed point; these are the roots it cannot derive, because they are
# where the environment and the config file are actually touched.
#
# `user_config_env_value` is here, and it is load-bearing. Maintainer mode is readable ONLY from the
# installed config env file -- `maintainer_mode_config_value` never consults the live environment,
# on purpose, so that a stale shell export cannot arm a checkout. Seeding only on environment reads
# would leave that hatch with an empty reader set while its docstring explains why.
ACCESSOR_ROOTS = (
    "resolve_env",
    "user_config_env_value",
    "env_value_with_user_config_fallback",
)

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_MAX_PASSES = 12


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT)
    if rel.parts[0] == "bin":
        return f"bin/{rel.name}"
    return ".".join(rel.with_suffix("").parts[1:])


def _called_name(node: ast.Call) -> str | None:
    """The bare name of a call target, whether or not it arrives through an attribute chain.

    `util_module().resolve_env(x)` and a bare `resolve_env(x)` are the same read.
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


class _Toplevel(ast.NodeVisitor):
    """Every function body, tagged with the module-level name it is reachable through."""

    def __init__(self) -> None:
        self.functions: dict[str, ast.AST] = {}
        self._outer: str | None = None

    def visit_FunctionDef(self, node) -> None:
        if self._outer is None:
            self.functions.setdefault(node.name, node)
            self._outer = node.name
            self.generic_visit(node)
            self._outer = None
        else:
            self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node) -> None:
        # A method is not module-resolvable by its own name, so it is attributed to the CLASS --
        # which is. Skipping classes instead would have been a silent false NEGATIVE: a hatch read
        # from inside any method would be invisible to a guard whose whole job is to see it, and
        # the walk is over-approximate in every other direction on purpose.
        if self._outer is None:
            self.functions.setdefault(node.name, node)
            self._outer = node.name
            self.generic_visit(node)
            self._outer = None
        else:
            self.generic_visit(node)


def _param_names(node: ast.AST) -> list[str]:
    """A class is a valid attribution target but has no parameters of its own, so it can never be
    an accessor -- and asking it for `.args` is an AttributeError, not an empty list."""
    if not isinstance(node, _FUNC_NODES):
        return []
    args = node.args
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


def _accessor_set(trees: dict[str, ast.Module]) -> set[str]:
    """Bare names of every function that reads a setting keyed by its own parameter."""
    accessors = set(ACCESSOR_ROOTS)
    _ROOT_KEY_PARAM.update(_root_key_params(trees))
    for _ in range(_MAX_PASSES):
        grew = False
        # Recomputed INSIDE the loop: computing aliases once, before any wrapper was discovered,
        # meant `alias = wrapper` bound while `wrapper` was still unknown never entered the set, so
        # a second wrapper calling `alias(name)` was not an accessor and its callers were not
        # readers (Codex R3). An alias of a thing discovered later is still an alias.
        for tree in trees.values():
            found = _accessor_aliases(tree, accessors)
            if found - accessors:
                accessors |= found
                grew = True
        for tree in trees.values():
            walker = _Toplevel()
            walker.visit(tree)
            for name, node in walker.functions.items():
                if name in accessors:
                    continue
                ordered = _param_names(node)
                if not ordered:
                    continue
                for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                    # Keyword and alias forms count here too. Fixing only the READER scan for them
                    # left a wrapper forwarding `resolve_env(name=name)` outside the accessor set,
                    # so its callers were never treated as readers at all -- an undeclared reader
                    # one hop further out, staying green (Codex R2).
                    if _called_name(call) not in accessors:
                        continue
                    key = _call_key_node(call)
                    if isinstance(key, ast.Name) and key.id in ordered:
                        accessors.add(name)
                        grew = True
        if not grew:
            break
    else:  # pragma: no cover - a 12-deep wrapper chain is its own finding
        raise AssertionError("accessor derivation did not converge")
    return accessors


def _mentions(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(node))


def _calls_any(node: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(n, ast.Call) and _called_name(n) in names for n in ast.walk(node)
    )


def _sources_for(tree: ast.Module, hatch: str) -> set[str]:
    """Module-level constants whose value is (or ends with) the hatch name."""
    found = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        if value.value == hatch or value.value.endswith(hatch):
            found.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return found


def _suppliers_for(tree: ast.Module, sources: set[str]) -> set[str]:
    """Functions that hand a hatch's NAME to their caller, however they spell it."""
    suppliers: set[str] = set()
    walker = _Toplevel()
    walker.visit(tree)
    for _ in range(_MAX_PASSES):
        grew = False
        for name, node in walker.functions.items():
            if name in suppliers:
                continue
            for ret in (n for n in ast.walk(node) if isinstance(n, ast.Return)):
                if ret.value is None:
                    continue
                if _mentions(ret.value, sources) or _calls_any(ret.value, suppliers):
                    suppliers.add(name)
                    grew = True
                    break
        if not grew:
            break
    return suppliers


def _tainted_locals(
    node: ast.AST, sources: set[str], suppliers: set[str], hatch: str | None = None
) -> set[str]:
    """Locals carrying a hatch name: assigned a literal, assigned from a source, or iterated out of
    a supplier's result.

    The literal arm matters because the module-wide constant scan DROPS any name assigned more than
    once anywhere in the file -- deliberately, so it never binds the wrong value. A function doing
    `key = "MINERVIT_METHODOLOGY_UPDATE_POLICY"; resolve_env(key)` therefore resolved to nothing if
    any other function also used `key`, and that reader stayed invisible while being entirely
    compliant with the shipped env-read guard (Codex R2). Scoped to this function, a literal
    assignment is unambiguous.
    """
    tainted: set[str] = set()
    if hatch:
        for child in ast.walk(node):
            # AnnAssign as well as Assign: `key: str = "<HATCH>"` is the same binding with a type
            # on it, and skipping it left an annotated reader invisible while the shipped env-read
            # guard accepted it (Codex R3).
            if isinstance(child, ast.Assign):
                targets, value = child.targets, child.value
            elif isinstance(child, ast.AnnAssign):
                targets, value = [child.target], child.value
            else:
                continue
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            if value.value == hatch or value.value.endswith(hatch):
                tainted.update(t.id for t in targets if isinstance(t, ast.Name))
    for _ in range(_MAX_PASSES):
        grew = False
        reach = sources | tainted
        for child in ast.walk(node):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(child, ast.Assign):
                targets, value = list(child.targets), child.value
            elif isinstance(child, ast.AnnAssign):
                # `key: str = METHODOLOGY_UPDATE_POLICY_ENV` -- the literal seed above learned
                # AnnAssign, but this propagation loop did not, so a local annotated and
                # initialised from a hatch CONSTANT was never tainted and the later
                # `resolve_env(key)` produced no reader (Codex v2 R4).
                targets, value = [child.target], child.value
            elif isinstance(child, (ast.For, ast.AsyncFor)):
                targets, value = [child.target], child.iter
            elif isinstance(child, ast.comprehension):
                targets, value = [child.target], child.iter
            if value is None:
                continue
            if not (_mentions(value, reach) or _calls_any(value, suppliers)):
                continue
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and name.id not in tainted:
                        tainted.add(name.id)
                        grew = True
        if not grew:
            break
    return tainted


# The first parameter name of every discovered accessor, filled in as they are derived. A fixed
# guess list (`name`/`key`/`env`) was wrong by construction: a wrapper is classified as an accessor
# from its BODY, so it may legally call its first parameter anything, and a caller passing that
# keyword then vanished from the reader set while the wrapper stayed correctly classified
# (Codex v3 R2, escalated to P1 after being routed as P2).
# Keyword resolution is EXACT for the root accessors and absent for derived wrappers, and that
# asymmetry is the whole point. The roots are defined in POLICED_SOURCES, so their key parameter can
# be read from their own `def` -- a measurement. For derived wrappers it was a guess, three times:
# a fixed name list (a wrapper is classified from its BODY and may name the parameter anything),
# then "the first parameter" (broken by `def bridge(default, setting)` forwarding its second), then
# per-wrapper index tracking (broken by multiple forwarded parameters, keyword-only parameters, and
# a wrapper that also has a parameter called `name`).
#
# Four review rounds, nine P1s, every one in this machinery -- and it contributes ZERO measured
# readers: 27 reader sites with it, 27 without. Speculative coverage with that defect rate is worse
# than an honest gap, so the wrapper half is DELETED and stated in the residual instead. A caller
# passing a hatch to a derived wrapper BY KEYWORD is not covered. That sentence is true, stable,
# and cheaper than a fourth guess.
_ROOT_KEY_PARAM: dict[str, str] = {}


def _root_key_params(trees: dict[str, ast.Module]) -> dict[str, str]:
    """The first parameter name of each ACCESSOR_ROOT, read from its own definition."""
    found: dict[str, str] = {}
    for tree in trees.values():
        for name, node in toplevel_definitions(tree).items():
            if name in ACCESSOR_ROOTS:
                params = _param_names(node)
                if params:
                    found[name] = params[0]
    return found


# Derived accessors are read at POSITION 0 and nowhere else. That is the whole rule.
#
# Two richer versions were tried and both were deleted, for the same measured reason. Keyword
# resolution for wrappers produced nine P1s; per-wrapper positional-index tracking produced four
# more. Between them they contributed ZERO measured readers: of the derived accessors in this
# codebase, exactly one exists and it forwards position 0, so every slot-tracking refinement was
# machinery for a case that does not occur. Each attempt also grew new surface -- multiple
# forwarded parameters, keyword-only parameters, alias metadata propagation -- and each of those
# became its own finding.
#
# The gap this leaves is stated in the residual and asserted by a test: a derived wrapper that
# forwards any parameter OTHER than its first is not covered. That sentence is true of the code
# below, which is the property the previous two attempts failed at rather than the coverage.


def _root_key_param(called: str) -> str | None:
    """The root accessor's key parameter, populated ON DEMAND.

    Previously this map was filled only as a side effect of `_accessor_set`, so a test that ran
    alone -- or on an xdist worker that had not evaluated the shared fixture -- saw it empty and
    failed. Process-global state populated by whichever test happens to run first is an ordering
    dependency, and `scripts/test.sh` runs in parallel by default. I had also been running this
    module with `-p no:randomly`, which is precisely what hides this (Codex v3 R5).
    """
    if not _ROOT_KEY_PARAM:
        _ROOT_KEY_PARAM.update(_root_key_params(_parsed_sources()))
    return _ROOT_KEY_PARAM.get(called)


def _call_key_node(call: ast.Call) -> ast.expr | None:
    """The key an accessor call is reading: first positional, or the ROOT's exact keyword."""
    if call.args:
        return call.args[0]
    param = _root_key_param(_called_name(call) or "")
    if not param:
        return None
    for keyword in call.keywords:
        if keyword.arg == param:
            return keyword.value
    return None


def _accessor_aliases(tree: ast.Module, accessors: set[str]) -> set[str]:
    """Local names bound to an accessor by import-as or by assignment.

    `from ...util import resolve_env as _env` reads exactly as `resolve_env` does, and keying on the
    bare called name alone would not see it.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in accessors and alias.asname:
                    aliases.add(alias.asname)
                    if alias.name in _ROOT_KEY_PARAM:
                        _ROOT_KEY_PARAM[alias.asname] = _ROOT_KEY_PARAM[alias.name]
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # AnnAssign too: `env_reader: Callable[..., str] = resolve_env` is the same binding
            # with a type on it, and ignoring it left every call through that alias invisible
            # (Codex v3 R2).
            value = node.value
            if not isinstance(value, (ast.Name, ast.Attribute)):
                continue
            target_name = getattr(value, "id", None) or getattr(value, "attr", None)
            if target_name not in accessors:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bound = {t.id for t in targets if isinstance(t, ast.Name)}
            aliases.update(bound)
            # An alias of a ROOT is the same callable and reads the same parameter.
            if target_name in _ROOT_KEY_PARAM:
                for bound_name in bound:
                    _ROOT_KEY_PARAM[bound_name] = _ROOT_KEY_PARAM[target_name]
    return aliases


def _shell_literals(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, text) for every string literal in a module, docstrings excluded.

    Built ONCE per module. The per-hatch version walked the whole tree again for every hatch --
    697 whole-tree traversals across 41 modules and 17 hatches, about 22 seconds of the suite --
    and none of that work depends on which hatch is being looked for (Codex v2 R5).
    """
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, *_FUNC_NODES))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        text = _literal_text(node)
        if text:
            out.append((node.lineno, text))
    return out


def _literal_text(node: ast.AST) -> str | None:
    """The shell text a node contributes, for a plain string or an f-string.

    f-strings are not optional: the release-branch break-glass is emitted as
    `f'case "${{{CONST}:-}}" in'`, so the variable arrives as a FormattedValue and the literal
    halves carry only `case "${` and `:-}" in`. Reconstructing `{CONST}` in place is what lets the
    constant-interpolation pattern see it at all.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                name = getattr(piece.value, "id", None) or getattr(piece.value, "attr", "")
                parts.append("{" + str(name) + "}")
        return "".join(parts)
    return None


def _shell_reader_lines(
    literals: list[tuple[int, str]], hatch: str, constants: set[str] = frozenset()
) -> list[int]:
    """Line numbers where EMBEDDED SHELL reads the hatch.

    The generated launcher is shell held in Python string literals, so an AST walk sees opaque text.
    Measured on the tree at authoring time, `cli.py` carries 18 such reads -- `TL_UPDATE_POLICY=
    "${TAUTLINE_METHODOLOGY_UPDATE_POLICY:-}"` and friends -- and every one of them was invisible to
    the first version of this walk. A guard that cannot see the launcher would let a new hatch read
    be added there and stay green, which is the failure this registry exists to prevent (Codex R1).

    Deliberately narrow: parameter expansion (`$NAME` / `${NAME`) and a bare argument to a shell
    helper (`launcher_maintainer_mode_value NAME`). Prose that merely NAMES the variable -- help
    text, docstrings, the sunset lists -- does not match, so the registry keeps meaning "reads it"
    rather than "mentions it".
    """
    alternatives = [
        rf"\$\{{?(?:TAUTLINE_|MINERVIT_)?{re.escape(hatch)}\b",
        rf"\$\([a-z_][a-z0-9_]* +(?:TAUTLINE_|MINERVIT_){re.escape(hatch)}\b",
    ]
    alternatives += [rf"\$[{{]*\{{{re.escape(c)}\}}" for c in sorted(constants)]
    pattern = re.compile("|".join(alternatives))
    return [line for line, text in literals if pattern.search(text)]


def toplevel_definitions(tree: ast.Module) -> dict[str, ast.AST]:
    """The attribution targets this walk can emit, by name.

    THE ONE definition model, exported so the declaration resolver beside this module uses it too.
    Both previously iterated `tree.body` directly, which misses anything defined under module-level
    control flow -- and `bin/tautline` is exactly that shape: it has ZERO direct `Module.body`
    definitions because `main` lives inside an `except ModuleNotFoundError`. The walk would emit
    `bin/tautline:main` and the resolver would reject the only declaration that could satisfy it,
    leaving no valid registry update at all (Codex v3 R1).

    A resolver that disagrees with the walker about what exists is the fourth instance of that
    class in this item; sharing the model makes a fifth impossible rather than unlikely.
    """
    walker = _Toplevel()
    walker.visit(tree)
    return dict(walker.functions)


def _enclosing_toplevel(tree: ast.Module, line: int) -> str | None:
    """The attribution target whose source span contains `line`."""
    for name, node in toplevel_definitions(tree).items():
        start = min(
            [node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]
        )
        if start <= line <= (node.end_lineno or node.lineno):
            return name
    return None


_PARSED: dict[str, ast.Module] | None = None
# Indexed per module and reused across derive calls: the literal set does not depend on the hatch
# being looked for, and this walk runs at least twice per session.
_LITERALS: dict[str, list[tuple[int, str]]] = {}


def _parsed_sources() -> dict[str, ast.Module]:
    """POLICED_SOURCES parsed once per process.

    `cli.py` alone is megabytes, and this walk is called at least twice per run -- by the shared
    fixture and again by the inventory test, which derives over a different candidate set. Parsing
    is pure and the tree is only read, so the cache is safe and removes the larger half of the cost
    (Codex v2 R5).
    """
    global _PARSED
    if _PARSED is None:
        _PARSED = {
            _module_name(path): ast.parse(path.read_text(encoding="utf-8"))
            for path in POLICED_SOURCES
        }
    return _PARSED


_DERIVED: dict[str, set[str]] = {}


def derive_reader_sites(hatches) -> dict[str, set[str]]:
    """Measured module-qualified readers of each hatch, over every shipped source.

    Memoised PER HATCH, because callers ask about overlapping sets -- the shared fixture asks about
    the registry, the inventory test about a derived candidate list -- and recomputing the whole
    scan for each set is the same once-per-hatch waste that cost 22 seconds before.
    """
    wanted = [h for h in hatches if h not in _DERIVED]
    if not wanted:
        return {h: set(_DERIVED[h]) for h in hatches}
    hatches, _all = wanted, list(hatches)
    trees = _parsed_sources()

    accessors = _accessor_set(trees)
    readers: dict[str, set[str]] = {h: set() for h in hatches}

    for module, tree in trees.items():
        constants = _EnvReadScanner(tree).constants
        walker = _Toplevel()
        walker.visit(tree)
        module_accessors = accessors | _accessor_aliases(tree, accessors)
        literals = _LITERALS.get(module)
        if literals is None:
            literals = _LITERALS[module] = _shell_literals(tree)

        # Shell embedded in string literals, attributed to the def/class that emits it.
        for hatch in hatches:
            for line in _shell_reader_lines(literals, hatch, _sources_for(tree, hatch)):
                owner = _enclosing_toplevel(tree, line)
                if owner is None:
                    # Shell held in a MODULE-LEVEL template constant and emitted later by some
                    # function: the expansion is found but belongs to no def, and dropping it made
                    # a whole template's reads invisible. The module is a resolvable declaration
                    # target, so the read is attributed there rather than discarded (Codex v2 R4).
                    readers[hatch].add(module)
                elif owner:
                    # NOT skipped for accessor owners. The forwarded-parameter exception belongs to
                    # the forwarded CALL, not to the whole function: a builder that forwards a key
                    # to resolve_env AND emits shell reading a fixed hatch was dropping the shell
                    # read entirely, so a new launcher read could ship undeclared (Codex R5).
                    readers[hatch].add(f"{module}:{owner}")

        # Accessor calls at MODULE scope, which the function walk never visits.
        #
        # Nested definitions are excluded, not just top-level ones. A function defined under module
        # control flow -- `bin/tautline:main` lives inside an `except ModuleNotFoundError` -- was
        # walked here AND by the function pass, so its reads were attributed to the module as well
        # as to the function. The declaration then had to name the module to satisfy containment,
        # which is both wrong and less useful than naming the function (Codex v4 R4).
        nested_calls = {
            id(call)
            for outer in tree.body
            for inner in ast.walk(outer)
            if isinstance(inner, (*_FUNC_NODES, ast.ClassDef))
            for call in ast.walk(inner)
            if isinstance(call, ast.Call)
        }

        for node in tree.body:
            if isinstance(node, (*_FUNC_NODES, ast.ClassDef)):
                continue
            for call in (
                n
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and id(n) not in nested_calls
            ):
                if _called_name(call) not in module_accessors:
                    continue
                key = _call_key_node(call)
                literal = None
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    literal = key.value
                elif isinstance(key, ast.Name):
                    literal = constants.get(key.id)
                for hatch in hatches:
                    if literal and (literal == hatch or literal.endswith(hatch)):
                        # The MODULE is the declaration target, and it resolves -- `<module>` did
                        # not, so the form this walk had just started detecting could not be
                        # declared in any way that passed both tests. An unsatisfiable requirement
                        # is worse than an undetected one: it forces the next author to weaken the
                        # guard to get green (Codex R2).
                        readers[hatch].add(module)
        for hatch in hatches:
            sources = _sources_for(tree, hatch)
            suppliers = _suppliers_for(tree, sources) if sources else set()
            for name, node in walker.functions.items():
                # An accessor is skipped for its FORWARDED key -- that key belongs to its caller --
                # but not for a fixed one of its own. Skipping the whole body meant a wrapper that
                # forwards a parameter AND also reads a hatch by literal was invisible, and any
                # function becomes an accessor merely by forwarding one argument (Codex R3).
                forwards_only = name in module_accessors
                for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                    if _called_name(call) not in module_accessors:
                        continue
                    key = _call_key_node(call)
                    if key is None:
                        continue
                    if forwards_only and isinstance(key, ast.Name):
                        # The forwarded-parameter case: that key is the caller's, not this
                        # function's. A LITERAL key here is still this function's own read.
                        if key.id in set(_param_names(node)):
                            continue
                    literal = None
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        literal = key.value
                    elif isinstance(key, ast.Name):
                        literal = constants.get(key.id)
                    hit = literal is not None and (
                        literal == hatch or literal.endswith(hatch)
                    )
                    if not hit and literal is None:
                        tainted = _tainted_locals(node, sources, suppliers, hatch)
                        hit = _mentions(key, sources | tainted) or (
                            isinstance(key, ast.Call) and _called_name(key) in suppliers
                        )
                    if hit:
                        readers[hatch].add(f"{module}:{name}")
                        break

        # Direct environment reads keyed by the hatch, for anything not routed through an accessor.
        scanner = _EnvReadScanner(tree)
        scanner.visit(tree)
        for line, _form, key, where in scanner.reads:
            if not key:
                continue
            for hatch in hatches:
                if key == hatch or key.endswith(hatch):
                    # `where` is the INNERMOST scope the shipped scanner reports -- a method, a
                    # nested function, or `<module>` -- and only top-level names are in
                    # `walker.functions`, so those reads were silently dropped. They now resolve to
                    # their top-level owner by line span, the same attribution the shell scan uses,
                    # falling back to the module for genuine module-scope reads (Codex v4 R3).
                    owner = where if where in walker.functions else _enclosing_toplevel(tree, line)
                    readers[hatch].add(f"{module}:{owner}" if owner else module)
    _DERIVED.update({h: set(v) for h, v in readers.items()})
    return {h: set(_DERIVED[h]) for h in _all}
