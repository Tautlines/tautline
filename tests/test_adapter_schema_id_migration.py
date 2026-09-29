"""Schema `$id` migration compatibility (deferred implementation-review finding, Track A).

Flipping the canonical domain rewrites the `$id` of both JSON Schemas
(`methodology/adapter-schema.json`)
from the retired domain to minervit.ai. `$id` is a schema *identifier*, and nothing in this
repository resolves or pins it:

  - the CLI validates adapters with its own stdlib-only subset validator
    (`schema_validation_errors`), which implements type/properties/required/
    additionalProperties/enum/const/items/minItems/minLength/pattern/minimum/maximum/
    oneOf/allOf/if-then-else -- it has no `$ref`/`$id` resolution and makes no network call;
  - the schema is always loaded by filesystem path (`ADAPTER_SCHEMA`), never by identifier;
  - adapter documents point at the schema through `$schema`, which is either a relative path
    or the raw.githubusercontent.com URL in `PUBLIC_ADAPTER_SCHEMA_URL` -- never the `$id`.

So documents that pin the retired `$id` keep validating unchanged. These tests hold that
compatibility property in place, so a future `$ref`-resolving validator cannot silently
break adapters that still carry the old identifier.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_SCHEMA = REPO_ROOT / "methodology" / "adapter-schema.json"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"

CANONICAL_ADAPTER_SCHEMA_ID = "https://minervit.ai/schemas/adapter/v1.json"
RETIRED_ADAPTER_SCHEMA_ID = "https://minervit.com/schemas/adapter/v1.json"


def _schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schemas_declare_the_canonical_domain_id():
    # The bootstrap-legacy-allowlist schema was deleted in the 2026-08-28 process-bankruptcy
    # demolition (nothing loaded it); the adapter schema is the one shipped schema that remains.
    assert _schema(ADAPTER_SCHEMA)["$id"] == CANONICAL_ADAPTER_SCHEMA_ID


def test_adapter_pinning_the_retired_schema_id_still_validates(cli):
    """Compatibility: an adapter whose `$schema` names the pre-flip identifier is still valid."""
    adapter = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    adapter["$schema"] = RETIRED_ADAPTER_SCHEMA_ID

    errors = cli.schema_validation_errors(adapter, _schema(ADAPTER_SCHEMA))

    assert errors == [], errors


def test_adapter_pinning_the_canonical_schema_id_validates(cli):
    adapter = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    adapter["$schema"] = CANONICAL_ADAPTER_SCHEMA_ID

    errors = cli.schema_validation_errors(adapter, _schema(ADAPTER_SCHEMA))

    assert errors == [], errors


def test_generated_scaffolds_pin_the_schema_by_url_not_by_id(cli):
    """Scaffolded adapters reference the schema file, so the `$id` flip cannot reach them."""
    assert cli.PUBLIC_ADAPTER_SCHEMA_URL.startswith("https://raw.githubusercontent.com/")
    assert cli.PUBLIC_ADAPTER_SCHEMA_URL.endswith("/methodology/adapter-schema.json")

    scaffold = cli.project_scaffold("Example", "example-org/example", cli.PUBLIC_ADAPTER_SCHEMA_URL)

    assert scaffold["$schema"] == cli.PUBLIC_ADAPTER_SCHEMA_URL
