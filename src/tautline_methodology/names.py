"""Name availability helpers for the Minervit methodology CLI."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def name_availability(
    name: str,
    *,
    opener=urlopen,
    request_cls=Request,
    redact=lambda value: value,
) -> dict[str, str]:
    """Check package-name availability on npm and PyPI.

    A 404 means the name is free; a 200 means it is taken. Network errors
    degrade to "unknown" and never raise.
    """
    results: dict[str, str] = {}
    checks = [
        ("npm", f"https://registry.npmjs.org/{name}"),
        ("pypi", f"https://pypi.org/pypi/{name}/json"),
    ]
    for label, url in checks:
        try:
            with opener(request_cls(url, headers={"User-Agent": "minervit-methodology"}), timeout=15) as resp:
                resp.read(1)
                results[label] = "taken"
        except HTTPError as exc:
            results[label] = "available" if exc.code == 404 else f"http-{exc.code}"
        except (URLError, TimeoutError, OSError) as exc:
            results[label] = f"unknown ({redact(str(exc))})"
    return results
