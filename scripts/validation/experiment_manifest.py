#!/usr/bin/env python3

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
MANIFEST_FILENAME = "experiment_manifest.json"
LEGACY_MANIFEST_FILENAME = "manifest.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def git_output(repo_path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_path),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip()


def git_stdout_lines(repo_path: Path, *args: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_path),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return result.stdout.splitlines()


def normalize_relpath(path: str) -> str:
    normalized = path.strip().strip("/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def path_matches_prefix(path: str, prefix: str) -> bool:
    normalized_path = normalize_relpath(path)
    normalized_prefix = normalize_relpath(prefix)
    if not normalized_prefix:
        return False
    return normalized_path == normalized_prefix or normalized_path.startswith(
        normalized_prefix + "/"
    )


def parse_status_paths(line: str) -> list[str]:
    payload = line[3:].strip()
    if " -> " in payload:
        old_path, new_path = payload.split(" -> ", 1)
        return [old_path.strip(), new_path.strip()]
    return [payload]


def git_status_lines(repo_path: Path) -> list[str]:
    return git_stdout_lines(repo_path, "status", "--short", "--untracked-files=all")


def capture_repo_state(
    repo_path: Path, allowed_dirty_relpaths: list[str] | None = None
) -> dict[str, Any]:
    head = git_output(repo_path, "rev-parse", "HEAD")
    branch = git_output(repo_path, "symbolic-ref", "--short", "HEAD")
    allowed_dirty_relpaths = [normalize_relpath(path) for path in (allowed_dirty_relpaths or [])]
    status_lines = git_status_lines(repo_path)
    dirty_entries = []
    ignored_dirty_entries = []
    for line in status_lines:
        paths = parse_status_paths(line)
        if allowed_dirty_relpaths and all(
            any(path_matches_prefix(path, prefix) for prefix in allowed_dirty_relpaths)
            for path in paths
        ):
            ignored_dirty_entries.append(line)
        else:
            dirty_entries.append(line)
    raw_dirty = bool(status_lines)
    return {
        "path": str(repo_path),
        "head": head,
        "branch": branch,
        "dirty": bool(dirty_entries),
        "raw_dirty": raw_dirty,
        "dirty_entries": dirty_entries,
        "ignored_dirty_entries": ignored_dirty_entries,
        "allowed_dirty_paths": allowed_dirty_relpaths,
    }


def prepare_output_dir(output_dir: Path, clean: bool = False) -> None:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def manifest_path(manifest: dict[str, Any], path: str | Path | None) -> str | None:
    if path is None:
        return None
    path_obj = Path(path)
    output_dir = Path(manifest["provenance"]["output_dir"])
    try:
        resolved_path = path_obj.resolve()
        resolved_output_dir = output_dir.resolve()
        return str(resolved_path.relative_to(resolved_output_dir))
    except (RuntimeError, ValueError, FileNotFoundError):
        return str(path_obj)


def build_manifest(
    *,
    title: str,
    component: str,
    question: str,
    output_dir: Path,
    script_path: Path,
    repo_roots: dict[str, Path],
    repo_states: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    acceptance: list[dict[str, Any]] | None = None,
    lifecycle_state: str = "active",
    retention_policy: str = "normal",
) -> dict[str, Any]:
    created_at = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "experiment",
        "title": title,
        "component": component,
        "question": question,
        "tags": tags or [],
        "lifecycle": {
            "state": lifecycle_state,
            "retention_policy": retention_policy,
        },
        "intent": {},
        "provenance": {
            "created_at_utc": created_at,
            "updated_at_utc": created_at,
            "script": str(script_path),
            "output_dir": str(output_dir),
            "repo_states": repo_states
            if repo_states is not None
            else {name: capture_repo_state(path) for name, path in repo_roots.items()},
        },
        "inputs": inputs or {},
        "commands": [],
        "artifacts": [],
        "acceptance": acceptance or [],
        "analyses": [],
        "result": {
            "outcome": "running",
            "summary": "",
            "metrics": {},
        },
        "lessons": [],
        "details": {},
        "supersedes": [],
    }


def stage_intent(
    manifest: dict[str, Any], output_dir: Path, intent_path: Path | None
) -> None:
    if intent_path is None or not intent_path.is_file():
        return
    staged_path = output_dir / intent_path.name
    protected = manifest.get("lifecycle", {}).get("state") == "reference"
    if intent_path.resolve() != staged_path.resolve():
        shutil.copy2(intent_path, staged_path)
    intent_text = intent_path.read_text(encoding="utf-8")
    manifest["intent"] = {
        "source_path": manifest_path(manifest, intent_path),
        "staged_path": manifest_path(manifest, staged_path),
        "text": intent_text,
    }
    add_artifact(
        manifest,
        label="intent",
        path=staged_path,
        category="intent",
        description="Captured experiment intent for this run.",
        retention="keep" if protected else "normal",
        protected=protected,
    )


def add_command(
    manifest: dict[str, Any],
    *,
    label: str,
    argv: list[str],
    cwd: str | Path | None = None,
    stdout_path: str | Path | None = None,
    stderr_path: str | Path | None = None,
    exit_code: int | None = None,
) -> None:
    manifest["commands"].append(
        {
            "label": label,
            "argv": argv,
            "cwd": str(cwd) if cwd is not None else None,
            "stdout_path": manifest_path(manifest, stdout_path),
            "stderr_path": manifest_path(manifest, stderr_path),
            "exit_code": exit_code,
        }
    )


def add_artifact(
    manifest: dict[str, Any],
    *,
    label: str,
    path: str | Path,
    category: str,
    description: str | None = None,
    required: bool = True,
    retention: str = "normal",
    protected: bool = False,
) -> None:
    manifest["artifacts"].append(
        {
            "label": label,
            "path": manifest_path(manifest, path),
            "category": category,
            "description": description,
            "required": required,
            "retention": retention,
            "protected": protected,
        }
    )


def add_lesson(
    manifest: dict[str, Any],
    *,
    text: str,
    status: str = "active",
) -> None:
    manifest["lessons"].append({"status": status, "text": text})


def add_analysis(
    manifest: dict[str, Any],
    *,
    label: str,
    question: str,
    script: str | Path,
    inputs: list[str | Path] | None = None,
    outputs: list[str | Path] | None = None,
    status: str = "active",
    conclusion: str = "",
) -> None:
    manifest["analyses"].append(
        {
            "label": label,
            "question": question,
            "script": manifest_path(manifest, script),
            "inputs": [manifest_path(manifest, path) for path in (inputs or [])],
            "outputs": [manifest_path(manifest, path) for path in (outputs or [])],
            "status": status,
            "conclusion": conclusion,
        }
    )


def set_details(manifest: dict[str, Any], details: dict[str, Any]) -> None:
    manifest["details"] = details


def set_result(
    manifest: dict[str, Any],
    *,
    outcome: str,
    summary: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    manifest["result"] = {
        "outcome": outcome,
        "summary": summary,
        "metrics": metrics or {},
    }


def write_manifest(output_dir: Path, manifest: dict[str, Any]) -> Path:
    manifest["provenance"]["updated_at_utc"] = utc_now_iso()
    manifest_path = output_dir / MANIFEST_FILENAME
    with manifest_path.open("w", encoding="utf-8") as outfile:
        json.dump(manifest, outfile, indent=2, sort_keys=True)

    legacy_path = output_dir / LEGACY_MANIFEST_FILENAME
    with legacy_path.open("w", encoding="utf-8") as outfile:
        json.dump(manifest, outfile, indent=2, sort_keys=True)
    return manifest_path
