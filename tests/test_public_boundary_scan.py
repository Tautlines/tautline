import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
README_PUBLIC = ROOT / "README.md"
README_REFERENCE = ROOT / "docs" / "reference" / "operating-manual.md"
PLUGIN_CAPABILITY_REFERENCE = ROOT / "docs" / "reference" / "plugin-capability-catalog.md"
RISK_TIER_REFERENCE = (
    ROOT
    / "plugins"
    / "tautline-core"
    / "skills"
    / "risk-tier-autonomy"
    / "references"
    / "risk-tier-policy.md"
)
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
METHODOLOGY_BACKLOG = ROOT / "docs" / "backlog" / "methodology-backlog.md"
PUBLIC_EXPORT_MARKER = ROOT / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; its subject files are export-excluded",
)
PUBLIC_PRODUCT_DOCS = [
    ROOT / "docs" / "product" / "positioning.md",
    ROOT / "docs" / "product" / "support-sla-model.md",
]

IGNORED_PARTS = {
    ".git",
    ".superpowers",
    ".ai-runs",
    ".ai-work",
    ".ai-continuity",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
GENERIC_SURFACES = [
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    README_PUBLIC,
    README_REFERENCE,
    PLUGIN_CAPABILITY_REFERENCE,
    RISK_TIER_REFERENCE,
    CODEOWNERS,
    ROOT / ".agents" / "plugins" / "marketplace.json",
    ROOT / "bin" / "tautline",
    METHODOLOGY_BACKLOG,
    ROOT / "docs" / "governance" / "methodology-change-governance.md",
    ROOT / "docs" / "releases" / "minervit-ai-delivery-methodology.md",
    ROOT / "methodology" / "adapter-schema.json",
    ROOT / "methodology" / "canonical-rules.md",
    ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json",
    ROOT / "plugins" / "tautline-core" / "CHANGELOG.md",
]
PERSON_REFERENCE_RE = re.compile(r"\bja" + r"son\b|/Users/ja" + "son|@jrl12345", re.I)
PRODUCT_REFERENCE_RE = re.compile(r"\bexample-saas\b|example-saas-|Example SaaS", re.I)
INTERNAL_FINDING_REFERENCE_RE = re.compile(
    r"\b(?:sec|prod|arch|cross|dup|license)-[a-z0-9-]+-\d+\b"
    r"|\bMISSING-[a-z][a-z0-9-]*\b"
    r"|\bLANE-R\d+\b"
)
INTERNAL_AUDIT_REFERENCE_RE = re.compile(r"PRODUCTIZATION-AUDIT")
DOMAIN_REFERENCE_RE = re.compile(r"minervit\.(ai|dev)", re.I)


def _plugin_skill_files() -> list[Path]:
    skill_root = ROOT / "plugins" / "tautline-core" / "skills"
    return sorted(
        path
        for path in skill_root.rglob("SKILL.md")
        if path.parent.name != "example-saas-preflight"
    )


def _policy_module_files() -> list[Path]:
    return sorted((ROOT / "methodology" / "policy").rglob("*.md"))


def _reference_doc_files() -> list[Path]:
    return sorted((ROOT / "docs" / "reference").rglob("*.md"))


def _generic_surface_paths() -> list[Path]:
    # Filter to existing files: in a public release export, export-excluded
    # surfaces (for example docs/backlog/) are legitimately absent.
    return [p for p in [*GENERIC_SURFACES, *_plugin_skill_files(), *_policy_module_files()] if p.exists()]


def _shippable_public_text_paths() -> list[Path]:
    root_docs = [
        ROOT / "README.md",
        ROOT / "CODE_OF_CONDUCT.md",
        ROOT / "CHANGELOG.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        ROOT / "PRIVACY.md",
        ROOT / "TERMS.md",
        ROOT / "docs" / "releases" / "minervit-ai-delivery-methodology.md",
        ROOT / "methodology" / "adapter-schema.json",
        ROOT / "methodology" / "bootstrap-legacy-allowlist-schema.json",
        ROOT / "methodology" / "canonical-rules.md",
        ROOT / "methodology" / "policy-phrases-reference.md",
        ROOT / "methodology" / "public-contract-manifest.json",
        ROOT / "plugins" / "tautline-core" / ".codex-plugin" / "plugin.json",
        ROOT / "plugins" / "tautline-core" / ".claude-plugin" / "plugin.json",
    ]
    # Filter to existing files (see _generic_surface_paths): export-excluded
    # surfaces are legitimately absent in a public release export.
    return [p for p in [*root_docs, *_reference_doc_files(), *_plugin_skill_files(), *_policy_module_files(), *PUBLIC_PRODUCT_DOCS] if p.exists()]


def _assert_contains_all(text: str, phrases: list[str]) -> None:
    missing = [phrase for phrase in phrases if phrase not in text]
    assert missing == []


def test_repository_text_excludes_person_specific_machine_tokens():
    blocked = ("Ja" + "son", "ja" + "son", "/Users/" + "ja" + "son")
    # CODEOWNERS is a deliberate, sanctioned exception: it carries the real
    # public maintainer GitHub handle (which happens to contain this token)
    # so GitHub can actually route review requests. See
    # test_codeowners_active_lines_use_real_handle_not_placeholder for the
    # positive assertion on that handle.
    codeowners_relative = CODEOWNERS.relative_to(ROOT)
    errors = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if IGNORED_PARTS.intersection(relative.parts):
            continue
        if relative == codeowners_relative:
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in blocked:
            if token in text:
                errors.append(f"{relative}: contains {token!r}")

    assert errors == []


@private_repo_only
def test_methodology_backlog_keeps_regression_and_rca_entries():
    text = METHODOLOGY_BACKLOG.read_text(encoding="utf-8")
    required_phrases = [
        "METH-FU-BUG-BACKLOG-MANAGEMENT",
        "METH-FU-MILESTONE-CONTINUATION-CONTROLLER",
        "METH-FU-RCA-JOURNAL-PUBLICATION-ISOLATION",
        "METH-FU-REVIEW-EVIDENCE-LEDGER-AND-TIERING",
        "METH-FU-LANE-COORDINATION-TRACKED-STRICT-GATE",
        "METH-FU-FUNCTIONAL-ACCEPTANCE-HARNESS-ALIGNMENT",
        "METH-FU-IDEMPOTENT-DELIVERY-KEYS",
        "Implemented in 0.6.75 and 0.6.78",
        "Implemented in 0.6.74 and 0.6.76",
        "Implemented in 0.6.84 for active release-checkout isolation",
        "Implemented in 0.5.2 and hardened in later releases",
        "tracked implementation-review manifest",
        "strict coordination is clean when coordination artifacts are only local/untracked",
        "acceptance harness points at the wrong app",
        "A non-canonical delivery key fails before any external webhook post",
        "Publishing an RCA or session journal cannot change the branch, HEAD, dirty state, or untracked files",
        "do not ask \u201cspecs or GitHub?\u201d",
        "Define severity taxonomy",
        "Require bug fields",
        "Define tracker policy",
        "Auth, email, tenant data, security, deploy, billing, data-loss, and customer-blocking bugs default to at least `P1`",
        "After a PR is queued, merged, abandoned, or blocked, the agent runs the milestone transition command and starts the returned next action",
        "METH-FU-MID-SESSION-METHODOLOGY-CONTRACT-PINNING",
        "METH-FU-DERIVED-ARTIFACT-FRESHNESS-GATE",
        "METH-FU-MEASURED-CONTEXT-ROTATION-GUARD",
        "METH-FU-GOAL-CLOSEOUT-PENDING-REVIEW-GUARD",
    ]

    _assert_contains_all(text, required_phrases)


def test_codeowners_active_lines_use_real_handle_not_placeholder():
    # De-placeholdered CODEOWNERS: active ownership lines carry the real,
    # sanctioned maintainer handle so GitHub can actually route review
    # requests. The generic `@<org>/<methodology-maintainers-team>` pattern
    # is still documented for adopter forks, but only inside a clearly
    # marked, commented template block -- never on an active line.
    assert CODEOWNERS.exists()
    text = CODEOWNERS.read_text(encoding="utf-8")

    active_lines = [
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    active_text = "\n".join(active_lines)

    # Split to avoid tripping this file's own person-token scan on itself.
    sanctioned_handle = "@" + "ja" + "son-minervit"
    assert "@<org>/<methodology-maintainers-team>" not in active_text
    assert sanctioned_handle in active_text
    assert "@jrl12345" not in text

    # The placeholder pattern remains available as fork guidance, in a comment.
    assert "@<org>/<methodology-maintainers-team>" in text


def test_docs_product_contains_only_public_files():
    product_dir = ROOT / "docs" / "product"
    assert product_dir.is_dir()
    names = sorted(path.name for path in product_dir.iterdir() if path.is_file())
    assert names == ["positioning.md", "support-sla-model.md"]


def test_generated_graphify_output_is_not_tracked():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "graphify-out/*", "*/graphify-out/*"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""


def test_generic_methodology_surfaces_do_not_leak_private_people_or_example_product():
    assert PERSON_REFERENCE_RE.search("Reviewed by Ja" + "son.\n")
    errors = []
    for path in _generic_surface_paths():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            # CODEOWNERS is a deliberate, sanctioned exception: it must carry
            # the real public maintainer GitHub handle for GitHub to route
            # review requests, which is a required property of the file, not
            # a leak. See test_codeowners_active_lines_use_real_handle_not_placeholder.
            if path != CODEOWNERS and PERSON_REFERENCE_RE.search(line):
                errors.append(
                    f"{path.relative_to(ROOT)}:{lineno}: "
                    "generic methodology surfaces must not contain person-specific names, handles, or checkout paths"
                )
            if PRODUCT_REFERENCE_RE.search(line):
                errors.append(
                    f"{path.relative_to(ROOT)}:{lineno}: "
                    "generic methodology surfaces must not contain project-specific product references"
                )

    assert errors == []


def test_shippable_public_text_excludes_internal_audit_finding_ids():
    errors = []
    for path in _shippable_public_text_paths():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if INTERNAL_FINDING_REFERENCE_RE.search(line):
                errors.append(
                    f"{path.relative_to(ROOT)}:{lineno}: "
                    "shippable public text must not expose internal finding IDs"
                )
            if INTERNAL_AUDIT_REFERENCE_RE.search(line):
                errors.append(
                    f"{path.relative_to(ROOT)}:{lineno}: "
                    "shippable public text must not reference private productization audit files"
                )

    assert errors == []


def test_shippable_surfaces_unify_contact_domain_to_minervit_com():
    """Verify that shippable surfaces use minervit.com (not minervit.ai or minervit.dev)."""
    assert DOMAIN_REFERENCE_RE.search("contact@minervit.ai")
    errors = []
    for path in {*_generic_surface_paths(), *_shippable_public_text_paths()}:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if DOMAIN_REFERENCE_RE.search(line):
                errors.append(
                    f"{path.relative_to(ROOT)}:{lineno}: "
                    "shippable surfaces must use minervit.com (found minervit.ai or minervit.dev)"
                )

    assert errors == []
