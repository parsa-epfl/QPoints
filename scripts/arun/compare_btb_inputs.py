#!/usr/bin/env python3
"""Check that the PC BTB and the BBL BTB of WormCacheQFlex receive the same
branch inputs.

Reads the per-core logs written by `qflex test-worm --btb-trace` in a run
folder:

  btb_trace_core_<N>.pc_btb.log   inputs of BTB::train
  btb_trace_core_<N>.bbl_btb.log  inputs of BblBTB::record_basic_block

Both use the same line format, `pc=0x.. type=.. taken=0|1 target=0x..`, so the
two files of a core are compared line by line.

With --branch-trace, the PCs are also checked against
branch_trace_core_<N>.log (written by `--branch-trace`, one decimal PC per
branch, before either BTB is trained). That log has no line limit, so only its
first len(pc_btb log) lines are compared.

Exit status: 0 when every core matches, 1 otherwise.
"""
import argparse
import re
import sys
from pathlib import Path

PC_LOG = re.compile(r"btb_trace_core_(\d+)\.pc_btb\.log$")


def read_lines(path):
    with open(path) as f:
        return [line.rstrip("\n") for line in f]


def pc_of(line):
    # "pc=0x... type=..." -> int
    return int(line.split()[0][len("pc="):], 16)


def compare_lines(name_a, lines_a, name_b, lines_b, show):
    mismatches = [i for i in range(min(len(lines_a), len(lines_b)))
                  if lines_a[i] != lines_b[i]]
    for i in mismatches[:show]:
        print(f"    line {i + 1}:")
        print(f"      {name_a}: {lines_a[i]}")
        print(f"      {name_b}: {lines_b[i]}")
    return mismatches


def check_core(run_dir, core, show, branch_trace):
    pc_path = run_dir / f"btb_trace_core_{core}.pc_btb.log"
    bbl_path = run_dir / f"btb_trace_core_{core}.bbl_btb.log"
    if not bbl_path.exists():
        print(f"core {core}: FAIL, {bbl_path.name} is missing")
        return False

    pc_lines = read_lines(pc_path)
    bbl_lines = read_lines(bbl_path)
    print(f"core {core}: pc_btb {len(pc_lines)} lines, bbl_btb {len(bbl_lines)} lines")

    ok = True
    if len(pc_lines) != len(bbl_lines):
        print("    line counts differ")
        ok = False
    mismatches = compare_lines("pc_btb ", pc_lines, "bbl_btb", bbl_lines, show)
    print(f"    pc_btb vs bbl_btb: {len(mismatches)} mismatching lines")
    ok = ok and not mismatches

    if branch_trace:
        trace_path = run_dir / f"branch_trace_core_{core}.log"
        if not trace_path.exists():
            print(f"    FAIL, {trace_path.name} is missing")
            return False
        trace_pcs = [int(line) for line in read_lines(trace_path)[:len(pc_lines)]]
        btb_pcs = [pc_of(line) for line in pc_lines]
        if len(trace_pcs) < len(btb_pcs):
            print(f"    branch_trace has only {len(trace_pcs)} lines")
            ok = False
        bad = [i for i in range(len(trace_pcs)) if trace_pcs[i] != btb_pcs[i]]
        for i in bad[:show]:
            print(f"    line {i + 1}: branch_trace pc={trace_pcs[i]:#x}, "
                  f"pc_btb pc={btb_pcs[i]:#x}")
        print(f"    branch_trace vs pc_btb: {len(bad)} mismatching PCs")
        ok = ok and not bad

    print(f"    {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path, help="experiment run folder with the logs")
    parser.add_argument("--branch-trace", action="store_true",
                        help="also compare PCs with branch_trace_core_<N>.log")
    parser.add_argument("--show", type=int, default=5,
                        help="mismatches to print per comparison (default 5)")
    args = parser.parse_args()

    cores = sorted(int(m.group(1)) for p in args.run_dir.iterdir()
                   if (m := PC_LOG.match(p.name)))
    if not cores:
        print(f"no btb_trace_core_<N>.pc_btb.log files in {args.run_dir}")
        return 1

    results = [check_core(args.run_dir, core, args.show, args.branch_trace)
               for core in cores]
    print(f"{sum(results)}/{len(results)} cores match")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
