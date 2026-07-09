#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PATH="${ROOT}/.venv/bin:${PATH}" "${ROOT}/scripts/test.sh"
