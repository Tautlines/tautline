"""Brand guard (rebrand Phase 4.2): the "minervit methodology" framework brand is retired in favor
of "Tautline". Live, reader-facing surfaces must not reintroduce the dead brand. Deliberately NOT
banned: "Minervit" as the maintainer/company name, real on-disk artifact names that still carry the
legacy token until METH-FU-TAUTLINE-FALLBACK-REMOVAL renames them (.minervit-ai-delivery.json,
.minervit/, minervit-local-rescue/, MINERVIT_* env compat), and historical records.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Dead-brand phrases that must never appear on live reader-facing surfaces.
# (tuple, not list: keep out of the policy-phrases SSOT collector)
DEAD_BRAND_PATTERNS = (
    r"Minervit AI Delivery Methodology",
    r"minervit[- ]methodology(?!\.env)",  # the CLI/brand name
    r"minervit/minervit-ai-delivery-methodology",
    r"minervit-ai-delivery-methodology(?!\.md)",  # the repo/product name; archive filename exempt
    r"\.config/minervit/methodology\.env",  # the retired config location (legacy-context mentions exempt)
)

# Live reader-facing surfaces under guard. Code (bin/, plugins/, src/, tests/) and historical
# records join in Phase 6 when the legacy compat surfaces are removed.
GUARDED_PATHS = (
    "README.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "SECURITY.md",
    "TERMS.md",
    "PRIVACY.md",
    "ROADMAP.md",
    "CODE_OF_CONDUCT.md",
    "docs/reference/",
    "docs/governance/",
    "docs/product/",
    "examples/",
)

# Lines that discuss the legacy surface AS a legacy/compat surface are allowed to name it.
LEGACY_CONTEXT_RE = re.compile(r"legacy|compat|deprecated|shim|alias|renamed|formerly|fallback|pre-0\.9", re.I)


def _guarded_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", *GUARDED_PATHS],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [f for f in tracked if f.endswith((".md", ".txt"))]


def test_live_surfaces_do_not_use_the_dead_brand():
    # The exemption is WINDOW-scoped (Codex 0.9.3 T1 P2): a legacy-context word must sit within
    # 60 characters of the matched brand token. A line that merely also says "fallback" while
    # prescribing live legacy commands does not pass.
    patterns = [re.compile(p) for p in DEAD_BRAND_PATTERNS]
    violations: list[str] = []
    for rel in _guarded_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in patterns:
                match = pattern.search(line)
                if not match:
                    continue
                # A prescriptive invocation -- the legacy CLI name followed by a subcommand inside
                # the same backtick span -- is NEVER exempt: describing the shim is fine, telling a
                # reader to RUN it is a live-surface violation (Codex 0.9.3 T1 P2).
                tail = line[match.end():]
                prescriptive = bool(re.match(r" +[a-z][a-z0-9-]*", tail)) and "`" in tail
                window = line[max(0, match.start() - 60):match.end() + 60]
                if not prescriptive and LEGACY_CONTEXT_RE.search(window):
                    continue
                violations.append(f"{rel}:{lineno}: {line.strip()[:100]}")
                break
    assert violations == [], "dead-brand regression on live surfaces:\n" + "\n".join(violations[:40])
