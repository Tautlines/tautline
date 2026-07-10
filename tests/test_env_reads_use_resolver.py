import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _direct_minervit_reads(text: str) -> list[str]:
    # os.environ.get("MINERVIT_..") or os.getenv("MINERVIT_..") — the forms we migrate
    pat = re.compile(r"os\.(environ\.get|getenv)\(\s*[\"']MINERVIT_")
    return pat.findall(text)


def test_ghutil_has_no_direct_minervit_env_reads():
    text = (ROOT / "src/minervit_methodology/ghutil.py").read_text()
    assert not _direct_minervit_reads(text), "ghutil must read MINERVIT_ env via resolve_env"


def test_bin_has_no_direct_minervit_env_reads():
    text = (ROOT / "bin/tautline").read_text()
    assert not _direct_minervit_reads(text), "bin must read MINERVIT_ env via resolve_env"
