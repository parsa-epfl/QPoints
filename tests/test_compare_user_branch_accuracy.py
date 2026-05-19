import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "validation" / "tage_restore_compare" / "compare_user_branch_accuracy.py"
    spec = importlib.util.spec_from_file_location("compare_user_branch_accuracy", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_line_accepts_csv_trace_rows():
    module = _load_module()

    assert module.parse_line("aaaa1234,0,1,0\n") == ("aaaa1234", 0, 1, 0)


def test_parse_line_accepts_whitespace_trace_rows():
    module = _load_module()

    line = "228 44 0xffff800008198698 T F H r B H D 281473474314536\n"
    assert module.parse_line(line) == ("0xffff800008198698", 0, 1, 1)


def test_parse_line_infers_prediction_from_mispredict_flag():
    module = _load_module()

    line = "228 44 0xffff800008198698 T T H r B H D 281473474314536\n"
    assert module.parse_line(line) == ("0xffff800008198698", 0, 0, 1)


def test_pc_matches_user_prefix_ignores_hex_prefix_and_case():
    module = _load_module()

    assert module.pc_matches_user_prefix("0xaaaadebf09d0", "aaaa")
    assert module.pc_matches_user_prefix("AAAADebf09d0", "0xaaaa")
    assert not module.pc_matches_user_prefix("0xffff8000", "aaaa")
