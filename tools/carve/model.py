"""Symbol table over a monolithic Python module, for byte-slice relocation.

Every top-level statement is resolved to an exact byte span. A carve is then a
pure slice-and-concatenate: no line numbers cross a commit boundary, so the same
(base, batch) pair always recomputes the identical diff.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str  # "def" | "class" | "assign" | "import" | "other"
    start_line: int  # 1-based, inclusive; includes decorators + attached comments
    end_line: int  # 1-based, inclusive
    def_line: int  # the `def`/`class`/assignment line itself
    start_byte: int
    end_byte: int

    @property
    def n_lines(self) -> int:
        return self.end_line - self.start_line + 1


def _line_starts(source: str) -> list[int]:
    """Byte offset of the first character of each 1-based line."""
    data = source.encode("utf-8")
    starts = [0, 0]  # index 0 unused; line 1 starts at byte 0
    for i, byte in enumerate(data):
        if byte == 0x0A:
            starts.append(i + 1)
    return starts


def _target_name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign):
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        return targets[0].id if targets else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        # An annotation-only declaration (`TOKEN: str`) creates NO runtime attribute, so it
        # is not relocatable: the destination would not define it and the origin's eager
        # alias would raise AttributeError reading it back.
        return node.target.id if node.value is not None else None
    return None


def _kind(node: ast.stmt) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "def"
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return "assign"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    return "other"


def parse_module(source: str) -> list[Symbol]:
    """Top-level symbols in source order, each with an exact byte span.

    A symbol's span starts at its first decorator (not its `def`) and absorbs an
    immediately-preceding contiguous comment block, so relocating it carries its
    own documentation and leaves no orphaned comment at the deletion site.
    """
    tree = ast.parse(source)
    # split("\n"), not splitlines(): splitlines also breaks on VT/FF/NEL/U+2028,
    # which would desynchronise these indices from ast's line numbers.
    lines = source.split("\n")
    starts = _line_starts(source)
    data_len = len(source.encode("utf-8"))

    symbols: list[Symbol] = []
    prev_end = 0  # last line consumed by a previous symbol

    for node in tree.body:
        def_line = node.lineno
        start_line = def_line
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            start_line = min(start_line, min(d.lineno for d in decorators))
            # a decorator's lineno points at the expression after `@`; the `@`
            # shares that line, so no adjustment is needed.

        # Absorb an attached comment block: contiguous `#` lines directly above,
        # stopping at a blank line or at the previous symbol's territory.
        probe = start_line - 1
        while probe > prev_end and probe >= 1:
            text = lines[probe - 1].strip()
            if text.startswith("#"):
                start_line = probe
                probe -= 1
                continue
            break

        end_line = node.end_lineno or def_line
        start_byte = starts[start_line]
        end_byte = starts[end_line + 1] if end_line + 1 < len(starts) else data_len

        symbols.append(
            Symbol(
                name=_target_name(node) or f"<{_kind(node)}@{def_line}>",
                kind=_kind(node),
                start_line=start_line,
                end_line=end_line,
                def_line=def_line,
                start_byte=start_byte,
                end_byte=end_byte,
            )
        )
        prev_end = end_line

    return symbols


def adjacency_gaps(symbols: list[Symbol]) -> list[int]:
    """Lines strictly between consecutive symbols (blank or unattached comment)."""
    ordered = sorted(symbols, key=lambda s: s.start_line)
    return [
        ordered[i + 1].start_line - ordered[i].end_line - 1
        for i in range(len(ordered) - 1)
    ]
