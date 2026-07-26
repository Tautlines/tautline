"""Shared, migration-proof AST inventory of the CLI subcommand surface.

Single source of truth for BOTH neutrality goldens (the ``--help`` corpus and the
dispatch map), so the two can never drift apart. The walker is:

* **receiver-agnostic** -- it matches ``<anything>.add_parser("<verb>", ...)``; it
  never filters on the receiver name (today ``sub`` in ``main()``; tomorrow the
  ``sub`` parameter of an in-bin ``_register_<family>_<n>`` segment, or the
  ``subparsers`` parameter of a package-resident ``register()``).
* **scope-aware** -- every function/async-function body is walked as its own scope,
  so a parser variable reused as a local (e.g. ``p``) in two different registrar
  functions never cross-links its ``add_parser`` to the wrong ``set_defaults``.

Because of those two properties a fresh pass yields the identical ``(verb, handler)``
map before the registrar carve, after it, and after every later package-split move --
which is exactly what lets the committed golden act as a behavior-neutrality ratchet.
Nothing here hardcodes a subcommand count: the count is always ``len(map)``.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
_PKG_ROOT = REPO_ROOT / "src" / "tautline_methodology"


def source_files() -> list[Path]:
    """The migration-proof file set: the monolith plus the whole package tree.

    Scanning the package too means a registrar moved into ``tautline_methodology``
    keeps contributing its verbs to the map without any change here.
    """
    files = [CLI_PATH]
    if _PKG_ROOT.is_dir():
        files.extend(sorted(_PKG_ROOT.glob("**/*.py")))
    return files


def _iter_scopes(tree: ast.AST):
    """Yield the module scope and every function scope as independent namespaces."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Descendants of ``scope`` living in ITS namespace (never crossing into a nested
    function/lambda/class scope, which ``_iter_scopes`` visits separately)."""
    out: list[ast.AST] = []

    def rec(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
            ):
                continue
            out.append(child)
            rec(child)

    rec(scope)
    return out


def _handler_name(value: ast.AST) -> str | None:
    """Terminal name of a ``func=`` value: ``Name.id`` or ``Attribute.attr``.

    Using the terminal name keeps the golden byte-identical across moves: a body
    replaced by ``<name> = _mod.<name>`` still wires ``func=<name>`` (a bare Name),
    and even ``func=_mod.<name>`` yields the same ``.attr`` string.
    """
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def build_dispatch_map(files: list[Path] | None = None) -> dict[str, str | None]:
    """Return ``{verb: handler-name}`` for every ``add_parser`` in ``files``.

    ``handler`` is ``None`` only when the AST genuinely finds a parser with no
    ``set_defaults(func=...)`` -- never a hardcoded assumption. Raises loudly on a
    non-literal verb or a duplicate verb (argparse requires uniqueness, so a
    collision is a real defect the walker must surface rather than silently drop).
    """
    if files is None:
        files = source_files()
    pairs: dict[str, str | None] = {}
    for path in files:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
        for scope in _iter_scopes(tree):
            assign_map: dict[str, str] = {}
            defaults_map: dict[str, str] = {}
            for node in _scope_nodes(scope):
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "add_parser"
                ):
                    call = node.value
                    if (
                        not call.args
                        or not isinstance(call.args[0], ast.Constant)
                        or not isinstance(call.args[0].value, str)
                    ):
                        raise ValueError(
                            f"non-literal add_parser verb at {path}:{node.lineno}"
                        )
                    verb = call.args[0].value
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assign_map[target.id] = verb
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "set_defaults"
                    and isinstance(node.func.value, ast.Name)
                ):
                    var = node.func.value.id
                    for kw in node.keywords:
                        if kw.arg == "func":
                            name = _handler_name(kw.value)
                            if name is not None:
                                defaults_map[var] = name
            for var, verb in assign_map.items():
                if verb in pairs:
                    raise ValueError(f"duplicate verb {verb!r} (second in {path})")
                pairs[verb] = defaults_map.get(var)
    return dict(sorted(pairs.items()))


def verb_inventory(files: list[Path] | None = None) -> list[str]:
    """Sorted list of every registered verb (the enumeration source of truth)."""
    return list(build_dispatch_map(files).keys())
