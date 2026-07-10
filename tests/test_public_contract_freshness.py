"""Codex R2 P1: the committed public-contract manifest silently went stale across a
version bump because no test regenerates and compares it. Pin freshness here."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_contract_manifest_is_fresh():
    res = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "tautline"), "public-contract", "--check"],
        capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, f"stale public contract manifest; run bin/tautline public-contract --write\n{res.stdout}{res.stderr}"


def test_public_contract_manifest_carries_current_version():
    manifest = json.loads((ROOT / "methodology" / "public-contract-manifest.json").read_text(encoding="utf-8"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert manifest["version"] == version
