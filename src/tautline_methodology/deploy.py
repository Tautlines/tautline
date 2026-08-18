"""Deployment health helpers for the Minervit methodology CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .chat import webhook_env_value

from .paths import configured_path as default_configured_path


def normalize_deploy_health_config(raw: object, index: int, defaults: dict) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth must be an object")
    cfg = {**defaults, **raw}
    if "workflow" in raw and str(raw.get("workflow") or "").strip() and "enabled" not in raw:
        cfg["enabled"] = True
    if not isinstance(cfg.get("enabled"), bool):
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.enabled must be boolean")
    if not isinstance(cfg.get("failOnLatestFailure"), bool):
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.failOnLatestFailure must be boolean")
    cfg["provider"] = str(cfg.get("provider") or "").strip()
    if cfg["provider"] not in {"github-actions"}:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.provider must be github-actions")
    cfg["workflow"] = str(cfg.get("workflow") or "").strip()
    cfg["branch"] = str(cfg.get("branch") or "main").strip()
    if cfg["enabled"] and not cfg["workflow"]:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.workflow must be non-blank when enabled")
    if cfg["enabled"] and not cfg["branch"]:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.branch must be non-blank when enabled")
    for key in ["limit", "maxConsecutiveFailures", "maxSuccessAgeHours"]:
        try:
            cfg[key] = int(cfg.get(key, defaults[key]))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.{key} must be an integer") from exc
    if cfg["limit"] < 1:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.limit must be positive")
    if cfg["maxConsecutiveFailures"] < 1:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.maxConsecutiveFailures must be positive")
    if cfg["maxSuccessAgeHours"] < 0:
        raise SystemExit(f"Project adapter deploymentTargets[{index}].deployHealth.maxSuccessAgeHours must be zero or positive")
    return cfg


def deploy_health_configured_targets(data: dict) -> list[dict]:
    return [
        target
        for target in data.get("deploymentTargets", [])
        if isinstance(target, dict) and isinstance(target.get("deployHealth"), dict) and target["deployHealth"].get("enabled")
    ]


def deploy_health_parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def deploy_health_sorted_runs(runs: list[dict]) -> list[dict]:
    return sorted(
        [run for run in runs if isinstance(run, dict)],
        key=lambda run: deploy_health_parse_time(str(run.get("createdAt") or run.get("updatedAt") or ""))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def deploy_health_completed_runs(runs: list[dict]) -> list[dict]:
    return [
        run
        for run in deploy_health_sorted_runs(runs)
        if str(run.get("status") or "").lower() in {"", "completed"} and str(run.get("conclusion") or "").strip()
    ]


def deploy_health_run_label(run: dict) -> str:
    url = str(run.get("url") or "").strip()
    database_id = str(run.get("databaseId") or run.get("id") or "").strip()
    title = str(run.get("displayTitle") or run.get("name") or "").strip()
    label = f"run {database_id}" if database_id else "latest run"
    if title:
        label += f" ({title})"
    if url:
        label += f" {url}"
    return label


def deploy_health_issues_for_runs(
    target_name: str,
    cfg: dict,
    runs: list[dict],
    *,
    defaults: dict,
    failure_conclusions: set[str],
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    issues: list[str] = []
    completed = deploy_health_completed_runs(runs)
    if not completed:
        return [f"{target_name}: no completed deploy workflow runs found for {cfg['workflow']} on {cfg['branch']}"]
    latest = completed[0]
    latest_conclusion = str(latest.get("conclusion") or "").strip().lower()
    if cfg.get("failOnLatestFailure") and latest_conclusion in failure_conclusions:
        issues.append(f"{target_name}: latest deploy workflow concluded {latest_conclusion}: {deploy_health_run_label(latest)}")
    consecutive_failures = 0
    for run in completed:
        conclusion = str(run.get("conclusion") or "").strip().lower()
        if conclusion in failure_conclusions:
            consecutive_failures += 1
            continue
        break
    max_consecutive = int(cfg.get("maxConsecutiveFailures") or defaults["maxConsecutiveFailures"])
    if consecutive_failures >= max_consecutive:
        issues.append(
            f"{target_name}: deploy workflow has {consecutive_failures} consecutive failing runs (threshold {max_consecutive})"
        )
    max_success_age = int(cfg.get("maxSuccessAgeHours") or 0)
    if max_success_age:
        success = next(
            (run for run in completed if str(run.get("conclusion") or "").strip().lower() == "success"),
            None,
        )
        if success is None:
            issues.append(f"{target_name}: no successful deploy workflow run found in the last {len(completed)} completed runs")
        else:
            success_time = deploy_health_parse_time(str(success.get("updatedAt") or success.get("createdAt") or ""))
            if success_time is None:
                issues.append(f"{target_name}: latest successful deploy run has no parseable timestamp: {deploy_health_run_label(success)}")
            else:
                age_hours = (now - success_time).total_seconds() / 3600
                if age_hours > max_success_age:
                    issues.append(
                        f"{target_name}: last successful deploy is {age_hours:.1f}h old (threshold {max_success_age}h): {deploy_health_run_label(success)}"
                    )
    return issues


def deploy_health_runs_from_file(path: Path, cfg: dict) -> list[dict] | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise SystemExit("--runs-file must contain a JSON array or object keyed by workflow")
    workflow = str(cfg.get("workflow") or "")
    if workflow in payload and isinstance(payload[workflow], list):
        return payload[workflow]
    name = Path(workflow).name
    if name in payload and isinstance(payload[name], list):
        return payload[name]
    return None


def deploy_health_github_actions_runs(target: Path, cfg: dict, *, command_runner) -> tuple[list[dict] | None, str | None]:
    command = [
        "gh",
        "run",
        "list",
        "--workflow",
        str(cfg["workflow"]),
        "--branch",
        str(cfg["branch"]),
        "--limit",
        str(cfg["limit"]),
        "--json",
        "databaseId,conclusion,status,createdAt,updatedAt,headSha,url,displayTitle,workflowName",
    ]
    code, stdout, stderr = command_runner(command, cwd=target, timeout=45)
    if code != 0:
        return None, f"gh run list failed for {cfg['workflow']} on {cfg['branch']}: {(stderr or stdout or 'no output').strip()[:240]}"
    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        return None, f"gh run list returned invalid JSON for {cfg['workflow']}: {exc}"
    if not isinstance(payload, list):
        return None, f"gh run list returned non-array JSON for {cfg['workflow']}"
    return payload, None


def deploy_health_issues(
    data: dict,
    target: Path,
    *,
    runs_file: Path | None = None,
    defaults: dict | None = None,
    failure_conclusions: set[str] | None = None,
    command_runner=None,
    configured_targets_func=None,
    runs_from_file_func=None,
    github_actions_runs_func=None,
    issues_for_runs_func=None,
) -> list[str]:
    if configured_targets_func is None:
        configured_targets_func = deploy_health_configured_targets
    if runs_from_file_func is None:
        runs_from_file_func = deploy_health_runs_from_file
    if github_actions_runs_func is None and command_runner is not None:
        def github_actions_runs_func(target_path, cfg):
            return deploy_health_github_actions_runs(
                target_path,
                cfg,
                command_runner=command_runner,
            )

    if issues_for_runs_func is None:
        if defaults is None or failure_conclusions is None:
            raise SystemExit("deploy_health_issues requires defaults and failure_conclusions when issues_for_runs_func is not injected")

        def issues_for_runs_func(target_name, cfg, runs):
            return deploy_health_issues_for_runs(
                target_name,
                cfg,
                runs,
                defaults=defaults,
                failure_conclusions=failure_conclusions,
            )

    issues: list[str] = []
    for deployment in configured_targets_func(data):
        cfg = deployment["deployHealth"]
        name = str(deployment.get("name") or cfg.get("workflow") or "deployment")
        if runs_file is not None:
            runs = runs_from_file_func(runs_file, cfg)
            if runs is None:
                issues.append(f"{name}: --runs-file has no run history for workflow {cfg['workflow']}")
                continue
            error = None
        else:
            if github_actions_runs_func is None:
                raise SystemExit("deploy_health_issues requires github_actions_runs_func or command_runner when runs_file is not provided")
            runs, error = github_actions_runs_func(target, cfg)
        if error:
            issues.append(f"{name}: {error}")
            continue
        issues.extend(issues_for_runs_func(name, cfg, runs or []))
    return issues


def deployment_notification_config(data: dict) -> dict:
    return data["deploymentNotification"]


def deployment_notification_effective_webhook_env(data: dict, *, config_func=None) -> str:
    if config_func is None:
        config_func = deployment_notification_config
    cfg = config_func(data)
    explicit = str(cfg.get("webhookEnv") or "").strip()
    if explicit:
        return explicit
    if cfg.get("reuseIterationReviewWebhook"):
        return str(data["iterationReview"]["delivery"].get("webhookEnv") or "").strip()
    return ""


def deployment_notification_pipeline_issues(
    data: dict,
    target: Path,
    *,
    config_func=None,
    configured_path_func=None,
) -> list[str]:
    if config_func is None:
        config_func = deployment_notification_config
    if configured_path_func is None:
        configured_path_func = default_configured_path
    cfg = config_func(data)
    if not cfg["enabled"]:
        return []
    pipeline = cfg.get("pipeline") or {}
    if not pipeline.get("required"):
        return []
    issues: list[str] = []
    if pipeline.get("mode") != "ci-post-deploy":
        issues.append("deploymentNotification.pipeline.required is true but mode is not ci-post-deploy")
    if not pipeline.get("healthCheckBeforeNotify"):
        issues.append("deploymentNotification.pipeline.healthCheckBeforeNotify must be true for reliable deploy-ready notifications")
    required_command = str(pipeline.get("requiredCommand") or "").strip()
    if not required_command:
        issues.append("deploymentNotification.pipeline.requiredCommand is missing")
    evidence_paths = [str(item).strip() for item in (pipeline.get("evidencePaths") or []) if str(item).strip()]
    if not evidence_paths:
        issues.append("deploymentNotification.pipeline.required is true but no evidencePaths are configured")
        return issues
    for rel_path in evidence_paths:
        path = configured_path_func(target, rel_path)
        if not path.exists():
            issues.append(f"deployment notification pipeline evidence path is missing: {rel_path}")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(f"deployment notification pipeline evidence path is unreadable: {rel_path}: {exc}")
            continue
        command_present = any(
            required_command in line.split("#", 1)[0]
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        if required_command and not command_present:
            issues.append(f"deployment notification pipeline evidence path lacks required command `{required_command}`: {rel_path}")
    return issues


def deployment_notification_marker_path(
    data: dict,
    target: Path,
    marker_slug: str,
    *,
    config_func=None,
    configured_path_func=None,
) -> Path:
    if config_func is None:
        config_func = deployment_notification_config
    if configured_path_func is None:
        configured_path_func = default_configured_path
    cfg = config_func(data)
    return configured_path_func(target, cfg["sentStateDir"]) / f"{marker_slug}.json"


def deployment_notification_latest_marker(
    data: dict,
    target: Path,
    *,
    config_func=None,
    configured_path_func=None,
) -> dict | None:
    if config_func is None:
        config_func = deployment_notification_config
    if configured_path_func is None:
        configured_path_func = default_configured_path
    marker_dir = configured_path_func(target, config_func(data)["sentStateDir"])
    if not marker_dir.exists():
        return None
    markers = sorted(marker_dir.glob("*.json"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    for marker_path in markers:
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        marker["_path"] = marker_path
        return marker
    return None


def deployment_notification_ci_detected(*, environ=None) -> bool:
    if environ is None:
        environ = os.environ
    for env_name in ["GITHUB_ACTIONS", "CI", "CODEBUILD_BUILD_ID", "BUILDKITE", "GITLAB_CI", "CIRCLECI"]:
        if environ.get(env_name, "").strip():
            return True
    return False


def deployment_notification_source(requested_source: str, *, dry_run: bool, ci_detected_func=None) -> str:
    if ci_detected_func is None:
        ci_detected_func = deployment_notification_ci_detected
    requested_source = (requested_source or "auto").strip()
    if requested_source not in {"auto", "pipeline", "agent"}:
        raise SystemExit("publish-deploy-ready-update --source must be auto, pipeline, or agent")
    if requested_source == "agent":
        return "agent"
    if requested_source == "pipeline":
        if not dry_run and not ci_detected_func():
            raise SystemExit(
                "publish-deploy-ready-update --source pipeline requires a CI/deploy environment marker such as CI, GITHUB_ACTIONS, or CODEBUILD_BUILD_ID"
            )
        return "pipeline"
    return "pipeline" if ci_detected_func() else "agent"


def deployment_notification_content_from_args(args) -> str:
    sources = [bool(args.stdin), bool(args.content_file), bool(args.summary)]
    if sum(1 for item in sources if item) > 1:
        raise SystemExit("publish-deploy-ready-update accepts at most one of --stdin, --content-file, or --summary")
    if args.stdin:
        return sys.stdin.read()
    if args.content_file:
        try:
            return args.content_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"deploy-ready update content unreadable: {args.content_file}: {exc}") from exc
    return str(args.summary or "")


def deployment_notification_extra_validation_errors(
    *,
    iteration_review_url: str,
    commit: str,
    secret_patterns: list[str],
) -> list[str]:
    errors: list[str] = []
    if iteration_review_url and not re.match(r"https?://", iteration_review_url):
        errors.append("deploy-ready update iteration review URL must start with http:// or https://")
    for pattern in secret_patterns:
        if re.search(pattern, iteration_review_url):
            errors.append("deploy-ready update iteration_review_url contains a secret-looking value")
            break
    if re.search(r"https://chat\.googleapis\.com/v1/spaces/[^)\s]+", iteration_review_url):
        errors.append("deploy-ready update iteration_review_url must not include Google Chat webhook URLs")
    if commit and not re.fullmatch(r"[A-Za-z0-9._/-]{4,80}", commit):
        errors.append("deploy-ready update commit/ref contains unsupported characters")
    return errors


def deployment_notification_identity_hash(
    *,
    source: str,
    environment: str,
    url: str,
    iteration_review_url: str,
    commit: str,
    content: str,
) -> str:
    identity = "|".join([source, environment, url, iteration_review_url, commit, content.strip()])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def deployment_notification_webhook_url(
    webhook_env: str, *, dry_run: bool, environ=None, value: str | None = None
) -> str:
    webhook_url = value.strip() if value else webhook_env_value(webhook_env, environ)
    if not webhook_url and dry_run:
        webhook_url = "https://example.invalid/google-chat-webhook"
    if not webhook_url:
        raise SystemExit(
            f"deployment notification Google Chat webhook env var is missing: {webhook_env}. "
            f"Check the persisted secrets store with `tautline secret-status --name {webhook_env}` "
            "and re-run through the lane env before treating this as a blocker."
        )
    if not webhook_url.startswith("https://"):
        raise SystemExit(f"deployment notification Google Chat webhook env var must contain an https URL: {webhook_env}")
    return webhook_url


def deployment_notification_marker_record(
    *,
    environment: str,
    url: str,
    iteration_review_url: str,
    commit: str,
    source: str,
    identity_hash: str,
    provider: str,
    webhook_env: str,
    chat_space: str,
    posted_at: str,
) -> dict:
    return {
        "schema": "minervit-deployment-notification/v1",
        "environment": environment,
        "url": url,
        "iterationReviewUrl": iteration_review_url,
        "commit": commit,
        "source": source,
        "identitySha256": identity_hash,
        "provider": provider,
        "webhookEnv": webhook_env,
        "chatSpace": chat_space,
        "postedAt": posted_at,
    }


def deployment_notification_write_marker(
    marker_path: Path,
    *,
    environment: str,
    url: str,
    iteration_review_url: str,
    commit: str,
    source: str,
    identity_hash: str,
    provider: str,
    webhook_env: str,
    chat_space: str,
    posted_at: str,
) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            deployment_notification_marker_record(
                environment=environment,
                url=url,
                iteration_review_url=iteration_review_url,
                commit=commit,
                source=source,
                identity_hash=identity_hash,
                provider=provider,
                webhook_env=webhook_env,
                chat_space=chat_space,
                posted_at=posted_at,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
