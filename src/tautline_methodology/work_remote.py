"""Explicit, bounded GitHub observations attached to advisory work declarations."""
from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tautline_methodology.util import child_env

MAX_PRS = 8
MAX_PAGES = 3
MAX_RESPONSE_BYTES = 2_000_000
TERMINAL = {"completed", "abandoned"}
_PR_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]{0,9})/?",
    re.IGNORECASE,
)
_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


class ObservationUnavailable(Exception):
    """Only static, credential-safe explanations cross this boundary."""


def _url(value: object) -> tuple[str, str, int] | None:
    match = _PR_URL.fullmatch(value) if isinstance(value, str) else None
    if not match or any(part in {".", ".."} for part in match.groups()[:2]):
        return None
    owner, name, number = match.groups()
    repo = f"{owner}/{name}".lower()
    return f"https://github.com/{repo}/pull/{number}", repo, int(number)


def _stop(process: subprocess.Popen) -> None:
    # Killing the group also stops a credential helper or descendant holding stdout open.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=0.05)
    except subprocess.TimeoutExpired:
        pass


def _gh_json(target: Path, endpoint: str, deadline: float):
    if time.monotonic() >= deadline:
        raise ObservationUnavailable("Remote observation time budget exhausted")
    process = None
    try:
        process = subprocess.Popen(
            ["gh", "api", "--hostname", "github.com", endpoint], cwd=target,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=child_env(GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0"),
            start_new_session=True,
        )
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ObservationUnavailable("Remote observation time budget exhausted")
                ready = selector.select(remaining)
                if not ready:
                    raise ObservationUnavailable("Remote observation time budget exhausted")
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > MAX_RESPONSE_BYTES:
                    raise ObservationUnavailable("GitHub response exceeds observation size limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ObservationUnavailable("Remote observation time budget exhausted")
        if process.wait(timeout=remaining):
            raise ObservationUnavailable("GitHub observation unavailable or access denied")
        return json.loads(output)
    except (OSError, subprocess.TimeoutExpired, ValueError, RecursionError) as exc:
        raise ObservationUnavailable("GitHub observation unavailable or unreadable") from exc
    finally:
        if process is not None:
            _stop(process)
            if process.stdout:
                process.stdout.close()


def _pull(target: Path, repo: str, number: int, deadline: float) -> tuple[str, str]:
    data = _gh_json(target, f"repos/{repo}/pulls/{number}", deadline)
    if not isinstance(data, dict):
        raise ObservationUnavailable("GitHub returned an incomplete PR observation")
    head = data.get("head")
    base = data.get("base")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    identity = _url(data.get("html_url"))
    if (type(data.get("number")) is not int or data["number"] != number
            or identity is None or identity[1:] != (repo, number)
            or not isinstance(base_repo, dict)
            or not isinstance(base_repo.get("full_name"), str)
            or base_repo["full_name"].lower() != repo
            or not isinstance(head, dict) or not isinstance(head.get("sha"), str)
            or not _SHA.fullmatch(head["sha"])
            or type(data.get("merged")) is not bool or type(data.get("draft")) is not bool
            or data.get("state") not in ("open", "closed")
            or (data["merged"] and data["state"] != "closed")):
        raise ObservationUnavailable("GitHub PR identity or state is incomplete")
    state = ("merged" if data["merged"] else "closed" if data["state"] == "closed"
             else "draft" if data["draft"] else "open")
    return state, head["sha"]


def _pages(target: Path, repo: str, head: str, kind: str, deadline: float) -> list:
    records: list = []
    ids: set[int] = set()
    count = None
    combined = None
    for page in range(1, MAX_PAGES + 1):
        endpoint = f"repos/{repo}/commits/{head}/{kind}?per_page=100&page={page}"
        if kind == "check-runs":
            endpoint += "&filter=latest"
        data = _gh_json(target, endpoint, deadline)
        key = "check_runs" if kind == "check-runs" else "statuses"
        if (not isinstance(data, dict) or type(data.get("total_count")) is not int
                or data["total_count"] < 0 or not isinstance(data.get(key), list)):
            raise ObservationUnavailable("Incomplete CI observation")
        if kind == "status" and (data.get("sha") != head
                                   or data.get("state") not in ("success", "failure", "pending")):
            raise ObservationUnavailable("Commit statuses did not identify the observed PR head")
        if kind == "status":
            if combined is not None and combined != data["state"]:
                raise ObservationUnavailable("Commit statuses changed while reading pages")
            combined = data["state"]
        if count is not None and count != data["total_count"]:
            raise ObservationUnavailable("CI observations changed while reading pages")
        count = data["total_count"]
        if count > MAX_PAGES * 100 or len(data[key]) > 100:
            raise ObservationUnavailable("CI observations exceed the bounded page limit")
        for record in data[key]:
            if (not isinstance(record, dict) or type(record.get("id")) is not int
                    or record["id"] <= 0 or record["id"] in ids):
                raise ObservationUnavailable("Malformed or repeated CI observation")
            if kind == "check-runs" and record.get("head_sha") != head:
                raise ObservationUnavailable("A check run belongs to another PR head")
            ids.add(record["id"])
            records.append(record)
        if len(records) == count:
            if kind == "status":
                values = [record.get("state") for record in records]
                expected = ("pending" if not records else
                            "failure" if any(v in ("failure", "error") for v in values)
                            else "pending" if "pending" in values else "success")
                if combined != expected:
                    raise ObservationUnavailable("Inconsistent combined commit status")
            return records
        if not data[key] or len(records) > count:
            raise ObservationUnavailable("Incomplete CI page coverage")
    raise ObservationUnavailable("CI observations exceed the bounded page limit")


def _ci(target: Path, repo: str, head: str, deadline: float) -> str:
    checks = _pages(target, repo, head, "check-runs", deadline)
    statuses = _pages(target, repo, head, "status", deadline)
    states = []
    for check in checks:
        progress, conclusion = check.get("status"), check.get("conclusion")
        if progress in ("queued", "in_progress", "waiting", "pending", "requested"):
            states.append("pending" if conclusion is None else "unknown")
        elif progress != "completed" or not isinstance(conclusion, str):
            states.append("unknown")
        elif conclusion == "success":
            states.append("passed")
        elif conclusion in ("failure", "timed_out", "action_required", "startup_failure", "stale"):
            states.append("failed")
        elif conclusion == "cancelled":
            states.append("cancelled")
        else:
            states.append("unknown")
    for status in statuses:
        value = status.get("state")
        states.append({"success": "passed", "failure": "failed", "error": "failed",
                       "pending": "pending"}.get(value, "unknown")
                      if isinstance(value, str) else "unknown")
    return next((value for value in ("failed", "cancelled", "pending", "unknown")
                 if value in states), "passed" if states else "unknown")


def _unknown(reason: str, url: str | None = None) -> dict:
    return {"state": "unknown", "headSha": None, "ci": "unknown", "observedAt": None,
            "url": url, "reason": reason, "deployment": "unknown"}


def _observe(target: Path, identity: tuple[str, str, int], deadline: float) -> dict:
    url, repo, number = identity
    observation = _unknown("PR has not been observed", url)
    try:
        state, head = _pull(target, repo, number, deadline)
        observation.update(state=state, headSha=head, observedAt=time.time())
        ci = _ci(target, repo, head, deadline)
        # A push while checks were queried must not attach an old pass to the current PR head.
        final_state, final_head = _pull(target, repo, number, deadline)
        observation.update(state=final_state, headSha=final_head, observedAt=time.time())
        if final_head != head:
            observation["reason"] = "PR head changed during observation; refresh to inspect its CI"
        else:
            observation.update(ci=ci, reason=("CI observations absent or inconclusive"
                                             if ci == "unknown" else ""))
    except ObservationUnavailable as exc:
        observation["reason"] = str(exc)
    except Exception:
        # A malformed peer response must not discard healthy observations for other lanes.
        observation["reason"] = "GitHub observation unavailable or malformed"
    return observation


def attach_observations(target: Path, state: dict, *, all_records: bool = False,
                        timeout: float = 5.0) -> dict:
    """Enrich visible PR references on explicit request; never persist or alter lane state."""
    deadline = time.monotonic() + max(0.0, min(float(timeout), 5.0))
    records = [record for record in state["records"] if record.get("pr")
               and (all_records or record["state"].lower() not in TERMINAL)]
    identities: dict[str, tuple[str, str, int]] = {}
    for record in records:
        identity = _url(record["pr"])
        if identity is None:
            record["prObservation"] = _unknown("Only GitHub.com HTTPS pull-request URLs are supported")
        elif identity[0] not in identities and len(identities) >= MAX_PRS:
            record["prObservation"] = _unknown("Unique PR observation limit reached", identity[0])
        else:
            identities[identity[0]] = identity
    if not identities:
        return state
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="tautline-pr") as pool:
        futures = {url: pool.submit(_observe, target, identity, deadline)
                   for url, identity in identities.items()}
        results = {url: future.result() for url, future in futures.items()}
    for record in records:
        identity = _url(record["pr"])
        if identity and identity[0] in results:
            record["prObservation"] = results[identity[0]]
    return state
