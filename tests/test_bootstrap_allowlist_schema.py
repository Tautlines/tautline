"""sec-supplychain-5 (productization): the bootstrap legacy allowlist is a privilege-granting file
(every listed adapter is grandfathered past the bootstrap-evidence requirement) but previously had no
schema. It is now validated against methodology/bootstrap-legacy-allowlist-schema.json using the CLI's
own stdlib-only validator (no third-party runtime dependency), with additionalProperties:false on the
root and on each entry and required non-empty path/project/reason on every grant.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = REPO_ROOT / "adapters" / "projects" / ".bootstrap-legacy-allowlist.json"
SCHEMA = REPO_ROOT / "methodology" / "bootstrap-legacy-allowlist-schema.json"


def _allowlist():
    return json.loads(ALLOWLIST.read_text())


def _schema():
    return json.loads(SCHEMA.read_text())


def test_allowlist_conforms_to_schema(cli):
    errors = cli.schema_validation_errors(_allowlist(), _schema())
    assert errors == [], errors


def test_entry_missing_reason_is_rejected(cli):
    data = _allowlist()
    data["adapters"].append({"path": "adapters/projects/example-saas.json", "project": "X"})
    errors = cli.schema_validation_errors(data, _schema())
    assert any("reason" in e and "missing required property" in e for e in errors), errors
