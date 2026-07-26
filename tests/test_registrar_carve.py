"""Structural pins for the PR-A1 registrar carve.

The ``--help`` corpus and dispatch-map goldens prove the carve is *behavior*-neutral;
these AST assertions pin its *shape* so a later edit cannot quietly reintroduce an
inline ``add_parser`` into ``main()`` (which would drift the file back toward the
monolith the package split is dismantling). Nothing here hardcodes the segment or
subcommand count -- every number is derived from the AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# Post the package-split flip (roadmap #11): main(), dispatch_command, and every
# _register_<family>_<n> segment moved into the CLI engine module; bin/tautline is a thin shim.
# The registrar-carve shape pins scan the engine source, not the shim.
CLI_PATH = Path(__file__).resolve().parents[1] / "src" / "tautline_methodology" / "cli.py"
_SEGMENT_RE = re.compile(r"^_register_[a-z_]+_\d+$")


def _tree() -> ast.Module:
    return ast.parse(CLI_PATH.read_text(encoding="utf-8"))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no def {name}()")


def _add_parser_linenos(scope: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(scope)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
    ]


def _segment_defs(tree: ast.Module) -> list[ast.FunctionDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and _SEGMENT_RE.match(node.name)
    ]


def _segment_calls_in_main(main: ast.FunctionDef) -> list[str]:
    names = []
    for node in main.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and _SEGMENT_RE.match(node.value.func.id)
        ):
            names.append(node.value.func.id)
    return names


def test_no_inline_add_parser_remains_in_main():
    main = _func(_tree(), "main")
    assert _add_parser_linenos(main) == []


def test_every_add_parser_lives_in_a_segment_registrar():
    tree = _tree()
    segment_names = {d.name for d in _segment_defs(tree)}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
        ):
            continue
        enclosing = None
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef) and any(
                child is node for child in ast.walk(func)
            ):
                if func.name in segment_names:
                    enclosing = func.name
        assert enclosing is not None, f"add_parser at line {node.lineno} outside a segment"


def test_main_calls_match_defined_segments_in_order():
    tree = _tree()
    defined = [d.name for d in _segment_defs(tree)]
    called = _segment_calls_in_main(_func(tree, "main"))
    # Same set, same count, and called in definition order (order-preserving carve).
    assert called == defined
    assert len(defined) == len(set(defined))


def test_each_segment_takes_sub_and_registers_at_least_one_parser():
    tree = _tree()
    for seg in _segment_defs(tree):
        args = [a.arg for a in seg.args.args]
        assert args == ["sub"], (seg.name, args)
        assert _add_parser_linenos(seg), f"{seg.name} registers no parser"


def test_preserved_prologue_and_normalizations_intact():
    tree = _tree()
    main = _func(tree, "main")
    first = main.body[0]
    assert (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Call)
        and isinstance(first.value.func, ast.Name)
        and first.value.func.id == "_consume_legacy_launcher_marker"
    ), "compat-sunset marker consumption must stay main()'s first statement"
    source = CLI_PATH.read_text(encoding="utf-8")
    assert '"--write and --check are mutually exclusive"' in source
    assert 'args.command[0] == "--"' in source
    assert "return dispatch_command(args)" in source
