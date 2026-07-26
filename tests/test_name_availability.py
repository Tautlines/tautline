"""MISSING-trademark (productization): check-name-availability gives the trademark/name-clearance
work real tooling -- it checks npm + PyPI package-name availability (404 == free, 200 == taken) and
degrades to 'unknown' on network errors, never raising. USPTO/domain/GitHub remain manual.
"""

import io
from urllib.error import HTTPError

from tautline_methodology import names


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_available_when_404(cli, monkeypatch):
    def fake_urlopen(req, timeout=0):
        raise HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(cli, "urlopen", fake_urlopen)
    res = cli.name_availability("totally-free-name-xyz")
    assert res["npm"] == "available"
    assert res["pypi"] == "available"
    assert cli.name_availability("totally-free-name-xyz") == names.name_availability(
        "totally-free-name-xyz",
        opener=fake_urlopen,
        request_cls=cli.Request,
        redact=cli.redact_secrets,
    )


def test_taken_when_200(cli, monkeypatch):
    monkeypatch.setattr(cli, "urlopen", lambda req, timeout=0: _Resp(b"{}"))
    res = cli.name_availability("react")
    assert res["npm"] == "taken"
    assert res["pypi"] == "taken"


def test_network_error_is_unknown_not_raise(cli, monkeypatch):
    def boom(req, timeout=0):
        raise OSError("network down")

    monkeypatch.setattr(cli, "urlopen", boom)
    res = cli.name_availability("x")
    assert res["npm"].startswith("unknown")
    assert res["pypi"].startswith("unknown")


def test_command_rejects_invalid_name(run_cli):
    res = run_cli("check-name-availability", "Bad Name!")
    assert res.returncode != 0
    assert "invalid package name" in res.stderr
