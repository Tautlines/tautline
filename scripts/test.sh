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

echo "==> [1/3] ruff lint (fast)"
ruff check bin/tautline src tests

echo "==> [2/3] mypy type-check (lenient baseline)"
mypy --config-file pyproject.toml bin/tautline src

echo "==> [3/3] pytest unit tests"
pytest

echo "all python checks passed"
