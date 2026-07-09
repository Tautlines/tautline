import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "bin" / "tautline"
EXAMPLE_ADAPTER = REPO_ROOT / "adapters" / "projects" / "example-saas.json"


VALID_MILESTONE_UPDATE = """## Plain English
The milestone finished and the product owner can see what changed without waiting for the full goal.

## Progress
Goal G1 is halfway complete; milestone M1 is complete and the next milestone is ready.

## What Changed
The implementation shipped the focused milestone scope and recorded the remaining follow-up work.

## Validation
Local validation and review evidence passed for the completed milestone.

## Next
Continue directly into the next reviewed milestone plan.

## Technical Details
PR #12 merged with validation logs recorded in the lane evidence directory.
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _run_cli(
    tmp_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    command_env = {**os.environ, "HOME": str(home), "MINERVIT_METHODOLOGY_REPO": ""}
    if env:
        command_env.update(env)
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        env=command_env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def _prepare_target(tmp_path: Path) -> Path:
    target = tmp_path / "delivery-target"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "test@example.invalid")
    _git(target, "config", "user.name", "Test User")
    _git(target, "remote", "add", "origin", "git@github.com:example-org/example-saas.git")
    (target / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-m", "Initial fixture", "-q")
    return target


def _write_pipeline_adapter(path: Path) -> Path:
    adapter = json.loads(EXAMPLE_ADAPTER.read_text(encoding="utf-8"))
    adapter["latestCode"] = {"enabled": False}
    adapter["bootstrapEvidence"] = {
        "project": "Example SaaS",
        "status": "repo-evident",
        "summary": "Pytest fixture for deployment notification pipeline coverage.",
        "repoEvidence": [
            {"path": "docs/product/specs/product-direction.md", "fact": "Product direction fixture exists."},
            {"path": "docs/product/specs/technical-shape.md", "fact": "Technical shape fixture exists."},
        ],
    }
    adapter["deploymentNotification"] = {
        "enabled": True,
        "trigger": "deploy-ready",
        "provider": "google-chat-webhook",
        "webhookEnv": "EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK",
        "reuseIterationReviewWebhook": False,
        "chatSpace": "Example SaaS Deploys",
        "dedupe": True,
        "sentStateDir": ".ai-work/deployment-notification-delivery",
        "maxChars": 3000,
        "pipeline": {
            "required": True,
            "mode": "ci-post-deploy",
            "evidencePaths": [".github/workflows/deploy.yml"],
            "requiredCommand": "tautline publish-deploy-ready-update",
            "healthCheckBeforeNotify": True,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(adapter, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_deployment_notification_status_publish_and_pipeline_guards(tmp_path):
    target = _prepare_target(tmp_path)

    missing_env = _run_cli(
        tmp_path,
        "deployment-notification-status",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--strict",
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": ""},
        check=False,
    )
    assert missing_env.returncode == 1
    assert "deployment notification Google Chat webhook env var is missing" in missing_env.stdout

    status = _run_cli(
        tmp_path,
        "deployment-notification-status",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    )
    assert "deployment_notification: enabled=true" in status.stdout
    assert "deployment_notification_webhook_value: set" in status.stdout
    assert "deployment_notification_pipeline_required: true" in status.stdout

    published = _run_cli(
        tmp_path,
        "publish-deploy-ready-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--environment",
        "dev",
        "--url",
        "https://dev.example.test/example-saas",
        "--iteration-review-url",
        "https://reviews.example.com/example-saas/iteration-reviews/catalog/index.html",
        "--source",
        "agent",
        "--summary",
        "The latest reviewed catalog change is live on dev and ready for review.",
        "--dry-run",
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    )
    assert "deployment_notification_chat_post_dry_run: google-chat-webhook" in published.stdout
    assert "deployment_notification_chat_posted: dry_run" in published.stdout
    assert "deployment_notification_source: agent" in published.stdout

    secret_url = _run_cli(
        tmp_path,
        "publish-deploy-ready-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--environment",
        "dev",
        "--url",
        "https://dev.example.test/example-saas",
        "--iteration-review-url",
        "https://chat.googleapis.com/v1/spaces/AAA/messages?key=SECRET&token=TOKEN",
        "--dry-run",
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
        check=False,
    )
    assert secret_url.returncode == 1
    assert "iteration_review_url must not include Google Chat webhook URLs" in secret_url.stderr

    (target / "docs" / "product" / "specs").mkdir(parents=True)
    (target / "docs" / "product" / "specs" / "product-direction.md").write_text("# Product Direction\n", encoding="utf-8")
    (target / "docs" / "product" / "specs" / "technical-shape.md").write_text("# Technical Shape\n", encoding="utf-8")
    adapter = _write_pipeline_adapter(target / ".minervit" / "adapter.json")
    pipeline_missing = _run_cli(
        tmp_path,
        "deployment-notification-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
        check=False,
    )
    assert pipeline_missing.returncode == 1
    assert "pipeline evidence path is missing: .github/workflows/deploy.yml" in pipeline_missing.stdout

    workflow = target / ".github" / "workflows" / "deploy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        """name: deploy
# tautline publish-deploy-ready-update TODO
jobs:
  deploy:
    steps:
      - run: echo "deploy and health check only"
""",
        encoding="utf-8",
    )
    no_command = _run_cli(
        tmp_path,
        "deployment-notification-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
        check=False,
    )
    assert no_command.returncode == 1
    assert "pipeline evidence path lacks required command `tautline publish-deploy-ready-update`" in no_command.stdout

    workflow.write_text(
        """name: deploy
jobs:
  deploy:
    steps:
      - run: curl --fail "$DEPLOY_READY_URL/health"
      - run: |
          tautline publish-deploy-ready-update \\
            --target . \\
            --environment "${DEPLOY_ENVIRONMENT:-dev}" \\
            --url "${DEPLOY_READY_URL}" \\
            --source pipeline \\
            --summary "Deploy health checks passed; the live site is ready for review."
""",
        encoding="utf-8",
    )
    pipeline_ok = _run_cli(
        tmp_path,
        "deployment-notification-status",
        "--project",
        str(adapter),
        "--target",
        str(target),
        "--strict",
        env={"EXAMPLE_SAAS_DEPLOY_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    )
    assert "deployment_notification_pipeline_required: true" in pipeline_ok.stdout
    assert "deployment_notification_pipeline_status: configured" in pipeline_ok.stdout
    snippet = _run_cli(tmp_path, "deployment-notification-pipeline-snippet", "--project", str(adapter), "--target", str(target))
    assert "Put this in the deploy/build workflow after deploy completion and live-site health checks" in snippet.stdout
    assert "tautline publish-deploy-ready-update" in snippet.stdout
    assert "--source pipeline" in snippet.stdout


def test_milestone_update_status_publish_slug_and_validation_guards(tmp_path):
    target = _prepare_target(tmp_path)

    missing_env = _run_cli(
        tmp_path,
        "milestone-update-status",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--strict",
        env={"EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": ""},
        check=False,
    )
    assert missing_env.returncode == 1
    assert "milestoneUpdate webhook env var is missing" in missing_env.stdout

    status = _run_cli(
        tmp_path,
        "milestone-update-status",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        env={"EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    )
    assert "milestone_update: enabled=true" in status.stdout
    assert "milestone_update_rule: milestone-complete requires a text-only internal Product Milestones update" in status.stdout
    assert "milestone_update_webhook_value: set" in status.stdout

    (target / ".ai-work").mkdir(exist_ok=True)
    (target / ".ai-work" / "GOAL_RUN.json").write_text(
        json.dumps(
            {
                "schema": "minervit-goal-run/v1",
                "goalId": "milestone-update-canonicalization",
                "status": "active",
                "sourceGoal": "docs/product/specs/goals/milestone-update-canonicalization.md",
                "activeMilestone": 0,
                "milestones": [
                    {
                        "index": 1,
                        "id": "M1",
                        "title": "Alpha Launch Milestone",
                        "status": "in-progress",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    content = tmp_path / "valid-milestone-update.md"
    content.write_text(VALID_MILESTONE_UPDATE, encoding="utf-8")
    published = _run_cli(
        tmp_path,
        "publish-milestone-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--milestone",
        "M1",
        "--content-file",
        str(content),
        "--dry-run",
        env={"EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    )
    assert "milestone_update: alpha-launch-milestone" in published.stdout
    assert "milestone_update_chat_post_dry_run: google-chat-webhook" in published.stdout
    assert "milestone_update_chat_space: Product Milestones" in published.stdout

    marker_path = target / ".ai-work" / "milestone-update-delivery" / "alpha-launch-milestone.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            {
                "schema": "minervit-milestone-update-delivery/v1",
                "milestone": "Alpha Launch Milestone",
                "contentSha256": hashlib.sha256(VALID_MILESTONE_UPDATE.strip().encode("utf-8")).hexdigest(),
                "provider": "google-chat-webhook",
                "webhookEnv": "EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK",
                "chatSpace": "Product Milestones",
                "postedAt": "2026-07-06T00:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    already_sent = _run_cli(
        tmp_path,
        "publish-milestone-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--milestone",
        "M1",
        "--content-file",
        str(content),
        env={"EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": ""},
    )
    assert "milestone_update: alpha-launch-milestone" in already_sent.stdout
    assert "milestone_update_chat_posted: already_sent" in already_sent.stdout

    forced = _run_cli(
        tmp_path,
        "publish-milestone-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--milestone",
        "M1",
        "--content-file",
        str(content),
        "--dry-run",
        "--force",
        env={"EXAMPLE_SAAS_PRODUCT_MILESTONES_GOOGLE_CHAT_WEBHOOK": ""},
    )
    assert "milestone_update_chat_post_dry_run: google-chat-webhook" in forced.stdout
    assert "milestone_update_chat_posted: dry_run" in forced.stdout

    (target / ".ai-work" / "GOAL_RUN.json").unlink()
    missing_heading = _run_cli(
        tmp_path,
        "publish-milestone-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--milestone",
        "M1",
        "--summary",
        "## Plain English\nMissing sections",
        "--dry-run",
        check=False,
    )
    assert missing_heading.returncode == 1
    assert "milestone update content missing required heading: ## Progress" in missing_heading.stderr

    secret_content = tmp_path / "secret-milestone-update.md"
    secret_content.write_text(
        VALID_MILESTONE_UPDATE
        + "\nWebhook: https://chat.googleapis.com/v1/spaces/AAA/messages?key=SECRET&token=TOKEN\n",
        encoding="utf-8",
    )
    secret = _run_cli(
        tmp_path,
        "publish-milestone-update",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--milestone",
        "M1",
        "--content-file",
        str(secret_content),
        "--dry-run",
        check=False,
    )
    assert secret.returncode == 1
    assert "Google Chat webhook URLs" in secret.stderr


def test_product_note_publish_dry_run_cli_contract(tmp_path):
    target = _prepare_target(tmp_path)

    published = _run_cli(
        tmp_path,
        "publish-product-note",
        "--project",
        str(EXAMPLE_ADAPTER),
        "--target",
        str(target),
        "--title",
        "Customer Wireframes Ready",
        "--summary",
        "Wireframes are ready for product review.",
        "--dry-run",
        env={"EXAMPLE_SAAS_PRODUCT_CHAT_GOOGLE_CHAT_WEBHOOK": "https://example.invalid/google-chat-webhook"},
    )

    assert "product_note: customer-wireframes-ready" in published.stdout
    assert "product_note_chat_post_dry_run: google-chat-webhook" in published.stdout
    assert "product_note_chat_space: Example SaaS Product" in published.stdout
