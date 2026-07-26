"""Product-dev mode: the per-checkout state reader, the boolean wrapper, and the
`product-dev-mode on|off|status` verb (state plan T1-T2).

The mode is a gitignored per-checkout `.ai-work/PRODUCT_DEV_MODE.json` resolved exactly
like the latest-code baseline. `product_dev_mode_state(root)` is the SINGLE metadata
reader (returns the validated, unexpired dict with `expiresAt`/`startedAt`, else None);
`product_dev_mode_active(root)` is its boolean wrapper (`state is not None`). Both are
pure, fail-safe reads: a missing / corrupt / wrong-schema / expired / on-false file reads
INACTIVE, so an edited or stale-but-valid JSON file can never accidentally arm the mode.

Activity is determined by the STAMPED `expiresAt`, never recomputed from a live TTL value,
so a later config change can't retroactively shorten or extend an already-open session.

The verb is the SINGLE writer. It resolves `--target` through find_adapter_root BEFORE any
file access, so a nested-subdir `on` writes the SAME `<adapter-root>/.ai-work/...json` a
repo-root reader later reads; a `--target` outside any checkout fails closed (no file).

The safety invariant across the whole feature: NEITHER reader is called from any code-safety
path (`guard_check`, `cut_release`, the version-contract predicate). The `status` verb is the
only legitimate production caller of `product_dev_mode_state`.
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
# Post the package-split flip (roadmap #11): the engine lives in cli.py; bin/tautline is a thin
# shim. Source-body scans read the engine module; CLI_PATH stays the subprocess entrypoint.
CLI_ENGINE_PATH = REPO_ROOT / "src" / "tautline_methodology" / "cli.py"
STATE_REL = ".ai-work/PRODUCT_DEV_MODE.json"
SCHEMA = "tautline-product-dev-mode/v1"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_state(root: Path, *, on=True, started=None, expires=None, schema=SCHEMA, extra=None):
    """Write a PRODUCT_DEV_MODE.json under root/.ai-work, returning its path.

    Defaults to an armed, unexpired file. Individual fields are overridable so the
    fail-safe cases can craft wrong-schema / missing-expiresAt / on-false shapes.
    """
    now = datetime.now(timezone.utc)
    started = now if started is None else started
    expires = (now + timedelta(minutes=240)) if expires is None else expires
    payload = {"schema": schema, "on": on}
    if started is not None:
        payload["startedAt"] = _iso(started)
    if expires is not None:
        payload["expiresAt"] = _iso(expires)
    if extra:
        payload.update(extra)
    path = root / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- T1: the shared reader + boolean wrapper + state file -----------------------------------


def test_state_path_is_under_ai_work(cli, tmp_path):
    """The mode file resolves under the gitignored `.ai-work/`, mirroring the latest-code
    baseline residency (never committed, never follows a branch to another checkout)."""
    _write_state(tmp_path)
    assert (tmp_path / STATE_REL).exists()
    assert cli.product_dev_mode_active(tmp_path) is True
    # The resolved path the reader uses is under .ai-work (belt-and-suspenders on residency).
    assert ".ai-work" in STATE_REL


def test_active_false_when_no_file(cli, tmp_path):
    assert cli.product_dev_mode_state(tmp_path) is None
    assert cli.product_dev_mode_active(tmp_path) is False


def test_active_true_when_on_and_unexpired(cli, tmp_path):
    _write_state(tmp_path, on=True, expires=datetime.now(timezone.utc) + timedelta(minutes=30))
    assert cli.product_dev_mode_active(tmp_path) is True


def test_active_false_after_expiry(cli, tmp_path):
    _write_state(tmp_path, on=True, expires=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert cli.product_dev_mode_active(tmp_path) is False
    assert cli.product_dev_mode_state(tmp_path) is None


def test_active_false_on_corrupt_file(cli, tmp_path):
    """A corrupt (unparseable) file reads INACTIVE -- fail-safe, no exception escapes."""
    path = tmp_path / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not valid json ", encoding="utf-8")
    assert cli.product_dev_mode_active(tmp_path) is False
    assert cli.product_dev_mode_state(tmp_path) is None


def test_active_false_on_wrong_schema(cli, tmp_path):
    _write_state(tmp_path, schema="tautline-product-dev-mode/v99")
    assert cli.product_dev_mode_active(tmp_path) is False


def test_active_false_on_missing_or_invalid_expiresat(cli, tmp_path):
    # Start from a valid armed file, then drop expiresAt entirely.
    path = _write_state(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("expiresAt", None)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.product_dev_mode_active(tmp_path) is False

    # Non-ISO / garbage expiresAt.
    payload["expiresAt"] = "not-a-timestamp"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.product_dev_mode_active(tmp_path) is False


def test_active_false_when_on_field_false(cli, tmp_path):
    """A valid, unexpired file with `on: false` never arms the mode."""
    _write_state(tmp_path, on=False, expires=datetime.now(timezone.utc) + timedelta(minutes=30))
    assert cli.product_dev_mode_active(tmp_path) is False


def test_activity_from_stamped_expiresat_not_live_ttl(cli, tmp_path):
    """Activity is read from the STAMPED expiresAt, never recomputed from startedAt + TTL.

    A file whose startedAt is far in the past (well beyond the 240-min TTL) but whose stamped
    expiresAt is still in the future reads ACTIVE -- proving the reader trusts the stamp, so a
    later TTL config change cannot retroactively shorten an already-open session.
    """
    now = datetime.now(timezone.utc)
    _write_state(
        tmp_path,
        on=True,
        started=now - timedelta(hours=48),
        expires=now + timedelta(minutes=10),
    )
    assert cli.product_dev_mode_active(tmp_path) is True

    # And the inverse: a recent startedAt but an already-past stamped expiresAt reads inactive.
    _write_state(tmp_path, on=True, started=now, expires=now - timedelta(minutes=1))
    assert cli.product_dev_mode_active(tmp_path) is False


def test_state_reader_returns_expiresat_when_active(cli, tmp_path):
    expires = datetime.now(timezone.utc) + timedelta(minutes=90)
    _write_state(tmp_path, on=True, expires=expires)
    state = cli.product_dev_mode_state(tmp_path)
    assert state is not None
    assert state.get("expiresAt") == _iso(expires)
    assert cli.product_dev_mode_active(tmp_path) is True


def test_state_reader_none_when_inactive(cli, tmp_path):
    assert cli.product_dev_mode_state(tmp_path) is None
    assert cli.product_dev_mode_active(tmp_path) is False


def test_default_ttl_is_240_minutes(cli):
    assert cli.PRODUCT_DEV_MODE_DEFAULT_TTL_MINUTES == 240


# --- The safety invariant: neither reader is read by any code-safety path -------------------


def test_mode_never_read_by_code_safety():
    """NEITHER product_dev_mode_active NOR product_dev_mode_state may be referenced inside any
    code-safety path in bin/tautline -- guard_check or cut_release. The `status` verb
    (product_dev_mode_command) is the only allowed production caller of the state reader.

    (The version-contract predicate that decides a VERSION bump is required lives in the test
    module tests/test_release_change_contract.py, not bin/tautline, so it can never reference
    these bin/tautline-internal readers; the two functions scanned here are the code-safety
    paths inside the CLI itself.)

    Enforced by scanning the source bodies of the code-safety functions for either reader symbol.
    """
    import ast

    source = CLI_ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    code_safety_names = {"guard_check", "cut_release"}
    reader_symbols = {"product_dev_mode_active", "product_dev_mode_state"}

    funcs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert code_safety_names <= set(funcs), (
        f"code-safety functions missing (renamed?): {code_safety_names - set(funcs)}"
    )

    for name in code_safety_names:
        called = {
            n.id
            for n in ast.walk(funcs[name])
            if isinstance(n, ast.Name) and n.id in reader_symbols
        }
        assert not called, (
            f"code-safety path {name}() references the product-dev-mode reader(s) {called}: "
            "the mode must NEVER be read by a code-safety path"
        )


# --- T2: the `product-dev-mode` verb (root-normalized, sole writer, public-contract) -------


def _cli_env(home: Path):
    import os

    home.mkdir(parents=True, exist_ok=True)
    return {"PATH": os.environ["PATH"], "HOME": str(home)}


def _run(args, home: Path, cwd: Path):
    return subprocess.run(
        [__import__("sys").executable, str(CLI_PATH), *args],
        cwd=str(cwd),
        env=_cli_env(home),
        text=True,
        capture_output=True,
        timeout=60,
    )


def test_verb_on_off_status(cli, tmp_path):
    """`on` arms the mode with a future expiresAt; `status` reports on + remaining TTL; `off`
    disarms. Black-box through the CLI so the whole verb path is exercised."""
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)  # a plausible adapter root
    (root / ".tautline.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "home"

    on = _run(["product-dev-mode", "on", "--target", str(root)], home, root)
    assert on.returncode == 0, on.stdout + on.stderr
    assert cli.product_dev_mode_active(root) is True

    status_on = _run(["product-dev-mode", "status", "--target", str(root)], home, root)
    assert status_on.returncode == 0, status_on.stdout + status_on.stderr
    assert "on" in status_on.stdout.lower()

    off = _run(["product-dev-mode", "off", "--target", str(root)], home, root)
    assert off.returncode == 0, off.stdout + off.stderr
    assert cli.product_dev_mode_active(root) is False

    status_off = _run(["product-dev-mode", "status", "--target", str(root)], home, root)
    assert status_off.returncode == 0
    assert "off" in status_off.stdout.lower()


def test_verb_is_sole_writer(cli, tmp_path):
    """After `on`, the state file matches the schema and validates through the reader -- the verb
    is the only thing that wrote it."""
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / ".tautline.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "home"
    _run(["product-dev-mode", "on", "--target", str(root)], home, root)
    state_file = root / STATE_REL
    assert state_file.exists()
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA
    assert payload["on"] is True
    assert "expiresAt" in payload and "startedAt" in payload


def test_verb_resolves_target_to_adapter_root(cli, tmp_path):
    """Invoked with a NESTED subdir --target, the verb writes <adapter-root>/.ai-work/...json
    (NOT <nested-subdir>/.ai-work/...), and a repo-root reader then sees it active. This is the
    round-4 finding that motivated the split."""
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / ".tautline.json").write_text("{}", encoding="utf-8")
    nested = root / "docs" / "product" / "deep"
    nested.mkdir(parents=True)
    home = tmp_path / "home"

    on = _run(["product-dev-mode", "on", "--target", str(nested)], home, root)
    assert on.returncode == 0, on.stdout + on.stderr

    assert (root / STATE_REL).exists(), "state must land at the adapter root"
    assert not (nested / STATE_REL).exists(), "no stray state file under the nested subdir"
    assert cli.product_dev_mode_active(root) is True


def test_verb_refuses_target_outside_adapter_root(cli, tmp_path):
    """A --target with no resolvable adapter root fails closed: non-zero exit, no state file."""
    outside = tmp_path / "not-a-checkout"
    outside.mkdir()
    home = tmp_path / "home"
    result = _run(["product-dev-mode", "on", "--target", str(outside)], home, outside)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (outside / STATE_REL).exists()


def test_startup_remediation_registry_partition(cli):
    """`product-dev-mode` is in EXACTLY ONE of the startup-remediation allow/block lists so the
    partition test the registry ships stays green."""
    allowed = set(cli.STARTUP_REMEDIATION_ALLOWED_COMMANDS)
    blocked = set(cli.STARTUP_REMEDIATION_BLOCKED_COMMANDS)
    assert "product-dev-mode" in (allowed | blocked)
    assert not (allowed & blocked), "no command may be in both lists"
    # An operator-convenience verb is ALLOWED (never blocked by startup remediation).
    assert "product-dev-mode" in allowed


def test_verb_public_contract_status_experimental(cli):
    """The public contract binds `product-dev-mode` experimental (mirroring maintainer-mode),
    since the sibling plans complete its behavior."""
    status = cli.public_contract_status_for_command("product-dev-mode")
    assert status["status"] == "experimental", status
