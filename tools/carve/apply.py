"""Relocate top-level symbols out of a monolith by byte-slice, driven by a manifest.

A batch is a declarative manifest:

    {"dest": "release_migrations.py", "symbols": ["release_migration_report_data"]}

Symbols resolve **by name, never by line number**, so the diff a batch produces is a
pure function of (base commit, batch). Rebasing is therefore a recomputation --
`git checkout <base> -- src && apply.py --batch <name>` -- not a merge. That is what
makes parallel lanes conflict-free in a file where 89.8% of adjacent symbol pairs
sit inside git's default diff context.
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import symtable
import sys
from pathlib import Path

try:  # importable both as `carve.apply` and as a direct script
    from .model import Symbol, parse_module
except ImportError:  # pragma: no cover - direct-script path
    from model import Symbol, parse_module  # type: ignore[no-redef,import-not-found]

ALIAS_MARKER = "# --- carved: re-exported for the cli.<attr> surface ---"


class CarveError(RuntimeError):
    pass


def resolve(symbols: list[Symbol], names: list[str]) -> list[Symbol]:
    """Map requested names to spans, refusing anything ambiguous or absent.

    A duplicate top-level name is fatal rather than last-wins: carving the wrong
    one of two same-named symbols would silently change behaviour.
    """
    by_name: dict[str, list[Symbol]] = {}
    for sym in symbols:
        by_name.setdefault(sym.name, []).append(sym)

    resolved: list[Symbol] = []
    problems: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            # The reverse splice would delete this span twice, and the second deletion lands
            # on whatever followed it -- silent source corruption, not a duplicate symbol.
            problems.append(f"  duplicated in the batch: {name}")
            continue
        seen.add(name)
        found = by_name.get(name, [])
        if not name.isidentifier():
            # `parse_module` labels unnamed top-level statements `<other@LINE>` -- the
            # try/except import guards, `if __name__ == "__main__"`. They are module wiring,
            # not relocatable symbols, and a batch that swept them up would move the guards
            # away from the code they protect.
            problems.append(f"  not a relocatable symbol: {name}")
        elif not found:
            problems.append(f"  absent: {name}")
        elif len(found) > 1:
            lines = ", ".join(str(s.def_line) for s in found)
            problems.append(f"  ambiguous: {name} defined at lines {lines}")
        else:
            resolved.append(found[0])
    # Overlapping spans mean two statements share a source line (`X = 1; Y = 2`):
    # model.py gives both the full lines' bytes, so the reverse splice would delete
    # the co-lined survivor along with the moved span -- silent corruption, and with
    # both moving, the second deletion lands on whatever followed. Top-level spans
    # cannot nest, so after sorting an overlap is always between neighbours.
    if not problems and resolved:
        chosen = {id(s) for s in resolved}
        ordered = sorted(symbols, key=lambda s: (s.start_byte, s.end_byte))
        for a, b in zip(ordered, ordered[1:], strict=False):
            if b.start_byte < a.end_byte and (id(a) in chosen or id(b) in chosen):
                problems.append(
                    f"  span of {a.name} overlaps {b.name}: the statements share a source line"
                )
    if problems:
        raise CarveError("batch does not resolve against this base:\n" + "\n".join(problems))
    return resolved


def _scope_globals(table: symtable.SymbolTable) -> set[str]:
    """Names this scope and its children reference but never bind locally."""
    names: set[str] = set()
    for sym in table.get_symbols():
        # is_assigned() matters: symtable reports is_referenced() False for a pure
        # `global X; X = ...`, so a write-only global would look like no dependency at
        # all and the move would fork module state into two copies.
        if (sym.is_referenced() or sym.is_assigned()) and sym.is_global() and not sym.is_local():
            names.add(sym.get_name())
    for child in table.get_children():
        names |= _scope_globals(child)
    return names


def free_names(source: str, sym: Symbol, lines: list[str] | None = None) -> set[str]:
    """Names a symbol's body loads from module scope.

    Uses real scope analysis rather than a name intersection: a loop variable or
    local named `version` must not be mistaken for a dependency on the module's
    `version()`, or every batch would look uncarvable.

    `lines` lets a caller hoist the split out of a per-symbol loop; re-splitting a
    54k-line module once per symbol is quadratic.
    """
    if lines is None:
        lines = source.split("\n")
    # From start_line, NOT def_line: the span must include decorators. A decorator runs at
    # definition time, so `@contextmanager` is a genuine dependency -- and slicing from the
    # `def` line drops it silently, because the result still parses. That produced a
    # destination module whose decorators were undefined at import.
    snippet = "\n".join(lines[sym.start_line - 1 : sym.end_line])
    try:
        table = symtable.symtable(snippet, "<carve>", "exec")
    except SyntaxError:  # an attached comment block that confuses the slice
        snippet = "\n".join(lines[sym.def_line - 1 : sym.end_line])
        table = symtable.symtable(snippet, "<carve>", "exec")
    # The symbol itself binds at the snippet's top level; only nested scopes'
    # unbound references are genuine module-scope dependencies.
    names = _scope_globals(table)
    # A QUOTED annotation hides its names inside a string literal where symtable
    # cannot see them, but they still resolve against module globals whenever the
    # annotations are evaluated later (typing.get_type_hints) -- so they are real
    # dependencies, given the same treatment the pruner gives them (codex R5).
    try:
        span_tree: ast.AST = ast.parse(snippet)
    except SyntaxError:
        return names
    for node in ast.walk(span_tree):
        annotations: list[ast.expr | None] = []
        if isinstance(node, (ast.AnnAssign, ast.arg)):
            annotations = [node.annotation]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [node.returns]
        for ann in annotations:
            if ann is None or not (
                isinstance(ann, ast.Constant) and isinstance(ann.value, str)
            ):
                continue
            try:
                parsed = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                continue
            for sub in ast.walk(parsed):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    return names


def _has_future_annotations(tree: ast.Module) -> bool:
    """Whether the module enables PEP 563, decided structurally.

    A substring test also matched the directive inside a comment, a docstring or an
    ordinary string -- prose like `NOTE = "from __future__ import annotations"` would
    have silently switched every annotation gate to lazy mode and injected the future
    header into destinations whose origin never enabled it.
    """
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def module_scope_refs(source: str, moved_names: set[str]) -> set[str]:
    """Top-level names that the REMAINING module-level code evaluates at import time.

    A GATE, not a diagnostic. It was briefly demoted on the reasoning that a deletion-site
    alias rebinds a moved name at or before its original position, so module-scope readers
    are safe by construction. That holds only on the SUCCESS path. On the fail-open path the
    alias binds `_MissingFrameworkPackage.__getattr__`'s stub -- a *function* -- so a
    module-scope CONSUMER of a moved name explodes while evaluating it:

        HARD_EXCLUDED_FILES = frozenset((*RELEASE_ARTIFACT_PATHS, ...))
        TypeError: Value after * must be an iterable, not function

    which is exactly the wedge the arch-errors-1 contract promises cannot happen. The
    success path hides it, so the suite stays green and only a forced fallback reveals it.

    Statements that are themselves moving are excluded: they travel with the symbol.

    Plain Store (and Del) targets count alongside loads: a surviving compound statement
    that REBINDS a moved name (`if USE_FAST: greet = _fast_greet`) leaves the origin's
    conditional pointing at the alias while co-moved callers resolve the destination's
    original -- the same divergence as an import-time read, entered through a write.
    (A surviving top-level PLAIN duplicate of a moved name is already refused as
    ambiguous by resolve(); this catches the bindings resolve() cannot see.)
    """
    tree = ast.parse(source)
    # PEP 563 makes annotations strings, so they are never evaluated at def time. Without
    # it they ARE, and a moved class named in one would be a guided stub on the fail-open
    # path -- raising during import instead of failing open.
    eager_annotations = not _has_future_annotations(tree)
    referenced: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in moved_names:
                continue
            # Decorators, argument defaults, class bases/keywords and a class body all run at
            # definition time. Omitting bases let a batch move a base out from under a
            # surviving subclass, and left prune_unused_imports blind to the CLI's only
            # NamedTuple use -- deleting an import the origin still needs at class-creation.
            executed: list[ast.AST] = list(node.decorator_list)
            args = getattr(node, "args", None)
            if args is not None:
                executed += [d for d in (*args.defaults, *args.kw_defaults) if d is not None]
                if eager_annotations:
                    # *args / **kwargs annotations evaluate at def time like any other:
                    # omitting them let a surviving `def f(*args: Moved())` slip the
                    # consumer gate and call the fail-open stub mid-import (codex R5).
                    annotated = [*args.posonlyargs, *args.args, *args.kwonlyargs]
                    if args.vararg is not None:
                        annotated.append(args.vararg)
                    if args.kwarg is not None:
                        annotated.append(args.kwarg)
                    executed += [a.annotation for a in annotated if a.annotation is not None]
                    if getattr(node, "returns", None) is not None:
                        executed.append(node.returns)
            if isinstance(node, ast.ClassDef):
                executed += list(node.bases)
                executed += [kw.value for kw in node.keywords]
                executed += _class_body_evaluated(node, eager_annotations)
        else:
            if _assigned_names(node) & moved_names:
                continue
            executed = [node]
        for root in executed:
            for sub in ast.walk(root):
                if isinstance(sub, ast.Name) and isinstance(
                    sub.ctx, (ast.Load, ast.Store, ast.Del)
                ):
                    referenced.add(sub.id)
                elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
                    # `VALUE += 1` reads VALUE before storing it, but the target's ctx is
                    # Store, so a Load-only scan reported the origin's updating statement
                    # as no consumer at all.
                    referenced.add(sub.target.id)
    return referenced


def _class_body_evaluated(node: ast.ClassDef, eager_annotations: bool = True) -> list[ast.AST]:
    """The parts of a class body that actually run when the class is created.

    A plain statement in the body runs; a method's DEFAULTS, DECORATORS and ANNOTATIONS run;
    a method's BODY does not. Walking the whole body treated a surviving method's call to a
    moved helper as an import-time consumer and refused batches that were perfectly safe.
    """
    evaluated: list[ast.AST] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            evaluated += list(item.decorator_list)
            args = item.args
            evaluated += [d for d in (*args.defaults, *args.kw_defaults) if d is not None]
            if eager_annotations:
                # Same vararg/kwarg coverage as module_scope_refs: a method's
                # `*args:`/`**kwargs:` annotations run at class-creation time too.
                annotated = [*args.posonlyargs, *args.args, *args.kwonlyargs]
                if args.vararg is not None:
                    annotated.append(args.vararg)
                if args.kwarg is not None:
                    annotated.append(args.kwarg)
                evaluated += [a.annotation for a in annotated if a.annotation is not None]
                if item.returns is not None:
                    evaluated.append(item.returns)
            continue
        if isinstance(item, ast.ClassDef):
            evaluated += list(item.decorator_list)
            evaluated += list(item.bases)
            evaluated += [kw.value for kw in item.keywords]
            evaluated += _class_body_evaluated(item, eager_annotations)
            continue
        evaluated.append(item)
    return evaluated


def module_bound_names(source: str) -> set[str]:
    """Every name bound at module scope, including inside compound statements.

    Top-level `def`/`class`/assignment covers most of a module, but not all of it: the
    package-split guards bind their handles inside a `try:`/`except ModuleNotFoundError:`
    block, so `_adapters_mod` and friends are module-level names that no top-level symbol
    owns. Treating them as unbound made the dependency analysis miss them entirely, and a
    batch carrying `X = _adapters_mod.X` landed in a module where that handle does not
    exist -- a NameError at import, discovered only by running it.
    """
    bound: set[str] = set()

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
                continue  # its own body is a new scope
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    bound.add(sub.id)
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # A def/class inside a top-level `if`/`try` binds its name at module
                    # scope but creates no `ast.Name` node for it, so the Store scan alone
                    # reported no binding -- and a moved caller of one showed no back-edge.
                    bound.add(sub.name)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        bound.add((alias.asname or alias.name).split(".")[0])
                elif isinstance(sub, (ast.MatchAs, ast.MatchStar)):
                    # A match-pattern capture binds at module scope with no Name node
                    # either; missing it reported a moved reader of the capture as
                    # dependency-free (codex R5).
                    if sub.name:
                        bound.add(sub.name)
                elif isinstance(sub, ast.MatchMapping):
                    if sub.rest:
                        bound.add(sub.rest)
    walk(ast.parse(source).body)
    return bound


def importable_names(source: str) -> dict[str, str]:
    """Names the origin gets from an import, mapped to the import line that provides them.

    These are not back-edges: the destination module can import `Path` or `NamedTuple`
    exactly as the origin does. Only names the origin *defines* are true back-edges.
    Restricted to unconditional top-level imports -- an import inside a try/except guard
    is a fallback whose binding depends on the origin's own recovery logic, and copying
    it would silently duplicate that policy.
    """
    tree = ast.parse(source)
    # A name rebound at module scope after its import is no longer provided BY that import.
    # Rebinding hides anywhere at the top level, not just in direct assignments: an `if`,
    # `try`, loop or `with` body, an augmented assignment, a `del`, a guarded re-import or
    # a conditional def/class all break the "the destination can re-import this and get
    # the same object" guarantee. The walk is deliberately over-broad (it also collects
    # bindings local to nested scopes); the cost is a name treated as a back-edge instead
    # of an import, which refuses rather than miscompiles.
    rebound: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                rebound.add(sub.id)
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                rebound.add(sub.name)
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                for alias in sub.names:
                    rebound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(sub, (ast.MatchAs, ast.MatchStar)):
                # A match capture rebinding an imported name is a rebind like any
                # other, just with no Name node (codex R5).
                if sub.name:
                    rebound.add(sub.name)
            elif isinstance(sub, ast.MatchMapping):
                if sub.rest:
                    rebound.add(sub.rest)
    # A name ANY body rebinds through `global` is not provided by its import either:
    # the destination would re-import the ORIGINAL object while the surviving writer
    # rebinds only the origin's binding, so post-write behaviour diverges between
    # origin readers and carved readers (codex R5). Counting it as rebound turns a
    # moved reader into an open back-edge, which refuses -- and plan_core's fixed
    # point drops such readers instead of emitting a manifest apply then rejects.
    rebound |= global_written_names(source)

    provides: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.level:
            continue  # relative import; the destination sits at a different depth
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            if isinstance(node, ast.Import):
                stmt = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
            else:
                stmt = f"from {node.module} import {alias.name}" + (
                    f" as {alias.asname}" if alias.asname else ""
                )
            if bound not in rebound:
                provides[bound] = stmt
    # Eager alias re-exports (`name = _core_runtime_mod.name`) are importable from
    # their carved module too -- validated by alias_importable_names' own stricter
    # rules (sole module-scope binding, no global writes), which is why they merge
    # here rather than fighting this function's rebound set (the alias assign is
    # itself a Store of the name).
    for name, stmt in alias_importable_names(source).items():
        provides.setdefault(name, stmt)
    return provides


def alias_importable_names(source: str) -> dict[str, str]:
    """Names the origin re-exports from a carved/split module, mapped to direct imports.

    A carve leaves `name = _core_runtime_mod.name` eager aliases behind, with the
    handle bound by a guarded `from tautline_methodology.core import runtime as
    _core_runtime_mod`. The alias IS the destination's object (eager identity), so a
    LATER family carve may import the name straight from that module: the success
    path binds the same object cli.<name> resolves, and on the fail-open path the
    whole package is absent together, so the family destination fails open through
    its own guarded handle exactly like the origin does. Without this, every W2
    family member that calls a core-moved helper reads as an origin back-edge and
    the post-W1 family yield is zero.

    A name qualifies only when its alias assign is its SOLE module-scope binding
    (anything else rebinding it breaks the identity claim) and nothing writes it
    through `global`.
    """
    tree = ast.parse(source)
    handles: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                if alias.asname and re.fullmatch(r"_[A-Za-z0-9_]+_mod", alias.asname):
                    dotted = f"{node.module}.{alias.name}"
                    if dotted.startswith("tautline_methodology"):
                        handles[alias.asname] = dotted

    provides: dict[str, str] = {}
    alias_nodes: dict[str, ast.stmt] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in handles
            and node.value.attr == node.targets[0].id
        ):
            name = node.targets[0].id
            provides[name] = f"from {handles[node.value.value.id]} import {name}"
            alias_nodes[name] = node
    if not provides:
        return {}

    global_written = global_written_names(source)

    def disqualify(parent: ast.AST, top: ast.stmt) -> None:
        # SCOPE-AWARE, like surviving_rebinders: a LOCAL named `helper` inside some
        # function is not a module-scope rebinding and cannot break the alias
        # identity -- descending into bodies dropped otherwise-movable family
        # members from restricted plans (codex R1).
        for sub in ast.iter_child_nodes(parent):
            names_bound: list[str] = []
            descend = True
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names_bound = [sub.name]
                descend = False
            elif isinstance(sub, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
                                  ast.GeneratorExp)):
                descend = False
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                names_bound = [sub.id]
            elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                names_bound = [(a.asname or a.name).split(".")[0] for a in sub.names]
            elif isinstance(sub, (ast.MatchAs, ast.MatchStar)):
                names_bound = [sub.name] if sub.name else []
            elif isinstance(sub, ast.MatchMapping):
                names_bound = [sub.rest] if sub.rest else []
            for name in names_bound:
                if name in provides and (top is not alias_nodes.get(name)):
                    del provides[name]
            if descend:
                disqualify(sub, top)

    for node in tree.body:
        if not provides:
            break
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in provides:
                del provides[node.name]
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                bound = (a.asname or a.name).split(".")[0]
                if bound in provides:
                    del provides[bound]
            continue
        disqualify(node, node)
    for name in list(provides):
        if name in global_written:
            del provides[name]
    return provides


def prune_unused_imports(
    source: str, protect: frozenset[str] = frozenset()
) -> tuple[str, list[str]]:
    """Drop top-level imports whose last user just moved out.

    Carving removes the only caller of `difflib` or `signal` and leaves the import behind
    as an F401. Doing this inside the tool rather than by hand keeps the promise that a
    batch's diff is a pure function of (base, batch) -- a rebase recomputes the pruning
    too. `__future__` is never pruned: it is a compiler directive, not a binding.
    """
    tree = ast.parse(source)
    # Scope-aware, not a flat name sweep: a function that does its OWN `import signal` and
    # then reads `signal.SIGTERM` is not a user of the module-level import, and counting it
    # as one leaves a dead import behind (F401 plus an F811 against the local one).
    used: set[str] = set()
    for child in symtable.symtable(source, "<origin>", "exec").get_children():
        used |= _scope_globals(child)
    # Module-level references only. `ast.walk` over a top-level FunctionDef would descend
    # into its body and re-count every local use, which is what kept `import signal` alive.
    used |= module_scope_refs(source, set())
    # Annotations count as uses, and `from __future__ import annotations` means symtable
    # does not see them. Collect them explicitly rather than treating every string literal
    # as a use -- prose like "a health signal ..." would otherwise pin `import signal`.
    for node in ast.walk(tree):
        annotations: list[ast.expr | None] = []
        if isinstance(node, (ast.AnnAssign, ast.arg)):
            annotations = [node.annotation]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [node.returns]
        for ann in annotations:
            if ann is None:
                continue
            if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
                try:
                    ann = ast.parse(ann.value, mode="eval").body
                except SyntaxError:
                    continue
            for sub in ast.walk(ann):
                if isinstance(sub, ast.Name):
                    used.add(sub.id)

    # split("\n"), not splitlines(keepends=True): an exotic line break inside a string
    # literal desynchronised these indices from ast's linenos, so the edits below
    # rewrote or deleted the WRONG lines. "\n".join() restores the file losslessly.
    lines = source.split("\n")
    removed: list[str] = []
    edits: list[tuple[int, int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        # An import carrying a lint suppression is unused ON PURPOSE -- it is there for a
        # registration side effect. It has no lexical user by design, so the usage analysis
        # cannot distinguish it from a genuinely dead import; honour the marker instead.
        line = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
        if "noqa" in line or "# side-effect" in line:
            continue
        if any(a.name == "*" for a in node.names):
            # `from x import *` provides names this analysis cannot enumerate, so the
            # keep-test below ("is the alias's name used?") compared the literal '*'
            # against real used names and deleted the import on every carve -- a
            # NameError for any survivor relying on a star-provided name. Never prune.
            continue
        keep = [
            a
            for a in node.names
            if (a.asname or a.name.split(".")[0]) in used
            or (a.asname or a.name.split(".")[0]) in protect
        ]
        if len(keep) == len(node.names):
            continue
        removed += [
            a.asname or a.name for a in node.names if a not in keep
        ]
        if keep:
            if isinstance(node, ast.Import):
                text = "import " + ", ".join(
                    a.name + (f" as {a.asname}" if a.asname else "") for a in keep
                )
            else:
                dots = "." * node.level
                text = f"from {dots}{node.module or ''} import " + ", ".join(
                    a.name + (f" as {a.asname}" if a.asname else "") for a in keep
                )
            edits.append((node.lineno, node.end_lineno or node.lineno, text))
        else:
            edits.append((node.lineno, node.end_lineno or node.lineno, ""))

    for start, end, text in sorted(edits, reverse=True):
        lines[start - 1 : end] = [text] if text else []
    return "\n".join(lines), sorted(set(removed))


def _assigned_names(node: ast.stmt) -> set[str]:
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    return {t.id for t in targets if isinstance(t, ast.Name)}


SELF_REFERENTIAL = frozenset({"__file__", "__name__", "__loader__", "__package__", "__spec__"})


def self_referential_users(source: str, moving: list[Symbol]) -> list[str]:
    """Moved symbols whose behaviour depends on WHICH module they live in.

    Byte-identical relocation is not behaviour-preserving for these. The instance that
    proved it: `registered_subcommand_names()` does
    `Path(__file__).read_text()` and regexes for `.add_parser(...)`. In cli.py that
    enumerates every CLI command; moved to core/runtime.py the same bytes read a file with
    no parsers in it and return an empty list -- which silently emptied the public-contract
    manifest's entire command list, and cascaded into the startup-remediation partition,
    the snapshot/maintainer/instrumentation classification tests, and more.

    Nothing in the byte-slice model can detect this from the diff, so it has to be refused
    by name. `globals()` and `vars()` are included for the same reason: they resolve
    against the defining module.
    """
    offenders: list[str] = []
    # split("\n"), like model.py: splitlines() also breaks on VT/FF/NEL/U+2028 inside
    # string literals, which desynchronises these indices from ast's line numbers --
    # a gate slicing the wrong lines judges the wrong code.
    lines = source.split("\n")
    for sym in moving:
        tree = _parse_span(source, sym, lines)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in SELF_REFERENTIAL:
                offenders.append(sym.name)
                break
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"globals", "vars", "locals"}
                and not node.args
            ):
                offenders.append(sym.name)
                break
    return sorted(set(offenders))


def _parse_span(source: str, sym: Symbol, lines: list[str]) -> ast.AST:
    """Parse a symbol's span, falling back the way `free_names` does, never silently.

    Both refusal gates used to `except SyntaxError: continue`, which reports the symbol as
    CLEAN -- so an unparseable `__file__` reader would have been relocated. A gate that
    cannot read a symbol must refuse it, not wave it through; that fail-open is the same
    class of defect as the one `self_referential_users` exists to catch.
    """
    try:
        return ast.parse("\n".join(lines[sym.start_line - 1 : sym.end_line]))
    except SyntaxError:
        pass
    try:  # an attached comment block can confuse the wider slice
        return ast.parse("\n".join(lines[sym.def_line - 1 : sym.end_line]))
    except SyntaxError as exc:
        raise CarveError(f"cannot parse the span of {sym.name}; refusing to judge it") from exc


def multi_binding_symbols(source: str, moving: list[Symbol]) -> list[str]:
    """Moved symbols whose statement also binds OTHER module-scope names.

    `ALPHA = BETA = (...)` is one statement with two bindings. The span moves whole but the
    alias block is generated from the symbol's own name, so BETA would vanish from the
    origin with nothing re-exporting it -- and `dependencies()` cannot see it, because it
    only analyses the moved bodies, not what the survivors still read.
    """
    moved = {s.name for s in moving}
    offenders: list[str] = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        bound = _assigned_names(node)
        for sub in ast.walk(node):  # walrus leaks bind at module scope too
            if isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                bound.add(sub.target.id)
        if len(bound) > 1 and bound & moved:
            offenders += sorted(bound & moved)
    return sorted(set(offenders))


def _mutable_reachable(expr: ast.AST) -> bool:
    """True when the value this expression produces can RETAIN a mutable object.

    Only the top node was inspected before, so `X = ([], {})`, `X = [0] * 4` and
    `X = FLAG or {}` all escaped the per-load gate while being exactly the
    cross-engine singletons it exists to hold back. Recurse structurally instead.
    `frozenset(...)` stays carvable -- it consumes its argument into an immutable
    result -- and a `tuple(...)`/unknown call is judged by what its arguments could
    hand it to keep. A bare Name stays out of scope, as before: aliasing an existing
    binding creates no NEW per-load object, and the aliased name is gated on its own.
    """
    if isinstance(expr, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.SetComp,
                         ast.DictComp, ast.GeneratorExp)):
        return True
    if isinstance(expr, ast.Call):
        callee = expr.func.id if isinstance(expr.func, ast.Name) else ""
        if callee in {"set", "dict", "list", "defaultdict", "Counter"}:
            return True
        if callee == "frozenset":
            return False
        return any(_mutable_reachable(a) for a in expr.args) or any(
            _mutable_reachable(kw.value) for kw in expr.keywords
        )
    if isinstance(expr, ast.Tuple):
        return any(_mutable_reachable(e) for e in expr.elts)
    if isinstance(expr, ast.BoolOp):
        return any(_mutable_reachable(v) for v in expr.values)
    if isinstance(expr, ast.IfExp):
        return _mutable_reachable(expr.body) or _mutable_reachable(expr.orelse)
    if isinstance(expr, ast.BinOp):
        return _mutable_reachable(expr.left) or _mutable_reachable(expr.right)
    if isinstance(expr, ast.Starred):
        return _mutable_reachable(expr.value)
    return False


def mutable_module_state(source: str) -> list[str]:
    """Top-level names whose bound value can reach a mutable container.

    These are per-load state, not values. `cli.py` is loaded more than once in-process by
    the repository's SourceFileLoader fixtures, and each load used to get its own
    `_SUNSET_EMITTED_FALLBACK` / `_SNAPSHOT_STORE_WARNINGS`. Moved into a destination module,
    every engine imports the SAME singleton, so one engine's warning suppresses another's --
    a behaviour change a byte-identical diff cannot show. Reachability is judged by
    `_mutable_reachable`, not the top node alone: a mutable nested in a tuple, a BoolOp
    fallback or a conditional expression is the same singleton in other packaging.
    """
    tree = ast.parse(source)
    eager = not _has_future_annotations(tree)
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        checked: list[ast.AST] = [node.value]
        if eager and isinstance(node, ast.AnnAssign):
            # An eager annotation's result is retained in module __annotations__, so a
            # mutable one is per-load state exactly like the bound value itself.
            checked.append(node.annotation)
        if any(_mutable_reachable(expr) for expr in checked):
            names += sorted(_assigned_names(node))
    return sorted(set(names))


ENV_DERIVED_CALLS = frozenset(
    {"home", "getenv", "getcwd", "gettempdir", "expanduser", "cwd", "resolve_env"}
)

# Callables whose import-time result is a pure function of their arguments, so a shared
# destination computes the same value every load. Everything OUTSIDE this set is treated
# as per-load state: the gate is an allowlist like `_pure_expr`, not a denylist, because
# the denylist form silently admitted every source it had not heard of -- `uuid.uuid4()`,
# `time.time()`, `tempfile.mkdtemp()`, `socket.gethostname()` all walked straight through
# while being exactly the per-load values the gate exists to hold back.
_DETERMINISTIC_IMPORT_CALLS = frozenset(
    {
        # Immutable results only. Determinism is NOT sufficient: sorted()/list()/map()
        # return mutable or stateful objects, so a shared destination would hand every
        # engine the SAME list/iterator -- mutation or consumption in one leaks into the
        # next, which is the exact singleton this gate holds back.
        "frozenset", "tuple",
        "str", "int", "float", "bool", "bytes", "repr", "abs", "round",
        "len", "min", "max",
        "compile", "escape",  # re.compile / re.escape constants
        "Path",  # Path("literal"); Path.home() hits ENV_DERIVED_CALLS first
    }
)


def _env_derived_expr(expr: ast.AST) -> bool:
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Call):
            func = sub.func
            callee = getattr(func, "attr", getattr(func, "id", ""))
            if callee in ENV_DERIVED_CALLS:
                return True
            if isinstance(func, ast.Name):
                deterministic = callee in _DETERMINISTIC_IMPORT_CALLS
            elif isinstance(func, ast.Attribute):
                # Owner-qualified: the allowlist justifies exactly re.compile and
                # re.escape. A bare attribute-name match let ANY object's .compile()
                # or .escape() -- an imported factory, say -- pass as deterministic
                # and become a shared singleton (codex R5).
                deterministic = (
                    callee in {"compile", "escape"}
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "re"
                )
            else:
                deterministic = False
            if not deterministic:
                # An unknown call at import time is assumed per-load rather than proven
                # safe; the cost of over-refusal is a smaller batch, the cost of the
                # old under-refusal was a silent cross-engine singleton.
                return True
        # `os.environ.get("X")` hides behind the undistinctive method name `get`, and
        # `os.environ["X"]` is not a call at all; both are environment reads.
        if isinstance(sub, ast.Attribute) and sub.attr == "environ":
            return True
        if isinstance(sub, ast.Name) and sub.id == "environ":
            return True
    return False


def _def_time_exprs(node: ast.stmt, eager_annotations: bool = False) -> list[ast.AST]:
    """Expressions a def/class statement evaluates when the statement itself runs.

    A function BODY runs later; its decorators and argument defaults run at definition
    time. A class body's plain statements and its methods' decorators/defaults run at
    class-creation time. Without PEP 563, ANNOTATIONS evaluate at definition time too,
    and their results are RETAINED in __annotations__ -- `def f(x: Path.home())` or
    `def f(x: [])` is the same per-load leak in annotation syntax (codex R5) -- so the
    caller passes eagerness and they are collected here, vararg/kwarg included.
    """
    exprs: list[ast.AST] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        exprs += list(node.decorator_list)
        args = node.args
        exprs += [d for d in (*args.defaults, *args.kw_defaults) if d is not None]
        if eager_annotations:
            annotated = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            if args.vararg is not None:
                annotated.append(args.vararg)
            if args.kwarg is not None:
                annotated.append(args.kwarg)
            exprs += [a.annotation for a in annotated if a.annotation is not None]
            if node.returns is not None:
                exprs.append(node.returns)
    elif isinstance(node, ast.ClassDef):
        exprs += list(node.decorator_list)
        exprs += list(node.bases)
        exprs += [kw.value for kw in node.keywords]
        for item in node.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                if item.value is not None:
                    exprs.append(item.value)
                if eager_annotations and isinstance(item, ast.AnnAssign):
                    # A class-body annotation lands in the class's __annotations__.
                    exprs.append(item.annotation)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                exprs += _def_time_exprs(item, eager_annotations)
            else:
                # An `if`/`try`/loop in a class body runs at class-creation time -- the
                # platform-switch idiom `if sys.platform == ...: ROOT = Path.home() / ...`
                # binds a class attribute from the environment exactly like the direct
                # form. Hand the whole statement to the walker; over-collecting a nested
                # body is a smaller cost than the invisible singleton was.
                exprs.append(item)
    return exprs


def environment_derived_state(source: str) -> list[str]:
    """Top-level names whose value is computed from the environment at import time.

    `METHODOLOGY_UPDATE_PINS_FILE = Path.home() / ...` is immutable, so the mutable-container
    check does not see it -- but its VALUE depends on HOME, and the repo's SourceFileLoader
    fixtures load cli.py more than once with different HOMEs. In cli.py that assignment ran
    per load; in a shared destination it is a singleton bound to whichever HOME came first, so
    a later engine reads the first profile's update-pin allowlist.

    A function default is the same leak in another syntax: `def load(path=Path.home())`
    evaluates ONCE, at definition time -- per load in cli.py, but once per process in a
    shared destination, so a later engine under a different HOME keeps the first profile's
    path. Only def-time expressions count; an environment read inside a body is runtime
    behaviour and moves safely.
    """
    tree = ast.parse(source)
    eager = not _has_future_annotations(tree)
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            checked: list[ast.AST] = [node.value] if node.value is not None else []
            if eager and isinstance(node, ast.AnnAssign) and node.value is not None:
                # The annotation is evaluated and RETAINED in module __annotations__,
                # so an env-derived annotation is the same leak in another slot.
                checked.append(node.annotation)
            if any(_env_derived_expr(expr) for expr in checked):
                names += sorted(_assigned_names(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if any(_env_derived_expr(expr) for expr in _def_time_exprs(node, eager)):
                names.append(node.name)
    return sorted(set(names))


_MUTABLE_CONSTRUCTS = (
    ast.List, ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp
)
_MUTABLE_CONSTRUCTORS = frozenset({"set", "dict", "list", "defaultdict", "Counter"})


def mutable_default_symbols(source: str) -> list[str]:
    """Top-level defs/classes whose def-time expressions build a mutable object.

    `def collect(items=[])` evaluates its default ONCE, at definition time. In cli.py
    that is once per SourceFileLoader load; in a shared destination it is once per
    process, so every engine shares one function and ONE list -- `mutable_module_state`
    never sees it because it only inspects assignments. A mutable class attribute or a
    decorator argument is the same leak through other syntax; `_def_time_exprs` collects
    them all.
    """
    tree = ast.parse(source)
    eager = not _has_future_annotations(tree)
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for expr in _def_time_exprs(node, eager):
            hit = False
            for sub in ast.walk(expr):
                if isinstance(sub, _MUTABLE_CONSTRUCTS):
                    hit = True
                elif (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id in _MUTABLE_CONSTRUCTORS
                ):
                    hit = True
                if hit:
                    break
            if hit:
                names.append(node.name)
                break
    return sorted(set(names))


def global_writing_symbols(source: str, moving: list[Symbol]) -> list[str]:
    """Moved symbols whose bodies contain a `global` statement.

    A moved function that does `global COUNT; COUNT = ...` rebinds the DESTINATION
    module's global. The origin's eager alias is a snapshot, so `cli.COUNT` and every
    surviving origin reader keep seeing the old value while moved callers see the new
    one -- module state forked in two, invisibly to the dependency analysis (which
    correctly reports the batch as closed). Refused rather than forwarded: nothing in
    the byte-slice model can keep two module dicts in sync.
    """
    offenders: list[str] = []
    lines = source.split("\n")
    for sym in moving:
        tree = _parse_span(source, sym, lines)
        if any(isinstance(node, ast.Global) for node in ast.walk(tree)):
            offenders.append(sym.name)
    return sorted(set(offenders))


def global_written_names(source: str) -> set[str]:
    """Every name ANY body in the module rebinds through a `global` statement.

    Batch-independent: the writer either moves (refused by `global_writing_symbols`)
    or survives (refused by `surviving_global_writers`), so a globally-written name
    itself can never move. plan_core subtracts these up front for that reason.
    """
    return {
        name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Global)
        for name in node.names
    }


def surviving_global_writers(source: str, moving: list[Symbol]) -> list[str]:
    """Moved names that a SURVIVING body rebinds through a `global` statement.

    `global_writing_symbols` catches a `global` in a body that MOVES; this is the
    other direction. `_CACHE = None` moves while `def warm(): global _CACHE; ...`
    stays: every dependency gate sees a closed batch, but after the carve the
    survivor rebinds the ORIGIN's alias while co-moved readers resolve the
    destination's stale copy -- the same forked module state, entered from the
    other side.
    """
    moved = {s.name for s in moving}
    moved_lines = {s.def_line for s in moving}
    offenders: set[str] = set()
    for node in ast.parse(source).body:
        if node.lineno in moved_lines:
            continue  # travels with the batch; the moving-span gate already judged it
        for sub in ast.walk(node):
            if isinstance(sub, ast.Global):
                offenders |= set(sub.names) & moved
    return sorted(offenders)


def self_reading_bindings(source: str, moving: list[Symbol]) -> list[str]:
    """Moved assignments whose value READS the name being bound.

    `VALUE = VALUE + 1` (augmenting a re-imported or inherited binding) reads the
    ORIGIN's prior value; symtable scopes the sliced snippet, so free_names marks
    the name local and reports no dependency -- and the carved destination then
    opens with `VALUE = VALUE + 1` and no prior VALUE, a NameError at import
    (codex R5). Function-body self-recursion is fine; a binding-time self-read
    is not.
    """
    offenders: list[str] = []
    lines = source.split("\n")
    for sym in moving:
        if sym.kind != "assign":
            continue
        tree = _parse_span(source, sym, lines)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = _assigned_names(node)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                targets = {node.target.id}
            else:
                continue
            loads = {
                s.id
                for s in ast.walk(node)
                if isinstance(s, ast.Name) and isinstance(s.ctx, ast.Load)
            }
            if targets & loads:
                offenders.append(sym.name)
                break
    return sorted(set(offenders))


def surviving_rebinders(source: str, moving: list[Symbol]) -> list[str]:
    """Moved names that a SURVIVING statement rebinds, in ANY binding form.

    The consumer gate's walk counts Name stores, but Python rebinds through shapes
    that carry no ast.Name node at all: a surviving `from replacement import greet`
    overwrites the alias with another object, `if FAST:\\n    def greet(): ...`
    rebinds it through a nested definition, and a match-pattern capture binds its
    name as a bare string (codex R5). Either way the origin's binding diverges from
    the destination's original, so co-moved callers and cli.<name> readers split.
    A top-level PLAIN duplicate def/assign is already ambiguous at resolve(); these
    are the bindings resolve() cannot see.
    """
    moved = {s.name for s in moving}
    moved_lines = {s.def_line for s in moving}
    offenders: set[str] = set()

    def scan(parent: ast.AST) -> None:
        # SCOPE-AWARE, not ast.walk: a `lock_path = ...` LOCAL inside a surviving
        # function is not a module binding, and descending into bodies dropped three
        # perfectly safe symbols from the real W1 batch. Function/class/lambda bodies
        # are new scopes; a nested def/class still binds its NAME in this scope.
        for sub in ast.iter_child_nodes(parent):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if sub.name in moved:
                    offenders.add(sub.name)
                continue
            if isinstance(sub, ast.Lambda):
                continue
            if isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                # A comprehension is its own scope, but a walrus inside it binds HERE.
                for w in ast.walk(sub):
                    if isinstance(w, ast.NamedExpr) and isinstance(w.target, ast.Name):
                        if w.target.id in moved:
                            offenders.add(w.target.id)
                continue
            if isinstance(sub, (ast.Import, ast.ImportFrom)):
                for alias in sub.names:
                    name = (alias.asname or alias.name).split(".")[0]
                    if name in moved:
                        offenders.add(name)
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                if sub.id in moved:
                    offenders.add(sub.id)
            elif isinstance(sub, (ast.MatchAs, ast.MatchStar)):
                if sub.name and sub.name in moved:
                    offenders.add(sub.name)
            elif isinstance(sub, ast.MatchMapping):
                if sub.rest and sub.rest in moved:
                    offenders.add(sub.rest)
            scan(sub)

    for node in ast.parse(source).body:
        if node.lineno in moved_lines:
            continue  # travels with the batch
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # a top-level duplicate name is already ambiguous at resolve()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # scan() inspects CHILDREN, and a bare top-level import's children are
            # alias nodes -- so `from m import B` at module top level slipped past
            # while the same import inside a try/except was caught (codex R5: the
            # forward-read pattern `from m import B; A = B; B = ...` applied with
            # exit 0 because this rebind went unseen).
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                if name in moved:
                    offenders.add(name)
            continue
        scan(node)
    return sorted(offenders)


MANAGED_PREFIXES = ("MINERVIT_", "TAUTLINE_")


def env_name_constants(source: str) -> set[str]:
    """Constants whose VALUE is a managed env var name.

    tests/test_env_reads_use_resolver.py proves every managed env read has a statically
    resolvable key, and it resolves a `Name` key within one file. Moving
    `X = "MINERVIT_..."` away from the function that calls `os.environ.get(X)` turns a
    provable read into an `<unprovable key>` finding -- so these stay beside their readers
    rather than the guard being widened to chase them. Enforced here, not only in
    plan_core: a hand-authored or stale manifest goes straight through apply.py.
    """
    return {
        target.id
        for node in ast.parse(source).body
        # AnnAssign too: `K: str = "MINERVIT_THING"` is the same constant with an
        # annotation, and parse_module treats it as a relocatable assignment
        # (codex R5).
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(getattr(node, "value", None), ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.startswith(MANAGED_PREFIXES)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }


MONKEYPATCH_PATTERNS = (
    r"setattr\(\s*(?:cli|_cli|module|engine)\s*,\s*[\"']([A-Za-z_]\w*)[\"']",
    r"setattr\(\s*[\"'][\w.]*cli\.([A-Za-z_]\w*)[\"']",
    # A direct rebind is the same seam: `cli.foo = fake` patches the origin alias only,
    # so a co-moved caller keeps calling the real function. The SourceFileLoader
    # fixtures also name the loaded engine `module` or `engine` (codex R5), so those
    # spellings count too -- the setattr pattern above already did.
    r"^\s*(?:cli|_cli|module|engine)\.([A-Za-z_]\w*)\s*=\s*[^=]",
)


def monkeypatched_symbols(root: Path) -> set[str]:
    """Names the test suite rebinds on the `cli` module.

    An eager alias is a SNAPSHOT, not a forwarder. If a batch moves both a patched name and
    something that calls it, the caller resolves the destination's own global and
    `setattr(cli, name, fake)` never reaches it -- the test keeps passing while exercising
    nothing. This lives in apply so EVERY manifest path is covered, not just the derived one:
    a hand-authored or stale batch goes straight through apply.py.
    """
    names: set[str] = set()
    tests = root / "tests"
    if not tests.is_dir():
        return names
    # rglob, not glob: pytest collects tests/unit/test_x.py too, and a seam patched
    # only in a nested module was invisible to this gate (codex R5).
    for path in sorted(tests.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in MONKEYPATCH_PATTERNS:
            names |= set(re.findall(pattern, text, re.MULTILINE))
    return names


def relative_import_users(source: str, moving: list[Symbol]) -> list[str]:
    """Moved symbols whose bodies contain a relative import.

    Bodies move byte-identically, so `from . import x` moves with them -- and `.` then
    means the DESTINATION's package. `cli.py` sits in `tautline_methodology`, so
    `from . import test_evidence` resolves there; the same line inside
    `tautline_methodology.core.runtime` resolves against `core` and raises ImportError.
    Rewriting the line would break the byte-identity guarantee that makes a carve
    reviewable, so a batch that would relocate one is refused instead.
    """
    offenders: list[str] = []
    lines = source.split("\n")  # not splitlines(): see self_referential_users
    for sym in moving:
        tree = _parse_span(source, sym, lines)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                offenders.append(sym.name)
                break
    return sorted(offenders)


_PURE_CONSTRUCTORS = frozenset({"frozenset", "tuple", "set", "dict", "list"})


def _pure_expr(expr: ast.AST | None) -> bool:
    """True when evaluating the expression neither runs foreign code nor reads mutables.

    A bare Name load is allowed: the other gates already pin what a moved statement's
    names can resolve to (moved-with, or an import nothing rebinds), so the residual
    channel -- mutating an imported OBJECT between two top-level statements, through an
    attribute (`mod.attr = v`) or equally a subscript (`REGISTRY["k"] = v`, whose Name
    carries Load ctx and so survives the rebind check) -- is accepted as out of the
    ordering gate's scope. Calls, attribute reads and anything else that
    can observe external state are impure; builtin container constructors over pure
    arguments are the one call form admitted, or every `frozenset((...))` constant would
    be pinned in place.
    """
    if expr is None:
        return True
    if isinstance(expr, ast.Constant):
        return True
    if isinstance(expr, ast.Name):
        return isinstance(expr.ctx, ast.Load)
    if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
        return all(_pure_expr(e) for e in expr.elts)
    if isinstance(expr, ast.Dict):
        return all(_pure_expr(k) for k in expr.keys if k is not None) and all(
            _pure_expr(v) for v in expr.values
        )
    if isinstance(expr, ast.UnaryOp):
        return _pure_expr(expr.operand)
    if isinstance(expr, ast.BinOp):
        return _pure_expr(expr.left) and _pure_expr(expr.right)
    if isinstance(expr, ast.Starred):
        return _pure_expr(expr.value)
    if isinstance(expr, ast.Call):
        return (
            isinstance(expr.func, ast.Name)
            and expr.func.id in _PURE_CONSTRUCTORS
            and all(_pure_expr(a) for a in expr.args)
            and all(_pure_expr(kw.value) for kw in expr.keywords)
        )
    return False


def _pure_at_import(node: ast.stmt, eager_annotations: bool) -> bool:
    """True when executing this top-level statement is order-insensitive."""
    if isinstance(node, ast.Pass):
        return True
    if isinstance(node, ast.Expr):
        return isinstance(node.value, ast.Constant)  # a docstring
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                continue
            if isinstance(target, ast.Tuple) and all(
                isinstance(e, ast.Name) for e in target.elts
            ):
                continue
            return False  # an attribute/subscript target mutates existing state
        if (
            eager_annotations
            and isinstance(node, ast.AnnAssign)
            and not _pure_expr(node.annotation)
        ):
            return False
        return _pure_expr(node.value)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.decorator_list:
            return False
        args = node.args
        if not all(_pure_expr(d) for d in (*args.defaults, *args.kw_defaults) if d is not None):
            return False
        if eager_annotations:
            annotated = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            if args.vararg is not None:
                annotated.append(args.vararg)
            if args.kwarg is not None:
                annotated.append(args.kwarg)
            anns: list[ast.AST | None] = [a.annotation for a in annotated]
            anns.append(node.returns)
            if not all(_pure_expr(a) for a in anns):
                return False
        return True
    if isinstance(node, ast.ClassDef):
        if node.decorator_list or node.keywords:
            return False  # a decorator or metaclass runs arbitrary code at class creation
        if not all(_pure_expr(base) for base in node.bases):
            return False
        return all(_pure_at_import(item, eager_annotations) for item in node.body)
    return False


def import_order_hazards(source: str, moving: list[Symbol]) -> list[str]:
    """Moved symbols whose import-time effects would be reordered past a survivor.

    The alias block imports the destination at the FIRST moved symbol's offset, which
    executes every moved statement there. A later moved statement that does real work at
    import time -- an assignment computed by a call, a decorated def -- originally ran
    AFTER the surviving statements between them; now it runs before. The dependency and
    consumer gates cannot see an interaction routed through imported external state (both
    sides calling into the same imported module, say), so displacement past an effectful
    survivor is refused rather than reasoned about.

    Both sides must be effectful to be a hazard: reordering a pure def past anything is
    unobservable, and so is reordering anything past one. That keeps the common batch --
    plain functions scattered between other plain functions -- flowing.

    Imports are displaced too, in the other direction: when a moved symbol was an
    import's LAST user, `prune_unused_imports` deletes the import from the origin and
    the destination header re-creates it -- so the module's import-time side effects
    now run at the ALIAS site instead of the original import line. Any effectful
    survivor between the two positions observes the reorder, and the hazard is charged
    to the moved symbols that pull the import across.
    """
    tree = ast.parse(source)
    eager = not _has_future_annotations(tree)
    name_at = {s.def_line: s.name for s in moving}
    top = [(node.lineno, node) for node in tree.body]
    moved_positions = [lineno for lineno, _ in top if lineno in name_at]
    if not moved_positions:
        return []
    first = min(moved_positions)
    offenders: list[str] = []
    for lineno, node in top:
        if lineno not in name_at or lineno == first:
            continue
        if _pure_at_import(node, eager):
            continue
        displaced_past = [
            other
            for other_line, other in top
            if first < other_line < lineno
            and other_line not in name_at
            and not _pure_at_import(other, eager)
        ]
        if displaced_past:
            offenders.append(name_at[lineno])

    # Displaced re-imports. "Will be pruned" is decided against the origin WITH the
    # moved spans spliced out -- the same text the pruner will see -- via one symtable
    # pass plus the module-scope walk. Annotation-only uses are not counted, which can
    # only over-refuse (the pruner would keep the import; we assume it goes).
    lines = source.split("\n")
    wanted: set[str] = set()
    users: dict[str, set[str]] = {}
    for sym in moving:
        free = free_names(source, sym, lines)
        wanted |= free
        for name in free:
            users.setdefault(name, set()).add(sym.name)
    candidates = wanted & set(importable_names(source))
    if candidates:
        data = source.encode("utf-8")
        remaining = bytearray(data)
        for sym in sorted(moving, key=lambda s: s.start_byte, reverse=True):
            del remaining[sym.start_byte : sym.end_byte]
        remaining_src = remaining.decode("utf-8")
        survivor_used: set[str] = set()
        for child in symtable.symtable(remaining_src, "<remaining>", "exec").get_children():
            survivor_used |= _scope_globals(child)
        survivor_used |= module_scope_refs(remaining_src, set())
        import_line: dict[str, int] = {}
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__"):
                continue
            for alias in node.names:
                import_line[alias.asname or alias.name.split(".")[0]] = node.lineno
        for name in sorted(candidates - survivor_used):
            if name not in import_line:
                continue
            line_text = lines[import_line[name] - 1] if import_line[name] - 1 < len(lines) else ""
            if "noqa" in line_text or "# side-effect" in line_text:
                continue  # the pruner keeps marked imports, so nothing is displaced
            lo, hi = sorted((import_line[name], first))
            reordered_past = [
                other
                for other_line, other in top
                if lo < other_line < hi
                and other_line not in name_at
                and not _pure_at_import(other, eager)
            ]
            if reordered_past:
                offenders += sorted(users.get(name, set()))
        # The destination header re-creates every import the moved bodies use, whether
        # or not the pruner ALSO keeps it in the origin for a surviving user. At the
        # alias site a re-import is a sys.modules hit -- a no-op -- whenever the origin
        # imported the module before that line; but an import that originally ran BELOW
        # the alias site now executes its import-time side effects up there, ahead of
        # every effectful survivor between the two positions.
        for name in sorted(candidates & survivor_used):
            if name not in import_line or import_line[name] <= first:
                continue
            reordered_past = [
                other
                for other_line, other in top
                if first < other_line < import_line[name]
                and other_line not in name_at
                and not _pure_at_import(other, eager)
            ]
            if reordered_past:
                offenders += sorted(users.get(name, set()))
        # Alias-provided names are the same displacement in a third shape: the
        # destination header imports the PROVIDER MODULE (core.runtime) at the new
        # alias site. The provider's import-time effects ran at its guarded HANDLE
        # import -- not at the per-name alias assign, which is a pure attribute read
        # -- so the boundary is the handle line: a moved user ABOVE it pulls the
        # provider's import up past every effectful survivor between the two
        # positions (codex R1; using the alias-assign line here over-refused 13 of
        # 17 real batch members whose providers were imported thousands of lines
        # earlier).
        alias_stmts = alias_importable_names(source)
        handle_line: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    if alias.asname and alias.asname not in handle_line:
                        handle_line[alias.asname] = node.lineno
        provider_line: dict[str, int] = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in alias_stmts
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
            ):
                provider_line[node.targets[0].id] = handle_line.get(node.value.value.id, 0)
        for name in sorted(wanted & set(alias_stmts)):
            if provider_line.get(name, 0) <= first:
                continue
            reordered_past = [
                other
                for other_line, other in top
                if first < other_line < provider_line[name]
                and other_line not in name_at
                and not _pure_at_import(other, eager)
            ]
            if reordered_past:
                offenders += sorted(users.get(name, set()))
    return sorted(set(offenders))


def dependencies(
    source: str,
    moving: list[Symbol],
    all_symbols: list[Symbol],
    patched: frozenset[str] = frozenset(),
) -> list[str]:
    """Top-level names the moved bodies still need from the origin module."""
    moved_names = {s.name for s in moving}
    # Every module-scope binding counts, not just the ones a top-level symbol owns:
    # a handle bound inside a try/except import guard is just as unavailable in the
    # destination module as a function would be.
    origin_names = module_bound_names(source) | {
        s.name for s in all_symbols if s.kind in ("def", "class", "assign")
    }
    lines = source.split("\n")
    needed: set[str] = set()
    for sym in moving:
        needed |= free_names(source, sym, lines) & origin_names
    # An imported name the suite patches on `cli` must NOT be treated as freely
    # re-importable: the destination would import the real object while the test stubs
    # cli's copy, so a stubbed network call becomes a real one.
    safe_imports = set(importable_names(source)) - set(patched)
    return sorted(needed - moved_names - safe_imports)


LINE_LIMIT = 100  # ruff's configured line-length; the E501 ratchet counts every breach


def _alias_line(name: str, handle: str) -> str:
    """One eager re-export, wrapped if it would breach the line-length ratchet.

    A long symbol name appears twice in `NAME = _handle.NAME`, so the longest ones reach
    126 characters -- each one a new E501 against a ratchet that refuses any growth.
    """
    flat = f"{name} = {handle}.{name}\n"
    if len(flat) - 1 <= LINE_LIMIT:
        return flat
    return f"{name} = (\n    {handle}.{name}\n)\n"


def binding_floor(source: str) -> int:
    """Line of `_MissingFrameworkPackage`, below which a guarded alias may be emitted.

    The alias block names `_MissingFrameworkPackage` to honour the arch-errors-1 fail-open
    contract, so emitting it above that class NameErrors at import and takes every hook
    down. Returns 0 when the origin has no such guard (a plain module).
    """
    for sym in parse_module(source):
        if sym.name == "_MissingFrameworkPackage":
            return sym.end_line
    return 0


def carve(
    source: str, moving: list[Symbol], dest_module: str, origin_module: str, subject: str = ""
) -> tuple[str, str]:
    """Return (new origin source, dest module source).

    The alias lands AT THE DELETION SITE, not at EOF. That is the recipe the previous
    package-split wave proved (see the `core.paths` / `core.policy` re-exports in cli.py),
    and it is what makes module-scope references safe: every moved name rebinds at or
    before the position its definition held, so any top-level statement that read it still
    reads it. An EOF alias would bind too late and NameError at import.

    Spans are excised back-to-front so earlier byte offsets stay valid; the alias is then
    inserted at the first moved symbol's original offset, which nothing before it disturbed.
    """
    data = source.encode("utf-8")
    ordered = sorted(moving, key=lambda s: s.start_byte)
    bodies = [data[s.start_byte : s.end_byte].decode("utf-8") for s in ordered]

    remaining = bytearray(data)
    for sym in sorted(ordered, key=lambda s: s.start_byte, reverse=True):
        del remaining[sym.start_byte : sym.end_byte]

    names = [s.name for s in ordered]
    handle = f"_{dest_module.replace('.', '_')}_mod"
    # `from pkg import a.b` is a SyntaxError: a dotted dest has to be split so the package
    # is imported from and only the leaf name is bound.
    pkg, _, leaf = f"tautline_methodology.{dest_module}".rpartition(".")
    if binding_floor(source):
        # Guarded form: a standalone bin/tautline with no package must still fail open.
        alias = (
            f"{ALIAS_MARKER}\n"
            f"# {len(names)} symbol(s) moved to tautline_methodology.{dest_module}; re-exported\n"
            f"# here as eager aliases so cli.<name> reach and in-bin references keep resolving.\n"
            f"try:\n"
            f"    from {pkg} import {leaf} as {handle}\n"
            f"except ImportError as exc:\n"
f"    # Only an ABSENT destination may fail open. A destination that exists but raises\n"
f"    # while initialising is a real implementation failure, and converting it here would\n"
f"    # make every hook swallow it. find_spec distinguishes the two -- including when\n"
f"    # find_spec itself raises: importing a parent package can re-raise the parent's own\n"
f"    # initialisation failure, and only a ModuleNotFoundError naming a module on the\n"
f"    # destination's dotted path means ABSENT rather than broken.\n"
f"    import importlib.util as _ilu\n"
f"    _dotted = \"tautline_methodology.{dest_module}\".split(\".\")\n"
f"    _chain = {{\".\".join(_dotted[:_n]) for _n in range(1, len(_dotted) + 1)}}\n"
f"    try:\n"
f"        _locatable = _ilu.find_spec(\"tautline_methodology.{dest_module}\") is not None\n"
f"    except ModuleNotFoundError as _probe_exc:\n"
f"        if _probe_exc.name not in _chain:\n"
f"            raise\n"
f"        _locatable = False\n"
f"    except ValueError:\n"
f"        _locatable = False\n"
f"    if _locatable:\n"
f"        raise\n"
f"    # A missing SUBMODULE of an importable package raises plain ImportError, but the\n"
f"    # hook fail-open path keys on SystemExit.__cause__ being a ModuleNotFoundError.\n"
f"    if not isinstance(exc, ModuleNotFoundError):\n"
f"        exc = ModuleNotFoundError(str(exc), name=\"tautline_methodology.{dest_module}\")\n"
            # Wrapped like _alias_line, and for the same reason: with a real subject the
            # flat form reaches ~110 characters, so the FIRST committed carve would grow
            # the frozen E501 ratchet and be unmergeable without a hand edit -- which
            # would break the promise that a batch's diff is a pure function of
            # (base, batch). json.dumps produces a valid, fully escaped Python string
            # literal, so a subject containing quotes cannot splice into the source.
            f"    {handle} = _MissingFrameworkPackage(  # type: ignore[assignment]\n"
            f"        exc, {json.dumps(subject or dest_module)}\n"
            f"    )\n"
        ) + "".join(_alias_line(n, handle) for n in names)
    else:
        alias = f"{ALIAS_MARKER}\nfrom .{dest_module} import (\n" + "".join(
            f"    {n},\n" for n in names
        ) + ")\n"

    insert_at = ordered[0].start_byte
    remaining[insert_at:insert_at] = alias.encode("utf-8")
    spliced = remaining.decode("utf-8")
    # Validate BEFORE pruning: the pruner parses too, and a malformed alias would surface
    # as a raw SyntaxError from inside it rather than a refusal the caller can act on.
    try:
        ast.parse(spliced)
    except SyntaxError as exc:
        raise CarveError(f"generated origin does not parse: {exc}") from exc
    new_origin, pruned = prune_unused_imports(spliced, protect=frozenset(names) | {handle})
    if pruned:
        print(f"pruned now-unused imports: {', '.join(pruned)}")

    provides = importable_names(source)
    split = source.split("\n")
    wanted: set[str] = set()
    for sym in ordered:
        wanted |= free_names(source, sym, split)
    # ORIGIN order, never sorted(): two modules imported for their side effects
    # (`import b` then `import a`) must initialise in the destination in the same
    # order they did in the origin -- alphabetising the header reversed them while
    # the carve exited 0 (codex R5). Multi-alias statements keep their within-
    # statement order too, because provides was built alias by alias.
    needed = wanted & set(provides)
    alias_stmts = alias_importable_names(source)
    imports = []
    for node in ast.parse(source).body:
        stmts: list[str] = []
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__"):
                continue
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound in needed:
                    stmts.append(provides[bound])
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            # An eager alias re-export provides its name at ITS position -- after the
            # real import block, exactly where the origin bound it.
            name = node.targets[0].id
            if name in needed and provides.get(name) == alias_stmts.get(name):
                stmts.append(provides[name])
        for stmt in stmts:
            if stmt not in imports:
                imports.append(stmt)

    header = f'"""Carved out of {origin_module}.py. Behaviour-identical by construction."""\n\n'
    # The future flag follows the ORIGIN, not the presence of other imports. An import-free
    # batch that dropped it would leave forward annotations to be evaluated eagerly, and the
    # resulting NameError happens at import of the destination -- after ast.parse has already
    # pronounced the file valid, so nothing in this tool would catch it.
    if _has_future_annotations(ast.parse(source)):
        header += "from __future__ import annotations\n\n"
    if imports:
        header += "\n".join(imports) + "\n\n"
    dest_source = header + "\n\n".join(b.strip("\n") for b in bodies) + "\n"

    # Never hand back source that does not parse. A generated alias is easy to get subtly
    # wrong (`from pkg import a.b` is a SyntaxError, not an import error), and a carve that
    # writes broken files has already destroyed the origin by the time anything runs.
    for label, text in (("origin (post-prune)", new_origin), (dest_module, dest_source)):
        try:
            ast.parse(text)
        except SyntaxError as exc:
            raise CarveError(f"generated {label} does not parse: {exc}") from exc

    return new_origin, dest_source


def main(argv: list[str] | None = None) -> int:
    """Structured refusals, never tracebacks: any CarveError is REFUSED with exit 2.

    The numbered gates return their own codes (3-15); everything they cannot classify
    -- an unparseable span inside a gate helper, a generated file that does not parse,
    a span misattached by an exotic decorator layout -- must still surface as a
    refusal the caller can act on, not a raw traceback with exit 1.
    """
    try:
        return _main_inner(argv)
    except CarveError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


def _main_inner(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="path to the batch manifest JSON")
    ap.add_argument("--origin", required=True, help="path to the monolith module")
    ap.add_argument("--plan", action="store_true", help="report, do not write")
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.batch).read_text())
    origin_path = Path(args.origin)
    source = origin_path.read_text(encoding="utf-8")
    symbols = parse_module(source)

    try:
        moving = resolve(symbols, manifest["symbols"])
    except CarveError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if not moving:
        # plan_core can legitimately emit an empty list when no symbol survives its
        # gates; that must be a structured refusal here, not a ValueError from min().
        print("REFUSED: the batch resolves to no symbols; nothing to carve.", file=sys.stderr)
        return 14
    if any(
        isinstance(sub, ast.ImportFrom) and any(a.name == "*" for a in sub.names)
        # Walk, don't skim tree.body: a star inside a module-scope `if`/`try` guard
        # still binds its names in the module (codex R5); one inside a function is a
        # SyntaxError, so the walk cannot over-match.
        for node in ast.parse(source).body
        for sub in ast.walk(node)
    ):
        # A star import binds names no static analysis here can enumerate, so every
        # judgement downstream -- module_bound_names, importable_names, dependencies,
        # the pruner's used-set -- would be unsound: a moved body reading a
        # star-provided name would get no destination import and NameError at call.
        print(
            "REFUSED: the origin contains a top-level star import; the names it binds "
            "are not statically known, so dependency and pruning judgements would be "
            "unsound. De-star the import before carving.",
            file=sys.stderr,
        )
        return 2

    link = next(
        (p for p in (origin_path, *origin_path.parents[:3]) if p.is_symlink()), None
    )
    if link is not None:
        # resolve() follows a symlinked origin out of its lexical tree, so every
        # root-relative gate judges the WRONG repository -- and monkeypatched_symbols
        # returns empty for a root with no tests/, which silently disabled the exit-11
        # gate instead of refusing.
        print(
            f"REFUSED: {link} is a symlink, so the derived repo root and the "
            "monkeypatch scan would judge a different tree than the one being carved. "
            "Run apply against the real path.",
            file=sys.stderr,
        )
        return 11
    repo_root = origin_path.resolve().parents[2]
    patched = frozenset(monkeypatched_symbols(repo_root))
    if not (repo_root / "tests").is_dir():
        # A gate with nothing to scan must at least say so: an empty result that
        # LOOKS like "nothing is patched" is how a misplaced origin waves a
        # suite-patched batch through.
        print(
            f"note: no test suite at {repo_root / 'tests'}; the monkeypatch gate has "
            "nothing to check in this tree.",
            file=sys.stderr,
        )
    deps = dependencies(source, moving, symbols, patched)
    moved_lines = sum(s.n_lines for s in moving)
    dest_module = manifest["dest"].removesuffix(".py")
    if not all(
        seg.isidentifier() and seg.isascii() and not keyword.iskeyword(seg)
        and seg != "__init__"
        for seg in dest_module.split(".")
    ):
        # A dest like "../evil" would both splice garbage into the generated import and
        # let joinpath escape the package directory (an absolute component RESETS the
        # path). The dest names a module, so every dotted segment must be an identifier
        # -- an ASCII one: identifier-valid confusables NFKC-normalize at compile time,
        # so the generated import and the written filename would diverge and the origin
        # ImportErrors on its next load. A keyword segment ("import", "True") passes
        # isidentifier() but makes the generated import a SyntaxError. And "__init__"
        # writes a real file the alias can never reach: `from pkg import __init__`
        # binds the package's own initializer attribute, not the carved module, so
        # every eager alias AttributeErrors at import while the carve reports success.
        print(
            f"REFUSED: dest '{manifest['dest']}' is not a dotted module name; every "
            "segment must be an ASCII Python identifier that is not a keyword and "
            "not __init__.",
            file=sys.stderr,
        )
        return 13
    dest_path = origin_path.parent.joinpath(*dest_module.split(".")).with_suffix(".py")
    collisions: list[str] = []
    if dest_path.exists():
        collisions.append(
            f"{dest_path} already exists: a second batch writing the same destination "
            "erases the first batch's symbols while the origin still aliases them"
        )
    if dest_path.with_suffix("").is_dir():
        # Python's import machinery prefers the package: the carve would write a file
        # that can never be imported, while the alias points at it.
        collisions.append(
            f"{dest_path.with_suffix('')}/ is an existing package, which shadows a "
            f"sibling {dest_path.name} on import -- the carved file would be dead"
        )
    probe_dir = dest_path.parent
    while probe_dir != origin_path.parent and probe_dir != probe_dir.parent:
        if probe_dir.exists() and not probe_dir.is_dir():
            # A bare FILE occupying a parent component would make mkdir traceback
            # mid-apply instead of refusing up front (codex R5).
            collisions.append(
                f"{probe_dir} exists and is not a directory; the destination cannot "
                "be scaffolded beneath it"
            )
        sibling = probe_dir.with_suffix(".py")
        if sibling.exists() and not (probe_dir / "__init__.py").exists():
            # Scaffolding a NEW directory beside a module of the same name shadows that
            # module -- and an EXISTING namespace directory (no __init__.py) is just as
            # hazardous: the module wins over it today, but the write path drops an
            # __init__.py into the destination's parent, flipping it to a regular
            # package that takes precedence. Only a pre-existing regular package (which
            # already owned the name before this carve) passes.
            collisions.append(
                f"scaffolding or initialising {probe_dir}/ beside the existing module "
                f"{sibling.name} would shadow it on import"
            )
        probe_dir = probe_dir.parent

    relative = relative_import_users(source, moving) if "." in dest_module else []
    self_ref = self_referential_users(source, moving)
    moved_names = {s.name for s in moving}
    consumed = sorted(
        (moved_names & module_scope_refs(source, moved_names))
        | set(surviving_rebinders(source, moving))
    )
    multi = multi_binding_symbols(source, moving)
    patched_moved = sorted(moved_names & patched)
    # Enforced HERE, not only in plan_core: a hand-authored or stale manifest goes
    # straight through apply.py, and these two classes change behaviour silently.
    per_load = sorted(
        moved_names
        & (
            set(mutable_module_state(source))
            | set(environment_derived_state(source))
            | set(mutable_default_symbols(source))
        )
    )
    global_writers = global_writing_symbols(source, moving)
    forked = surviving_global_writers(source, moving)
    env_consts = sorted(moved_names & env_name_constants(source))
    self_reads = self_reading_bindings(source, moving)
    ordering = import_order_hazards(source, moving)
    floor = binding_floor(source)
    alias_line = min(s.start_line for s in moving)
    below_floor = floor == 0 or alias_line > floor

    print(f"batch:      {Path(args.batch).name}")
    print(f"symbols:    {len(moving)}  ({moved_lines:,} lines)")
    print(f"dest:       {manifest['dest']}")
    print(f"alias site: line {alias_line:,}  (binding floor {floor:,})")
    print(f"needs from origin: {len(deps)} name(s)")
    for dep in deps[:20]:
        print(f"  - {dep}")
    if len(deps) > 20:
        print(f"  ... and {len(deps) - 20} more")

    if patched_moved:
        print(f"symbols the test suite rebinds on cli: {len(patched_moved)}")
        for name in patched_moved[:10]:
            print(f"  - {name}")
    if per_load:
        print(f"per-load state (mutable, environment-derived, or def-time): {len(per_load)}")
        for name in per_load[:10]:
            print(f"  - {name}")
    if global_writers:
        print(f"bodies containing a `global` statement: {len(global_writers)}")
        for name in global_writers[:10]:
            print(f"  - {name}")
    if forked:
        print(f"moved names rebound by a surviving `global` writer: {len(forked)}")
        for name in forked[:10]:
            print(f"  - {name}")
    if env_consts:
        print(f"managed env-name constants: {len(env_consts)}")
        for name in env_consts[:10]:
            print(f"  - {name}")
    if self_reads:
        print(f"bindings that read their own name: {len(self_reads)}")
        for name in self_reads[:10]:
            print(f"  - {name}")
    if collisions:
        print(f"destination collisions: {len(collisions)}")
        for text in collisions:
            print(f"  - {text}")
    if multi:
        print(f"statements binding more than one module name: {len(multi)}")
        for name in multi[:10]:
            print(f"  - {name}")
    if ordering:
        print(f"import-time effects reordered past a survivor: {len(ordering)}")
        for name in ordering[:10]:
            print(f"  - {name}")
    if consumed:
        print(f"read by module-level code that stays behind: {len(consumed)}")
        for name in consumed[:10]:
            print(f"  - {name}")
    if self_ref:
        print(f"module-introspecting bodies (__file__/globals): {len(self_ref)}")
        for name in self_ref[:10]:
            print(f"  - {name}")
    if relative:
        print(f"relative imports in moved bodies: {len(relative)}")
        for name in relative[:10]:
            print(f"  - {name}")

    if args.plan:  # a dry run reports every refusal reason, then declines to write
        return 0
    if patched_moved:
        print(
            f"REFUSED: {len(patched_moved)} symbol(s) are rebound on `cli` by the test suite. "
            "An eager alias is a snapshot, not a forwarder, so a co-moved caller would stop "
            "seeing the patch and the test would pass while exercising nothing.",
            file=sys.stderr,
        )
        return 11
    if per_load:
        print(
            f"REFUSED: {len(per_load)} symbol(s) are per-load state -- a mutable container or "
            "a value computed from the environment at import time. cli.py is loaded more than "
            "once in-process by the SourceFileLoader fixtures, and a shared destination turns "
            "them into a singleton bound to whichever load came first.",
            file=sys.stderr,
        )
        return 10
    if global_writers:
        print(
            f"REFUSED: {len(global_writers)} symbol(s) contain a `global` statement. A moved "
            "body rebinds the DESTINATION's global while the origin's eager alias stays a "
            "snapshot, so module state forks in two. Nothing in the byte-slice model can keep "
            "two module dicts in sync; keep these in the origin module.",
            file=sys.stderr,
        )
        return 15
    if forked:
        print(
            f"REFUSED: {len(forked)} moved symbol(s) are rebound by a surviving `global` "
            "writer. The survivor rebinds the origin's alias while co-moved readers "
            "resolve the destination's stale copy -- the same forked module state, "
            "entered from the other direction. Keep the written name beside its writer.",
            file=sys.stderr,
        )
        return 15
    if env_consts:
        print(
            f"REFUSED: {len(env_consts)} symbol(s) are managed env-name constants "
            "(MINERVIT_*/TAUTLINE_* values). The env-read guard proves every managed "
            "read against a key resolvable in the SAME file; moving the constant away "
            "from its reader turns that proof into an unprovable-key finding.",
            file=sys.stderr,
        )
        return 10
    if ordering:
        print(
            f"REFUSED: {len(ordering)} symbol(s) reorder import-time effects across an "
            "effectful surviving statement -- either their own evaluation moves ahead of "
            "survivors they ran after, or they displace a pruned import's side effects to "
            "the alias site. The gates cannot see interactions routed through imported "
            "external state, so the reorder is refused. Make the batch contiguous, keep "
            "another user of the import behind, or drop these symbols.",
            file=sys.stderr,
        )
        return 12
    if multi:
        print(
            f"REFUSED: {len(multi)} symbol(s) share a statement with another module-scope "
            "binding. The span moves whole but the alias is generated from one name, so the "
            "others would vanish with nothing re-exporting them.",
            file=sys.stderr,
        )
        return 8
    if consumed:
        print(
            f"REFUSED: {len(consumed)} symbol(s) are evaluated or rebound by module-level "
            "code that stays behind. On the fail-open path an evaluating statement binds a "
            "guided stub and raises at import; a rebinding survivor (a Store, a guarded "
            "import, a conditional def) overwrites the origin's alias while co-moved "
            "callers keep the destination's original. Move the consuming statement too, "
            "or drop these from the batch.",
            file=sys.stderr,
        )
        return 7
    if self_ref:
        print(
            f"REFUSED: {len(self_ref)} symbol(s) read __file__/__name__/globals(), so their "
            "behaviour depends on which module defines them. Byte-identical relocation "
            "changes what they see. Keep them in the origin module.",
            file=sys.stderr,
        )
        return 6
    if relative:
        print(
            f"REFUSED: {len(relative)} symbol(s) contain a relative import, and the destination "
            f"'{dest_module}' sits at a different package depth, so `.` would rebind. Move them "
            "to a same-depth module, or drop them from this batch.",
            file=sys.stderr,
        )
        return 5
    if not below_floor:
        print(
            f"REFUSED: the alias would land at line {alias_line}, above _MissingFrameworkPackage "
            f"at line {floor}. The alias names that class to honour the hook fail-open contract, "
            "so emitting it here NameErrors at import and takes every hook down. Drop the "
            "symbols above the floor from this batch.",
            file=sys.stderr,
        )
        return 4
    if deps:
        print(
            "REFUSED: this batch still depends on origin-module names; "
            "carving it would need an import back-edge. Split the batch or move the deps with it.",
            file=sys.stderr,
        )
        return 3
    if self_reads:
        print(
            f"REFUSED: {len(self_reads)} moved binding(s) read the name they are "
            "binding (`VALUE = VALUE + 1`). The read resolves against the ORIGIN's "
            "prior binding, which the destination does not have -- the carved module "
            "would NameError at import. Keep these in the origin module.",
            file=sys.stderr,
        )
        return 3

    if collisions:
        # Both directions of dest/tree shadowing plus the plain already-exists case,
        # all computed up front so --plan reports them too.
        print(
            "REFUSED: the destination collides with the existing tree:\n  "
            + "\n  ".join(collisions),
            file=sys.stderr,
        )
        return 9

    new_origin, dest_source = carve(
        source, moving, dest_module, origin_path.stem, manifest.get("subject", "")
    )
    # Track scaffolding so a failed carve leaves the tree exactly as it found it. Creating a
    # directory or an __init__.py and then failing would still mutate the checkout -- and an
    # __init__.py can silently convert a namespace package into a regular one.
    created_dirs: list[Path] = []
    created_init: Path | None = None
    probe = dest_path.parent
    while not probe.exists():
        created_dirs.append(probe)
        probe = probe.parent
    # Both files or neither. A crash between the two writes leaves a committed destination
    # beside an unchanged origin -- and the collision refusal above then blocks the retry, so
    # the half-applied state is not self-healing. Stage to temporaries in the same directory
    # (so os.replace is atomic), then swap, then clean up on any failure. The scaffolding
    # writes sit INSIDE the rollback scope: an mkdir or __init__.py write that raises must
    # not leave directories behind either, or the all-or-nothing promise only covers the
    # second half of the transaction.
    dest_tmp = dest_path.with_suffix(".py.carve-tmp")
    origin_tmp = origin_path.with_suffix(".py.carve-tmp")
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if not (dest_path.parent / "__init__.py").exists():
            created_init = dest_path.parent / "__init__.py"
            created_init.write_text(
                f'"""Carved out of {origin_path.stem}.py."""\n', encoding="utf-8"
            )
        dest_tmp.write_text(dest_source, encoding="utf-8")
        origin_tmp.write_text(new_origin, encoding="utf-8")
        os.replace(dest_tmp, dest_path)
        try:
            os.replace(origin_tmp, origin_path)
        except BaseException:
            # BaseException, not OSError: a KeyboardInterrupt here would otherwise skip the
            # rollback while the finally clause still deleted the staged origin, leaving a
            # committed destination beside an untouched origin -- and the collision check then
            # blocks the retry, so that state is not self-healing.
            dest_path.unlink(missing_ok=True)
            raise
    except BaseException:
        if created_init is not None:
            created_init.unlink(missing_ok=True)
        for directory in created_dirs:  # innermost first
            try:
                directory.rmdir()
            except FileNotFoundError:
                # mkdir(parents=True) may have failed before reaching this depth, or a
                # concurrent cleanup got here first; the OUTER directories still need
                # removing, so a missing inner one must not abandon the sweep.
                continue
            except OSError:
                break  # genuinely non-empty: something else now owns this subtree
        raise
    finally:
        dest_tmp.unlink(missing_ok=True)
        origin_tmp.unlink(missing_ok=True)
    print(f"carved {moved_lines:,} lines -> {manifest['dest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
