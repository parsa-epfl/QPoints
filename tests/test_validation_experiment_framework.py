import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _init_git_repo(repo_path: Path):
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def test_experiment_manifest_stages_intent_and_writes_files(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        "experiment_manifest",
        repo_root / "scripts" / "validation" / "experiment_manifest.py",
    )

    output_dir = tmp_path / "out"
    module.prepare_output_dir(output_dir)
    intent_path = tmp_path / "INTENT.txt"
    intent_path.write_text("Why this experiment exists.\n", encoding="utf-8")

    manifest = module.build_manifest(
        title="Validation smoke",
        component="validation.test",
        question="Does manifest writing work?",
        output_dir=output_dir,
        script_path=repo_root / "scripts" / "validation" / "run_experiment.py",
        repo_roots={"QPoints": repo_root},
        inputs={"snapshot": "snapshot_0"},
        tags=["smoke"],
    )
    module.stage_intent(manifest, output_dir, intent_path)
    module.add_artifact(
        manifest,
        label="artifact",
        path=output_dir / "artifact.txt",
        category="generated-file",
    )
    module.set_result(
        manifest,
        outcome="completed",
        summary="Manifest smoke completed.",
        metrics={"artifacts": 1},
    )
    manifest_path = module.write_manifest(output_dir, manifest)

    assert manifest_path == output_dir / "experiment_manifest.json"
    manifest_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_disk = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_disk == legacy_disk
    assert manifest_disk["title"] == "Validation smoke"
    assert manifest_disk["intent"]["text"] == "Why this experiment exists.\n"
    assert manifest_disk["artifacts"][0]["label"] == "intent"
    assert "status" not in manifest_disk
    assert manifest_disk["result"]["outcome"] == "completed"


def test_experiment_manifest_reuses_in_place_reference_intent(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        "experiment_manifest",
        repo_root / "scripts" / "validation" / "experiment_manifest.py",
    )

    output_dir = tmp_path / "out"
    module.prepare_output_dir(output_dir)
    intent_path = output_dir / "INTENT.txt"
    intent_path.write_text("Reference intent.\n", encoding="utf-8")

    manifest = module.build_manifest(
        title="Reference validation",
        component="validation.reference",
        question="Can the intent live in the output dir itself?",
        output_dir=output_dir,
        script_path=repo_root / "scripts" / "validation" / "run_experiment.py",
        repo_roots={"QPoints": repo_root},
        lifecycle_state="reference",
        retention_policy="keep",
    )
    module.stage_intent(manifest, output_dir, intent_path)

    assert manifest["intent"]["staged_path"] == str(intent_path)
    assert manifest["artifacts"][0]["protected"] is True
    assert manifest["artifacts"][0]["retention"] == "keep"
    assert intent_path.read_text(encoding="utf-8") == "Reference intent.\n"


def test_experiment_manifest_records_analysis_metadata(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        "experiment_manifest",
        repo_root / "scripts" / "validation" / "experiment_manifest.py",
    )

    output_dir = tmp_path / "out"
    module.prepare_output_dir(output_dir)
    manifest = module.build_manifest(
        title="Replacement replay validation",
        component="restore.llc",
        question="Does the recorded analysis show how eviction order was verified?",
        output_dir=output_dir,
        script_path=repo_root / "scripts" / "validation" / "run_experiment.py",
        repo_roots={"QPoints": repo_root},
        lifecycle_state="reference",
        retention_policy="keep",
    )
    module.add_analysis(
        manifest,
        label="lru-replay",
        question="Does runtime eviction match the replayed LRU order?",
        script=Path("verify_lru_replay.py"),
        inputs=[Path("debug.insts"), Path("restore_llc_state.args")],
        outputs=[Path("lru_replay_report.json")],
        status="validated",
        conclusion="The first ten recorded replacements matched the replayed LRU victim.",
    )

    analysis = manifest["analyses"][0]
    assert analysis["label"] == "lru-replay"
    assert analysis["status"] == "validated"
    assert analysis["inputs"] == ["debug.insts", "restore_llc_state.args"]
    assert analysis["outputs"] == ["lru_replay_report.json"]


def test_capture_repo_state_ignores_allowed_validation_path(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        "experiment_manifest",
        repo_root / "scripts" / "validation" / "experiment_manifest.py",
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)

    validation_path = repo_path / "validation_records" / "llc_reference"
    validation_path.mkdir(parents=True)
    (validation_path / "INTENT.txt").write_text("intent\n", encoding="utf-8")

    state = module.capture_repo_state(repo_path, ["validation_records/llc_reference"])
    assert state["raw_dirty"] is True
    assert state["dirty"] is False
    assert state["ignored_dirty_entries"]
    assert state["dirty_entries"] == []


def test_capture_repo_state_keeps_unrelated_dirtiness(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    module = _load_module(
        "experiment_manifest",
        repo_root / "scripts" / "validation" / "experiment_manifest.py",
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)

    validation_path = repo_path / "validation_records" / "llc_reference"
    validation_path.mkdir(parents=True)
    (validation_path / "INTENT.txt").write_text("intent\n", encoding="utf-8")
    (repo_path / "notes.txt").write_text("unexpected\n", encoding="utf-8")

    state = module.capture_repo_state(repo_path, ["validation_records/llc_reference"])
    assert state["raw_dirty"] is True
    assert state["dirty"] is True
    assert any("notes.txt" in entry for entry in state["dirty_entries"])


def test_run_experiment_writes_manifest_and_logs(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "scripts" / "validation" / "run_experiment.py"
    intent_path = tmp_path / "INTENT.txt"
    intent_path.write_text("Run a tiny command under the shared manifest.\n", encoding="utf-8")
    source_artifact = tmp_path / "source.txt"
    source_artifact.write_text("staged artifact\n", encoding="utf-8")
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--output-dir",
            str(output_dir),
            "--title",
            "Runner smoke",
            "--component",
            "validation.runner",
            "--question",
            "Does the guarded runner record the command outcome?",
            "--intent-file",
            str(intent_path),
            "--stage-artifact-from",
            f"{source_artifact}:copied/source.txt",
            "--",
            sys.executable,
            "-c",
            "print('hello from runner')",
        ],
        cwd=str(repo_root),
        check=False,
        text=True,
    )

    assert result.returncode == 0
    manifest = json.loads(
        (output_dir / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["result"]["outcome"] == "passed"
    assert manifest["commands"][0]["argv"][0] == sys.executable
    assert (output_dir / "copied" / "source.txt").read_text(encoding="utf-8") == (
        "staged artifact\n"
    )
    assert (output_dir / "experiment_stdout.log").read_text(encoding="utf-8").strip() == (
        "hello from runner"
    )


def test_validation_records_readme_exists():
    repo_root = Path(__file__).resolve().parents[1]
    readme = repo_root / "validation_records" / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    assert "sim_outs/" in text
    assert "self-contained" in text
    assert "reproduce" in text
