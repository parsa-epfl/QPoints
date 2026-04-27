#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


VALIDATION_ROOT = Path(__file__).resolve().parent
QPOINTS_ROOT = VALIDATION_ROOT.parent.parent
QFLEX_ROOT = QPOINTS_ROOT.parent
GEM5_ROOT = QPOINTS_ROOT / "gem5"

if str(VALIDATION_ROOT) not in sys.path:
    sys.path.insert(0, str(VALIDATION_ROOT))

from experiment_manifest import (  # noqa: E402
    add_artifact,
    add_command,
    build_manifest,
    capture_repo_state,
    normalize_relpath,
    prepare_output_dir,
    set_result,
    stage_intent,
    write_manifest,
)


def parse_stat_requirement(spec: str) -> tuple[str, str, int]:
    parts = [part.strip() for part in spec.split(",", 2)]
    if len(parts) != 3:
        raise SystemExit(
            f"Invalid --require-stat spec {spec!r}. Use 'stat_name,op,expected'."
        )
    stat_name, op, expected_text = parts
    if op not in {"gt", "ge", "eq", "le", "lt"}:
        raise SystemExit(
            f"Invalid stat operator {op!r} in {spec!r}. Use one of gt, ge, eq, le, lt."
        )
    try:
        expected = int(expected_text)
    except ValueError as exc:
        raise SystemExit(
            f"Invalid expected value {expected_text!r} in {spec!r}; use an integer."
        ) from exc
    return stat_name, op, expected


def stat_matches(actual: int, op: str, expected: int) -> bool:
    if op == "gt":
        return actual > expected
    if op == "ge":
        return actual >= expected
    if op == "eq":
        return actual == expected
    if op == "le":
        return actual <= expected
    if op == "lt":
        return actual < expected
    raise ValueError(f"Unsupported operator: {op}")


def read_stat_value(stats_path: Path, stat_name: str) -> int:
    for line in stats_path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == stat_name:
            return int(fields[1])
    raise KeyError(stat_name)


def parse_stage_spec(spec: str) -> tuple[Path, Path]:
    source_text, sep, dest_text = spec.partition(":")
    if not source_text.strip():
        raise SystemExit(
            f"Invalid --stage-artifact-from {spec!r}. Use '/abs/source[:relative/dest]'."
        )
    source = Path(source_text).expanduser().resolve()
    dest = Path(dest_text) if sep and dest_text.strip() else Path(source.name)
    if dest.is_absolute() or ".." in dest.parts:
        raise SystemExit(
            f"Invalid staged destination in {spec!r}; destination must be a clean relative path."
        )
    return source, dest


def stage_artifact_into_output(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def parse_allowed_dirty_specs(
    specs: list[str], repo_roots: dict[str, Path], output_dir: Path
) -> dict[str, list[str]]:
    allowed: dict[str, list[str]] = {name: [] for name in repo_roots}
    for spec in specs:
        repo_name, sep, relpath = spec.partition(":")
        if not sep or repo_name not in repo_roots or not relpath.strip():
            raise SystemExit(
                f"Invalid --allow-dirty-path {spec!r}. Use 'repo_name:relative/path'."
            )
        allowed[repo_name].append(normalize_relpath(relpath))

    qpoints_validation_root = QPOINTS_ROOT / "validation_records"
    if output_dir.is_relative_to(qpoints_validation_root):
        relpath = normalize_relpath(str(output_dir.relative_to(QPOINTS_ROOT)))
        allowed["QPoints"].append(relpath)
        allowed["qflex"].append("QPoints")
    return allowed


def capture_repo_states_for_run(
    repo_roots: dict[str, Path], allowed_dirty: dict[str, list[str]]
) -> dict[str, dict]:
    return {
        name: capture_repo_state(path, allowed_dirty.get(name, []))
        for name, path in repo_roots.items()
    }


def require_clean_repo_states(repo_states: dict[str, dict]) -> None:
    failures = []
    for name, state in repo_states.items():
        if state["dirty"]:
            failures.append(
                f"{name} dirty entries: {', '.join(state['dirty_entries'])}"
            )
    if failures:
        raise SystemExit(
            "Refusing to record a validated experiment from a dirty workspace.\n"
            + "\n".join(failures)
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run a command under a shared experiment-manifest contract and "
            "capture stable provenance into one output directory."
        )
    )
    parser.add_argument("--output-dir", required=True, help="Output folder for logs and manifest.")
    parser.add_argument("--title", required=True, help="Short human-readable experiment title.")
    parser.add_argument("--component", required=True, help="Primary component under study.")
    parser.add_argument("--question", required=True, help="Question this experiment is meant to answer.")
    parser.add_argument("--intent-file", help="Optional INTENT.txt or markdown file to stage into the output.")
    parser.add_argument("--clean-output", action="store_true", help="Delete any pre-existing output directory.")
    parser.add_argument("--tag", action="append", default=[], help="Optional tag; may be repeated.")
    parser.add_argument(
        "--lifecycle-state",
        choices=("probe", "active", "reference", "stale"),
        default="active",
        help="Lifecycle state for this experiment output.",
    )
    parser.add_argument(
        "--retention-policy",
        choices=("normal", "keep", "archive", "discardable"),
        default="normal",
        help="Retention policy for this experiment output.",
    )
    parser.add_argument(
        "--track-artifact",
        action="append",
        default=[],
        help="Relative path under the output dir to record as a normal artifact.",
    )
    parser.add_argument(
        "--protect-artifact",
        action="append",
        default=[],
        help="Relative path under the output dir to record as a protected reference artifact.",
    )
    parser.add_argument(
        "--stats-file",
        help="Relative path under the output dir to a gem5 stats file for acceptance checks.",
    )
    parser.add_argument(
        "--require-stat",
        action="append",
        default=[],
        help="Acceptance check in the form 'stat_name,op,expected'.",
    )
    parser.add_argument(
        "--stage-artifact-from",
        action="append",
        default=[],
        help=(
            "Copy an artifact produced elsewhere into the output dir before validation. "
            "Use '/abs/source[:relative/dest]'."
        ),
    )
    parser.add_argument(
        "--require-clean-repos",
        action="store_true",
        help=(
            "Require all repos in provenance to be clean before the run, except for "
            "explicitly allowed paths."
        ),
    )
    parser.add_argument(
        "--allow-dirty-path",
        action="append",
        default=[],
        help=(
            "Allow dirtiness under one relative repo path when enforcing clean runs. "
            "Use 'repo_name:relative/path'."
        ),
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run after '--'. Example: -- bash -lc 'echo hello'",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("No command provided. Pass the experiment command after '--'.")
    stat_requirements = [parse_stat_requirement(spec) for spec in args.require_stat]
    if stat_requirements and not args.stats_file:
        raise SystemExit(
            "--require-stat requires --stats-file so stat acceptance checks can be evaluated."
        )

    output_dir = Path(args.output_dir).resolve()
    repo_roots = {
        "qflex": QFLEX_ROOT,
        "QPoints": QPOINTS_ROOT,
        "gem5": GEM5_ROOT,
    }
    allowed_dirty = parse_allowed_dirty_specs(
        args.allow_dirty_path,
        repo_roots,
        output_dir,
    )
    repo_states = capture_repo_states_for_run(repo_roots, allowed_dirty)
    enforce_clean = args.require_clean_repos or output_dir.is_relative_to(
        QPOINTS_ROOT / "validation_records"
    )
    if enforce_clean:
        require_clean_repo_states(repo_states)

    prepare_output_dir(output_dir, clean=args.clean_output)

    stdout_path = output_dir / "experiment_stdout.log"
    stderr_path = output_dir / "experiment_stderr.log"

    manifest = build_manifest(
        title=args.title,
        component=args.component,
        question=args.question,
        output_dir=output_dir,
        script_path=Path(__file__).resolve(),
        repo_roots=repo_roots,
        repo_states=repo_states,
        inputs={"command": command},
        tags=args.tag,
        acceptance=(
            [
                {
                    "name": "command_exit_zero",
                    "kind": "process_exit_code",
                    "expected": 0,
                }
            ]
            + [
                {
                    "name": stat_name,
                    "kind": "stats_check",
                    "operator": op,
                    "expected": expected,
                }
                for stat_name, op, expected in stat_requirements
            ]
        ),
        lifecycle_state=args.lifecycle_state,
        retention_policy=args.retention_policy,
    )
    manifest["provenance"]["clean_run_policy"] = {
        "enforced": enforce_clean,
        "allowed_dirty_paths": allowed_dirty,
    }

    stage_intent(
        manifest,
        output_dir,
        Path(args.intent_file).resolve() if args.intent_file else None,
    )
    add_artifact(
        manifest,
        label="stdout",
        path=stdout_path,
        category="log",
        description="Captured stdout from the experiment command.",
        retention="keep" if args.retention_policy == "keep" else "normal",
        protected=args.lifecycle_state == "reference",
    )
    add_artifact(
        manifest,
        label="stderr",
        path=stderr_path,
        category="log",
        description="Captured stderr from the experiment command.",
        retention="keep" if args.retention_policy == "keep" else "normal",
        protected=args.lifecycle_state == "reference",
    )
    write_manifest(output_dir, manifest)

    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_file:
        completed = subprocess.run(
            command,
            cwd=str(QPOINTS_ROOT),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            check=False,
        )

    metrics = {"exit_code": completed.returncode}
    summary = (
        "Experiment command completed successfully."
        if completed.returncode == 0
        else f"Experiment command failed with exit code {completed.returncode}."
    )
    status = "passed" if completed.returncode == 0 else "failed"

    for spec in args.stage_artifact_from:
        source, relative_dest = parse_stage_spec(spec)
        try:
            stage_artifact_into_output(source, output_dir / relative_dest)
        except FileNotFoundError:
            status = "failed"
            summary = f"Expected staged artifact not found: {source}"
            break

    for relative_path in args.track_artifact:
        artifact_path = output_dir / relative_path
        add_artifact(
            manifest,
            label=f"artifact:{relative_path}",
            path=artifact_path,
            category="file" if artifact_path.is_file() else "path",
            description="Tracked experiment artifact.",
        )
    for relative_path in args.protect_artifact:
        artifact_path = output_dir / relative_path
        add_artifact(
            manifest,
            label=f"protected:{relative_path}",
            path=artifact_path,
            category="file" if artifact_path.is_file() else "path",
            description="Protected reference artifact.",
            retention="keep",
            protected=True,
        )

    if args.stats_file:
        stats_path = output_dir / args.stats_file
        add_artifact(
            manifest,
            label="stats",
            path=stats_path,
            category="stats",
            description="Stats file used for acceptance checks.",
            retention="keep" if args.lifecycle_state == "reference" else "normal",
            protected=args.lifecycle_state == "reference",
        )
        if not stats_path.is_file():
            status = "failed"
            summary = f"Expected stats file not found: {stats_path}"
        else:
            stats_metrics = {}
            for stat_name, op, expected in stat_requirements:
                try:
                    actual = read_stat_value(stats_path, stat_name)
                except KeyError:
                    status = "failed"
                    summary = f"Missing stat {stat_name} in {stats_path}"
                    break
                stats_metrics[stat_name] = actual
                if not stat_matches(actual, op, expected):
                    status = "failed"
                    summary = (
                        f"Stats acceptance failed: {stat_name} {op} {expected} "
                        f"was not satisfied (actual={actual})."
                    )
                    break
            metrics.update(stats_metrics)

    add_command(
        manifest,
        label="experiment",
        argv=command,
        cwd=QPOINTS_ROOT,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        exit_code=completed.returncode,
    )
    set_result(
        manifest,
        outcome=status,
        summary=summary,
        metrics=metrics,
    )
    write_manifest(output_dir, manifest)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
