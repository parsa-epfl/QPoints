#!/usr/bin/env python3
"""Compare TLB states and TLB event traces for the gem5 vs WormCacheQFlex
TLB round-trip test.

  state A B   Compare two L1 ITLB/DTLB states. Each side is either a gem5
              checkpoint-format file (mmu-cpuN.cpt, or an m5.cpt written at the
              end of a run) or a WormCacheQFlex gem5 TLB model file
              (gem5-tlbs-N.json or .json.zstd). Entries are compared on
              (vpn, N, ASID or G for global, pfn), in recency order: table
              order for gem5, descending ts for WormCacheQFlex.

  traces A B  Compare two event traces of one TLB (a gem5
              --tlb-event-trace-dir file and the matching gem5_tlb_replay
              output) line by line, on the outcome fields only: hit/miss, hit
              index, the entry used, the evicted entry, and the entries removed
              by each TLBI.

Exit status: 0 when identical, 1 when anything differs.
"""
import argparse
import io
import json
import re
import subprocess
import sys

SECTION = re.compile(r"\.cpus(\d*)\.mmu\.(itb|dtb)\.Entry(\d+)$")
WC_NAME = {"itb": "itlb", "dtb": "dtlb"}


def read_cpt(path, core):
    """Valid ITB/DTB entries of one core, in table order (index 0 = MRU)."""
    sections, cur = {}, None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1]
                sections[cur] = {}
            elif cur is not None and "=" in line:
                k, v = line.split("=", 1)
                sections[cur][k] = v
    tlbs = {"itb": [], "dtb": []}
    for name, fields in sections.items():
        m = SECTION.search(name)
        if not m or int(m.group(1) or 0) != core:
            continue
        if fields.get("valid") != "true":
            continue
        is_global = fields["global"] == "true"
        key = (int(fields["vpn"]), int(fields["N"]),
               "G" if is_global else int(fields["asid"]), int(fields["pfn"]))
        tlbs[m.group(2)].append((int(m.group(3)), key))
    return {t: [k for _, k in sorted(v)] for t, v in tlbs.items()}


def read_wormcache(path, core):
    """Entries of one core from a gem5-tlbs-N.json[.zstd], most recent first."""
    with open(path, "rb") as f:
        raw = f.read()
    if path.endswith((".zst", ".zstd")):
        try:
            import zstandard
            raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
        except ImportError:
            raw = subprocess.run(["zstd", "-dc"], input=raw, check=True,
                                 capture_output=True).stdout
    data = json.loads(raw)[core]
    tlbs = {}
    for tlb, wc in WC_NAME.items():
        entries = [e for s in data[wc]["entries"] for e in s["entries"]
                   if e.get("valid", True)]
        entries.sort(key=lambda e: -e["ts"])
        tlbs[tlb] = [(e["vpn"], e["n"],
                      "G" if e["asid"] == "Global" else e["asid"]["NonGlobal"],
                      e["ppn"]) for e in entries]
    return tlbs


def read_state(path, core):
    if ".json" in path:
        return read_wormcache(path, core)
    return read_cpt(path, core)


def fmt(key):
    vpn, n, asid, pfn = key
    return f"vpn=0x{vpn:x} N={n} asid={asid} pfn=0x{pfn:x}"


def compare_state(args):
    a, b = read_state(args.a, args.core), read_state(args.b, args.core)
    same = True
    for tlb in ("itb", "dtb"):
        la, lb = a[tlb], b[tlb]
        sa, sb = set(la), set(lb)
        only_a, only_b = [k for k in la if k not in sb], [k for k in lb if k not in sa]
        common_a = [k for k in la if k in sb]
        common_b = [k for k in lb if k in sa]
        order_same = common_a == common_b
        print(f"{tlb}: A={len(la)} B={len(lb)} common={len(common_a)} "
              f"only_A={len(only_a)} only_B={len(only_b)} "
              f"order_of_common={'same' if order_same else 'different'}")
        for k in only_a[:args.show]:
            print(f"  only in A: {fmt(k)}")
        for k in only_b[:args.show]:
            print(f"  only in B: {fmt(k)}")
        if not order_same:
            i = next(i for i, (x, y) in enumerate(zip(common_a, common_b)) if x != y)
            print(f"  first order difference at common position {i}: "
                  f"A {fmt(common_a[i])} | B {fmt(common_b[i])}")
        same &= not only_a and not only_b and order_same
    print("IDENTICAL" if same else "DIFFERENT")
    return 0 if same else 1


# Outcome fields; register values are copied from gem5 and not compared.
OUTCOME = {"L": ("va", "asid", "res", "index", "vpn", "n", "pfn", "g", "ev"),
           "T": ("op", "asid", "va", "rm")}


def parse_event(line):
    toks = line.split()
    fields = dict(t.split("=", 1) for t in toks[2:])
    return toks[0], toks[1], fields


def compare_traces(args):
    with open(args.a) as fa, open(args.b) as fb:
        la, lb = fa.read().splitlines(), fb.read().splitlines()
    diffs = 0
    for i, (x, y) in enumerate(zip(la, lb)):
        ka, sa, fa_ = parse_event(x)
        kb, sb, fb_ = parse_event(y)
        bad = (ka, sa) != (kb, sb)
        if not bad:
            bad = any(fa_.get(k) != fb_.get(k) for k in OUTCOME.get(ka, ()))
        if bad:
            diffs += 1
            if diffs <= args.show:
                print(f"line {i + 1}:\n  A: {x}\n  B: {y}")
    if len(la) != len(lb):
        print(f"line counts differ: A={len(la)} B={len(lb)}")
    print(f"lines={min(len(la), len(lb))} differing={diffs}")
    same = diffs == 0 and len(la) == len(lb)
    print("IDENTICAL" if same else "DIFFERENT")
    return 0 if same else 1


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("state", help="compare two ITLB/DTLB states")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--core", type=int, default=0)
    s.add_argument("--show", type=int, default=10, help="entries to print per list")
    s.set_defaults(func=compare_state)
    t = sub.add_parser("traces", help="compare two TLB event traces")
    t.add_argument("a")
    t.add_argument("b")
    t.add_argument("--show", type=int, default=10, help="differing lines to print")
    t.set_defaults(func=compare_traces)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
