"""Every read of a Tautline-managed env var must go through util.resolve_env.

This is the guard four program plans cite as policing env-read discipline automatically. It used to
be a regex over `os.(environ.get|getenv)("MINERVIT_...")` -- a STRING-LITERAL match. Every other way
of naming the same variable walked straight past it:

    os.environ.get(SOME_ENV_CONSTANT)   # a constant -- which is how this codebase actually spells
                                        #   nearly every env read, so the guard saw almost nothing
    os.environ["MINERVIT_X"]            # subscript
    os.getenv(f"MINERVIT_{suffix}")     # computed
    os.environ.get("TAUTLINE_X")        # the OTHER managed prefix, unmatched entirely
    env = os.environ; env.get("MINERVIT_X")   # one alias away from invisible

It was passing because it was blind, and everyone had stopped looking. The scan is now AST-based,
and it is written to fail closed: a read whose key it cannot PROVE is unmanaged is a finding, not a
pass, because "I could not tell" and "it is fine" are the two answers a guard must never confuse.

Why the resolver: resolve_env aliases every MINERVIT_ setting to its TAUTLINE_ spelling and prefers
the alias. A read that skips it is a setting the operator can only reach by its legacy name -- the
rebrand half-applied, invisibly, one call site at a time.

Two escape hatches, both deliberately narrow and both audited by tests in this file:

* EXEMPT_DIRECT_READS -- names that must NEVER be aliased. Each is a process-private handoff, not a
  setting; aliasing them lets a stale shell variable outrank what this process exported into its
  own environment moments earlier. The exemption is a PROHIBITION: passing one of these to
  resolve_env is itself a failure.
* UNPROVABLE_KEY_SITES -- functions that read an env var whose NAME is data (a name the project
  configured, or the resolver's own parameter). The key cannot be resolved statically and is not a
  Tautline setting.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Everything that ships and executes. The old guard read exactly two files (bin/tautline and
# ghutil.py), so a bypass in telemetry.py -- and there was one -- was not merely undetected, it was
# out of scope.
POLICED_SOURCES = tuple(
    sorted(
        [ROOT / "bin" / "tautline", ROOT / "bin" / "minervit-methodology"]
        + list((ROOT / "src" / "minervit_methodology").glob("*.py"))
    )
)

MANAGED_PREFIXES = ("MINERVIT_", "TAUTLINE_")

# Env names read with a direct os.environ.get and never through resolve_env.
#
# resolve_env aliases every MINERVIT_ name to a TAUTLINE_ spelling and PREFERS the alias when both
# are set. That is right for operator settings and actively wrong for these, which are not settings:
# each is a private handoff a process writes into its own os.environ moments before os.execve, for
# its successor to read back. A shell-settable alias would let a stale value in the operator's
# environment outrank the one this process actually exported.
EXEMPT_DIRECT_READS = {
    # A raw FILE DESCRIPTOR NUMBER: the still-open, inheritable fd holding the launcher gate's
    # flock across the exec. A descriptor number is meaningful only inside the process it was
    # handed to. Aliased, a stale TAUTLINE_ spelling in the operator's shell would outrank it and
    # the successor would adopt a foreign descriptor (flocking whatever file occupies that number)
    # or, failing the identity check, reopen the lock file and deadlock against the lock it already
    # holds.
    "MINERVIT_METHODOLOGY_SYNC_LOCK_FD": "inherited file descriptor number; process-private",
    # Marks the same handoff. A shell-settable spelling would let an UNGATED sync write freshness
    # stamps that every other lane then trusts.
    "MINERVIT_METHODOLOGY_SYNC_GATE": "launcher-gate handoff marker; process-private",
    # The path to the single-use re-exec token this process just wrote for its successor. A stale
    # TAUTLINE_ spelling would outrank it and the successor would consume the wrong token -- and a
    # token that fails validation does not degrade, it fails the launch.
    "MINERVIT_METHODOLOGY_REEXEC_TOKEN": "single-use re-exec handoff token; process-private",
    # The session's own exec root, exported by the launcher and by the post-update re-exec, and read
    # back by the shim -- which honours the MINERVIT_ spelling and ONLY that spelling. Python reads
    # it to pin the snapshot the session is really executing. Aliased, a stale TAUTLINE_ spelling
    # would make Python pin one snapshot while the shell half of the same session execs another.
    "MINERVIT_METHODOLOGY_EXEC_ROOT": "session exec root; single-spelling handoff with the shim",
}

# Reads whose KEY is runtime data rather than a Tautline setting, so no static key exists to check
# and resolve_env has nothing to alias. Keyed by (repo-relative path, enclosing function).
UNPROVABLE_KEY_SITES = {
    (
        "src/minervit_methodology/util.py",
        "resolve_env",
    ): "this IS the resolver: its key is the caller's parameter",
    (
        "bin/tautline",
        "brand_env_pairs",
    ): "this IS the aliaser: it mirrors each MINERVIT_ key of the mapping to its TAUTLINE_ "
    "spelling, so its key is a loop variable over that mapping's own keys, not a setting it read",
    (
        "src/minervit_methodology/chat.py",
        "google_chat_webhook_url",
    ): "reads a caller-injected mapping; the key is the project's configured delivery.webhookEnv",
    (
        "src/minervit_methodology/deploy.py",
        "deployment_notification_webhook_url",
    ): "reads a caller-injected mapping; the key is the project's configured delivery.webhookEnv",
    (
        "src/minervit_methodology/deploy.py",
        "deployment_notification_ci_detected",
    ): "reads a caller-injected mapping; the keys are third-party CI markers (GITHUB_ACTIONS, ...)",
}

# .get/.pop/.setdefault all READ the value; a bare subscript in Load context does too. A subscript
# in Store/Del context is a WRITE -- exporting a variable for a child process is not a read and is
# not policed.
_READ_METHODS = ("get", "pop", "setdefault")

# An alias chain deeper than this is not something a reviewer would wave through anyway.
_MAX_BINDING_PASSES = 12

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_Func = ast.FunctionDef  # naming only; AsyncFunctionDef is handled everywhere FunctionDef is
_Scope = int  # id() of the enclosing function node, or _MODULE
_MODULE = 0


def _iter_scoped(tree: ast.Module):
    """(node, enclosing-function-scope) for every node.

    A function node is yielded in its ENCLOSING scope -- its default arguments are evaluated there,
    even though they bind names inside it.
    """
    stack: list[tuple[ast.AST, _Scope]] = [(tree, _MODULE)]
    while stack:
        node, scope = stack.pop()
        for child in ast.iter_child_nodes(node):
            yield child, scope
            stack.append((child, id(child) if isinstance(child, _FUNC_NODES) else scope))


class _EnvBindings:
    """Every name in one module that reaches the process environment, resolved per scope.

    The mapping, not just the key, has to be recognised through its aliases. The first AST version
    of this guard resolved keys rigorously and then handed them to a mapping test that understood
    exactly one spelling (`environ` as an attribute of the literal name `os`). `from os import
    environ` -- the idiom the docstring above calls "one alias away from invisible" -- walked
    straight past it, and so did eight other forms. A guard that fails closed on the key and open on
    the mapping fails open.

    So the environment is followed through every binding form that can name it:

    * `import os`, `import os as o`, `import os.path` -- the module's local name for the module
    * `from os import environ [as E]`, `from os import getenv [as g]` -- the imported name
    * `E = os.environ`, and aliases of aliases, to a fixed point
    * `(e := os.environ)` -- the walrus
    * `os.environ.copy()`, `dict(os.environ)` -- a copy still carries every managed setting
    * `base_env or os.environ`, `x if c else os.environ` -- it MIGHT be the environment, which under
      a fail-closed reading means it is treated as the environment
    * `read = os.environ.get`, `read = os.getenv` -- the bound reader
    * `helper(os.environ)` / `def helper(env=os.environ)` -- the parameter of a helper defined in
      this module, which is how chat.py, deploy.py and bin/tautline actually spell it

    Bindings are SCOPED. Names are resolved per function and inherited from enclosing scopes, never
    shared between siblings: `env` means the process environment in one function of bin/tautline and
    a JSON block loaded from a settings file in another, and a scanner that conflated the two would
    hand back a false positive for every dict in the file -- which is its own way of going blind,
    since a guard nobody believes gets routed around.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.os_names = {"os"}
        self.env_names: dict[_Scope, set[str]] = {_MODULE: set()}
        self.reader_names: dict[_Scope, set[str]] = {_MODULE: set()}
        self.parent: dict[_Scope, _Scope | None] = {_MODULE: None}
        self.functions = _unique_module_functions(tree)
        self._map_scopes(tree)
        self._seed_imports(tree)
        self._resolve(tree)

    def _map_scopes(self, tree: ast.Module) -> None:
        for node, scope in _iter_scoped(tree):
            if isinstance(node, _FUNC_NODES):
                self.parent[id(node)] = scope
                self.env_names.setdefault(id(node), set())
                self.reader_names.setdefault(id(node), set())

    def _seed_imports(self, tree: ast.Module) -> None:
        """Imports bind at the scope they appear in; `import os` inside a function is still `os`."""
        for node, scope in _iter_scoped(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "os" or alias.name.startswith("os."):
                        self.os_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module == "os":
                for alias in node.names:
                    if alias.name == "environ":
                        self.env_names[scope].add(alias.asname or alias.name)
                    elif alias.name == "getenv":
                        self.reader_names[scope].add(alias.asname or alias.name)

    def _visible(self, table: dict[_Scope, set[str]], scope: _Scope) -> set[str]:
        names: set[str] = set()
        cursor: _Scope | None = scope
        while cursor is not None:
            names |= table.get(cursor, set())
            cursor = self.parent.get(cursor)
        return names

    def is_env_mapping(self, node: ast.expr, scope: _Scope) -> bool:
        """Is this expression the process environment, or a copy of it, or possibly one?"""
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            return isinstance(node.value, ast.Name) and node.value.id in self.os_names
        if isinstance(node, ast.Name):
            return node.id in self._visible(self.env_names, scope)
        if isinstance(node, ast.NamedExpr):  # (e := os.environ).get(...)
            return self.is_env_mapping(node.value, scope)
        if isinstance(node, ast.BoolOp):  # base_env or os.environ -- it may BE os.environ
            return any(self.is_env_mapping(value, scope) for value in node.values)
        if isinstance(node, ast.IfExp):
            return self.is_env_mapping(node.body, scope) or self.is_env_mapping(node.orelse, scope)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "copy":
                return self.is_env_mapping(func.value, scope)  # os.environ.copy()
            if isinstance(func, ast.Name) and func.id == "dict" and node.args:
                return self.is_env_mapping(node.args[0], scope)  # dict(os.environ)
        return False

    def is_env_reader(self, node: ast.expr, scope: _Scope) -> bool:
        """Is this expression a callable whose first argument is an env var NAME?"""
        if isinstance(node, ast.Attribute):
            if node.attr == "getenv":
                return isinstance(node.value, ast.Name) and node.value.id in self.os_names
            if node.attr in _READ_METHODS:
                return self.is_env_mapping(node.value, scope)  # read = os.environ.get
            return False
        return isinstance(node, ast.Name) and node.id in self._visible(self.reader_names, scope)

    def _bind(self, name: str, value: ast.expr, *, read_in: _Scope, bind_in: _Scope) -> None:
        if self.is_env_mapping(value, read_in):
            self.env_names[bind_in].add(name)
        elif self.is_env_reader(value, read_in):
            self.reader_names[bind_in].add(name)

    def _bind_target(self, target: ast.expr, value: ast.expr, scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            self._bind(target.id, value, read_in=scope, bind_in=scope)

    def _bind_defaults(self, func: _Func, scope: _Scope) -> None:
        """def helper(env=os.environ) -- the default evaluates out here and binds in there."""
        args = func.args
        slots = args.posonlyargs + args.args
        # Both pairings are equal-length by construction: defaults fill the trailing slots, and the
        # grammar keeps kw_defaults aligned with kwonlyargs (padding it with None). strict=True
        # says so out loud.
        tail = slots[len(slots) - len(args.defaults):]
        for arg, default in zip(tail, args.defaults, strict=True):
            self._bind(arg.arg, default, read_in=scope, bind_in=id(func))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if default is not None:
                self._bind(arg.arg, default, read_in=scope, bind_in=id(func))

    def _bind_arguments(self, func: _Func, call: ast.Call, scope: _Scope) -> None:
        """helper(os.environ) -- the callee reads the environment under its parameter's name."""
        positional = func.args.posonlyargs + func.args.args
        for index, arg in enumerate(call.args):
            if index < len(positional):
                self._bind(positional[index].arg, arg, read_in=scope, bind_in=id(func))
        named = {a.arg for a in positional + func.args.kwonlyargs}
        for keyword in call.keywords:
            if keyword.arg in named:
                self._bind(keyword.arg, keyword.value, read_in=scope, bind_in=id(func))

    def _resolve(self, tree: ast.Module) -> None:
        """Follow the bindings to a fixed point: an alias of an alias is still an alias."""
        for _pass in range(_MAX_BINDING_PASSES):
            before = self._size()
            for node, scope in _iter_scoped(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        self._bind_target(target, node.value, scope)
                elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                    if node.value is not None:
                        self._bind_target(node.target, node.value, scope)
                elif isinstance(node, _FUNC_NODES):
                    self._bind_defaults(node, scope)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    callee = self.functions.get(node.func.id)
                    if callee is not None:
                        self._bind_arguments(callee, node, scope)
            if self._size() == before:
                return
        raise AssertionError(  # pragma: no cover - a 12-deep alias chain is its own finding
            "env alias resolution did not converge: this module aliases the environment more "
            "deeply than the guard follows, which is itself worth a look"
        )

    def _size(self) -> int:
        return sum(len(v) for v in self.env_names.values()) + sum(
            len(v) for v in self.reader_names.values()
        )


def _unique_module_functions(tree: ast.Module) -> dict[str, _Func]:
    """Functions callable by bare name, and unambiguously so.

    A name defined twice is dropped rather than guessed: binding a caller's argument into the wrong
    body is how a scanner invents a finding, and an invented finding costs exactly as much trust as
    a missed one.
    """
    seen: dict[str, list[_Func]] = {}
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODES):
            seen.setdefault(node.name, []).append(node)
    return {name: nodes[0] for name, nodes in seen.items() if len(nodes) == 1}


class _EnvReadScanner(ast.NodeVisitor):
    """Every environment READ in one module, with its key resolved when that is provable.

    Resolution is deliberately conservative. A key is proven only when it is a string literal, or a
    module-level constant assigned a string literal exactly once in the file. An f-string, a
    computed name, a parameter, or a name the module reassigns is UNPROVABLE -- and an unprovable
    key is reported as unprovable, never as safe.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.constants = _module_string_constants(tree)
        self.bindings = _EnvBindings(tree)
        self.reads: list[tuple[int, str, str | None, str]] = []
        self._names: list[str] = []
        self._scopes: list[_Scope] = [_MODULE]
        self._consumed: set[int] = set()

    # -- scope tracking (so a finding can name the function it lives in, and so a name is read in
    #    the scope it actually belongs to) --
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._names.append(node.name)
        self._scopes.append(id(node))
        self.generic_visit(node)
        self._scopes.pop()
        self._names.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    @property
    def _where(self) -> str:
        return self._names[-1] if self._names else "<module>"

    @property
    def _scope(self) -> _Scope:
        return self._scopes[-1]

    def _record(self, node: ast.AST, form: str, key_node: ast.expr | None) -> None:
        self.reads.append((getattr(node, "lineno", 0), form, self._key_of(key_node), self._where))

    def _key_of(self, key_node: ast.expr | None) -> str | None:
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            return key_node.value
        if isinstance(key_node, ast.Name):
            return self.constants.get(key_node.id)
        return None

    def _is_getattr_on_environ(self, node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and bool(node.args)
            and self.bindings.is_env_mapping(node.args[0], self._scope)
        )

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        key = node.args[0] if node.args else None
        if isinstance(func, ast.Attribute) and func.attr in _READ_METHODS:
            if self.bindings.is_env_mapping(func.value, self._scope):
                self._record(node, f"environ.{func.attr}", key)
        elif self.bindings.is_env_reader(func, self._scope):
            self._record(node, "getenv", key)
        elif self._is_getattr_on_environ(func):
            # getattr(os.environ, "get")("MINERVIT_X") -- reflection is still a read.
            self._consumed.add(id(func))
            self._record(node, "getattr(environ, ...)", key)
        if self._is_getattr_on_environ(node) and id(node) not in self._consumed:
            # The mapping escaping through reflection into something the scanner cannot follow. The
            # key is unknowable from here, so it is reported unprovable rather than waved through.
            self._record(node, "getattr(environ, ...)", None)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Load) and self.bindings.is_env_mapping(node.value, self._scope):
            self._record(node, "environ[...]", node.slice)
        self.generic_visit(node)


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level NAME = "literal", excluding any name the module ever rebinds.

    A name assigned twice cannot be resolved from one of its assignments, so it is left unprovable
    rather than guessed -- guessing is how a guard starts lying.
    """
    assignments: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        elif isinstance(node, (ast.For, ast.comprehension)):
            targets = [node.target]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            targets = [ast.Name(id=arg.arg) for arg in node.args.args + node.args.kwonlyargs]
        for target in targets:
            if isinstance(target, ast.Name):
                value = getattr(node, "value", None)
                assignments.setdefault(target.id, []).append(value)
    resolved = {}
    for name, values in assignments.items():
        if len(values) != 1:
            continue  # rebound somewhere: unprovable
        value = values[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            resolved[name] = value.value
    return resolved


def env_reads(source: str) -> list[tuple[int, str, str | None, str]]:
    """(line, form, key-or-None, enclosing function) for every env read in `source`."""
    tree = ast.parse(source)
    scanner = _EnvReadScanner(tree)
    scanner.visit(tree)
    return scanner.reads


def _findings(rel_path: str, source: str) -> list[str]:
    """Every read in one file that the policy forbids."""
    findings = []
    for line, form, key, where in env_reads(source):
        if key is None:
            if (rel_path, where) in UNPROVABLE_KEY_SITES:
                continue
            findings.append(
                f"{rel_path}:{line} {form}(<unprovable key>) in {where}() -- a key this guard "
                "cannot resolve may name a managed setting; read it through resolve_env, or "
                "declare the site in UNPROVABLE_KEY_SITES with the reason its key is data"
            )
            continue
        if not key.startswith(MANAGED_PREFIXES):
            continue
        if key in EXEMPT_DIRECT_READS:
            continue
        findings.append(
            f"{rel_path}:{line} {form}({key!r}) in {where}() -- managed env must be read through "
            "util_module().resolve_env()"
        )
    return findings


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


# --- the guard itself --------------------------------------------------------------------------


def test_no_shipped_source_bypasses_the_resolver():
    findings = []
    for path in POLICED_SOURCES:
        findings.extend(_findings(_rel(path), path.read_text(encoding="utf-8")))
    assert not findings, "\n".join(findings)


# --- the guard is not vacuous ------------------------------------------------------------------
#
# The point of failure last time was not a wrong rule, it was a rule that matched nothing. So the
# forms are pinned by construction: each bypass below is one this codebase could plausibly grow,
# and each must be CAUGHT. If a future rewrite of the scanner stops catching one of them, this test
# fails rather than the guard silently going quiet again.

BYPASS_FORMS = {
    "literal get": 'import os\ndef f():\n    return os.environ.get("MINERVIT_THING")\n',
    "literal getenv": 'import os\ndef f():\n    return os.getenv("MINERVIT_THING")\n',
    "literal subscript": 'import os\ndef f():\n    return os.environ["MINERVIT_THING"]\n',
    "tautline prefix": 'import os\ndef f():\n    return os.environ.get("TAUTLINE_THING")\n',
    "module constant": (
        'import os\nTHING = "MINERVIT_THING"\ndef f():\n    return os.environ.get(THING)\n'
    ),
    "constant subscript": (
        'import os\nTHING = "MINERVIT_THING"\ndef f():\n    return os.environ[THING]\n'
    ),
    "f-string key": 'import os\ndef f(part):\n    return os.environ.get(f"MINERVIT_{part}")\n',
    "variable key": "import os\ndef f(name):\n    return os.environ.get(name)\n",
    "computed key": (
        'import os\ndef f(part):\n    return os.environ.get("MINERVIT_" + part)\n'
    ),
    "environ alias": (
        'import os\ndef f():\n    env = os.environ\n    return env.get("MINERVIT_THING")\n'
    ),
    "alias subscript": (
        'import os\ndef f():\n    env = os.environ\n    return env["MINERVIT_THING"]\n'
    ),
    "pop": 'import os\ndef f():\n    return os.environ.pop("MINERVIT_THING", None)\n',
    "setdefault": 'import os\ndef f():\n    return os.environ.setdefault("MINERVIT_THING", "")\n',
    # The environment mapping named by IMPORT rather than by attribute. `from os import environ` is
    # the mainstream spelling of the very class the docstring above claims to have closed, and the
    # first version of this scanner could not see it: it matched `environ` only as an attribute of
    # the literal name `os`, so every form below was reported CLEAN.
    "from-import environ": (
        'from os import environ\ndef f():\n    return environ.get("MINERVIT_THING")\n'
    ),
    "from-import environ subscript": (
        'from os import environ\ndef f():\n    return environ["MINERVIT_THING"]\n'
    ),
    "from-import environ aliased": (
        'from os import environ as E\ndef f():\n    return E.get("MINERVIT_THING")\n'
    ),
    "from-import getenv": (
        'from os import getenv\ndef f():\n    return getenv("MINERVIT_THING")\n'
    ),
    "from-import getenv aliased": (
        'from os import getenv as g\ndef f():\n    return g("MINERVIT_THING")\n'
    ),
    "aliased os module": (
        'import os as o\ndef f():\n    return o.environ.get("MINERVIT_THING")\n'
    ),
    # The mapping laundered through a copy. A copy of os.environ still carries every managed
    # setting; only WRITES to it stop mattering, and writes are not what this guard polices.
    "environ copy": (
        'import os\ndef f():\n    e = os.environ.copy()\n    return e.get("MINERVIT_THING")\n'
    ),
    "dict of environ": (
        'import os\ndef f():\n    e = dict(os.environ)\n    return e["MINERVIT_THING"]\n'
    ),
    "alias of an alias": (
        'import os\nENV = os.environ\ndef f():\n    e = ENV\n    return e.get("MINERVIT_THING")\n'
    ),
    "walrus alias": (
        'import os\ndef f():\n    return (e := os.environ).get("MINERVIT_THING")\n'
    ),
    "getattr indirection": (
        'import os\ndef f():\n    return getattr(os.environ, "get")("MINERVIT_THING")\n'
    ),
    "bound reader method": (
        'import os\nread = os.environ.get\ndef f():\n    return read("MINERVIT_THING")\n'
    ),
    "bound getenv": (
        'import os\nread = os.getenv\ndef f():\n    return read("MINERVIT_THING")\n'
    ),
    # The mapping handed to a helper defined in the same module, which then reads it under a
    # parameter name. This is how chat.py and deploy.py really do it.
    "helper parameter": (
        'import os\n'
        'def helper(env):\n    return env.get("MINERVIT_THING")\n'
        "def f():\n    return helper(os.environ)\n"
    ),
    "helper default argument": (
        'import os\n'
        'def helper(env=os.environ):\n    return env.get("MINERVIT_THING")\n'
    ),
}


def test_the_guard_catches_every_bypass_form():
    missed = [
        label
        for label, source in BYPASS_FORMS.items()
        if not _findings("scratch/probe.py", source)
    ]
    assert not missed, f"the guard does not catch: {missed}"


COMPLIANT_FORMS = {
    "through the resolver": (
        'def f():\n    return util_module().resolve_env("MINERVIT_THING")\n'
    ),
    "imported resolver": (
        'from .util import resolve_env\ndef f():\n    return resolve_env("MINERVIT_THING")\n'
    ),
    "unmanaged literal": 'import os\ndef f():\n    return os.environ.get("HOME")\n',
    "unmanaged constant": (
        'import os\nHOME_ENV = "HOME"\ndef f():\n    return os.environ.get(HOME_ENV)\n'
    ),
    "exempt handoff": (
        'import os\nFD = "MINERVIT_METHODOLOGY_SYNC_LOCK_FD"\n'
        "def f():\n    return os.environ.get(FD)\n"
    ),
    "exporting a variable is not a read": (
        'import os\ndef f():\n    os.environ["MINERVIT_THING"] = "1"\n'
    ),
    "passing the mapping is not a read": (
        "import os\ndef f():\n    return helper(environ=os.environ)\n"
    ),
}


def test_the_guard_does_not_cry_wolf():
    """A guard that fires on the compliant form teaches people to route around it."""
    false_alarms = {
        label: _findings("scratch/probe.py", source)
        for label, source in COMPLIANT_FORMS.items()
        if _findings("scratch/probe.py", source)
    }
    assert not false_alarms, f"false positives: {false_alarms}"


def test_the_guard_actually_reads_the_shipped_sources():
    """A path list that has gone stale is a guard that passes by measuring nothing."""
    assert len(POLICED_SOURCES) >= 5
    for path in POLICED_SOURCES:
        assert path.is_file(), f"{path} is policed but does not exist"
    total = sum(len(env_reads(p.read_text(encoding="utf-8"))) for p in POLICED_SOURCES)
    # A floor, and a tight one. It used to be 10 against an actual 18: eight reads could have been
    # converted into a form the scanner no longer recognised and this test would still have passed,
    # which is the same "passing by measuring nothing" it was written to prevent. Reads leave this
    # count by migrating to resolve_env -- a deliberate change, which should lower the floor in the
    # same commit that makes it.
    assert total >= _EXPECTED_ENV_READS, (
        f"only {total} env reads found across the shipped sources (expected at least "
        f"{_EXPECTED_ENV_READS}) -- either reads migrated to resolve_env, in which case lower this "
        "floor deliberately, or the scanner has stopped recognising the forms this codebase uses"
    )


_EXPECTED_ENV_READS = 21

# An independent, deliberately stupid oracle: a regex that knows nothing about the AST. It exists to
# catch the exact failure that shipped once already -- a scanner that resolves KEYS rigorously and
# then hands them to a mapping test that recognises only one spelling of the mapping. A source that
# says `os.environ` (or `from os import environ`) and that the scanner reports as containing no env
# read at all is a scanner that has gone blind, and no amount of internal self-consistency will say
# so. Writes and passes of the mapping are why this asks for ONE read per naming file, not a count.
_NAMES_THE_ENVIRONMENT = re.compile(r"os\.environ|os\.getenv|from os import (?:environ|getenv)")


def test_no_source_names_the_environment_without_the_guard_seeing_a_read():
    blind = []
    for path in POLICED_SOURCES:
        text = path.read_text(encoding="utf-8")
        if _NAMES_THE_ENVIRONMENT.search(text) and not env_reads(text):
            blind.append(_rel(path))
    assert not blind, (
        f"these sources name the process environment but the scanner sees no read in them: {blind} "
        "-- the scanner is not recognising the mapping, which is how this guard went vacuous before"
    )


# --- the escape hatches are audited, not assumed ------------------------------------------------


def test_exempt_env_names_are_declared_as_constants_in_bin():
    """An exemption that names nothing real is a licence nobody asked for."""
    text = (ROOT / "bin/tautline").read_text(encoding="utf-8")
    for name in EXEMPT_DIRECT_READS:
        pattern = rf"^[A-Z0-9_]+ = \"{name}\"$"
        assert re.search(pattern, text, re.MULTILINE), (
            f"{name} is exempted from the resolver but is not defined in bin/tautline"
        )


def test_every_exemption_is_actually_used():
    """An exemption for a variable nobody reads directly is a hole waiting for a future read."""
    read_directly = set()
    for path in POLICED_SOURCES:
        for _line, _form, key, _where in env_reads(path.read_text(encoding="utf-8")):
            if key is not None:
                read_directly.add(key)
    unused = sorted(set(EXEMPT_DIRECT_READS) - read_directly)
    assert not unused, (
        f"exempted but never read directly: {unused} -- delete the exemption; if a read is added "
        "later it must arrive with its own justification, not inherit a stale one"
    )


def test_exempt_env_names_never_pass_through_the_resolver():
    """The exemption is a prohibition, not a loophole: these must never be aliased.

    Resolving one would let a TAUTLINE_-spelled shell variable override an inherited file
    descriptor, an exec token, or the session's exec root -- see EXEMPT_DIRECT_READS.
    """
    text = (ROOT / "bin/tautline").read_text(encoding="utf-8")
    for name in EXEMPT_DIRECT_READS:
        match = re.search(rf"^([A-Z0-9_]+) = \"{name}\"$", text, re.MULTILINE)
        assert match is not None
        constant = match.group(1)
        for call in (f'resolve_env("{name}"', f"resolve_env('{name}'", f"resolve_env({constant}"):
            assert call not in text, f"{name} must not be read through resolve_env"


def test_unprovable_key_sites_are_real_and_still_needed():
    """Every licence must name a function that exists and that still has an unprovable read.

    A stale entry here is exactly how the old guard rotted: a rule that no longer describes the
    code, left in place because nothing checked.
    """
    live = set()
    for path in POLICED_SOURCES:
        rel = _rel(path)
        for _line, _form, key, where in env_reads(path.read_text(encoding="utf-8")):
            if key is None:
                live.add((rel, where))
    stale = sorted(set(UNPROVABLE_KEY_SITES) - live)
    assert not stale, f"licensed but no longer reads an unprovable key: {stale}"
