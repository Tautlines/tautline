"""Work-profile helper primitives for the Minervit methodology CLI."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path


def path_matches_work_profile_pattern(rel_path: str, pattern: str) -> bool:
    rel_path = rel_path.strip("/")
    pattern = pattern.strip("/")
    if not pattern:
        return False
    if "/" not in pattern and not pattern.startswith("**/"):
        return "/" not in rel_path and fnmatch.fnmatchcase(rel_path, pattern)
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return rel_path == prefix or rel_path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(rel_path, pattern)


def git_blob_sizes(target: Path, object_ids: list[str]) -> dict[str, int]:
    unique_ids = [oid for oid in dict.fromkeys(object_ids) if oid]
    if not unique_ids:
        return {}
    proc = subprocess.run(
        ["git", "-C", str(target), "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        input=("\n".join(unique_ids) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return {}
    sizes: dict[str, int] = {}
    for raw_line in proc.stdout.splitlines():
        parts = raw_line.decode("utf-8", errors="replace").split()
        if len(parts) >= 3 and parts[1] == "blob":
            try:
                sizes[parts[0]] = int(parts[2])
            except ValueError:
                continue
    return sizes


def work_profile_committed_file_metadata(target: Path, event: str, paths: list[str]) -> dict[str, dict]:
    if not paths or event not in {"pre-commit", "pre-push"}:
        return {}
    if event == "pre-commit":
        command = ["git", "-C", str(target), "ls-files", "-s", "-z", "--", *paths]
    else:
        command = ["git", "-C", str(target), "ls-tree", "-rz", "HEAD", "--", *paths]
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        return {}
    metadata: dict[str, dict] = {}
    object_ids: list[str] = []
    for raw_entry in proc.stdout.split(b"\0"):
        if not raw_entry or b"\t" not in raw_entry:
            continue
        raw_meta, raw_path = raw_entry.split(b"\t", 1)
        rel_path = raw_path.decode("utf-8", errors="replace")
        parts = raw_meta.decode("utf-8", errors="replace").split()
        if event == "pre-commit":
            if len(parts) < 2:
                continue
            mode, object_id = parts[0], parts[1]
            object_type = "blob"
        else:
            if len(parts) < 3:
                continue
            mode, object_type, object_id = parts[0], parts[1], parts[2]
        metadata[rel_path] = {"mode": mode, "type": object_type, "objectId": object_id}
        if object_type == "blob":
            object_ids.append(object_id)
    sizes = git_blob_sizes(target, object_ids)
    for item in metadata.values():
        object_id = item.get("objectId")
        if object_id in sizes:
            item["size"] = sizes[object_id]
    return metadata


def work_profile_file_issues(
    data: dict,
    target: Path,
    profile: str,
    profile_cfg: dict,
    paths: list[str],
    *,
    event: str = "status",
    file_metadata: dict[str, dict] | None = None,
) -> list[str]:
    if profile == "development":
        return []
    allowed_paths = profile_cfg["allowedPaths"]
    allowed_extensions = set(profile_cfg["allowedExtensions"])
    blocked_paths = profile_cfg["blockedPaths"]
    max_file_bytes = int(profile_cfg.get("maxFileBytes", 0))
    file_metadata = file_metadata or {}
    issues: list[str] = []
    for rel_path in paths:
        normalized = rel_path.strip("/")
        absolute = target / normalized
        metadata = file_metadata.get(rel_path) or file_metadata.get(normalized) or {}
        if any(path_matches_work_profile_pattern(normalized, pattern) for pattern in blocked_paths):
            issues.append(f"{normalized}: blocked path for {profile}; switch to development for code/config/generated artifacts")
            continue
        mode = str(metadata.get("mode", ""))
        if mode == "120000" or (event not in {"pre-commit", "pre-push"} and absolute.is_symlink()):
            issues.append(f"{normalized}: symlinks are not allowed in {profile}")
            continue
        if mode == "160000":
            issues.append(f"{normalized}: gitlinks/submodules are not allowed in {profile}")
            continue
        if not any(path_matches_work_profile_pattern(normalized, pattern) for pattern in allowed_paths):
            issues.append(f"{normalized}: outside allowed docs/assets paths for {profile}")
            continue
        suffix = Path(normalized).suffix.lower()
        if suffix not in allowed_extensions:
            issues.append(f"{normalized}: extension {suffix or '<none>'} is not allowed in {profile}")
            continue
        size = metadata.get("size")
        if size is None and event not in {"pre-commit", "pre-push"} and absolute.exists() and absolute.is_file():
            try:
                size = absolute.stat().st_size
            except OSError:
                size = 0
        if max_file_bytes and isinstance(size, int):
            if size > max_file_bytes:
                issues.append(
                    f"{normalized}: file is {size} bytes, over {profile} maxFileBytes={max_file_bytes}; "
                    "use adapter-approved LFS/asset policy or reduce the artifact"
                )
    return issues
