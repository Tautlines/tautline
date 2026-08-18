"""An escape hatch may only be read by functions that declare they read it.

Item 70 WS3. The variables in `ESCAPE_HATCH_READERS` each disable a subsystem: sync rescue, the
snapshot store, the update policy, trust verification, the main-branch requirement. The trust-pin
RCA (2026-07-22) found a hatch being honoured somewhere nobody expected, and the failure was not
that the hatch existed -- it was that nothing could enumerate who obeyed it.

So the registry is the enumeration, and these tests are what keep it true: the reader set is
re-derived from source on every run and compared with what is declared.

The direction of the containment is deliberate. `derived` as a subset of `declared` means a NEW
reader fails, while
a declaration left behind by a deleted reader does not -- and that is the asymmetry we want, because
the walk over-approximates on purpose (see `escape_hatch_walk`). An over-wide guess costs one extra
declared line; an over-narrow one costs the registry its entire point. `test_every_declared_reader_
resolves` is what stops the declared side from accumulating fiction.
"""

import ast
import importlib

import pytest

from tautline_methodology.core.runtime import ESCAPE_HATCH_READERS
from conftest import _OPERATOR_SESSION_ENV
from escape_hatch_walk import ROOT, derive_reader_sites, toplevel_definitions

HATCHES = tuple(name for name, _ in ESCAPE_HATCH_READERS)
DECLARED = {name: set(readers) for name, readers in ESCAPE_HATCH_READERS}

# The measurement taken when this registry was authored, per hatch. Its job is non-vacuity: without
# it, a walk that silently stopped finding anything would satisfy the containment perfectly --
# the empty set is a subset of everything. A control that passes hardest when it is broken is the
# failure mode this whole program is closing, so the floor is pinned per variable, not in total.
MEASURED_BASELINE = {
    "GITHUB_COALESCE": 1,
    "GITHUB_RATE_GUARD": 1,
    "GITHUB_SERIALIZE": 2,
    "METHODOLOGY_ALLOW_FANOUT": 1,
    "WORK_PROFILE_SKIP_DEV_GATES": 1,
    "METHODOLOGY_CLI": 1,
    "METHODOLOGY_EXEC_ROOT": 3,
    "METHODOLOGY_ALLOW_MAIN_COMMIT": 1,
    "METHODOLOGY_ALLOW_NON_MAIN": 2,
    "METHODOLOGY_AVAILABLE_VERSION": 2,
    "METHODOLOGY_DISABLE_AUTO_RESCUE": 2,
    "METHODOLOGY_DISABLE_SNAPSHOT_EXEC": 3,
    "METHODOLOGY_EXEC_OVERRIDE": 1,
    "METHODOLOGY_MAINTAINER_MODE": 2,
    "METHODOLOGY_OPERATOR_CHANNEL": 1,
    "METHODOLOGY_UPDATE_PINS": 2,
    "METHODOLOGY_UPDATE_POLICY": 3,
    "METHODOLOGY_UPDATE_PROBE": 1,
    "NO_REPAIR_SESSION": 1,
    "METHODOLOGY_UPDATE_SIGNERS": 1,
}


@pytest.fixture(scope="module")
def derived():
    return derive_reader_sites(HATCHES)


def test_no_undeclared_reader_of_a_subsystem_disabling_variable(derived):
    """The headline. A new reader of a hatch must say so in the registry."""
    undeclared = {
        hatch: sorted(sites - DECLARED[hatch])
        for hatch, sites in derived.items()
        if sites - DECLARED[hatch]
    }
    assert not undeclared, (
        "these functions read an escape hatch without declaring it in ESCAPE_HATCH_READERS "
        f"(core/runtime.py): {undeclared}. Each of these variables disables a subsystem; an "
        "undeclared reader is a second off switch nobody reviewed. Declare it, or route the read "
        "through a function that already does."
    )


@pytest.mark.parametrize("hatch", HATCHES)
def test_the_walk_still_finds_the_measured_readers(derived, hatch):
    """Non-vacuity, per variable: the empty set would pass the containment check perfectly."""
    assert len(derived[hatch]) >= MEASURED_BASELINE[hatch], (
        f"the reader walk found {len(derived[hatch])} site(s) for {hatch}, below the "
        f"{MEASURED_BASELINE[hatch]} measured when this registry was authored. Either a reader was "
        "removed (lower the baseline in the same commit, with the reason) or the walk stopped "
        "seeing a form it used to resolve -- which would make every other assertion here vacuous."
    )


@pytest.mark.parametrize("hatch,readers", ESCAPE_HATCH_READERS)
def test_every_declared_reader_resolves(hatch, readers):
    """A relocation that orphans a declaration is red, not silently satisfied.

    Without this, the containment stays green forever after a rename: the derived side shrinks
    to nothing and the declared side keeps naming a function that no longer exists.
    """
    for qualified in readers:
        module_name, _, attribute = qualified.partition(":")
        if module_name.startswith("bin/"):
            # Launcher scripts are checked FIRST, whether or not an attribute follows. Testing the
            # bare-module case before this branch sent `bin/tautline` into `import_module`, which
            # can never succeed -- so a module-scope read in a launcher was detectable and
            # undeclarable at the same time. That is the THIRD instance of this class in this file,
            # after `<module>` and the launcher-function case, and it is worth naming as a class:
            # every attribution target the walk can emit must have a resolution path, or the next
            # author's only way to green is to weaken the guard (Codex v2 R1).
            source = (ROOT / module_name).read_text(encoding="utf-8")
            if not attribute:
                continue  # the script itself is the target; it exists because we just read it
            # Resolved by AST, using the SAME node types the walker attributes with. A regex over
            # the text rejected `async def` -- which the walker will happily emit, making that
            # declaration impossible -- and would accept the words `def <name>` sitting inside a
            # multiline string long after the real function was deleted. A resolver that disagrees
            # with the walker about what exists is worse than none (Codex v2 R2).
            defined = set(toplevel_definitions(ast.parse(source)))
            assert attribute in defined, (
                f"{hatch} declares {qualified}, but {module_name} defines no top-level "
                f"{attribute!r}."
            )
            continue
        if not attribute:
            # A bare module name is the declaration target for a MODULE-SCOPE read, which belongs
            # to no function. It has to resolve as itself.
            importlib.import_module(module_name)
            continue
        module = importlib.import_module(module_name)
        assert hasattr(module, attribute), (
            f"{hatch} declares {qualified}, but {module_name} has no attribute {attribute!r}. "
            "A declared reader that no longer exists makes the containment check vacuous for this "
            "variable -- re-measure and update the registry."
        )


def test_every_hatch_the_operator_launcher_scrubs_is_registered():
    """The conftest scrub and the registry cannot drift apart.

    `_OPERATOR_SESSION_ENV` is the launcher's own profile: the variables that disable whole
    subsystems, exported under BOTH spellings. Anything on that list is by definition an escape
    hatch, so anything on that list must be enumerable here.
    """
    scrubbed = {
        name.split("_METHODOLOGY_", 1)[1]
        for name in _OPERATOR_SESSION_ENV
        if "_METHODOLOGY_" in name
    }
    # Not every hatch is a METHODOLOGY_ one -- GITHUB_RATE_GUARD bypasses the API budget gate --
    # so the suffix is taken only when the prefix is actually there.
    registered = {
        hatch.split("METHODOLOGY_", 1)[1] if "METHODOLOGY_" in hatch else hatch
        for hatch in HATCHES
    }
    missing = sorted(scrubbed - registered)
    assert not missing, (
        f"the operator launcher scrubs {missing} but ESCAPE_HATCH_READERS does not list "
        "them. A variable worth scrubbing from every test session is a subsystem switch, and its "
        "readers belong in the registry."
    )


def test_the_registry_is_not_shaped_like_policy_prose():
    """Tuples, not an UPPER_CASE list-of-str -- that shape is auto-collected into the policy-phrases
    SSOT, and these are symbols. Pinned because the auto-collector fails loudly but far away."""
    assert isinstance(ESCAPE_HATCH_READERS, tuple)
    for hatch, readers in ESCAPE_HATCH_READERS:
        assert isinstance(hatch, str) and isinstance(readers, tuple)


def test_the_walk_resolves_the_two_forms_a_call_site_scan_misses(derived):
    """The finding that shaped this workstream, pinned so it cannot regress.

    A scan for `resolve_env("<name>")` call sites attributes ZERO readers to these two: maintainer
    mode is read from the config FILE under a name computed by string surgery, and snapshot-exec is
    read through a helper whose key is its own parameter. Both hatches would have shipped with an
    empty measured set and a permanently green test.
    """
    assert (
        "tautline_methodology.cli:maintainer_mode_config_value"
        in derived["METHODOLOGY_MAINTAINER_MODE"]
    )
    assert (
        "tautline_methodology.cli:methodology_snapshot_exec_disabled"
        in derived["METHODOLOGY_DISABLE_SNAPSHOT_EXEC"]
    )


def test_a_class_containing_a_reader_is_collected_as_an_attribution_target(tmp_path):
    """Methods are attributed to their CLASS, which is module-resolvable; skipping classes entirely
    would be a silent false negative.

    Scope, stated so this does not read as more than it is: this asserts the CLASS is collected as
    an attribution target. It does NOT assert that a parameterised accessor *method*
    (`Config.get(name)` forwarding to `resolve_env`) is discovered -- that form is a routed gap, not
    a covered one (Codex v2 R1, filed).
    """
    from escape_hatch_walk import _Toplevel
    import ast

    tree = ast.parse(
        "class Loader:\n"
        "    def load(self):\n"
        "        return resolve_env('MINERVIT_METHODOLOGY_DISABLE_AUTO_RESCUE')\n"
    )
    walker = _Toplevel()
    walker.visit(tree)
    assert "Loader" in walker.functions


def test_the_generated_launchers_shell_reads_are_measured(derived):
    """Codex R1: the walk was Python-only, and half these hatches are read by SHELL.

    `install_cli` and `claude_launcher_content` emit shell that reads the hatches directly, held as
    string literals an AST walk sees as opaque text. Before this, a new hatch read added to the
    generated launcher would not have failed a single test -- the registry would have looked
    comprehensive while being blind to the surface that actually runs on every session start.
    """
    assert (
        "tautline_methodology.cli:claude_launcher_content"
        in derived["METHODOLOGY_UPDATE_POLICY"]
    )
    assert "tautline_methodology.cli:install_cli" in derived["METHODOLOGY_DISABLE_SNAPSHOT_EXEC"]


def test_prose_that_merely_names_a_hatch_is_not_a_read(derived):
    """The other half of the same fix, and the reason the shell pattern is narrow.

    A first version matched any English word before the variable name, so a migration description
    reading *"...is MINERVIT_METHODOLOGY_ALLOW_NON_MAIN=1"* made `release_migration_report_data` a
    declared reader. The registry has to keep meaning "reads it" rather than "mentions it", or every
    doc string that documents a hatch dilutes it into noise.
    """
    assert (
        "tautline_methodology.cli:release_migration_report_data"
        not in derived["METHODOLOGY_ALLOW_NON_MAIN"]
    )


def test_a_keyword_form_reader_is_not_invisible():
    """`resolve_env(name="X")` has no positional args at all, so it was skipped while staying
    compliant with the shipped env-read guard -- an undeclared reader in a legal form."""
    import ast

    from escape_hatch_walk import _call_key_node

    call = ast.parse('resolve_env(name="MINERVIT_METHODOLOGY_UPDATE_POLICY")').body[0].value
    key = _call_key_node(call)
    assert isinstance(key, ast.Constant)
    assert key.value == "MINERVIT_METHODOLOGY_UPDATE_POLICY"


def test_the_release_main_break_glass_switch_is_measured(derived):
    """Codex R2, and the sharpest of its findings.

    `METHODOLOGY_ALLOW_MAIN_COMMIT` is the break-glass that lets a commit onto the release branch.
    Its shell is assembled by INTERPOLATING the constant -- `f'case "${{{CONST}:-}}" in'` -- so the
    variable name appears nowhere in the source text and a name-based scan measured zero readers for
    the single most consequential switch in the registry.
    """
    assert derived["METHODOLOGY_ALLOW_MAIN_COMMIT"] == {
        "tautline_methodology.cli:methodology_release_main_pre_commit_hook"
    }


def test_a_hatch_name_bound_to_a_local_literal_is_measured():
    """A function doing `key = "<HATCH>"; resolve_env(key)` resolved to nothing whenever any other
    function reused the name `key`, because the module-wide constant scan drops rebound names by
    design. Scoped to one function body, a literal assignment is unambiguous (Codex R2)."""
    import ast

    from escape_hatch_walk import _tainted_locals

    node = ast.parse(
        "def f():\n"
        "    key = 'MINERVIT_METHODOLOGY_UPDATE_POLICY'\n"
        "    return resolve_env(key)\n"
    ).body[0]
    assert "key" in _tainted_locals(node, set(), set(), "METHODOLOGY_UPDATE_POLICY")


# Names whose shape says "standdown" but which are not subsystem switches. Each needs a reason:
# the point of the derived inventory is that a new switch cannot be added silently, and a blanket
# exemption would give that back.
# Managed variables the launcher emitters read that are NOT subsystem switches. Each needs a
# written reason, because an exemption is a claim and a blank one silences the guard while
# asserting nothing.
# The functions that EMIT the generated launcher. Anything they read is a candidate switch, because
# that is the surface where an execution override can hide -- measured behaviour rather than name
# spelling, which missed six switches in a row.
_LAUNCHER_EMITTERS = frozenset(
    {
        "tautline_methodology.cli:claude_launcher_content",
        "tautline_methodology.cli:operator_launcher_content",
        "tautline_methodology.cli:install_cli",
    }
)

NOT_A_HATCH: dict[str, str] = {
    "CLAUDE_AUTOCOMPACT_PCT": "a threshold the launcher passes through; disables nothing",
    "CLAUDE_AUTOCOMPACT_REQUIRED": "a threshold companion, same pass-through",
    "PREPUSH_RECORDS_FILE": "where the pre-push hook writes its records; a path, not a switch",
    "SESSION_ID": "the session identifier, carried for correlation; disables nothing",
    "METHODOLOGY_CANONICAL_REPO": "names which upstream is canonical; changes WHERE sync reads, "
    "not WHETHER it runs",
    "METHODOLOGY_REPO": "the repo location, not a switch over any subsystem",
    "METHODOLOGY_REPO_ENV": "names which env var holds the repo location; data about data",
    "METHODOLOGY_REPO_PRESET": "selects a repo preset; no subsystem stands down",
    "METHODOLOGY_RESCUE_STATE_DIR": "where rescue state is written; DISABLE_AUTO_RESCUE is the switch",
    "METHODOLOGY_SNAPSHOT_STORE": "the store path; DISABLE_SNAPSHOT_EXEC is the switch",
    "SECRETS_ENV": "the secrets file path, read to source it, not to skip anything",
    "SHOW_GOAL_PROMPT": "display preference for the session banner",
    "SUNSET_SHELL_WARNED": "a once-per-shell marker so the sunset warning is not repeated",
    "SUPPRESS_SUNSET_WARNINGS": "silences a DEPRECATION NOTICE, not a control; the sunset surface "
    "still applies and nothing is bypassed",
}


def _has_written_exemption(name: str, table: dict[str, str] | None = None) -> bool:
    """An exemption counts only when it actually says something.

    Membership alone let `{"FOO": ""}` silence an inventory finding, so the guard went green because
    somebody typed a key rather than because anybody decided anything (Codex v2 R2).
    """
    reasons = NOT_A_HATCH if table is None else table
    return bool(str(reasons.get(name, "")).strip())


def test_the_registry_is_not_incomplete_on_arrival():
    """Which VARIABLES count is derived from the tree, not remembered.

    Four review rounds each named subsystem switches missing from this registry -- five in total,
    including the release-branch break-glass. Every one was found by a human-shaped reading of the
    codebase, which is exactly the enumeration method that had already failed. So the candidate set
    is now derived: any managed env name whose spelling says standdown (`DISABLE`, `ALLOW`,
    `OVERRIDE`, `GUARD`, `NO_REPAIR`, `MAINTAINER`) and which has at least one MEASURED reader must
    be registered or carry a written exemption.

    This is a TRIGGER, not a proof. It is a heuristic on the NAME, and R5 demonstrated the limit by
    naming two switches (`GITHUB_SERIALIZE`, `GITHUB_COALESCE`) carrying none of these tokens until
    the pattern was widened for them -- widening per finding is the same remembering it replaced.

    Measured, so the successor is a bounded task rather than an aspiration: 73 managed env names
    appear in POLICED_SOURCES, 63 have a measurable reader, and 17 are classified here. Classifying
    all 63 into this registry or a reasoned NOT_A_HATCH lets the heuristic be deleted and makes the
    candidate set "every managed variable that is read", which cannot miss a differently-named
    switch. Filed as `ready/2026-08-14-escape-hatch-walk-completeness/`.

    What this does close is the failure that actually happened nine times: a switch sitting in plain
    sight, named like a switch, that nobody added.
    """
    import ast as _ast
    import re
    from pathlib import Path as _Path

    from escape_hatch_walk import (
        _shell_literals,
        _shell_reader_lines,
        _sources_for,
        derive_reader_sites,
    )
    from test_env_reads_use_resolver import POLICED_SOURCES

    standdown = re.compile(r"DISABLE|ALLOW|OVERRIDE|GUARD|NO_REPAIR|MAINTAINER|SERIALIZE|COALESCE")
    names: set[str] = set()
    for path in POLICED_SOURCES:
        for match in re.finditer(
            r"\b(?:MINERVIT_|TAUTLINE_)([A-Z0-9_]+)\b", path.read_text(encoding="utf-8")
        ):
            names.add(match.group(1))
    # TWO triggers, and the second is the one that works. Name-shape found nothing for
    # METHODOLOGY_CLI or METHODOLOGY_EXEC_ROOT, both of which redirect which executable the
    # launcher runs -- six switches in a row were found by review rather than by the spelling.
    # BEHAVIOUR is the better signal: anything the launcher emitters read is a candidate, because
    # that is the surface where an execution override can hide. Adding a token per finding is the
    # remembering this guard exists to replace.
    # Read from the emitters' OWN source. Deriving reader sets for all 73 managed names answered
    # this question in 30 seconds by computing far more than it needs.
    emitter_read: set[str] = set()
    for qualified in _LAUNCHER_EMITTERS:
        module_name, _, attribute = qualified.partition(":")
        source = (
            ROOT / "src" / _Path(module_name.replace(".", "/")).with_suffix(".py")
        ).read_text(encoding="utf-8")
        node = toplevel_definitions(_ast.parse(source)).get(attribute)
        assert node is not None, (
            f"configured launcher emitter {qualified} no longer exists. Silently skipping it would "
            "leave that surface unscanned while the other emitters keep this test green -- a "
            "renamed or carved emitter would quietly stop policing its own hatches (Codex v4 R4)."
        )
        body = _ast.get_source_segment(source, node) or ""
        emitter_read.update(
            m.group(1) for m in re.finditer(r"\b(?:MINERVIT_|TAUTLINE_)([A-Z0-9_]+)\b", body)
        )
        # ...and the constant-interpolated form, which the regex above cannot see because the
        # emitted shell names a SYMBOL rather than the variable. Resolved with the same
        # constant-aware analysis the walk already uses, not a second bespoke matcher: a trigger
        # blind to a form the walk resolves is a guard that reports success while looking away
        # (Codex v4 R3).
        emitter_tree = _ast.parse(source)
        literals = _shell_literals(emitter_tree)  # parsed and indexed ONCE, not once per name
        emitter_read.update(
            name
            for name in names
            if _shell_reader_lines(literals, name, _sources_for(emitter_tree, name))
        )
    candidates = sorted({n for n in names if standdown.search(n)} | (emitter_read & names))
    assert candidates, "the inventory scan found nothing, which would make this test vacuous"

    derived = derive_reader_sites(candidates)
    missing = sorted(
        name
        for name in candidates
        if derived[name] and name not in DECLARED and not _has_written_exemption(name)
    )
    assert not missing, (
        f"these variables are named like subsystem standdowns, have measured readers, and are not "
        f"in ESCAPE_HATCH_READERS: {missing}. Register each with its measured reader set, "
        "or add it "
        "to NOT_A_HATCH with the reason it is not a subsystem switch."
    )


def test_an_exemption_without_a_reason_does_not_silence_the_inventory():
    """`NOT_A_HATCH = {"FOO": ""}` used to suppress a finding while stating nothing.

    An exemption is a CLAIM that a variable is not a subsystem switch. A blank or whitespace one
    asserts nothing and silences everything, which is the control-reports-success-while-requiring-
    nothing shape this registry exists to catch, one level up from the code it guards.
    """
    assert _has_written_exemption("FOO", {"FOO": "a real, stated reason"})
    assert not _has_written_exemption("FOO", {"FOO": ""})
    assert not _has_written_exemption("FOO", {"FOO": "   "})
    assert not _has_written_exemption("FOO", {})


def test_a_launcher_declaration_resolves_by_ast_not_by_text():
    """The resolver must agree with the walker about what exists.

    A regex rejected `async def` -- which the walker emits -- making that declaration impossible,
    and accepted the words `def name` inside a multiline string long after the function was gone.
    """
    import ast as _ast

    source = (
        'HELP = """\n'
        "def deleted_long_ago():\n"
        '    pass\n'
        '"""\n'
        "async def really_here():\n"
        "    pass\n"
    )
    defined = {
        node.name
        for node in _ast.parse(source).body
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef))
    }
    assert defined == {"really_here"}


def test_the_baseline_and_the_registry_name_the_same_hatches():
    """A registry row cannot be deleted quietly.

    `test_the_walk_still_finds_the_measured_readers` is parametrized over `HATCHES`, which is
    derived FROM the registry — so removing a row also removes its own check, and the suite stays
    green while a hatch and every one of its readers disappear. `METHODOLOGY_OPERATOR_CHANNEL` and
    `METHODOLOGY_UPDATE_PROBE` are covered by neither the launcher-scrub check nor the standdown
    name trigger, so nothing else would notice (Codex v2 R3).

    Key parity makes the baseline an independent witness: dropping a row now fails here, and
    dropping BOTH is a two-line deliberate act with a diff that says what it did.
    """
    registry = set(HATCHES)
    baseline = set(MEASURED_BASELINE)
    assert registry == baseline, (
        f"registry-only: {sorted(registry - baseline)}; "
        f"baseline-only: {sorted(baseline - registry)}"
        ". Every hatch needs a measured non-vacuity floor, and every floor needs the row it "
        "measures -- otherwise deleting a row deletes its own check."
    )


def test_a_comment_quoting_shell_is_not_a_reader(derived):
    """The shell scan reads STRING LITERALS, never raw file text.

    Attributing module-level shell matches (v2 R4) immediately turned a comment in the registry
    itself -- one that quotes `"${TAUTLINE_METHODOLOGY_UPDATE_POLICY:-}"` as an EXAMPLE -- into a
    module-level reader of that hatch. Same "mentions it, not reads it" dilution the narrow pattern
    was chosen to avoid, arriving through a different door: broadening WHERE you look undoes a
    narrow WHAT just as thoroughly.
    """
    assert "tautline_methodology.core.runtime" not in derived["METHODOLOGY_UPDATE_POLICY"]
    # ...and the real emitters are still found, so this is not passing by seeing nothing.
    assert (
        "tautline_methodology.cli:claude_launcher_content"
        in derived["METHODOLOGY_UPDATE_POLICY"]
    )


def test_a_launcher_definition_under_control_flow_is_declarable():
    """The walker and the declaration resolver share ONE definition model.

    `bin/tautline` has zero direct `Module.body` definitions -- `main` lives inside an
    `except ModuleNotFoundError` -- so a resolver reading only `tree.body` rejected every launcher
    declaration that the walk could emit. A hatch read added to `main` would have failed the
    undeclared-reader test while the declaration that fixes it failed the resolver: no valid
    registry update existed (Codex v3 R1).
    """
    import ast as _ast

    from escape_hatch_walk import ROOT as _ROOT

    launcher = _ast.parse((_ROOT / "bin" / "tautline").read_text(encoding="utf-8"))
    direct = {
        node.name
        for node in launcher.body
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef))
    }
    shared = set(toplevel_definitions(launcher))
    assert not direct, "launcher shape changed; this test's premise needs re-checking"
    assert "main" in shared, "the shared model must see definitions under module control flow"


def test_a_root_accessor_keyword_is_read_from_its_own_definition():
    """Keyword support is EXACT for the roots, because their `def` is in POLICED_SOURCES.

    `resolve_env`'s key parameter is not guessed from a list -- it is read from the function itself,
    so the walk cannot be wrong about it. This is what survived after the wrapper-side guessing was
    deleted: cover what can be measured, state what cannot.
    """
    import ast as _ast

    from escape_hatch_walk import _ROOT_KEY_PARAM, _call_key_node, derive_reader_sites

    derive_reader_sites(["METHODOLOGY_UPDATE_POLICY"])  # populates the root signatures
    assert _ROOT_KEY_PARAM.get("resolve_env") == "name", _ROOT_KEY_PARAM
    call = _ast.parse('resolve_env(name="MINERVIT_METHODOLOGY_UPDATE_POLICY")').body[0].value
    key = _call_key_node(call)
    assert isinstance(key, _ast.Constant) and key.value.endswith("UPDATE_POLICY")


def test_a_keyword_call_to_a_DERIVED_wrapper_is_a_declared_gap():
    """The stated residual, asserted so it cannot be quietly re-claimed.

    Four rounds produced nine P1s in the wrapper-keyword machinery -- a fixed name list, then "the
    first parameter", then per-wrapper index tracking -- each a narrower guess rather than a
    measurement. It contributed ZERO measured readers (27 reader sites with it and without), so it
    was deleted and the gap written down instead. This test exists so a successor sees the gap is
    deliberate, not an oversight.
    """
    import ast as _ast

    from escape_hatch_walk import _call_key_node

    call = _ast.parse('bridge(setting="MINERVIT_METHODOLOGY_UPDATE_POLICY")').body[0].value
    assert _call_key_node(call) is None


def test_an_annotated_accessor_alias_is_recognised():
    """`env_reader: Callable[..., str] = resolve_env` is an alias with a type on it. Ignoring
    AnnAssign left every call through it invisible, while the shipped resolver-discipline guard
    permits the form (Codex v3 R2)."""
    import ast as _ast

    from escape_hatch_walk import _accessor_aliases

    tree = _ast.parse(
        "from tautline_methodology.util import resolve_env\n"
        "env_reader: Callable[..., str] = resolve_env\n"
    )
    assert "env_reader" in _accessor_aliases(tree, {"resolve_env"})


def test_a_wrapper_forwarding_a_later_parameter_is_a_declared_gap():
    """Derived accessors are read at POSITION 0 and nowhere else, and the residual says so.

    Two richer versions were built and deleted. Keyword resolution for wrappers produced nine P1s;
    per-wrapper index tracking produced four more. Both contributed ZERO measured readers -- this
    codebase has exactly one derived accessor and it forwards position 0 -- so each refinement was
    machinery for a case that does not occur, and each grew surface that became its own finding.

    This test exists so the gap reads as deliberate, and so the documented claim and the code can
    only change together. A claim that outruns the code is the defect this registry exists to catch.
    """
    import ast as _ast

    from escape_hatch_walk import _call_key_node

    call = _ast.parse('bridge("", "MINERVIT_METHODOLOGY_UPDATE_POLICY")').body[0].value
    key = _call_key_node(call)
    assert isinstance(key, _ast.Constant) and key.value == "", (
        "position 0 is the documented rule; a later slot is not covered"
    )


def test_root_signatures_do_not_depend_on_test_order():
    """The map is populated on demand, so this passes alone and on any xdist worker.

    It previously filled only as a side effect of `_accessor_set`, making the assertion depend on
    whichever test ran first -- and `scripts/test.sh` runs in parallel by default.
    """
    from escape_hatch_walk import _ROOT_KEY_PARAM, _root_key_param

    _ROOT_KEY_PARAM.clear()
    assert _root_key_param("resolve_env") == "name"
