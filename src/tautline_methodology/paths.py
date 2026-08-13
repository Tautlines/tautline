"""Path, Markdown, and adapter-config helper primitives for the Minervit CLI."""

from __future__ import annotations

import re
from pathlib import Path

from . import plan_reference


def configured_path(target: Path, path_text: str, *, allow_outside: bool = False) -> Path:
    """Resolve an adapter/CLI-configured path against the project ``target``.

    sec-config-path-1: by default the resolved path must stay under ``target`` even after ``..``
    normalization; absolute and ``~``-expanded paths escape it and are rejected. This is the runtime
    backstop for adapter values that bypass schema validation. ``allow_outside=True`` opts a call
    site out for fields that legitimately live outside the project root (e.g. the framework's shared
    ``~/.claude/plans/`` scratch dir, lane-coordination roots, and operator-supplied CLI paths).
    """
    path = Path(path_text).expanduser()
    resolved = path if path.is_absolute() else target / path
    if not allow_outside:
        candidate = resolved.resolve(strict=False)
        target_root = target.resolve(strict=False)
        if candidate != target_root and not candidate.is_relative_to(target_root):
            raise ValueError(
                f"configured path {path_text!r} escapes the project root {target} "
                f"(resolved to {candidate}); adapter paths must stay under the project root "
                "(set allow_outside for fields that are intentionally external)"
            )
    return resolved


def cli_path(target: Path, path_text: str) -> Path:
    """Resolve an operator-supplied CLI path or framework-internal computed path against ``target``.

    Sibling of :func:`configured_path` WITHOUT the sec-config-path-1 containment backstop. Containment's
    threat model is adversarial *adapter-config* values that bypass schema validation (see A5). Operator-
    typed CLI file arguments (e.g. ``monitor-status --log /tmp/run.log``) and paths the framework itself
    wrote into run metadata / manifests / ledgers are trusted external inputs that legitimately live
    outside the project root, so they MUST NOT be contained. Do NOT use this for any adapter-sourced value
    -- those stay on :func:`configured_path`.
    """
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else target / path


def goal_run_path(data: dict, target: Path) -> Path:
    return target / data["laneState"]["goalRun"]


def milestone_run_path(data: dict, target: Path) -> Path:
    return target / data["laneState"]["milestoneRun"]


def markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.end() : end].strip()


def goal_tracker_config(data: dict) -> dict:
    return data["goalTracker"]


def backlog_provider_config(data: dict) -> dict:
    return data["backlogProvider"]


def plan_repo_setting(data: dict) -> str:
    """The configured ``backlogProvider.planRepo`` value, or ``""`` when unset.

    Read tolerantly: plan-root resolution runs in contexts that hold a partial adapter, and an
    absent key must mean "lane-only", never an error.
    """
    provider = data.get("backlogProvider") if isinstance(data, dict) else None
    if not isinstance(provider, dict):
        return ""
    return str(provider.get("planRepo") or "").strip()


def configured_plan_roots(data: dict, target: Path) -> dict[str, Path]:
    """Map every configured plan-root token to its filesystem root.

    `lane` is always present and always the project ``target``. A configured plan repo is added
    under **its own directory basename**, dynamically -- no spelling is blessed. The real repo is
    ``tautline-backlog``; ``backlog`` appears in older fixtures only because one fixture repo was
    named that, and hardcoding it would leave every real lane unresolved (R3 P1).

    Deliberately does NOT consult ``backlogProvider.enabled``. This repository's own adapter has the
    provider disabled while its plans live externally, so gating on ``enabled`` would make the
    framework unable to dogfood the feature it ships.
    """
    # Both roots are normalized the same way. The realistic configured value is relative
    # (`../tautline-backlog`), and a root carrying a literal `..` compares unequal to the same
    # directory spelled directly -- which W2 would then record as a different manifest identity.
    roots: dict[str, Path] = {plan_reference.LANE_ROOT: target.resolve()}
    setting = plan_repo_setting(data)
    if not setting:
        return roots

    # sec-config-path-1 contains adapter paths under the project root, which would refuse a sibling
    # checkout before root resolution ever ran (R3 P2). The allowance is deliberate and narrow: it
    # applies to this one key, and `lane` above stays contained, so this is not a general escape.
    repo = configured_path(target, setting, allow_outside=True).resolve()
    token = repo.name
    if token == plan_reference.LANE_ROOT:
        raise ValueError(
            f"backlogProvider.planRepo {setting!r} has basename "
            f"{plan_reference.LANE_ROOT!r}, which is the reserved root for the lane itself; "
            "rename the plan repository directory, because allowing it would silently "
            "reinterpret every reference already recorded against the lane"
        )
    roots[token] = repo
    return roots


def resolve_plan_reference(data: dict, target: Path, text: str) -> Path:
    """Resolve a recorded plan reference -- rooted or bare legacy -- to a filesystem path.

    The composition callers actually want: parse the shape, resolve the root, join. A bare legacy
    string reads as the lane, so references recorded before item 59 resolve exactly as they always
    did.
    """
    root, relative = plan_reference.parse_plan_reference(text)
    return resolve_plan_root(data, target, root) / relative


def resolve_plan_root(data: dict, target: Path, root: str) -> Path:
    """Resolve a plan-reference root token to its filesystem root, or fail loudly.

    This is where an unknown token becomes an error. The parser accepts any shape on purpose, so a
    token that names nothing configured can only be caught here -- and the message names the roots
    that ARE configured, because "unknown root" without that list sends the reader looking in the
    wrong file.
    """
    roots = configured_plan_roots(data, target)
    if root in roots:
        return roots[root]
    known = ", ".join(sorted(roots))
    raise ValueError(
        f"plan reference root {root!r} is not a configured plan root for this lane; "
        f"configured roots are: {known}"
    )
