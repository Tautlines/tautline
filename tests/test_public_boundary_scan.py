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
    # Local agent-session state (worktrees of OTHER branches live under
    # .claude/worktrees): never tracked, never exported, absent in CI. Scanning
    # it makes this suite's verdict depend on which sessions ran on the machine
    # -- checkouts of historical branches legitimately contain text these rules
    # now ban.
    ".claude",
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
CANONICAL_DOMAIN = "minervit.ai"
RETIRED_DOMAIN_RE = re.compile(r"minervit\.(com|dev)", re.I)


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


def test_ignored_local_state_dirs_are_never_tracked():
    """.claude is exempt from the text sweeps ONLY because it is local,
    untracked session state (worktrees of other branches). If anything under
    it ever became tracked, the exemption would hide shipped text from the
    scan -- pin the invariant the exemption rests on."""
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", ".claude"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout.strip() == "", (
        "files under .claude/ are tracked; either untrack them or remove "
        "'.claude' from IGNORED_PARTS so the boundary scan sees them"
    )


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
    assert names == ["README.md", "positioning.md", "support-sla-model.md"]


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


STALE_ADAPTER_DRIFT_CATCH_ALL = "refusing to start Claude with adapter drift"
# Historical, dated design-history snapshots (this design's own planning-round archive) and the
# reader-facing changelog's past entries are allowed to quote the retired catch-all message while
# describing what it replaced; every other tracked surface -- the launcher template itself, docs,
# and policy/reference text -- must not carry it (0.8.9 startup remediation: T4 replaced the
# catch-all with the truthful `methodology_status_blocking` refusal; see
# docs/reference/startup-remediation.md).
STALE_ADAPTER_DRIFT_EXEMPT_PATHS = {
    ROOT / "CHANGELOG.md",
    # This scanner's own source necessarily quotes the retired string to check for it.
    Path(__file__).resolve(),
}
STALE_ADAPTER_DRIFT_EXEMPT_DIRS = {
    ROOT / "docs" / "superpowers" / "plans",
    ROOT / "docs" / "releases",
    ROOT / "docs" / "productization",
}


def test_repository_text_excludes_retired_adapter_drift_catch_all_refusal():
    errors = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if IGNORED_PARTS.intersection(relative.parts):
            continue
        if not path.is_file():
            continue
        if path in STALE_ADAPTER_DRIFT_EXEMPT_PATHS:
            continue
        if any(exempt_dir in path.parents for exempt_dir in STALE_ADAPTER_DRIFT_EXEMPT_DIRS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if STALE_ADAPTER_DRIFT_CATCH_ALL in text:
            errors.append(f"{relative}: still contains the retired catch-all refusal string")

    assert errors == []


# Historical records keep the retired domain verbatim -- they document what past
# releases did, and rewriting them would falsify the record:
#   - migration JSONs and archived changelogs (directory level),
#   - the frozen release-note string literals in bin/tautline for the 0.6.254
#     domain unification (line level; their exact wording is asserted by
#     tests/test_release_tracks_and_migrations.py). Any OTHER retired-domain line
#     in bin/tautline is a live surface and still fails.
RETIRED_DOMAIN_RECORD_DIRS = {
    ROOT / "docs" / "releases" / "migrations",
    ROOT / "docs" / "productization" / "archive",
}
RETIRED_DOMAIN_RELEASE_NOTE_RE = re.compile(
    r"now use minervit\.com as the single canonical contact domain", re.I
)
# The enforcement surface itself. tests/ ships, but it is machinery, not a contact
# surface: this file has to WRITE the banned strings in order to ban them, and the
# migration tests assert the historical 0.6.254 release-note wording verbatim.
# Banning the retired domain here would ban the ban.
DOMAIN_ENFORCEMENT_DIRS = {ROOT / "tests"}
# Shipped assets the domain scan cannot read as text.
DOMAIN_SCAN_BINARY_SUFFIXES = {
    ".gif", ".ico", ".jpeg", ".jpg", ".pdf", ".png", ".woff", ".woff2", ".zip",
}
# What a directory exemption is allowed to actually contain -- see
# test_retired_domain_exemptions_are_justified_by_what_they_ship. A record directory may ship only
# versioned release records (docs/releases/migrations/0.6.254.json and friends); an enforcement
# directory may ship only test machinery (modules and their fixtures).
VERSIONED_RECORD_FILENAME_RE = re.compile(r"^\d+\.\d+\.\d+\.json$")

# Shipped, reader-facing surfaces that carry contact information (or would, if someone added a
# contact line). Every one of them is tracked, exported, and covered by no exemption, so a retired
# domain planted in any of them MUST be reported. They are the canaries for an over-broad
# exemption: the plant is injected at the file's REAL repo path, so _is_historical_domain_record()
# is evaluated against the true in-ROOT path it would see in production. Planting into a tmp_path
# copy instead evaluates the exemption predicate against a path outside ROOT, where no exemption
# directory can ever match -- which makes the check inert and lets the exemption list be widened
# until the scan covers nothing.
DOMAIN_SCAN_CANARY_RELATIVE_PATHS = (
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "PRIVACY.md",
    "README.md",
    "ROADMAP.md",
    "SECURITY.md",
    "TERMS.md",
    # The CLI engine (cli.py) is the one canary with a line-level exemption (the frozen 0.6.254
    # release note), so it also pins that exemption: a planted contact line is not the release note
    # and must still fail. Post the flip the release note lives in cli.py, not the shim.
    "src/tautline_methodology/cli.py",
    "docs/README.md",
    "docs/product/positioning.md",
    "docs/product/support-sla-model.md",
    "docs/reference/operating-manual.md",
    "methodology/canonical-rules.md",
    "plugins/tautline-core/CHANGELOG.md",
)
PLANTED_RETIRED_DOMAIN_LINE = "- Support: support@" + "minervit.com"

# Swept surface -> strings that must be PRESENT. The ban alone is satisfied by a
# deleted or mistyped contact line, so every file swept in the domain flip also
# has to positively carry its canonical-domain reference.
CANONICAL_DOMAIN_REQUIRED_STRINGS: dict[Path, tuple[str, ...]] = {
    README_PUBLIC: ("hello@minervit.ai", "https://minervit.ai"),
    ROOT / "CODE_OF_CONDUCT.md": ("conduct@minervit.ai",),
    ROOT / "SECURITY.md": ("security@minervit.ai",),
    ROOT / "docs" / "product" / "support-sla-model.md": ("security@minervit.ai",),
    ROOT / ".claude-plugin" / "marketplace.json": ("hello@minervit.ai",),
    ROOT / "methodology" / "adapter-schema.json": (
        "https://minervit.ai/schemas/adapter/v1.json",
    ),
    ROOT / "methodology" / "bootstrap-legacy-allowlist-schema.json": (
        "https://minervit.ai/schemas/bootstrap-legacy-allowlist/v1.json",
    ),
    ROOT / "docs" / "assets" / "demo.tape": ("demo@minervit.ai",),
}


def _shipped_paths(cli) -> list[Path]:
    """Every file the public release actually SHIPS, derived from the CLI's own export rules."""
    return sorted(path for path, _rel in cli.public_release_export_files(ROOT) if path.is_file())


def _domain_scan_paths(cli) -> list[Path]:
    """Every text file the public release actually SHIPS.

    Derived from the CLI's own export rules (public_release_export_files, which applies
    PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES) rather than from a hand-maintained allowlist. A hand
    list only ever covers a SUBSET of the shipped surface: GOVERNANCE.md, ROADMAP.md and
    docs/README.md are all tracked, all exported, and none of them was on it -- so
    `support@minervit.com` in any of them would have published the retired domain to the public
    repo with scripts/test.sh fully green. That is precisely the class of regression this ban
    exists to prevent, so the scan set has to be the ship set.
    """
    return [
        path
        for path in _shipped_paths(cli)
        if path.suffix.lower() not in DOMAIN_SCAN_BINARY_SUFFIXES
    ]


def _is_historical_domain_record(path: Path, line: str) -> bool:
    if any(record_dir in path.parents for record_dir in RETIRED_DOMAIN_RECORD_DIRS):
        return True
    if any(enforcement_dir in path.parents for enforcement_dir in DOMAIN_ENFORCEMENT_DIRS):
        return True
    # Post the package-split flip (roadmap #11): the 0.6.254 release-note literal moved with the
    # engine body into cli.py; bin/tautline is now a thin shim carrying no release notes.
    if path == ROOT / "src" / "tautline_methodology" / "cli.py":
        return bool(RETIRED_DOMAIN_RELEASE_NOTE_RE.search(line))
    return False


def _domain_scan_label(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _retired_domain_offenders(paths, *, overrides: dict[Path, str] | None = None) -> list[str]:
    """Run the real scan over `paths`, reading `overrides[path]` instead of the file's own bytes.

    `overrides` is how a plant is tested without writing to the repo: the scanned CONTENT is
    substituted, but the PATH stays the real in-ROOT path, so _is_historical_domain_record() sees
    exactly the path it sees in production and an over-broad exemption cannot hide behind a
    tmp_path copy that no exemption directory could ever match.
    """
    overrides = overrides or {}
    offenders = []
    for path in paths:
        if path in overrides:
            text = overrides[path]
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if not RETIRED_DOMAIN_RE.search(line):
                continue
            if _is_historical_domain_record(path, line):
                continue
            offenders.append(
                f"{_domain_scan_label(path)}:{lineno}: "
                f"shippable surfaces must use {CANONICAL_DOMAIN} "
                "(found a retired minervit.com or minervit.dev reference)"
            )
    return offenders


def test_shippable_surfaces_unify_contact_domain_to_minervit_ai(cli):
    """Verify that shippable surfaces use minervit.ai (not minervit.com or minervit.dev)."""
    assert RETIRED_DOMAIN_RE.search("contact@minervit.com")
    assert RETIRED_DOMAIN_RE.search("contact@minervit.dev")

    assert _retired_domain_offenders(_domain_scan_paths(cli)) == []


def _plant_retired_domain(text: str) -> tuple[str, int]:
    """Append the banned contact line to `text`.

    Returns the new text and the planted line's number.
    """
    body = text.rstrip("\n")
    return f"{body}\n{PLANTED_RETIRED_DOMAIN_LINE}\n", len(body.splitlines()) + 1


def test_domain_scan_reports_a_retired_domain_planted_in_any_shipped_file(cli):
    """The ban must cover the whole shipped surface, not a hand-maintained subset of it.

    GOVERNANCE.md, ROADMAP.md and docs/README.md are tracked and exported (none matches
    PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES), and the old hand list scanned none of them.

    The plant is injected at each canary's REAL repo path (content substituted in memory, nothing
    written to disk), so the scan resolves exemptions against the true in-ROOT path. That is what
    makes this test bite: widen an exemption -- say add `ROOT / "docs"` to
    RETIRED_DOMAIN_RECORD_DIRS -- and docs/README.md stops being scanned, the plant in it goes
    unreported, and this fails. Planting into a tmp_path copy instead would put the file outside
    ROOT, where no exemption directory can ever match, and the check would pass no matter how
    broad the exemptions grew.
    """
    scanned = _domain_scan_paths(cli)
    overrides: dict[Path, str] = {}
    expected_offenders = []
    for rel in DOMAIN_SCAN_CANARY_RELATIVE_PATHS:
        path = ROOT / rel
        assert cli.public_release_export_path_included(Path(rel)), f"{rel} no longer ships"
        assert path in scanned, f"{rel} ships but the domain scan does not cover it"
        overrides[path], lineno = _plant_retired_domain(path.read_text(encoding="utf-8"))
        expected_offenders.append(f"{rel}:{lineno}:")

    offenders = _retired_domain_offenders(scanned, overrides=overrides)

    unreported = [
        prefix
        for prefix in expected_offenders
        if not any(offender.startswith(prefix) for offender in offenders)
    ]
    assert unreported == [], (
        "the domain scan did not report a retired domain planted in these shipped contact "
        f"surfaces: {unreported}. They ship to the public repo, so an exemption "
        "(RETIRED_DOMAIN_RECORD_DIRS, DOMAIN_ENFORCEMENT_DIRS, or the bin/tautline release-note "
        "line exemption) is too broad and is hiding a live surface from the ban."
    )


def _is_test_machinery(path: Path) -> bool:
    # .py modules and fixtures WRITE the banned strings in order to ban them. tests/data/ holds
    # the A1 neutrality goldens (help corpus + dispatch map); each is pinned byte-for-byte to an
    # already-scanned source (a help .txt to bin/tautline's --help, itself a domain-scan canary;
    # the dispatch map to AST handler names), so it cannot smuggle an unscanned contact surface.
    rel_parts = path.relative_to(ROOT).parts
    return (
        path.suffix == ".py"
        or "fixtures" in rel_parts
        or rel_parts[:2] == ("tests", "data")
    )


def test_retired_domain_exemptions_are_justified_by_what_they_ship(cli):
    """Pin the exemptions themselves: an exemption may only cover records and enforcement machinery.

    _is_historical_domain_record() skips whole directories, so the exemption list is the scan's
    blind spot. Nothing else in this file constrains how big that blind spot may grow -- and an
    exemption wide enough to swallow a live contact surface defeats the ban entirely while leaving
    the suite green. So justify every exemption directory against the REAL ship set:

      * a record directory must either ship nothing at all (export-excluded, like
        docs/productization/archive/) or ship only versioned release records
        (docs/releases/migrations/0.6.254.json and friends) -- never prose a reader is pointed at;
      * an enforcement directory must ship only test machinery -- the modules and fixtures that
        have to WRITE the banned string in order to ban it.

    Adding `ROOT / "docs"` to RETIRED_DOMAIN_RECORD_DIRS fails here: docs/ ships hundreds of
    Markdown files, and none of them is a versioned release record.
    """
    shipped = _shipped_paths(cli)
    errors = []

    for record_dir in sorted(RETIRED_DOMAIN_RECORD_DIRS):
        rel_dir = record_dir.relative_to(ROOT).as_posix()
        shipped_here = [path for path in shipped if record_dir in path.parents]
        if not shipped_here:
            # Nothing under it reaches the public repo, so exempting it costs the ban nothing --
            # provided that is because the export excludes it, not because the entry is dead.
            if cli.public_release_export_path_included(Path(rel_dir) / "any-file.md"):
                errors.append(
                    f"{rel_dir}/: exempted by RETIRED_DOMAIN_RECORD_DIRS but it ships no record; "
                    "an exemption that guards nothing is either dead or a placeholder for future "
                    "unscanned files -- drop it"
                )
            continue
        errors.extend(
            f"{path.relative_to(ROOT).as_posix()}: exempted by RETIRED_DOMAIN_RECORD_DIRS "
            f"({rel_dir}/) but it is not a versioned release record -- an exempted directory that "
            "ships anything else is an unscanned public contact surface"
            for path in shipped_here
            if not VERSIONED_RECORD_FILENAME_RE.match(path.name)
        )

    for enforcement_dir in sorted(DOMAIN_ENFORCEMENT_DIRS):
        rel_dir = enforcement_dir.relative_to(ROOT).as_posix()
        errors.extend(
            f"{path.relative_to(ROOT).as_posix()}: exempted by DOMAIN_ENFORCEMENT_DIRS "
            f"({rel_dir}/) but it is not test machinery -- the enforcement exemption exists so the "
            "ban can quote the string it bans, not to hide shipped prose from the scan"
            for path in shipped
            if enforcement_dir in path.parents and not _is_test_machinery(path)
        )

    assert errors == []


def test_domain_scan_exempts_only_records_and_the_enforcement_surface(cli):
    """The widened scan must not swallow the surfaces that legitimately carry the retired domain.

    Historical records (migration JSONs, archived changelogs), the frozen 0.6.254 release-note
    literal in bin/tautline, and the tests that BAN the string all keep it verbatim. They are
    exemptions, not reasons to narrow the scan back to a hand list.
    """
    migration = ROOT / "docs" / "releases" / "migrations" / "0.6.254.json"
    assert migration in _domain_scan_paths(cli), "the migration record must be scanned-and-exempted"
    assert RETIRED_DOMAIN_RE.search(migration.read_text(encoding="utf-8"))
    assert _retired_domain_offenders([migration]) == []

    cli_source = ROOT / "src" / "tautline_methodology" / "cli.py"
    frozen = [
        line
        for line in cli_source.read_text(encoding="utf-8").splitlines()
        if RETIRED_DOMAIN_RE.search(line)
    ]
    assert frozen, "the frozen 0.6.254 release-note literal is gone; drop its exemption"
    assert all(_is_historical_domain_record(cli_source, line) for line in frozen)
    # A retired-domain line in cli.py that is NOT the frozen release note is still a live
    # surface and still fails.
    assert not _is_historical_domain_record(cli_source, "hello@minervit.com")


def test_swept_surfaces_positively_carry_the_canonical_domain():
    errors = []
    for path, required in CANONICAL_DOMAIN_REQUIRED_STRINGS.items():
        if not path.exists():
            errors.append(
                f"{path.relative_to(ROOT)}: swept canonical-domain surface is missing"
            )
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in required:
            if phrase not in text:
                errors.append(f"{path.relative_to(ROOT)}: must contain {phrase!r}")

    assert errors == []
