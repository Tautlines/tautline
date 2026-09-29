import json
import os
import re
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from tautline_methodology import public_release

CLI_PATH = Path(__file__).resolve().parents[1] / "bin" / "tautline"
SRC_ROOT = CLI_PATH.parents[1] / "src"

ACCOUNT_ID_PATTERN = re.compile(r"(?<!\d)\d{12}(?!\d)")
# Real digests lifted from this repository's own review evidence. Each embeds a run of
# exactly twelve digits purely by chance, because its neighbouring hex characters happen
# to be letters -- which is precisely what a bare \d{12} account-id scan misreads.
_SHA256_EMBEDDING_A_TWELVE_DIGIT_RUN = (
    "a551b354d8e440f2d4cdc4b2ef7b7eb9213845d010451675063ffb7e0642a898"
)
_GIT_SHA1_EMBEDDING_A_TWELVE_DIGIT_RUN = "ad712393414906d85d47245e45020ede5183a4f6"


def _embedded_twelve_digit_run(digest: str) -> str:
    """The account-like 12-digit run a bare account-id scan finds inside ``digest``."""
    match = ACCOUNT_ID_PATTERN.search(digest)
    assert match, f"fixture digest must embed a 12-digit run: {digest}"
    return match.group(0)


def _digest_embedding_a_twelve_digit_run() -> str:
    digest = _SHA256_EMBEDDING_A_TWELVE_DIGIT_RUN
    assert len(digest) == 64
    _embedded_twelve_digit_run(digest)
    return digest


def _copy_cli_with_package(source: Path) -> Path:
    """Copy bin/minervit-methodology alongside its required src/tautline_methodology
    package into `source`. Note: the copied-bin-without-src execution mode is not
    supported for extracted helpers, so any fixture that runs a copied CLI end-to-end
    must bring the package with it."""
    cli_path = source / "bin" / "tautline"
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text(CLI_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(SRC_ROOT, source / "src")
    return cli_path


def _symlink_or_skip(target: str, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable in this test environment: {exc}")


def _next_minor(version: str) -> str:
    major, minor, *_rest = [int(part) for part in version.split(".")]
    return f"{major}.{minor + 1}.0"


def _next_patch(version: str) -> str:
    major, minor, patch = [int(part) for part in version.split(".")]
    return f"{major}.{minor}.{patch + 1}"


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _init_example_saas_repo(path: Path) -> Path:
    remote = path / "example-org" / "example-saas.git"
    target = path / "adopter"
    remote.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(target), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin", str(remote)], check=True)
    (target / "README.md").write_text("# Example\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(target), "push", "-q", "-u", "origin", "main"], check=True)
    return target


PUBLIC_EXPORT_MARKER = Path(__file__).resolve().parents[1] / ".minervit-public-release-export.json"
private_repo_only = pytest.mark.skipif(
    PUBLIC_EXPORT_MARKER.exists(),
    reason="private-repo-context test; the export tree has no private history to block",
)


def _known_public_release_private_terms() -> str:
    """SYNTHETIC private terms for exercising the export CLI's plumbing.

    These are deliberately fake. Codex R2 (P2) caught the previous version gating these
    behavior tests on real, locally-configured terms: in clean CI, where nothing is
    configured, two export-safety paths silently stopped running. A test that proves the
    CLI accepts and threads private terms does not need the REAL denylist -- it needs
    some terms. Auditing the real denylist is a different job, and the boundary scan owns
    it. Real client and product names are never written into a file that ships.
    """
    # Assembled from fragments so the terms do not appear literally in any tracked file
    # -- otherwise the private-term scan finds them HERE, in the file that defines them,
    # and reports a leak that does not exist.
    #
    # Splitting is correct here and was wrong for real identifiers, and the difference is
    # the point: for a real name, splitting changes nothing about disclosure because the
    # fragments rejoin to the real value. These values are fake by construction, so there
    # is nothing to disclose and the only property that matters is not colliding with the
    # scan.
    return ",".join((
        "SYNTH" + "ETIC-CLIENT-ALPHA",
        "SYNTH" + "ETIC-PRODUCT-BETA",
        "Synth" + "etic Engine",
    ))




def test_framework_pin_defaults_to_stable_manual(cli):
    pin = cli.normalize_framework_pin(None)

    assert pin == {
        "channel": "stable",
        "version": "",
        "updatePolicy": "manual",
        "migrationPolicy": "dry-run",
    }


def test_experimental_channel_maps_to_experimental_release_branch(cli, monkeypatch):
    def fake_run_git(_target, args):
        if args == ["remote", "get-url", "origin"]:
            return "https://example.invalid/methodology.git"
        return "unavailable"

    monkeypatch.setattr(cli, "run_git", fake_run_git)

    assert cli.methodology_release_upstream("experimental") == ("origin", "experimental", "origin/experimental")
    assert cli.methodology_release_upstream("stable") == ("origin", "main", "origin/main")


def test_methodology_repo_invocation_skips_auto_update(cli, tmp_path):
    data = {"repo": "minervit/minervit-ai-delivery-methodology", "laneState": dict(cli.DEFAULT_LANE_STATE)}
    pin = {
        "channel": "stable",
        "version": "",
        "updatePolicy": "manual",
        "migrationPolicy": "dry-run",
    }

    decision = cli.framework_update_decision(pin, data, cli.REPO_ROOT)

    assert decision["action"] == "skip"
    assert "uses the current checkout without auto-update" in decision["reason"]


def test_explicit_external_target_updates_even_when_invoked_from_methodology_repo(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "invoked_from_methodology_repo", lambda: True)
    monkeypatch.setenv("MINERVIT_METHODOLOGY_AVAILABLE_VERSION", _next_patch(cli.methodology_version()))
    data = {"laneState": dict(cli.DEFAULT_LANE_STATE)}
    pin = {
        "channel": "experimental",
        "version": "",
        "updatePolicy": "patch-auto",
        "migrationPolicy": "dry-run",
    }

    decision = cli.framework_update_decision(pin, data, tmp_path, manual_request=True)

    assert decision["action"] == "update"
    assert "permits patch update" in decision["reason"]


def test_migration_commands_after_0_10_0_use_portable_cli_spellings(cli):
    """SWEEP-10 (deferral sweep): forward-only command-spelling ratchet.

    0.10.0's `bin/tautline install-cli` requiredMigration stays as committed — amending a
    frozen report re-opens the release (`release-migration-report --check` byte-binds it;
    precedent CODEX-R1-P2-1 in .impl-reviews/fix-review-guard-followups.json), and the bare
    spelling is correct for the pre-rename checkout machines that migration targets. NEW
    reports must not repeat it: bare `bin/tautline` does not exist for a pipx/wheel user, so
    commands are spelled mode-independently (`tautline ...`) or checkout-relative
    (`<methodology_repo>/bin/tautline ...`, the launcher's own spelling)."""
    migrations_dir = CLI_PATH.parents[1] / "docs" / "releases" / "migrations"
    frozen_floor = cli.version_tuple("0.10.0")
    reports_after = sorted(
        (
            path
            for path in migrations_dir.glob("*.json")
            if cli.version_tuple(path.stem) > frozen_floor
        ),
        key=lambda path: cli.version_tuple(path.stem),
    )
    assert reports_after, "expected at least one committed migration report after 0.10.0"
    for report_path in reports_after:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        migrations = [
            ("requiredMigration", item) for item in report.get("requiredMigrations") or []
        ] + [
            ("optionalMigration", item) for item in report.get("optionalMigrations") or []
        ]
        for kind, item in migrations:
            command = str(item.get("command", ""))
            outside_sanctioned = command.replace("<methodology_repo>/bin/tautline", "")
            assert "bin/tautline" not in outside_sanctioned, (
                f"{report_path.name} {kind} {item.get('id')!r} uses the checkout-only "
                f"spelling in {command!r}; spell it `tautline ...` (mode-independent) or "
                "`<methodology_repo>/bin/tautline ...` (checkout-relative)"
            )


def test_public_release_current_tree_ships_no_private_source_adapters(cli):
    issues = cli.public_release_issues()
    private_adapter_paths = {issue["path"] for issue in issues if issue["code"] == "private-source-adapter"}

    assert private_adapter_paths == set()
    assert not [issue for issue in issues if issue["code"] == "live-host-in-private-adapter"]
    assert not [issue for issue in issues if issue["code"] == "account-id"]
    assert not [issue for issue in issues if issue["code"] == "private-adapter-path"]


def test_public_release_helper_primitives_are_served_from_package(cli, tmp_path):
    # Note: the copied-bin-without-src execution mode is not supported for extracted
    # helpers; public_release_module() always resolves the real package or raises SystemExit
    # (adapter_module()-style), so this only asserts wrapper/module parity, not a fallback.
    cli._PUBLIC_RELEASE_MODULE = None
    assert cli.public_release_module() is public_release

    placeholder_account = "123456" + "789012"
    touch_timestamp = "202607" + "061230"
    invalid_touch_timestamp = "202613" + "061230"
    assert cli.public_release_allowed_account_like_token(placeholder_account, f"account {placeholder_account}") == (
        public_release.allowed_account_like_token(
            placeholder_account,
            f"account {placeholder_account}",
            placeholder_account_ids=cli.PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS,
        )
    )
    assert cli.public_release_allowed_account_like_token(touch_timestamp, f"touch -t {touch_timestamp} file") == (
        public_release.allowed_account_like_token(
            touch_timestamp,
            f"touch -t {touch_timestamp} file",
            placeholder_account_ids=cli.PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS,
        )
    )
    assert cli.public_release_allowed_account_like_token(
        invalid_touch_timestamp,
        f"touch -t {invalid_touch_timestamp} file",
    ) is False

    allowed_doc = Path("docs/product/positioning.md")
    excluded_doc = Path("docs/product/internal-roadmap.md")
    internal_plan = Path("docs/superpowers/plans/private.md")
    readme = Path("README.md")
    for rel in (allowed_doc, excluded_doc, internal_plan, readme):
        assert cli.public_release_export_path_included(rel) == public_release.export_path_included(
            rel,
            allowed_product_docs=cli.PUBLIC_RELEASE_EXPORT_ALLOWED_PRODUCT_DOCS,
            excluded_prefixes=cli.PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES,
        )

    marker_text = public_release.export_marker_text(
        version=cli.plugin_version(),
        marker_schema=cli.PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA,
        private_terms_source="file",
        private_terms_count=2,
    )
    assert cli.public_release_export_marker_text(private_terms_source="file", private_terms_count=2) == marker_text

    destination = tmp_path / "public-export"
    destination.mkdir()
    assert cli.public_release_export_destination_is_prior_export(destination) is False
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(marker_text, encoding="utf-8")
    assert cli.public_release_export_destination_is_prior_export(destination) is True
    assert public_release.export_destination_is_prior_export(
        destination,
        marker_name=cli.PUBLIC_RELEASE_EXPORT_MARKER,
        marker_schema=cli.PUBLIC_RELEASE_EXPORT_MARKER_SCHEMA,
    ) is True

    issues: list[dict] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    cli.public_release_add_issue(
        issues,
        seen,
        "private-product-reference",
        tmp_path / "docs" / "public.md",
        "public surface references a real product/client adapter name",
        tmp_path,
        line=3,
    )
    public_release.add_issue(
        issues,
        seen,
        "private-product-reference",
        tmp_path / "docs" / "public.md",
        "public surface references a real product/client adapter name",
        repo_root=tmp_path,
        max_issues_per_rule=cli.PUBLIC_RELEASE_MAX_ISSUES_PER_RULE,
        line=3,
    )
    assert issues == [
        {
            "code": "private-product-reference",
            "path": "docs/public.md",
            "message": "public surface references a real product/client adapter name",
            "line": 3,
        }
    ]


@private_repo_only
def test_public_release_check_current_tree_blocks_only_history_until_public_cut(cli, capsys, monkeypatch):
    monkeypatch.delenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, raising=False)

    code = cli.public_release_check(Namespace(as_json=False))

    captured = capsys.readouterr()
    assert code == 1
    assert "public_release_check: blocked" in captured.out
    assert (
        "private-adapter-history adapters/projects/" in captured.out
        or "git-history-shallow .:" in captured.out
    )
    assert "private-source-adapter" not in captured.out
    assert "live-host-in-private-adapter" not in captured.out
    assert "account-id" not in captured.out
    assert "private-adapter-path" not in captured.out


@private_repo_only
def test_public_release_check_cli_current_tree_json_blocks_only_history_until_public_cut(run_cli):
    result = run_cli("public-release-check", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "private-source-adapter" not in codes
    assert "live-host-in-private-adapter" not in codes
    assert "account-id" not in codes
    assert "private-adapter-path" not in codes
    assert codes <= {
        "private-adapter-history",
        "git-history-shallow",
        "same-history-remote",
        "release-update-overdue",
        "release-update-current-missing",
    }
    assert "private-adapter-history" in codes or "git-history-shallow" in codes


@private_repo_only
def test_public_release_check_current_tree_json_blocks_only_history_with_private_terms(
    cli, capsys, monkeypatch
):
    monkeypatch.setenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, _known_public_release_private_terms())

    code = cli.public_release_check(Namespace(as_json=True))

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    codes = {issue["code"] for issue in payload["issues"]}
    assert "private-source-adapter" not in codes
    assert "live-host-in-private-adapter" not in codes
    assert "account-id" not in codes
    assert "private-adapter-path" not in codes
    assert "private-product-reference" not in codes
    assert codes <= {
        "private-adapter-history",
        "git-history-shallow",
        "same-history-remote",
        "release-update-overdue",
        "release-update-current-missing",
    }
    assert "private-adapter-history" in codes or "git-history-shallow" in codes


def test_public_release_issues_export_marker_skips_release_update_gate_without_ledger(cli, tmp_path):
    """Inside an export candidate the ledger is deliberately export-excluded, so the
    release-update accountability gate (a maintainer-side check) must not fire there
    even though the scanned tree has a VERSION but no delivery ledger at all."""
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("## 1.2.3 - 2026-07-12\n\n- did a thing\n", encoding="utf-8")
    (tmp_path / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(
        cli.public_release_export_marker_text(), encoding="utf-8"
    )

    issues = cli.public_release_issues(tmp_path)

    assert not [issue for issue in issues if issue["code"].startswith("release-update-")]


def test_public_release_issues_export_marker_and_absent_ledger_still_skips_gate(cli, tmp_path):
    """Companion to the regression test above: a genuine export candidate --
    marker present AND the export-excluded ledger genuinely absent -- must
    still skip the release-update gate cleanly, preserving prior behavior."""
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "## 1.2.3 - 2026-07-12\n\n- did a thing\n", encoding="utf-8"
    )
    (tmp_path / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(
        cli.public_release_export_marker_text(), encoding="utf-8"
    )

    issues = cli.public_release_issues(tmp_path)

    assert not [issue for issue in issues if issue["code"].startswith("release-update-")]


def test_public_release_check_blocks_private_adapter_fixture(cli, tmp_path):
    adapter_dir = tmp_path / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    (adapter_dir / "example-saas.json").write_text(
        '{"project":"Example SaaS","repo":"example/example-saas"}\n',
        encoding="utf-8",
    )
    (adapter_dir / private_name).write_text(
        '{"project":"Private Customer","repo":"example/private","healthCheck":"https://private.example.test"}\n',
        encoding="utf-8",
    )

    issues = cli.public_release_issues(tmp_path)
    private_adapter_paths = {issue["path"] for issue in issues if issue["code"] == "private-source-adapter"}

    assert private_adapter_paths == {private_rel}
    assert "adapters/projects/example-saas.json" not in private_adapter_paths


def test_public_release_check_allows_touch_timestamp_literals(cli, tmp_path):
    script = tmp_path / "validate.sh"
    script.write_text('touch -t 202001010000 "${STALE_MONITOR_LOG}"\n', encoding="utf-8")

    issues = cli.public_release_issues(tmp_path)

    assert not [issue for issue in issues if issue["code"] == "account-id"]


def test_public_release_check_scans_impl_review_ledgers_without_hash_noise(cli, tmp_path, monkeypatch):
    ledger = tmp_path / "docs" / "superpowers" / "plans" / ".impl-reviews" / "review.json"
    ledger.parent.mkdir(parents=True)
    private_term = "Private Customer Alpha"
    leaked_account = "234567" + "890123"
    digest = _digest_embedding_a_twelve_digit_run()
    payload = (
        json.dumps(
            {
                "diff_sha256": digest,
                "branch": "feature/docs",
                "classified_findings": [
                    {
                        "evidence": f"Private note for {private_term}",
                    },
                    {"evidence": f"Found account {leaked_account} in free-form review text"},
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    ledger.write_text(payload, encoding="utf-8")
    lines = payload.splitlines()
    digest_line = next(lineno for lineno, line in enumerate(lines, 1) if digest in line)
    leak_line = next(lineno for lineno, line in enumerate(lines, 1) if leaked_account in line)
    monkeypatch.setenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, private_term)

    issues = cli.public_release_issues(tmp_path)
    issue_codes = {issue["code"] for issue in issues}
    account_id_lines = {issue["line"] for issue in issues if issue["code"] == "account-id"}

    assert "private-product-reference" in issue_codes
    # The digest line is hash noise; the free-form evidence line is a genuine leak.
    assert account_id_lines == {leak_line}
    assert digest_line not in account_id_lines


def test_public_release_check_allows_twelve_digit_runs_inside_hex_digests(cli, tmp_path):
    digest = _digest_embedding_a_twelve_digit_run()
    git_sha = _GIT_SHA1_EMBEDDING_A_TWELVE_DIGIT_RUN
    plans = tmp_path / "docs" / "superpowers" / "plans"
    (plans / ".plan-reviews").mkdir(parents=True)
    (plans / ".plan-reviews" / "plan-v2.json").write_text(
        json.dumps(
            {"log_sha256": digest, "plan_content_sha256": digest},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (plans / "plan-v2.md").write_text(f"- Log SHA256: `{digest}`\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(f"Verified against digest {digest}.\n", encoding="utf-8")
    (tmp_path / "commits.txt").write_text(f"{git_sha} initial commit\n", encoding="utf-8")

    issues = cli.public_release_issues(tmp_path)

    assert not [issue for issue in issues if issue["code"] == "account-id"]


def test_public_release_check_still_flags_a_standalone_account_id_beside_a_digest(cli, tmp_path):
    digest = _digest_embedding_a_twelve_digit_run()
    leaked_account = "234567" + "890123"
    notes = tmp_path / "notes.md"
    notes.write_text(
        f"- Log SHA256: `{digest}`\n"
        f"- Log SHA256: `{digest}` for account {leaked_account}\n",
        encoding="utf-8",
    )

    issues = cli.public_release_issues(tmp_path)

    assert [issue["line"] for issue in issues if issue["code"] == "account-id"] == [2]


def test_public_release_check_flags_a_bare_account_id_also_inside_a_digest(cli, tmp_path):
    digest = _digest_embedding_a_twelve_digit_run()
    embedded = _embedded_twelve_digit_run(digest)
    notes = tmp_path / "notes.md"
    notes.write_text(f"digest {digest} and bare id {embedded} on one line\n", encoding="utf-8")

    issues = cli.public_release_issues(tmp_path)

    assert [issue["line"] for issue in issues if issue["code"] == "account-id"] == [1]


def test_public_release_check_flags_a_leaked_account_id_on_an_impl_review_sha_line(cli, tmp_path):
    digest = _digest_embedding_a_twelve_digit_run()
    leaked_account = "234567" + "890123"
    ledger = tmp_path / "docs" / "superpowers" / "plans" / ".impl-reviews" / "review.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        '{"diff_sha256": "%s", "evidence": "leaked account %s"}\n' % (digest, leaked_account),
        encoding="utf-8",
    )

    issues = cli.public_release_issues(tmp_path)

    assert [issue["line"] for issue in issues if issue["code"] == "account-id"] == [1]


def test_allowed_account_like_token_distinguishes_digest_fragments_from_account_ids(cli):
    placeholder_account_ids = cli.PUBLIC_RELEASE_PLACEHOLDER_ACCOUNT_IDS

    def allowed(token: str, line: str) -> bool:
        return public_release.allowed_account_like_token(
            token,
            line,
            placeholder_account_ids=placeholder_account_ids,
        )

    digest = _digest_embedding_a_twelve_digit_run()
    embedded = _embedded_twelve_digit_run(digest)
    leaked_account = "234567" + "890123"
    placeholder_account = "123456" + "789012"
    same_digit_account = "9" * 12
    touch_timestamp = "202607" + "061230"
    invalid_touch_timestamp = "202613" + "061230"

    # Preserved: placeholders, all-same-digit runs, and `touch -t` timestamps.
    assert allowed(placeholder_account, f"account {placeholder_account}") is True
    assert allowed(same_digit_account, f"account {same_digit_account}") is True
    assert allowed(touch_timestamp, f"touch -t {touch_timestamp} file") is True
    assert allowed(invalid_touch_timestamp, f"touch -t {invalid_touch_timestamp} file") is False
    assert allowed(touch_timestamp, f"account {touch_timestamp}") is False
    assert allowed(leaked_account, f"account {leaked_account}") is False

    # New: a 12-digit run that is interior to a digest-length hex token is a digest fragment.
    assert allowed(embedded, f'  "log_sha256": "{digest}",') is True
    assert allowed(embedded, f"- Log SHA256: `{digest}`") is True
    assert (
        allowed(
            _embedded_twelve_digit_run(_GIT_SHA1_EMBEDDING_A_TWELVE_DIGIT_RUN),
            f"commit {_GIT_SHA1_EMBEDDING_A_TWELVE_DIGIT_RUN}",
        )
        is True
    )

    # Precise: sharing a line with a digest does not launder a real account id...
    assert allowed(leaked_account, f"digest {digest} account {leaked_account}") is False
    # ...not even when the same digits also occur inside that digest.
    assert allowed(embedded, f"digest {digest} bare {embedded}") is False

    # Boundary: digest-length hex runs shield, shorter hex-ish runs do not.
    min_length = public_release.DIGEST_MIN_HEX_LENGTH
    filler = "abcdefabcdefabcdefabcdefabcdefabcdef"
    long_enough = filler[: min_length - len(embedded)] + embedded
    too_short = filler[: min_length - len(embedded) - 1] + embedded
    assert len(long_enough) == min_length
    assert allowed(embedded, f"token {long_enough}") is True
    assert allowed(embedded, f"token {too_short}") is False


def test_public_release_check_supports_private_term_denylist_after_adapter_removal(cli, tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    private_term = "Fi" + "nch"
    readme.write_text(f"Legacy customer codename: {private_term}\n", encoding="utf-8")
    monkeypatch.setenv("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", private_term)

    issues = cli.public_release_issues(tmp_path)

    assert {
        "code": "private-product-reference",
        "path": "README.md",
        "line": 1,
        "message": "public surface references a real product/client adapter name",
    } in issues


def test_public_release_check_supports_private_terms_file_after_adapter_removal(cli, tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    private_term = "Private Customer Alpha"
    readme.write_text(f"Legacy customer codename: {private_term}\n", encoding="utf-8")
    terms_file = tmp_path / "private-terms.txt"
    terms_file.write_text("# untracked local denylist\nPrivate Customer Alpha\n", encoding="utf-8")
    monkeypatch.delenv(cli.PUBLIC_RELEASE_PRIVATE_TERMS_ENV, raising=False)

    issues = cli.public_release_issues(tmp_path, private_terms_file=terms_file)

    assert {
        "code": "private-product-reference",
        "path": "README.md",
        "line": 1,
        "message": "public surface references a real product/client adapter name",
    } in issues


def test_public_release_private_terms_file_accepts_json_string_array(cli, tmp_path):
    terms_file = tmp_path / "private-terms.json"
    terms_file.write_text('["Private Customer Alpha", "Private Customer Beta"]\n', encoding="utf-8")

    assert cli.public_release_private_terms([], terms_file) == [
        "Private Customer Alpha",
        "Private Customer Beta",
    ]


def test_public_release_check_blocks_private_adapter_paths_in_git_history(cli, tmp_path):
    repo = tmp_path / "repo"
    adapter_dir = repo / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(repo)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    private_adapter = adapter_dir / private_name
    private_adapter.write_text('{"project":"Private Customer","repo":"example/private"}\n', encoding="utf-8")
    subprocess.run(["git", "add", private_rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add private adapter"], cwd=repo, check=True)
    private_adapter.unlink()
    subprocess.run(["git", "add", "-u"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remove private adapter"], cwd=repo, check=True)

    issues = cli.public_release_issues(repo)

    assert {
        "code": "private-adapter-history",
        "path": private_rel,
        "message": "private adapter path remains in git history; rewrite history before flipping this repository public or publish from a clean public repo",
    } in issues


def test_public_release_history_scan_ignores_example_and_message_only_mentions(cli, tmp_path):
    repo = tmp_path / "repo"
    adapter_dir = repo / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(repo)
    example_adapter = adapter_dir / "example-saas.json"
    example_adapter.write_text('{"project":"Example SaaS","repo":"example/example-saas"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "adapters/projects/example-saas.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add example adapter"], cwd=repo, check=True)
    example_adapter.unlink()
    subprocess.run(["git", "add", "-u"], cwd=repo, check=True)
    private_ref = "adapters/projects/" + "private-customer.json"
    subprocess.run(["git", "commit", "-q", "-m", f"message mentions {private_ref} only"], cwd=repo, check=True)

    issues = cli.public_release_issues(repo)

    assert not [issue for issue in issues if issue["code"] == "private-adapter-history"]


def test_public_release_history_fails_closed_for_shallow_checkout(cli, tmp_path):
    source = tmp_path / "source"
    adapter_dir = source / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(source)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    private_adapter = adapter_dir / private_name
    private_adapter.write_text('{"project":"Private Customer","repo":"example/private"}\n', encoding="utf-8")
    subprocess.run(["git", "add", private_rel], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add private adapter"], cwd=source, check=True)
    private_adapter.unlink()
    subprocess.run(["git", "add", "-u"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remove private adapter"], cwd=source, check=True)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{source}", str(shallow)], check=True)

    issues = cli.public_release_issues(shallow)

    assert any(issue["code"] == "git-history-shallow" for issue in issues)


def test_public_release_check_blocks_same_history_remote(cli, tmp_path):
    repo = tmp_path / "repo"
    remote = tmp_path / "same-history.git"
    repo.mkdir()
    _init_git_repo(repo)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    (repo / "README.md").write_text("# Public Candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=repo, check=True)

    issues = cli.public_release_issues(repo)

    same_history = [issue for issue in issues if issue["code"] == "same-history-remote"]
    assert same_history
    assert same_history[0]["path"] == "."
    assert "target remote 'origin' shares this repository's root commit" in same_history[0]["message"]
    assert "public-release-export" in same_history[0]["message"]


def test_public_release_root_commits_accepts_sha256_hashes(cli, tmp_path, monkeypatch):
    sha256_root = "a" * 64

    def fake_run_command(command, cwd=None, timeout=None):
        if command[:4] == ["git", "-C", str(tmp_path), "rev-list"]:
            return 0, sha256_root + "\n", ""
        return 1, "", "unexpected command"

    monkeypatch.setattr(cli, "run_command", fake_run_command)

    assert cli.public_release_root_commits(tmp_path) == {sha256_root}


def test_public_release_export_builds_clean_repo_without_private_history(cli, tmp_path):
    source = tmp_path / "source"
    adapter_dir = source / "adapters" / "projects"
    adapter_dir.mkdir(parents=True)
    _init_git_repo(source)
    private_name = "private-" + "customer.json"
    private_rel = "adapters/projects/" + private_name
    private_adapter = adapter_dir / private_name
    private_adapter.write_text('{"project":"Private Customer","repo":"example/private"}\n', encoding="utf-8")
    subprocess.run(["git", "add", private_rel], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add private adapter"], cwd=source, check=True)
    private_adapter.unlink()
    example_adapter = adapter_dir / "example-saas.json"
    example_adapter.write_text('{"project":"Example SaaS","repo":"example/example-saas"}\n', encoding="utf-8")
    (source / "README.md").write_text("# Public Candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "public tree"], cwd=source, check=True)

    source_issues = cli.public_release_issues(source)
    destination = tmp_path / "public"
    result = cli.public_release_export_repository(source, destination)
    export_issues = cli.public_release_issues(destination)

    assert any(issue["code"] == "private-adapter-history" for issue in source_issues)
    assert result["files"] == 2
    assert result["commit"] != "unavailable"
    assert (destination / ".git").exists()
    assert (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).exists()
    assert (destination / "README.md").read_text(encoding="utf-8") == "# Public Candidate\n"
    assert not (destination / private_rel).exists()
    assert export_issues == []


def test_public_release_export_excludes_dependabot_config(cli):
    # The public repository is a force-pushed mirror: Dependabot PRs opened there
    # can never merge and always fail the release-change contract, so dependency
    # intake stays private and the config must not be exported.
    assert cli.public_release_export_path_included(Path(".github/dependabot.yml")) is False
    assert cli.public_release_export_path_included(Path(".github/workflows/ci-python.yml")) is True


def test_public_release_export_refuses_ancestor_destination_even_with_force(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    try:
        cli.public_release_export_repository(source, tmp_path, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("ancestor destination should be refused")

    assert "destination must be outside" in message
    assert source.exists()


def test_public_release_export_force_only_replaces_prior_export(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / "unrelated.txt").write_text("do not delete\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("force should not replace an unmarked directory")

    assert "only replaces a prior public-release-export destination" in message
    assert (destination / "unrelated.txt").exists()

    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    result = cli.public_release_export_repository(source, destination, force=True)

    assert result["issues"] == []
    assert (destination / "README.md").exists()
    assert not (destination / "unrelated.txt").exists()


def test_public_release_export_refuses_dirty_source_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("dirty tracked file should be refused before replacing a prior export")

    assert "dirty tracked files are not exported by default" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_preserves_safe_relative_symlink(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    _symlink_or_skip("README.md", source / "README-link.md")
    subprocess.run(["git", "add", "README.md", "README-link.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert (tmp_path / "public" / "README-link.md").is_symlink()
    assert os.readlink(tmp_path / "public" / "README-link.md") == "README.md"


def test_public_release_export_refuses_escaping_symlink_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not export\n", encoding="utf-8")
    _symlink_or_skip(str(outside), source / "secret-link.txt")
    subprocess.run(["git", "add", "secret-link.txt"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("escaping symlink should be refused before replacing a prior export")

    assert "absolute symlink targets are not exported" in message or "symlink target escapes" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_refuses_relative_symlink_that_would_escape_export(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    _symlink_or_skip("../source/README.md", source / "source-loop-link.md")
    subprocess.run(["git", "add", "README.md", "source-loop-link.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("relative symlink that would escape export should be refused")

    assert "symlink target escapes or is missing: source-loop-link.md -> ../source/README.md" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_refuses_dangling_symlink_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    _symlink_or_skip("missing.md", source / "missing-link.md")
    subprocess.run(["git", "add", "missing-link.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("dangling symlink should be refused before replacing a prior export")

    assert "symlink target escapes or is missing: missing-link.md -> missing.md" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_refuses_symlink_loop_before_force_delete(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    _symlink_or_skip("loop-b.md", source / "loop-a.md")
    _symlink_or_skip("loop-a.md", source / "loop-b.md")
    subprocess.run(["git", "add", "loop-a.md", "loop-b.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / cli.PUBLIC_RELEASE_EXPORT_MARKER).write_text(cli.public_release_export_marker_text(), encoding="utf-8")
    (destination / "prior-export.txt").write_text("keep until source is safe\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, destination, force=True)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("symlink loop should be refused before replacing a prior export")

    assert "symlink target escapes or is missing: loop-a.md -> loop-b.md" in message
    assert (destination / "prior-export.txt").exists()


def test_public_release_export_checks_private_terms_in_exported_tree(cli, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    private_term = "Fi" + "nch"
    (source / "README.md").write_text(f"# Public Candidate\n\nLegacy codename: {private_term}\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setenv("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", private_term)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert {
        "code": "private-product-reference",
        "path": "README.md",
        "line": 3,
        "message": "public surface references a real product/client adapter name",
    } in result["issues"]


def test_public_release_export_defaults_to_tracked_files_only(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    (source / "scratch.md").write_text("draft notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").exists()
    assert not (tmp_path / "public" / "scratch.md").exists()


def test_public_release_export_excludes_internal_docs_but_keeps_public_product_docs(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    tracked_files = {
        "README.md": "# Source\n",
        "docs/backlog/methodology-backlog.md": "internal backlog\n",
        "docs/productization/audit-disposition-register.md": "internal audit\n",
        "docs/superpowers/plans/refactor.md": "internal plan\n",
        "docs/product/telemetry-consent.md": "internal telemetry\n",
        "docs/product/a11y-i18n.md": "internal a11y\n",
        "docs/product/positioning.md": "public positioning\n",
        "docs/product/support-sla-model.md": "public support\n",
        # The framework's own self-adapter files are maintainer-lane config that
        # references private planning conventions; they must not ship in the export
        # (the self-adapter gates skip in export trees since 0.6.265, so the export
        # does not need them).
        ".minervit/adapter.json": '{"project": "self"}\n',
        ".minervit-ai-delivery.json": '{"project": "self"}\n',
        ".tautline/adapter.json": '{"project": "self"}\n',
        ".tautline.json": '{"project": "self"}\n',
        # The release-update delivery ledger is an internal ops record (who was
        # notified about which release, and when); the rest of docs/releases/ is
        # public release material and must still ship.
        "docs/releases/release-update-delivery.json": '{"schema":"minervit-release-update-delivery/v1","delivered":{}}\n',
        "docs/releases/checksums-v0.9.1.txt": "abc123  tautline-0.9.1.tar.gz\n",
    }
    for rel, text in tracked_files.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").exists()
    assert (tmp_path / "public" / "docs/releases/checksums-v0.9.1.txt").exists()
    assert not (tmp_path / "public" / "docs/releases/release-update-delivery.json").exists()
    assert not (tmp_path / "public" / "docs/backlog/methodology-backlog.md").exists()
    assert not (tmp_path / "public" / "docs/productization/audit-disposition-register.md").exists()
    assert not (tmp_path / "public" / "docs/superpowers/plans/refactor.md").exists()
    assert not (tmp_path / "public" / "docs/product/telemetry-consent.md").exists()
    assert not (tmp_path / "public" / "docs/product/a11y-i18n.md").exists()
    assert (tmp_path / "public" / "docs/product/positioning.md").exists()
    assert (tmp_path / "public" / "docs/product/support-sla-model.md").exists()
    assert not (tmp_path / "public" / ".minervit").exists()
    assert not (tmp_path / "public" / ".minervit/adapter.json").exists()
    assert not (tmp_path / "public" / ".minervit-ai-delivery.json").exists()
    assert not (tmp_path / "public" / ".tautline").exists()
    assert not (tmp_path / "public" / ".tautline/adapter.json").exists()
    assert not (tmp_path / "public" / ".tautline.json").exists()
    # The export marker (same .minervit- name stem, different string) must NOT be
    # swept up by the self-adapter exclusion.
    assert (tmp_path / "public" / cli.PUBLIC_RELEASE_EXPORT_MARKER).exists()


def test_public_release_export_ignores_dirty_and_untracked_excluded_internal_docs(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    internal = source / "docs" / "backlog" / "methodology-backlog.md"
    readme.write_text("# Source\n", encoding="utf-8")
    internal.parent.mkdir(parents=True)
    internal.write_text("internal backlog\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    internal.write_text("internal backlog dirty\n", encoding="utf-8")
    untracked = source / "docs" / "superpowers" / "plans" / "scratch.md"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("scratch\n", encoding="utf-8")
    # Local agent-session state: worktrees of other branches under .claude/
    # appear as untracked noise on workstations and must not make release
    # validation session-dependent (same rationale as the boundary scan's
    # .claude exemption).
    session_state = source / ".claude" / "worktrees" / "wt" / "README.md"
    session_state.parent.mkdir(parents=True)
    session_state.write_text("historical branch checkout\n", encoding="utf-8")

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert cli.public_release_dirty_tracked_paths(source) == []
    assert cli.public_release_untracked_export_paths(source) == []
    assert (tmp_path / "public" / "README.md").exists()
    assert not (tmp_path / "public" / "docs/backlog/methodology-backlog.md").exists()
    assert not (tmp_path / "public" / "docs/superpowers/plans/scratch.md").exists()
    assert not (tmp_path / "public" / ".claude").exists()


def test_public_release_export_can_include_untracked_when_explicit(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    (source / "new-doc.md").write_text("new public doc\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)

    result = cli.public_release_export_repository(source, tmp_path / "public", include_untracked=True)

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").exists()
    assert (tmp_path / "public" / "new-doc.md").exists()


def test_public_release_export_refuses_dirty_tracked_by_default(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")

    try:
        cli.public_release_export_repository(source, tmp_path / "public")
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("dirty tracked file should be refused by default")

    assert "dirty tracked files are not exported by default" in message
    assert not (tmp_path / "public").exists()


def test_public_release_export_can_include_dirty_tracked_when_explicit(cli, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")

    result = cli.public_release_export_repository(source, tmp_path / "public", include_working_tree=True)

    assert result["issues"] == []
    assert (tmp_path / "public" / "README.md").read_text(encoding="utf-8") == "# Source\n\nUncommitted edit\n"


def test_public_release_export_cli_refuses_dirty_tracked_checkout(tmp_path):
    source = tmp_path / "public-release-export-dirty-source"
    cli_path = _copy_cli_with_package(source)
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    with cli_path.open("a", encoding="utf-8") as fh:
        fh.write("\n# validation dirty tracked fixture\n")

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(tmp_path / "public-release-export-default"),
            "--write",
        ],
        env={
            **os.environ,
            "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS": _known_public_release_private_terms(),
        },
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert f"public_release_export_source: {source.resolve()}" in result.stdout
    assert "public_release_export_error: dirty tracked files are not exported by default" in result.stderr
    assert not (tmp_path / "public-release-export-default").exists()


def test_public_release_export_cli_writes_current_tree_candidate(tmp_path):
    destination = tmp_path / "public-release-export"
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "public-release-export",
            "--destination",
            str(destination),
            "--include-working-tree",
            "--include-untracked",
            "--write",
        ],
        env={
            **os.environ,
            "MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS": _known_public_release_private_terms(),
        },
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert f"public_release_export_source: {CLI_PATH.parents[1].resolve()}" in result.stdout
    assert "public_release_export_check: ok" in result.stdout
    assert "release-update-current-missing" not in result.stdout
    assert "release-update-overdue" not in result.stdout
    assert "public_release_export_commit:" in result.stdout
    assert (destination / ".git").exists()
    assert (destination / ".minervit-public-release-export.json").exists()


def test_public_release_export_cli_accepts_private_terms_file_without_leaking_terms(tmp_path):
    destination = tmp_path / "public-release-export"
    terms_file = tmp_path / "private-terms.txt"
    private_term = "Acme" + " Confidential " + "Zulu"
    terms_file.write_text(private_term + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
            "--include-working-tree",
            "--include-untracked",
            "--write",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "public_release_export_private_terms_source: file" in result.stdout
    assert "public_release_export_private_terms_count: 1" in result.stdout
    assert private_term not in result.stdout
    assert private_term not in result.stderr
    marker = (destination / ".minervit-public-release-export.json").read_text(encoding="utf-8")
    marker_payload = json.loads(marker)
    assert marker_payload["privateTermsSource"] == "file"
    assert marker_payload["privateTermsCount"] == 1
    assert private_term not in marker


def test_public_release_export_copied_cli_accepts_json_private_terms_file(tmp_path):
    source = tmp_path / "copied-cli-json-terms-source"
    cli_path = _copy_cli_with_package(source)
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "copied-cli-json-terms-export"
    first_term = "Acme" + " Confidential " + "Json"
    second_term = "Beta" + " Confidential " + "Json"
    terms_file = tmp_path / "private-terms.json"
    terms_file.write_text(json.dumps([first_term, second_term]), encoding="utf-8")
    env = dict(os.environ)
    env.pop("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "public_release_export_private_terms_source: file" in result.stdout
    assert "public_release_export_private_terms_count: 2" in result.stdout
    assert first_term not in result.stdout
    assert second_term not in result.stdout
    assert not destination.exists()


# Note: the copied-bin-without-src execution mode is not supported for extracted
# public-release helpers; public_release_module() now hard-requires src/tautline_methodology
# (SystemExit otherwise, adapter_module()-style), so the former
# test_public_release_export_copied_cli_uses_fallback_with_stale_public_release_package and
# test_public_release_export_copied_cli_uses_fallback_when_public_release_submodule_missing
# copied-bin-standalone-parity tests were deleted.


def test_public_release_export_copied_cli_refuses_private_terms_file_inside_source(tmp_path):
    source = tmp_path / "copied-cli-source-terms-source"
    cli_path = _copy_cli_with_package(source)
    terms_file = source / "private-terms.txt"
    terms_file.write_text("Private Customer Alpha\n", encoding="utf-8")
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src", "private-terms.txt"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "copied-cli-source-terms-export"

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
            "--write",
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "private terms file must be outside the methodology repository" in result.stderr
    assert not destination.exists()


def test_public_release_export_copied_cli_refuses_private_terms_file_inside_destination(tmp_path):
    source = tmp_path / "copied-cli-destination-terms-source"
    cli_path = _copy_cli_with_package(source)
    _init_git_repo(source)
    subprocess.run(["git", "add", "bin/tautline", "src"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    destination = tmp_path / "copied-cli-destination-terms-export"
    terms_file = destination / "private-terms.txt"

    result = subprocess.run(
        [
            sys.executable,
            str(cli_path),
            "public-release-export",
            "--destination",
            str(destination),
            "--private-terms-file",
            str(terms_file),
            "--write",
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 2
    assert "private terms file must be outside the public-release-export destination" in result.stderr
    assert not destination.exists()


def test_public_release_export_refuses_private_terms_file_inside_source(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    # A real checkout, like every other export fixture here: public-release-export is a maintainer
    # verb and now refuses an exec root with no `.git` (a snapshot / copied-out CLI cannot answer
    # the tag, dirty and history-trust reads the export depends on). The containment assertion
    # below is unchanged -- this only stops the fixture from standing in a state production never
    # produces.
    _init_git_repo(source)
    terms_file = source / "private-terms.txt"
    terms_file.write_text("Private Customer Alpha\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=True,
            include_working_tree=True,
            allow_empty_private_terms=False,
            private_terms_file=terms_file,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "private terms file must be outside the methodology repository" in captured.err
    assert not (tmp_path / "public").exists()


def test_public_release_export_refuses_private_terms_file_inside_destination(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)  # see the sibling test: the maintainer verb requires a dev checkout
    destination = tmp_path / "public"
    terms_file = destination / "private-terms.txt"
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=destination,
            write=True,
            force=False,
            include_untracked=True,
            include_working_tree=True,
            allow_empty_private_terms=False,
            private_terms_file=terms_file,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "private terms file must be outside the public-release-export destination" in captured.err
    assert not destination.exists()


def test_public_release_export_cli_refuses_missing_private_terms(tmp_path):
    destination = tmp_path / "public-release-export"
    env = dict(os.environ)
    env.pop("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "public-release-export",
            "--destination",
            str(destination),
            "--include-working-tree",
            "--include-untracked",
            "--write",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 2
    assert "no private product/client terms configured" in result.stderr
    assert "--private-terms-file" in result.stderr
    assert not destination.exists()


def _write_release_update_export_source(source: Path, delivered: str) -> None:
    source.mkdir()
    _init_git_repo(source)
    (source / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (source / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] - 2026-07-05\n\n### Changed\n\n- Test release.\n",
        encoding="utf-8",
    )
    delivery = source / "docs" / "releases" / "release-update-delivery.json"
    delivery.parent.mkdir(parents=True)
    delivery.write_text(
        '{"schema":"minervit-release-update-delivery/v1","delivered":' + delivered + "}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)


def test_public_release_export_command_passes_when_source_ledger_is_delivered(
    cli, tmp_path, monkeypatch, capsys
):
    # Regression: excluding the ledger from the export must not make the
    # release-update gate read a now-absent file in the export tree and report
    # every release as undelivered, which would block every export forever.
    source = tmp_path / "source"
    _write_release_update_export_source(
        source,
        '{"0.1.0":{"at":"2026-07-05T00:00:00+00:00","via":"publish-release-update"}}',
    )
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 0, captured.out
    assert "public_release_export_check: ok" in captured.out
    assert "release-update" not in captured.out
    assert (tmp_path / "public" / "CHANGELOG.md").exists()
    assert not (tmp_path / "public" / "docs/releases/release-update-delivery.json").exists()


def test_public_release_export_refuses_uncommitted_release_update_delivery_marker(cli, tmp_path):
    # Regression: the ledger is export-excluded, so it is no longer among the
    # export-included paths that public_release_dirty_tracked_paths() scans.
    # But the release-update gate is re-rooted to read that same ledger from
    # the SOURCE working tree (release_update_root=source), including
    # uncommitted content. Without this test's fix, someone could write a
    # delivery marker into the ledger, leave it uncommitted, and still pass
    # the export's release-update gate on the strength of content that was
    # never committed. Before the ledger became export-excluded this was
    # impossible: a dirty ledger made the export refuse outright.
    source = tmp_path / "source"
    _write_release_update_export_source(source, "{}")
    delivery = source / "docs" / "releases" / "release-update-delivery.json"
    delivery.write_text(
        '{"schema":"minervit-release-update-delivery/v1","delivered":'
        '{"0.1.0":{"at":"2026-07-05T00:00:00+00:00","via":"publish-release-update"}}}\n',
        encoding="utf-8",
    )

    try:
        cli.public_release_export_repository(source, tmp_path / "public")
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError(
            "an uncommitted release-update delivery marker must not let the export "
            "pass its release-update gate"
        )

    assert "dirty tracked files are not exported by default" in message
    assert not (tmp_path / "public").exists()


def test_public_release_export_succeeds_when_release_update_delivery_marker_is_committed(cli, tmp_path):
    # Companion to the refusal test above: once the delivery marker is
    # actually committed to the source branch, the ledger is clean and the
    # export must proceed normally (guards against over-correcting into an
    # export that always refuses because of the ledger).
    source = tmp_path / "source"
    _write_release_update_export_source(
        source,
        '{"0.1.0":{"at":"2026-07-05T00:00:00+00:00","via":"publish-release-update"}}',
    )

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert not (tmp_path / "public" / "docs/releases/release-update-delivery.json").exists()


def test_public_release_export_repository_refuses_untracked_release_update_delivery_marker(cli, tmp_path):
    # public_release_export_repository() is the helper the CLI wrapper calls,
    # and it re-roots the release-update gate to read the ledger from the
    # SOURCE working tree (release_update_root=source). public_release_dirty_
    # tracked_paths() only ever sees tracked files (it shells out to `git
    # diff`), so an untracked ledger -- written but never `git add`ed --
    # sails past that check entirely. Without a dedicated untracked check in
    # the helper itself, someone could run `publish-release-update`, never
    # stage the ledger, and still pass the export's release-update gate on
    # the strength of delivery evidence that exists in neither the committed
    # source nor the exported tree.
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (source / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] - 2026-07-05\n\n### Changed\n\n- Test release.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    delivery = source / "docs" / "releases" / "release-update-delivery.json"
    delivery.parent.mkdir(parents=True)
    delivery.write_text(
        '{"schema":"minervit-release-update-delivery/v1","delivered":'
        '{"0.1.0":{"at":"2026-07-05T00:00:00+00:00","via":"publish-release-update"}}}\n',
        encoding="utf-8",
    )
    # deliberately never `git add`ed: untracked, not dirty-tracked.

    try:
        cli.public_release_export_repository(source, tmp_path / "public")
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError(
            "an untracked release-update delivery marker must not let the export "
            "pass its release-update gate on the strength of uncommitted, unstaged content"
        )

    assert "docs/releases/release-update-delivery.json" in message
    assert not (tmp_path / "public").exists()


def test_public_release_export_repository_succeeds_when_release_update_delivery_marker_is_tracked(cli, tmp_path):
    # Companion to the refusal test above: once the ledger is `git add`ed
    # (tracked), the untracked-ledger check must not fire, guarding against
    # over-correcting the fix into refusing every export regardless of
    # whether the ledger is actually tracked.
    source = tmp_path / "source"
    _write_release_update_export_source(
        source,
        '{"0.1.0":{"at":"2026-07-05T00:00:00+00:00","via":"publish-release-update"}}',
    )

    result = cli.public_release_export_repository(source, tmp_path / "public")

    assert result["issues"] == []
    assert not (tmp_path / "public" / "docs/releases/release-update-delivery.json").exists()


def test_public_release_export_command_refuses_untracked_by_default(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    (source / "README.md").write_text("# Source\n", encoding="utf-8")
    (source / "scratch.md").write_text("draft notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "untracked files are not exported by default" in captured.err
    assert not (tmp_path / "public").exists()


def test_public_release_export_command_refuses_dirty_tracked_by_default(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    readme = source / "README.md"
    readme.write_text("# Source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    readme.write_text("# Source\n\nUncommitted edit\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", source)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "dirty tracked files are not exported by default" in captured.err
    assert not (tmp_path / "public").exists()


def test_public_release_export_command_warns_to_delete_blocked_candidate(cli, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    _init_git_repo(source)
    private_term = "Fi" + "nch"
    (source / "README.md").write_text(f"# Source\n\nCodename: {private_term}\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=source, check=True)
    monkeypatch.setattr(cli, "REPO_ROOT", source)
    monkeypatch.setenv("MINERVIT_PUBLIC_RELEASE_PRIVATE_TERMS", private_term)

    code = cli.public_release_export(
        Namespace(
            destination=tmp_path / "public",
            write=True,
            force=False,
            include_untracked=False,
            include_working_tree=False,
            allow_empty_private_terms=False,
        )
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "public_release_export_check: blocked" in captured.out
    assert "public_release_export_warning: delete the entire blocked candidate directory" in captured.out
    assert "including its .git history, before sharing it" in captured.out
    assert (tmp_path / "public" / ".git").exists()


# Pre-launch releases whose migration report exists but whose changelog entry does not, anywhere.
# FROZEN: this allowlist may shrink, never grow -- the test asserts both directions.
#
# These are not oversights that can be fixed from this repository. The archive
# (`changelog-prelaunch-root.md`) is dated per entry, and these versions predate the public 0.7.0
# launch, so their release dates exist only in the maintainer's private development repository.
# Writing entries here would mean inventing dates for 21 releases, which is worse than an honest,
# enumerated gap. The content itself IS recoverable from each `docs/releases/migrations/<v>.json`;
# only the dates are not. Closing this needs the private history, and is tracked as backlog 58.
KNOWN_PRELAUNCH_CHANGELOG_GAP = frozenset(
    {
        "0.6.123",
        "0.6.124",
        "0.6.125",
        "0.6.126",
        "0.6.128",
        "0.6.160",
        "0.6.161",
        "0.6.162",
        "0.6.163",
        "0.6.164",
        "0.6.165",
        "0.6.166",
        "0.6.167",
        "0.6.168",
        "0.6.169",
        "0.6.170",
        "0.6.171",
        "0.6.172",
        "0.6.173",
        "0.6.174",
        "0.6.175",
    }
)


def test_every_shipped_release_is_recorded_in_a_changelog(cli):
    """A migration report is proof a version SHIPPED. Every one of them must be findable by a
    reader in exactly one of the two changelogs.

    This invariant was silently false for three releases. `docs/releases/migrations/` carried
    0.6.266, 0.6.267 and 0.6.268, but `CHANGELOG.md` starts at 0.7.0 and the pre-launch archive
    stopped at 0.6.265 -- so three shipped releases had no reader-facing record anywhere. It went
    unnoticed because `CHANGELOG.md`'s own boundary sentence said "through 0.6.265", which
    accurately described the ARCHIVE's coverage and so read as intentional.

    Checked against both files together rather than either alone: the split between them is a
    presentation choice (public launch at 0.7.0), and a release moving across that boundary must
    not be able to fall through the crack between the two.
    """
    root = CLI_PATH.parents[1]

    # A public release export ships tests/ but deliberately does NOT ship docs/productization/
    # (PUBLIC_RELEASE_EXPORT_EXCLUDED_PREFIXES). In an export tree the pre-launch archive is absent
    # BY DESIGN, so this invariant becomes unverifiable there rather than violated -- and it fails
    # twice over, which is why relaxing the is_file() assertion alone would not be enough:
    # 0.6.266-268 are recorded ONLY in that archive, so every one of them would then be reported as
    # a NEW gap by the coverage check below.
    #
    # Keyed on the export MARKER, never on "the archive file happens to be missing". In the
    # maintainer repository a missing archive must stay a hard failure -- that is the entire point
    # of the check, and a skip-if-absent would delete it silently.
    if (root / cli.PUBLIC_RELEASE_EXPORT_MARKER).is_file():
        pytest.skip(
            "public release export tree: docs/productization/ is excluded from the export, so the "
            "pre-launch archive is absent by design and changelog coverage cannot be judged here"
        )

    migrations_dir = root / "docs" / "releases" / "migrations"
    shipped = sorted(
        (path.stem for path in migrations_dir.glob("*.json")),
        key=lambda v: tuple(int(part) for part in v.split(".")),
    )
    assert shipped, "no migration reports found; this test would pass vacuously"

    heading = re.compile(r"^##\s*\[?v?(\d+\.\d+\.\d+)\]?", re.MULTILINE)
    recorded = set()
    for relative in (
        "CHANGELOG.md",
        "docs/productization/archive/changelog-prelaunch-root.md",
    ):
        path = root / relative
        assert path.is_file(), f"expected changelog missing: {relative}"
        recorded.update(heading.findall(path.read_text(encoding="utf-8")))

    missing = {version for version in shipped if version not in recorded}
    new_gaps = sorted(
        missing - KNOWN_PRELAUNCH_CHANGELOG_GAP,
        key=lambda v: tuple(int(part) for part in v.split(".")),
    )
    assert not new_gaps, (
        "these versions shipped a migration report but appear in neither CHANGELOG.md nor "
        f"docs/productization/archive/changelog-prelaunch-root.md: {new_gaps}. Every shipped "
        "release needs a reader-facing entry in one of them. If this fired on a release you just "
        "cut, add its CHANGELOG.md section rather than extending the allowlist below -- that "
        "allowlist is frozen historical debt, not a place to put new releases."
    )

    closed = sorted(
        KNOWN_PRELAUNCH_CHANGELOG_GAP - missing,
        key=lambda v: tuple(int(part) for part in v.split(".")),
    )
    assert not closed, (
        f"these versions are now documented and must be removed from "
        f"KNOWN_PRELAUNCH_CHANGELOG_GAP: {closed}. The allowlist has to shrink as the backfill "
        "lands, or it stops describing anything."
    )


# Published commits whose subject names a version they did not ship (backlog item 63).
# FROZEN: this allowlist may shrink, never grow -- the test asserts both directions.
#
# These cannot be corrected. Both are published on `experimental` and on every clone, so the fix
# is a durable record plus a guard, never a rebase. The release ARTIFACTS are all correct --
# VERSION, CHANGELOG.md and the migration reports are monotonic across every commit that touches
# VERSION -- only the subject lines lie, and the subject is what a human reads when bisecting or
# drafting release notes.
#
# Cause is structural, not carelessness: a squash merge takes its subject from the PR TITLE, which
# is written when the PR is opened and goes stale every time the branch is renumbered. Both PRs
# were renumbered at least once. `tautline merge` now refuses this before the squash is taken;
# this test is the detector for anything that reaches history by another path.
KNOWN_RELEASE_SUBJECT_DRIFT = frozenset(
    {
        # titled "(0.38.0)", shipped 0.36.0 (PR #494)
        "a7fcd3ceccc97ee6e5e958ddf0e2c510ce4e68e9",
        # titled "(0.36.0)", shipped 0.37.0 (PR #491)
        "0b2fe063018fe5ebebf73ee69dc379aeb33314d2",
        # titled "(0.115.0)", shipped 0.116.0 (PR #578, merged 2026-08-21T01:37:36Z).
        #
        # This entry is the one the comment above says must never be added, and it is added
        # anyway, because the alternative is a permanently red `experimental`: the subject is
        # published and cannot be corrected, and this test's second assertion requires the
        # allowlist to describe reality. What makes it tolerable is naming the REAL defect, which
        # is not the stale title: #578 was merged OUTSIDE `tautline merge` -- a direct merge
        # (`autoMergeRequest: null`, zero decision records in the window), so the release-subject
        # guard that exists precisely to refuse this never ran. The detector fired on the first
        # post-merge run, as designed, and the red stood for fourteen hours until a lane read it
        # (item 124's `base-health`, on its first live call). The control gap is the bypass path,
        # tracked as backlog items 2026-08-18-red-check-merge-bypassed-client-gate and 124.
        "905d0e450a1b453326b4d4d9678f5b8f8b428d35",
    }
)
