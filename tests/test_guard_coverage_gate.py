"""Quality rec #5: guard-coverage upgrade -- real invocation + assertion + block/allow discrimination.

The previous gate was itself an FM1 specimen: ``core not in body`` passed if a guard-core *name*
appeared anywhere in the test corpus -- including a comment or a docstring. A name-drop is not a test,
so a guard could be re-defanged with the meta-gate still green (guards oscillating across releases is
this framework's highest-frequency regression class).

This gate proves, by AST analysis of the test corpus (never substring matching), that every enforcement
guard core is:

1. really INVOKED -- an actual call site ``cli.<core>(...)``, never just mentioned in prose;
2. ASSERTED -- the call's result (directly, or via a variable bound from the call) flows into an
   ``assert``; and
3. for a binary decision guard, DISCRIMINATING -- the corpus drives it to BOTH a positive outcome
   (block / non-empty / truthy / present) and a negative outcome (allow / empty / falsy / absent), so a
   no-op or over-mocked test that only ever sees one branch cannot satisfy the gate.

Plus a registration meta-test: a new function carrying an enforcement-guard name suffix cannot be added
without registering it here (so a guard can't ship with zero coverage), and every registered core must
resolve to a real function in the engine (so a rename/removal is caught, not silently un-enforced).
"""

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SOURCE = TESTS_DIR.parent / "bin" / "tautline"

# Binary decision guards: return a block/allow verdict (errors list / bool / None-or-error). Each MUST
# be shown driven to BOTH outcomes in the corpus, so a test that only ever sees one branch fails.
DECISION_GUARD_CORES = [
    "response_guard_errors",
    "response_guard_goal_boundary_errors",
    "plan_finalization_precheck_errors",
    "latest_code_command_allowed",
    "goal_boundary_claim_error",
    "schema_validation_errors",
    "verify_upstream_trust",
]
# Transform/compute cores: must be really invoked and asserted, but a single outcome is legitimate --
# they redact / count / compute a structured decision rather than gate a binary block/allow.
TRANSFORM_GUARD_CORES = [
    "context_rotation_decision",
    "redact_secrets",
    "count_live_background_runs",
]
GUARD_CORES = DECISION_GUARD_CORES + TRANSFORM_GUARD_CORES

# Function-name suffixes that denote an enforcement guard. A def matching one of these MUST be
# registered above, so a guard cannot ship with no coverage. Keep narrow: these map 1:1 to gates.
GUARD_NAME_SUFFIXES = (
    "_guard_errors",
    "_precheck_errors",
    "_boundary_errors",
    "_claim_error",
    "_command_allowed",
)


def _call_core(node: ast.AST) -> str | None:
    """If ``node`` is an ``ast.Call`` to a guard core (``core(...)`` or ``obj.core(...)``), the name."""
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
    return name if name in GUARD_CORES else None


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    return []


def _is_empty_literal(node: ast.AST) -> bool:
    """A falsy/empty constant or empty container literal -- the RHS of an 'allow' assertion."""
    if isinstance(node, ast.Constant):
        return node.value in (None, False, 0, "")
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _polarity(test: ast.AST) -> str:
    """Classify an assertion's expressed outcome as 'neg' (falsy/empty/absent) or 'pos' (else)."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return "neg"
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op = test.ops[0]
        right = test.comparators[0]
        if isinstance(op, (ast.Is, ast.Eq)):
            return "neg" if _is_empty_literal(right) else "pos"
        if isinstance(op, ast.NotIn):
            return "neg"
        # IsNot / NotEq / In / Lt / Gt / ... all assert a present/non-empty outcome.
        return "pos"
    return "pos"


def _analyze_function(fn: ast.AST) -> tuple[set[str], set[str], dict[str, set[str]]]:
    """For one function body: (cores invoked, cores asserted-on, core -> set of assert polarities)."""
    invoked: set[str] = set()
    var_core: dict[str, str] = {}
    for node in ast.walk(fn):
        core = _call_core(node)
        if core:
            invoked.add(core)
        if isinstance(node, ast.Assign):
            bound = _call_core(node.value)
            if bound:
                for target in node.targets:
                    for name in _target_names(target):
                        var_core[name] = bound
    asserted: set[str] = set()
    polarities: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assert):
            continue
        refs: set[str] = set()
        for sub in ast.walk(node.test):
            core = _call_core(sub)
            if core:
                refs.add(core)
            if isinstance(sub, ast.Name) and sub.id in var_core:
                refs.add(var_core[sub.id])
        if not refs:
            continue
        pol = _polarity(node.test)
        for core in refs:
            asserted.add(core)
            polarities.setdefault(core, set()).add(pol)
    return invoked, asserted, polarities


def _corpus() -> tuple[set[str], set[str], dict[str, set[str]]]:
    invoked: set[str] = set()
    asserted: set[str] = set()
    polarities: dict[str, set[str]] = {}
    self_name = Path(__file__).name
    for path in TESTS_DIR.glob("test_*.py"):
        if path.name == self_name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                i, a, pol = _analyze_function(node)
                invoked |= i
                asserted |= a
                for core, pols in pol.items():
                    polarities.setdefault(core, set()).update(pols)
    return invoked, asserted, polarities


def test_guard_cores_registered():
    """No enforcement-guard def may go unregistered; no registered core may have a dangling name."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    dangling = [core for core in GUARD_CORES if core not in defined]
    assert not dangling, f"registered guard cores with no engine function (renamed/removed?): {dangling}"
    unregistered = sorted(
        name for name in defined if name.endswith(GUARD_NAME_SUFFIXES) and name not in GUARD_CORES
    )
    assert not unregistered, (
        "enforcement-guard functions not registered in GUARD_CORES -- a guard cannot ship uncovered; "
        f"add to the right list or rename: {unregistered}"
    )


def test_every_guard_core_is_really_invoked():
    invoked, _, _ = _corpus()
    missing = [core for core in GUARD_CORES if core not in invoked]
    assert not missing, f"guard cores never invoked by a real call site (a name-drop is not a test): {missing}"


def test_every_guard_core_is_asserted():
    _, asserted, _ = _corpus()
    missing = [core for core in GUARD_CORES if core not in asserted]
    assert not missing, f"guard cores invoked but whose result never flows into an assert: {missing}"


def test_decision_guards_show_block_and_allow():
    _, _, polarities = _corpus()
    gaps = {}
    for core in DECISION_GUARD_CORES:
        have = polarities.get(core, set())
        if {"pos", "neg"} - have:
            gaps[core] = sorted(have)
    assert not gaps, (
        "decision guards not exercised to BOTH a block and an allow outcome (a one-branch test does "
        f"not prove the guard discriminates) -- have only: {gaps}"
    )
