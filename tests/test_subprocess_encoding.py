"""Issue #186: pre-push hook crashed on Windows with UnicodeDecodeError + NoneType.strip.

``subprocess`` text mode without an explicit ``encoding`` decodes child output with the
locale codec -- ``charmap`` (cp1252) on Windows -- so a non-ASCII byte in ``gh`` JSON
output (byte 0x90 in the field report) raised ``UnicodeDecodeError`` inside the pre-push
hook and blocked the push unconditionally. Every text-mode subprocess call that captures
output must pass ``encoding="utf-8", errors="replace"`` so decoding can never raise,
and ``run_command`` must tolerate a ``None`` stdout instead of crashing on ``.strip()``.

Two layers:

1. Functional: ``run_command`` survives child output that is invalid in ANY codec
   (0x90 is invalid UTF-8 and undefined in cp1252 -- the exact byte from the report).
2. Policy (AST, never substring matching): no text-mode capturing subprocess call in the
   engine or the src package may omit ``encoding=``.
"""

import ast
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
ENGINE_SOURCE = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
SRC_ROOT = REPO_ROOT / "src"

INVALID_BYTES_CHILD = (
    "import sys; sys.stdout.buffer.write(b'{\\x22ok\\x22: \\x22\\x90\\xff\\x22}');"
    " sys.stderr.buffer.write(b'warn \\x90')"
)


def test_run_command_survives_undecodable_child_output(cli):
    """The issue #186 crash path: gh emitted a byte the locale codec cannot decode."""
    code, out, err = cli.run_command(
        [sys.executable, "-c", INVALID_BYTES_CHILD],
        timeout=30,
    )
    assert code == 0
    # Valid UTF-8 portions must survive intact; invalid bytes become U+FFFD, never a crash.
    assert out.startswith('{"ok": "')
    assert "�" in out
    assert err.startswith("warn")


def test_run_command_strip_tolerates_none_stdout(cli):
    """Second half of the #186 traceback: NoneType.strip when a reader thread died."""

    class _DeadProc:
        returncode = 1
        stdout = None
        stderr = None

    original = cli.subprocess.run
    cli.subprocess.run = lambda *args, **kwargs: _DeadProc()
    try:
        code, out, err = cli.run_command(["gh", "api", "anything"])
    finally:
        cli.subprocess.run = original
    assert code == 1
    assert out == ""
    assert err == ""


def _call_keywords(call: ast.Call) -> dict:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _captures_output(func_name: str, keywords: dict) -> bool:
    if func_name == "check_output":
        return True

    def piped(name: str) -> bool:
        # Only PIPE means the parent decodes the stream; stderr=STDOUT merely merges
        # into stdout, and file-handle redirects never pass through a TextIOWrapper.
        value = keywords.get(name)
        return isinstance(value, ast.Attribute) and value.attr == "PIPE"

    return piped("stdout") or piped("stderr")


def _text_capture_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in {"run", "Popen", "check_output"}):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
            continue
        keywords = _call_keywords(node)
        text_mode = _is_true(keywords.get("text")) or _is_true(keywords.get("universal_newlines"))
        if not text_mode or not _captures_output(func.attr, keywords):
            continue
        if "encoding" not in keywords:
            violations.append(f"{path.name}:{node.lineno} subprocess.{func.attr}")
    return violations


def test_no_locale_dependent_subprocess_text_capture():
    sources = [ENGINE_SOURCE, *sorted(SRC_ROOT.rglob("*.py"))]
    violations = [entry for source in sources for entry in _text_capture_violations(source)]
    assert not violations, (
        "text-mode subprocess captures decode with the locale codec (charmap on Windows, "
        "issue #186); pass encoding='utf-8', errors='replace': " + ", ".join(violations)
    )
