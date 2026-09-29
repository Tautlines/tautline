"""Standing guards that the vendor coupling cannot creep back in.

Three independent properties:

  SOLE SITE -- agent_compat.py is the only code in the tree that maps a vendor NAME (an agent
  id like "codex") to a vendor VALUE (a provider like "openai"). Enforceable from R1 and it
  must never regress.

  NO ALLOWLIST -- nothing anywhere validates a vendor against a known set. `vendor` is a
  free-form string: the framework compares two of them for inequality and does nothing else.

  NO NEW IDENTITY COMPARISONS -- the sites comparing an agent identity against a vendor literal
  are enumerated in IDENTITY_COMPARISON_BASELINE with the release that removes each. The
  scanned SET must equal the baseline: comparing counts alone is satisfied by removing one
  comparison while adding another elsewhere, which is the swap this guard exists to catch. R3
  drives both sides to zero.
"""
import ast
import re
import tempfile
from pathlib import Path

import pytest

from tautline_methodology import agent_compat

from _ast_inventory import source_files

# Provider values the shim is allowed to synthesise. Sourced from the shim itself so this guard
# cannot drift from what it guards.
VENDOR_VALUES = {seed["vendor"] for seed in agent_compat.LEGACY_AGENT_SEEDS.values()}

SHIM_FILENAME = "agent_compat.py"

IDENTITY_LITERALS = {"codex", "claude", "claude-code"}

# MEASURED at the R1 tip, not guessed. Reproduce with `_identity_literal_hits()`; it reports
# exactly these four and nothing else. (file, ENCLOSING FUNCTION, removing release) -- the middle
# element is the exact string the scanner reports, because the comparison below is literal.
IDENTITY_COMPARISON_BASELINE: set[tuple[str, str, str]] = set()
# EMPTIED BY R3.6, and asserted empty rather than deleted. Every one of these was a gate
# comparing a reviewer against the literal `codex`; they now resolve the reviewer through the
# adapter's role bindings and compare VENDORS instead. Keeping the (now empty) set and the test
# that scans against it means a new identity literal reappears as a failure rather than as a
# silently-growing allowlist -- the ratchet only holds while something still turns it.

# Documentary, not scanned: vendor-named constants and commands rather than comparisons. Each
# names the release that removes it and each gets its own targeted test in that release.
VENDOR_ARTIFACT_BASELINE = {
    ("cli.py", "implementation review manifest recorded_by gate", "R3"),
    ("cli.py", "IMPLEMENTATION_REVIEW_STAGE", "R3"),
    ("cli.py", "RUNTIME_TARGETS", "R4"),
    ("cli.py", "resolve_real_codex / fast-mode shim", "R3"),
    ("cli.py", "codex plan review command", "R3"),
}


def _enclosing_function(tree, target):
    """The name of the function containing `target`, or "<module>"."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(child is target for child in ast.walk(node)):
                return node.name
    return "<module>"


def _identity_literal_hits():
    """Every equality comparison against a vendor identity literal, in the CURRENT source.

    AST, not regex, and symmetric on purpose: a regex anchored to the right-hand side misses
    `"codex" == reviewer`, so the ratchet would stay green while the coupling was reintroduced
    with the operands swapped.

    Keyed by file and enclosing FUNCTION, not line number: a line-keyed baseline churns on every
    unrelated edit above it, and a baseline that must be updated constantly is one that gets
    rubber-stamped.
    """
    hits = []
    for path in source_files():
        if path.name == SHIM_FILENAME:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - the tree parses or the suite is already red
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                continue
            operands = [node.left, *node.comparators]
            if any(
                isinstance(operand, ast.Constant) and operand.value in IDENTITY_LITERALS
                for operand in operands
            ):
                hits.append(f"{path.name}:{_enclosing_function(tree, node)}")
    return hits


def _vendor_value_mappings(path):
    """Every place a provider name is used AS A VENDOR VALUE.

    Scanning for any string literal equal to a provider name is far too broad and fails on day
    one: `response_guard.py` has "anthropic" inside RESPONSE_GUARD_TRANSIENT_EXTERNAL_MARKERS --
    a transient-error TEXT marker matched against an error message, which maps nothing to
    anything -- and cli.py's package `keywords` list carries "claude" and "codex". A guard that
    reddens on those is not a guard: it gets weakened by whoever hits it, or it pushes an
    operational string into the compat shim where it does not belong.

    What is actually forbidden is the MAPPING: binding a provider name to a `vendor` key, or to
    a name ending in `vendor`. Match that shape.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:  # pragma: no cover
        return []
    hits = []

    def _is_vendor_literal(node):
        return isinstance(node, ast.Constant) and node.value in VENDOR_VALUES

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "vendor"
                    and _is_vendor_literal(value)
                ):
                    hits.append((value.lineno, value.value))
        if isinstance(node, ast.Assign) and _is_vendor_literal(node.value):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    key = target.slice
                    if isinstance(key, ast.Constant) and key.value == "vendor":
                        hits.append((node.lineno, node.value.value))
                elif isinstance(target, ast.Attribute) and target.attr == "vendor":
                    hits.append((node.lineno, node.value.value))
                elif isinstance(target, ast.Name) and target.id.lower().endswith("vendor"):
                    hits.append((node.lineno, node.value.value))
    return hits


def test_shim_is_the_sole_site_that_maps_a_name_to_a_vendor_value():
    offenders = []
    for path in source_files():
        if path.name == SHIM_FILENAME:
            continue
        for lineno, value in _vendor_value_mappings(path):
            offenders.append(f"{path}:{lineno} maps to vendor value {value!r}")
    assert offenders == [], (
        "a vendor value escaped the compat shim -- mapping a vendor name to a vendor value is "
        "the coupling this program removes, and agent_compat.py is its only sanctioned site:\n"
        + "\n".join(offenders)
    )


def test_a_transient_error_marker_naming_a_provider_is_not_flagged():
    """RESPONSE_GUARD_TRANSIENT_EXTERNAL_MARKERS contains "anthropic" as error-message TEXT. It
    maps nothing to anything and must not be dragged into the compat shim. Pinned so the guard
    cannot be re-broadened into a false-positive machine later."""
    source = 'MARKERS = ["anthropic", "claude api", "overloaded"]\n'
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        probe = Path(handle.name)
    assert _vendor_value_mappings(probe) == []


def test_a_real_vendor_mapping_is_flagged():
    """The guard must still catch what it exists to catch."""
    source = 'AGENT = {"vendor": "openai", "runtime": "codex"}\n'
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        probe = Path(handle.name)
    assert [value for _line, value in _vendor_value_mappings(probe)] == ["openai"]


def test_vendor_field_has_no_enum_allowlist_or_membership_check():
    """No code anywhere may validate a vendor against a known set. `vendor` is free-form."""
    pattern = re.compile(
        r"vendor\s*(?:in|not in)\s*[\[({]|"
        r"KNOWN_VENDORS|VENDOR_ALLOWLIST|SUPPORTED_VENDORS|VALID_VENDORS"
    )
    offenders = []
    for path in source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            lineno = text[: match.start()].count("\n") + 1
            offenders.append(f"{path}:{lineno}: {match.group(0)!r}")
    assert offenders == [], (
        "a vendor allowlist or membership check appeared. `vendor` is a free-form string: the "
        "framework compares two vendor strings for inequality and does nothing else with them. "
        "An adopter running Mistral registers 'mistral' and every gate must work unchanged:\n"
        + "\n".join(offenders)
    )


def test_identity_comparison_baseline_matches_the_source_exactly():
    """The ratchet, measured against the SOURCE and asserted as a SET.

    An assertion on the baseline's own length is satisfied by a constant nobody edits, and an
    assertion on counts is satisfied by removing one comparison while adding another elsewhere.
    Compare the sets, and report both drift directions by name.
    """
    hits = set(_identity_literal_hits())
    expected = {f"{path}:{context}" for path, context, _release in IDENTITY_COMPARISON_BASELINE}
    assert hits == expected, (
        "the vendor-identity comparisons in source do not match the enumerated baseline.\n"
        f"  new (not in baseline): {sorted(hits - expected)}\n"
        f"  gone (stale baseline entries): {sorted(expected - hits)}\n"
        "A NEW comparison against a vendor literal is a new instance of the coupling this "
        "program removes -- resolve the identity through `agents.role_agent_id` instead. A "
        "STALE entry must be removed in the same commit that removed its site, or the "
        "allowance silently re-inflates."
    )


def test_the_scanner_catches_a_reversed_comparison():
    """`"codex" == reviewer` must count. A right-hand-anchored regex would miss it and the
    ratchet would stay green while the coupling came back with the operands swapped."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write('def f(reviewer):\n    return "codex" == reviewer\n')
        probe = Path(handle.name)
    tree = ast.parse(probe.read_text(encoding="utf-8"))
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Compare)
        and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in n.ops)
        and any(isinstance(x, ast.Constant) and x.value in IDENTITY_LITERALS
                for x in [n.left, *n.comparators])
    ]
    assert found, "the scanner must be symmetric in operand order"


@pytest.mark.parametrize(
    "entry", sorted(IDENTITY_COMPARISON_BASELINE | VENDOR_ARTIFACT_BASELINE)
)
def test_every_baseline_entry_names_its_removing_release(entry):
    _path, _context, release = entry
    assert release in {"R2", "R3", "R4"}, entry
