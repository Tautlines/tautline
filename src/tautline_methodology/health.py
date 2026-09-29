"""On-demand local and exact-SHA GitHub health observations. Advisory, never a gate."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from tautline_methodology.doctor import _target_integration_branch
from tautline_methodology.util import flatten_printable

TIMEOUT_SECONDS = 8


class HealthUnavailable(Exception):
    pass


def _run(root: Path, command: list[str]) -> str:
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HealthUnavailable("Observation unavailable (missing tool or timeout)") from exc
    if result.returncode:
        # Credentials and remote URLs can occur in stderr. Report the failed observation without
        # copying subprocess output, config, or environment into a report.
        raise HealthUnavailable("Observation unavailable (command failed or access denied)")
    return result.stdout.strip()


def _git(root: Path, *args: str) -> str:
    return _run(root, ["git", *args])


def _gh_json(root: Path, endpoint: str, paginate: bool = False):
    command = ["gh", "api", "--hostname", "github.com", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    try:
        return json.loads(_run(root, command))
    except ValueError as exc:
        raise HealthUnavailable("GitHub returned an unreadable observation") from exc


def _repository(root: Path) -> str:
    url = _git(root, "remote", "get-url", "origin")
    if url.startswith("git@github.com:"):
        path = url.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(url)
        if parsed.hostname != "github.com" or parsed.scheme not in {"https", "ssh"}:
            raise HealthUnavailable("Live CI requires a GitHub.com origin")
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise HealthUnavailable("GitHub origin could not be identified")
    return path


def _ci(root: Path, repo: str, head: str) -> dict:
    pages = _gh_json(root, f"repos/{repo}/commits/{head}/check-runs?per_page=100&filter=latest", True)
    status = _gh_json(root, f"repos/{repo}/commits/{head}/status")
    if not isinstance(pages, list) or not pages or not isinstance(status, dict) or status.get("sha") != head:
        raise HealthUnavailable("CI response did not identify the requested commit")
    checks = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("check_runs"), list):
            raise HealthUnavailable("Incomplete check-run observation")
        checks.extend(page["check_runs"])
    if any(not isinstance(check, dict) or check.get("head_sha") != head for check in checks):
        raise HealthUnavailable("A check run belongs to a different commit")
    count = status.get("total_count")
    if type(count) is not int or count < 0:
        raise HealthUnavailable("Commit status count is unavailable")
    states = []
    for check in checks:
        progress, conclusion = check.get("status"), check.get("conclusion")
        if not isinstance(progress, str) or (conclusion is not None and not isinstance(conclusion, str)):
            states.append("unknown")
        elif progress in {"queued", "in_progress", "waiting", "pending", "requested"}:
            states.append("pending")
        elif progress != "completed":
            states.append("unknown")
        elif conclusion == "success":
            states.append("passed")
        elif conclusion in {"failure", "timed_out", "action_required", "startup_failure", "stale"}:
            states.append("failed")
        elif conclusion == "cancelled":
            states.append("cancelled")
        else:
            states.append("unknown")
    if count:
        combined = status.get("state")
        states.append({"success": "passed", "failure": "failed", "error": "failed",
                       "pending": "pending"}.get(combined, "unknown")
                      if isinstance(combined, str) else "unknown")
    if not states:
        state = "unknown"
    else:
        state = next((value for value in ("failed", "cancelled", "pending", "unknown")
                      if value in states), "passed")
    return {"state": state, "head": head, "checkRuns": len(checks), "commitStatuses": count,
            "reason": "Observed check runs and commit statuses for this exact integration commit"
            if states else "No CI observations for this commit"}


def health_snapshot(target: Path, *, remote: bool = False) -> dict:
    result = {"schema": "tautline-health/v1", "observedAt": datetime.now(timezone.utc).isoformat(),
              "local": {"state": "unknown"},
              "integration": {"state": "unknown", "source": "cached_local_ref"},
              "ci": {"state": "unknown", "reason": "Live CI is queried only with --remote"},
              "deployment": {"state": "unknown", "reason": "No deployment observation collected"}}
    try:
        root = Path(_git(target, "rev-parse", "--show-toplevel"))
        head = _git(root, "rev-parse", "HEAD")
        branch = _git(root, "branch", "--show-current") or "(detached)"
        result["local"] = {"state": "known", "branch": flatten_printable(branch, 160), "head": head}
        integration = _target_integration_branch(root)
        if not integration:
            result["integration"]["reason"] = "No integration branch declared in .tautline.json"
            return result
        # Validate a config-sourced ref before using it in Git or an API path. No shell is used.
        _git(root, "check-ref-format", f"refs/heads/{integration}")
        result["integration"]["branch"] = flatten_printable(integration, 160)
        try:
            cached = _git(root, "rev-parse", "--verify", f"refs/remotes/origin/{integration}^{{commit}}")
            ahead, behind = map(int, _git(root, "rev-list", "--left-right", "--count",
                                         f"{head}...{cached}").split())
            result["integration"].update(state="known", cachedHead=cached, ahead=ahead, behind=behind,
                                          includesCurrentHead=ahead == 0)
        except (HealthUnavailable, ValueError):
            result["integration"]["reason"] = "Cached origin integration ref unavailable"
        if remote:
            try:
                repo = _repository(root)
                observation = _gh_json(root, f"repos/{repo}/commits/{quote(integration, safe='')}")
                remote_head = observation.get("sha") if isinstance(observation, dict) else None
                if not isinstance(remote_head, str) or not re.fullmatch(r"[0-9a-f]{40,64}", remote_head):
                    raise HealthUnavailable("GitHub did not identify the integration commit")
                result["integration"].update(remoteHead=remote_head, remoteSource="github_live_query")
                result["ci"] = _ci(root, repo, remote_head)
            except (HealthUnavailable, ValueError):
                result["ci"] = {"state": "unknown", "reason": "Live integration or CI observation unavailable or incomplete"}
    except (HealthUnavailable, OSError, ValueError):
        result["local"]["reason"] = "Git checkout or integration configuration unavailable"
    return result


def health_command(args: argparse.Namespace) -> int:
    result = health_snapshot(args.target, remote=args.remote)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        local, integration = result["local"], result["integration"]
        print(f"Local: {local.get('branch', 'unknown')} {local.get('head', '')}")
        if integration["state"] == "known":
            print(f"Integration (cached origin/{integration['branch']}): {integration['cachedHead']}")
            print(f"Current branch: {integration['ahead']} ahead, {integration['behind']} behind cached integration")
        else:
            print(f"Integration: unknown — {integration.get('reason', 'not observed')}")
        if integration.get("remoteHead"):
            print(f"Integration (GitHub observation): {integration['remoteHead']}")
        print(f"CI: {result['ci']['state']} — {result['ci']['reason']}")
        print("Deployment: unknown — no deployment observation collected")
    return 0
