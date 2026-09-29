"""Path helper primitives for the Tautline CLI.

The goal/milestone ledger paths, the Markdown section reader, the goal-tracker and
backlog-provider config accessors and the whole plan-reference root resolver were deleted in
the 2026-08-28 process-bankruptcy demolition along with the ledgers, boards and plan-review
machinery that were their only callers. What remains are the two path resolvers -- one
contained (adapter-sourced values, sec-config-path-1) and one not (operator-supplied CLI
paths) -- and that distinction is still load-bearing."""

from __future__ import annotations

from pathlib import Path

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
