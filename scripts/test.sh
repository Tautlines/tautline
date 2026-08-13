#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "${ROOT}"
trap 'status=$?; if [ "$status" -ne 0 ]; then printf "test.sh failed at line %s: %s\n" "${BASH_LINENO[0]}" "${BASH_COMMAND}" >&2; fi; exit "$status"' EXIT

# Preflight: surface a clear, actionable message if the dev toolchain is missing,
# instead of a cryptic "ruff: command not found" mid-run.
missing=()
for tool in ruff mypy pytest; do
  command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
done
if [ "${#missing[@]}" -ne 0 ]; then
  printf 'missing dev tools: %s\ninstall the pinned toolchain with:  pip install -r requirements-dev.txt\n' "${missing[*]}" >&2
  exit 1
fi
# pytest-xdist is part of the pinned toolchain, not an optional nicety: this gate runs the WHOLE
# suite and CI runs it twice per Python leg. Probe pytest's own option table rather than importing
# xdist with a guessed interpreter, so the check follows whichever pytest is on PATH. Fail loudly
# instead of falling back to serial: a silent fallback would turn a ~16-minute regression into
# something nobody notices.
# No pipe into `grep -q` here, deliberately: grep exits on the first match, pytest then dies of
# SIGPIPE, and `set -o pipefail` reports the pipeline as FAILED even though the option was found --
# which reads as "xdist missing" on a machine that has it. Capture once, match with `case`.
#
# Match on the LONG option only. Python 3.13 changed argparse to print a short/long pair
# once instead of per-alias, so the same pinned xdist renders as `-n numprocesses,
# --numprocesses numprocesses` on 3.12 but `-n, --numprocesses numprocesses` on 3.13+.
# Probing for `-n numprocesses` therefore failed closed on every 3.13+ checkout -- telling
# the developer to install a toolchain they already had -- while CI's 3.12 leg stayed green.
pytest_help="$(pytest --help 2>/dev/null || true)"
case "${pytest_help}" in
  *"--numprocesses"*) ;;
  *)
    printf 'pytest-xdist is not installed for the pytest on PATH.\ninstall the pinned toolchain with:  pip install -r requirements-dev.txt\n' >&2
    exit 1
    ;;
esac

echo "==> [1/3] ruff lint (fast)"
ruff check bin/tautline src tests tools

echo "==> [2/3] mypy type-check (lenient baseline)"
mypy --config-file pyproject.toml bin/tautline src tools

echo "==> [3/3] pytest unit tests"
# Emit a machine-readable report so `tautline test-run` can record REAL counts instead of
# exit-code-only evidence. A stable path, not a per-run one: `test-run` copies it beside each
# record and hashes the copy, so a later run overwriting this file can never invalidate an older
# record. The directory is .ai-runs/test-runs/, which the tree digest excludes unconditionally --
# a report written during the run must not change the tree that run is recording.
# Passed via PYTEST_ADDOPTS rather than as an argument so the `pytest` line stays BARE. The
# validate-freeze contract pins `\npytest\n` to guarantee this gate runs the WHOLE suite, never a
# narrowed selection; adding a report must not cost that guarantee, and scoping the option here
# also keeps it out of every developer's ad-hoc pytest invocation.
mkdir -p "${ROOT}/.ai-runs/test-runs"
# The value is single-quoted INSIDE the variable: pytest shell-splits PYTEST_ADDOPTS, so an
# unquoted absolute path breaks the preflight on any checkout under a directory with spaces.
#
# `-n auto` goes FIRST so a developer debugging a single failure can override it from the
# environment (`PYTEST_ADDOPTS='-n 0' scripts/test.sh`) -- pytest takes the last value for -n.
# Measured on a 28-core machine: 955s serial -> ~110s parallel, same 4277 tests and the same
# junit report (tests/failures/errors/skipped all identical), so the test-run evidence chain is
# unaffected. --junitxml stays LAST because that report is mandatory evidence, not a preference.
export PYTEST_ADDOPTS="-n auto ${PYTEST_ADDOPTS:-} --junitxml='${ROOT}/.ai-runs/test-runs/latest-junit.xml'"
pytest

echo "all python checks passed"
