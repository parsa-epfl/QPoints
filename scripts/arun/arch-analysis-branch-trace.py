#!/usr/bin/env python3

"""
Compare a BXKraken/WormCache (test-worm --branch-trace) branch-trace log
against a gem5 (run-gem5 --branch-trace) branch-trace log for the same
checkpoint lineage. Produces a tabular plain-text report covering:

  1. Branch counts for each trace, kernel/user split and percentages,
     where the first kernel and first user branch occur in each trace,
     and the first 10 PCs recorded in each trace.
  2. First divergence: the first position where the two traces disagree
     when compared lockstep (position i vs position i), whether each
     side's branch there is kernel- or user-space, and a +/-10-branch
     context window around that position on both traces with the
     divergence row marked.
  3. ALL common contiguous runs: maximal stretches of branches that are
     identical, in the same order, on both traces. The search runs over
     the ENTIRE length of both traces (no truncation to the shorter one
     first) -- a run can start anywhere in either trace. Runs are found
     in an order-preserving way: sorted by where they occur in trace A,
     they occur in that same relative order in trace B too (no crossing).
  4. The longest such run: its length, where it starts/ends in each
     trace, the 10 branches immediately before it on each side, and the
     first 10 branches inside it (with each side's own index).
  5. Overall sharing: total matched branches as a percentage of EACH
     trace's own total length (the two traces can have very different
     lengths, so one shared percentage would be misleading), the count
     of common runs found, the details of the LAST such run (by
     position), and the divergence episodes between/around the runs --
     how many there are and, of the branches inside them, how many are
     kernel vs user on each side.
  6. The same analysis (1-5) repeated after removing every kernel-space
     branch from each trace independently. Because pruning shifts
     positions, every reported position in this section is given BOTH
     as a position in the pruned sequence AND mapped back to its
     position in that trace's original, unpruned sequence.

A branch is classified kernel-space if its PC >= 0xffff000000000000 (the
AArch64 canonical split-VA boundary: TTBR1/kernel owns the top half of
the address space, top 16 bits set; TTBR0/user owns the rest).

Supported log formats (auto-detected per line):
  - plain decimal/hex PC per line: WormCache test-worm, and gem5 classic/
    AtomicSimpleCPU --branch-trace (src/cpu/simple/base.cc: "%llu\\n")
  - gem5 CSV branch-trace ("branch_pc,direction,..." header, 4 fields)
  - gem5 O3/timing-ruby extended space-delimited format (branch PC is the
    3rd whitespace-separated field)

Matching algorithm: keeps only the first occurrence per 128-bit rolling
hash digest (two independent 64-bit hashes) instead of re-verifying
matches by slicing, and never truncates either trace before searching.
Real branch traces are dominated by a handful of extremely hot loop PCs;
a naive hash+re-verify approach (or Python's difflib) degrades to roughly
O(n^2) on that kind of data (every window of a periodic run looks the
same, so their candidate lists explode) -- this stays O(n log n)
regardless of repetition.

Output: a tabular plain-text report is ALWAYS written under
QPoints/scripts/arun/results/ (next to this script, not /tmp), and the
exact path is printed at the end. Pass --output-json to also dump the
full structured result as JSON.
"""

import argparse
import gzip
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

KERNEL_VA_BOUNDARY = 0xFFFF000000000000
RESULTS_DIR = Path(__file__).resolve().parent / "results"
CONTEXT_WINDOW = 10

MASK = (1 << 64) - 1
BASE_1 = 11400714819323198485  # golden-ratio-derived odd 64-bit constant
BASE_2 = 14029467366897019727  # a different odd 64-bit constant


def is_kernel_pc(pc: int) -> bool:
    return pc >= KERNEL_VA_BOUNDARY


def classify(pc: int) -> str:
    return "kernel" if is_kernel_pc(pc) else "user"


def filter_user_space_with_map(values: list):
    """Returns (pruned_values, original_indices) where original_indices[i]
    is the position in `values` that pruned_values[i] came from."""
    pruned, orig_idx = [], []
    for i, v in enumerate(values):
        if not is_kernel_pc(v):
            pruned.append(v)
            orig_idx.append(i)
    return pruned, orig_idx


def first_occurrence_by_space(values: list) -> dict:
    out = {"kernel": None, "user": None}
    for i, v in enumerate(values):
        space = classify(v)
        if out[space] is None:
            out[space] = i
        if out["kernel"] is not None and out["user"] is not None:
            break
    return out


def _parse_int(token: str) -> int:
    try:
        return int(token, 0)
    except ValueError:
        return int(token, 10)


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def load_branch_pcs(path: Path) -> list:
    pcs = []
    with _open_text(path) as infile:
        for line in infile:
            stripped = line.strip()
            if not stripped or stripped.lower().startswith("branch_pc"):
                continue
            if "," in stripped:
                fields = [f.strip() for f in stripped.split(",")]
                if len(fields) == 4:
                    try:
                        pcs.append(_parse_int(fields[0]))
                    except ValueError:
                        pass
                continue
            fields = stripped.split()
            if len(fields) == 1:
                try:
                    pcs.append(_parse_int(fields[0]))
                except ValueError:
                    pass
            elif len(fields) >= 3:
                try:
                    pcs.append(_parse_int(fields[2]))
                except ValueError:
                    pass
    return pcs


# --- Repeat-robust contiguous-run matching ---
#
# `_RollingHash` precomputes two independent prefix hashes over a whole
# sequence once; `digest(start, length)` then gives an O(1) 128-bit digest
# for any window. `_find_longest_run` binary-searches the run length and,
# for each candidate length, builds a dict of {digest: first_index} over
# one side and probes the other side against it -- O(1) per position, so
# O(range) per length probe and O(range log range) per call, independent
# of how repetitive the content is (no candidate lists, no slice
# re-verification).


class _RollingHash:
    def __init__(self, seq):
        n = len(seq)
        self.prefix1 = [0] * (n + 1)
        self.powers1 = [1] * (n + 1)
        self.prefix2 = [0] * (n + 1)
        self.powers2 = [1] * (n + 1)
        for i, value in enumerate(seq, start=1):
            v = (value & MASK) + 1
            self.prefix1[i] = ((self.prefix1[i - 1] * BASE_1) + v) & MASK
            self.powers1[i] = (self.powers1[i - 1] * BASE_1) & MASK
            self.prefix2[i] = ((self.prefix2[i - 1] * BASE_2) + v) & MASK
            self.powers2[i] = (self.powers2[i - 1] * BASE_2) & MASK

    def digest(self, start: int, length: int):
        end = start + length
        h1 = (self.prefix1[end] - ((self.prefix1[start] * self.powers1[length]) & MASK)) & MASK
        h2 = (self.prefix2[end] - ((self.prefix2[start] * self.powers2[length]) & MASK)) & MASK
        return (h1, h2)


def _probe_length(a_hash, a_lo, a_hi, b_hash, b_lo, b_hi, length):
    if length == 0:
        return (a_lo, b_lo)
    seen = {}
    for i in range(a_lo, a_hi - length + 1):
        digest = a_hash.digest(i, length)
        if digest not in seen:
            seen[digest] = i
    for j in range(b_lo, b_hi - length + 1):
        digest = b_hash.digest(j, length)
        i = seen.get(digest)
        if i is not None:
            return (i, j)
    return None


def _find_longest_run(a_hash, a_lo, a_hi, b_hash, b_lo, b_hi):
    """Longest common contiguous run between a[a_lo:a_hi] and b[b_lo:b_hi]."""
    low, high = 0, min(a_hi - a_lo, b_hi - b_lo)
    best_length, best_pair = 0, (a_lo, b_lo)
    while low <= high:
        mid = (low + high) // 2
        match = _probe_length(a_hash, a_lo, a_hi, b_hash, b_lo, b_hi, mid)
        if match is not None:
            best_length, best_pair = mid, match
            low = mid + 1
        else:
            high = mid - 1
    return best_length, best_pair[0], best_pair[1]


def find_all_common_runs(a: list, b: list):
    """All maximal common contiguous runs between a and b, searched over
    the FULL length of both (no truncation to the shorter one).

    Greedily extracts the single longest run in the current region, then
    pushes the (disjoint) regions strictly left and right of it onto a
    work list. Because every recursive split only ever looks strictly
    left of a match on BOTH sides, or strictly right of it on BOTH sides,
    the resulting runs are automatically order-preserving: sorted by
    their start in `a`, their starts in `b` come out sorted too.
    """
    a_hash, b_hash = _RollingHash(a), _RollingHash(b)
    blocks = []
    work = [(0, len(a), 0, len(b))]
    while work:
        a_lo, a_hi, b_lo, b_hi = work.pop()
        if a_lo >= a_hi or b_lo >= b_hi:
            continue
        length, a_start, b_start = _find_longest_run(a_hash, a_lo, a_hi, b_hash, b_lo, b_hi)
        if length == 0:
            continue
        blocks.append((a_start, b_start, length))
        work.append((a_lo, a_start, b_lo, b_start))
        work.append((a_start + length, a_hi, b_start + length, b_hi))
    blocks.sort(key=lambda blk: blk[0])
    return blocks


def compute_gaps(blocks, len_a, len_b):
    """Divergence episodes: the stretches between/around the common runs
    where the two traces disagree. Up to len(blocks)+1 of them."""
    gaps = []
    prev_a, prev_b = 0, 0
    for a_start, b_start, length in blocks:
        if a_start > prev_a or b_start > prev_b:
            gaps.append((prev_a, a_start, prev_b, b_start))
        prev_a, prev_b = a_start + length, b_start + length
    if prev_a < len_a or prev_b < len_b:
        gaps.append((prev_a, len_a, prev_b, len_b))
    return gaps


def classify_counts(values) -> dict:
    counts = Counter(classify(v) for v in values)
    return {"kernel": counts.get("kernel", 0), "user": counts.get("user", 0)}


def analyze_common_runs(worm: list, gem5: list) -> dict:
    """Sections 2-5: first divergence (lockstep, bounded by the shorter
    trace) + all common contiguous runs (unbounded, searched over the
    full length of both traces) + longest/last run + overall sharing,
    reported against both traces' own totals + divergence-episode
    kernel/user breakdown.
    """
    lockstep_len = min(len(worm), len(gem5))
    first_div = next((i for i in range(lockstep_len) if worm[i] != gem5[i]), None) if lockstep_len else None
    first_divergence = (
        None if first_div is None else {
            "position": first_div,
            "test_worm_pc": worm[first_div],
            "gem5_pc": gem5[first_div],
        }
    )

    blocks = find_all_common_runs(worm, gem5) if worm and gem5 else []
    total_matched = sum(length for _, _, length in blocks)
    first_run = blocks[0] if blocks else None  # sorted by a_start; earliest-occurring run
    longest = max(blocks, key=lambda blk: blk[2]) if blocks else None
    last = blocks[-1] if blocks else None  # sorted by a_start; order-preserving, so also last in b

    # Divergence episodes: the gap between/around each pair of consecutive
    # common runs. For each episode we only look at the SINGLE branch that
    # starts diverging -- the first branch right after the preceding run
    # ends, on each side -- not every branch in the whole gap.
    gaps = compute_gaps(blocks, len(worm), len(gem5))
    episodes = []
    worm_div = Counter({"kernel": 0, "user": 0})
    gem5_div = Counter({"kernel": 0, "user": 0})
    for a_start, a_end, b_start, b_end in gaps:
        worm_idx = a_start if a_start < a_end else None
        gem5_idx = b_start if b_start < b_end else None
        episodes.append({
            "test_worm_idx": worm_idx, "test_worm_pc": worm[worm_idx] if worm_idx is not None else None,
            "gem5_idx": gem5_idx, "gem5_pc": gem5[gem5_idx] if gem5_idx is not None else None,
        })
        if worm_idx is not None:
            worm_div[classify(worm[worm_idx])] += 1
        if gem5_idx is not None:
            gem5_div[classify(gem5[gem5_idx])] += 1

    return {
        "lockstep_len": lockstep_len,
        "first_divergence": first_divergence,
        "blocks": blocks,
        "num_runs": len(blocks),
        "matched_length": total_matched,
        "coverage_pct_test_worm": (total_matched / len(worm) * 100) if worm else 0.0,
        "coverage_pct_gem5": (total_matched / len(gem5) * 100) if gem5 else 0.0,
        "first_run": first_run,  # (test_worm_start, gem5_start, length) or None
        "longest_run": longest,
        "last_run": last,
        "num_divergence_episodes": len(gaps),
        "divergence_episodes": episodes,
        "divergent_test_worm": dict(worm_div),
        "divergent_gem5": dict(gem5_div),
    }


def fmt_pc(pc: int) -> str:
    return f"0x{pc:x}"


def fmt_int(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def fmt_pct(n: float) -> str:
    return f"{n:.4f}%"


def path_tag(p: Path) -> str:
    components = [part for part in p.parts[-3:-1] if part not in ("/", "", p.anchor)]
    return "-".join(components) if components else p.stem


def render_table(headers, rows) -> list:
    if not rows:
        rows = [["(none)"] + [""] * (len(headers) - 1)]
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(cells):
        parts = []
        for i, cell in enumerate(cells):
            text = str(cell)
            parts.append(text.ljust(widths[i]) if i == 0 else text.rjust(widths[i]))
        return "  ".join(parts)

    lines = [fmt_row(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt_row(row) for row in rows)
    return lines


def section_counts(worm_full, gem5_full) -> list:
    worm_split = classify_counts(worm_full)
    gem5_split = classify_counts(gem5_full)
    rows = [
        ["Total branches", fmt_int(len(worm_full)), fmt_int(len(gem5_full))],
        ["Kernel branches", fmt_int(worm_split["kernel"]), fmt_int(gem5_split["kernel"])],
        ["Kernel %", fmt_pct(worm_split["kernel"] / len(worm_full) * 100 if worm_full else 0.0),
         fmt_pct(gem5_split["kernel"] / len(gem5_full) * 100 if gem5_full else 0.0)],
        ["User branches", fmt_int(worm_split["user"]), fmt_int(gem5_split["user"])],
        ["User %", fmt_pct(worm_split["user"] / len(worm_full) * 100 if worm_full else 0.0),
         fmt_pct(gem5_split["user"] / len(gem5_full) * 100 if gem5_full else 0.0)],
    ]
    lines = render_table(["Metric", "test-worm", "gem5"], rows)

    worm_first = first_occurrence_by_space(worm_full)
    gem5_first = first_occurrence_by_space(gem5_full)
    lines.append("")
    lines.append("First occurrence index, by address space:")
    lines.extend(render_table(
        ["Address space", "test-worm", "gem5"],
        [
            ["kernel", fmt_int(worm_first["kernel"]) if worm_first["kernel"] is not None else "(none)",
             fmt_int(gem5_first["kernel"]) if gem5_first["kernel"] is not None else "(none)"],
            ["user", fmt_int(worm_first["user"]) if worm_first["user"] is not None else "(none)",
             fmt_int(gem5_first["user"]) if gem5_first["user"] is not None else "(none)"],
        ],
    ))

    lines.append("")
    lines.append(f"First {CONTEXT_WINDOW} PCs seen in each trace:")
    rows = []
    for i in range(min(CONTEXT_WINDOW, len(worm_full), len(gem5_full)) or CONTEXT_WINDOW):
        tw = f"{fmt_pc(worm_full[i])} ({classify(worm_full[i])})" if i < len(worm_full) else "-"
        g5 = f"{fmt_pc(gem5_full[i])} ({classify(gem5_full[i])})" if i < len(gem5_full) else "-"
        rows.append([i, tw, g5])
    lines.extend(render_table(["Index", "test-worm PC", "gem5 PC"], rows))
    return lines


def section_context_window(worm, gem5, position, label_a="test-worm", label_b="gem5",
                            orig_idx_a=None, orig_idx_b=None) -> list:
    n = len(worm)
    m = len(gem5)
    lo = max(0, position - CONTEXT_WINDOW)
    hi = min(min(n, m), position + CONTEXT_WINDOW + 1)
    headers = ["Index"]
    if orig_idx_a is not None:
        headers.append(f"{label_a} orig idx")
    headers += [f"{label_a} PC", "space", f"{label_b} PC", "space"]
    if orig_idx_b is not None:
        headers.append(f"{label_b} orig idx")
    headers.append("note")
    rows = []
    for i in range(lo, hi):
        row = [i]
        if orig_idx_a is not None:
            row.append(fmt_int(orig_idx_a[i]))
        row += [fmt_pc(worm[i]), classify(worm[i]), fmt_pc(gem5[i]), classify(gem5[i])]
        if orig_idx_b is not None:
            row.append(fmt_int(orig_idx_b[i]))
        row.append("<-- DIVERGES HERE" if i == position else "")
        rows.append(row)
    return render_table(headers, rows)


def section_first_divergence(r, worm, gem5, orig_idx_worm=None, orig_idx_gem5=None) -> list:
    lines = [f"Lockstep-compared length (shorter trace): {fmt_int(r['lockstep_len'])}"]
    fd = r["first_divergence"]
    if r["lockstep_len"] == 0:
        lines.append("(no branches to compare)")
        return lines
    if fd is None:
        lines.append(f"No divergence -- traces match exactly over all {fmt_int(r['lockstep_len'])} branches")
        return lines
    rows = [
        ["Position", fmt_int(fd["position"]), fmt_int(fd["position"])],
        ["PC", fmt_pc(fd["test_worm_pc"]), fmt_pc(fd["gem5_pc"])],
        ["Address space", classify(fd["test_worm_pc"]), classify(fd["gem5_pc"])],
    ]
    if orig_idx_worm is not None:
        rows.append(["Original-trace position", fmt_int(orig_idx_worm[fd["position"]]),
                     fmt_int(orig_idx_gem5[fd["position"]])])
    lines.extend(render_table(["Field", "test-worm", "gem5"], rows))
    lines.append("")
    lines.append(f"Context: {CONTEXT_WINDOW} branches before and after the divergence (both traces, same index):")
    lines.extend(section_context_window(worm, gem5, fd["position"], orig_idx_a=orig_idx_worm, orig_idx_b=orig_idx_gem5))
    return lines


def section_common_runs_summary(r) -> list:
    rows = [
        ["Number of common runs found", fmt_int(r["num_runs"])],
        ["Total matched branches", fmt_int(r["matched_length"])],
        ["Matched % of test-worm trace", fmt_pct(r["coverage_pct_test_worm"])],
        ["Matched % of gem5 trace", fmt_pct(r["coverage_pct_gem5"])],
    ]
    return render_table(["Metric", "Value"], rows)


def section_divergence_episodes(r, orig_idx_worm=None, orig_idx_gem5=None) -> list:
    lines = [
        f"Number of divergence episodes (gaps between/around the {fmt_int(r['num_runs'])} common runs): "
        f"{fmt_int(r['num_divergence_episodes'])}"
    ]
    lines.append(
        "Each episode's branch below is ONLY the single branch that starts diverging -- the first "
        "branch right after the preceding common run ends, on each side -- not every branch in the gap."
    )
    headers = ["Episode #", "test-worm idx"]
    if orig_idx_worm is not None:
        headers.append("test-worm orig idx")
    headers += ["test-worm PC", "space", "gem5 idx"]
    if orig_idx_gem5 is not None:
        headers.append("gem5 orig idx")
    headers += ["gem5 PC", "space"]

    rows = []
    for n, ep in enumerate(r["divergence_episodes"], start=1):
        row = [n, fmt_int(ep["test_worm_idx"]) if ep["test_worm_idx"] is not None else "-"]
        if orig_idx_worm is not None:
            row.append(fmt_int(orig_idx_worm[ep["test_worm_idx"]]) if ep["test_worm_idx"] is not None else "-")
        row += [
            fmt_pc(ep["test_worm_pc"]) if ep["test_worm_pc"] is not None else "-",
            classify(ep["test_worm_pc"]) if ep["test_worm_pc"] is not None else "-",
            fmt_int(ep["gem5_idx"]) if ep["gem5_idx"] is not None else "-",
        ]
        if orig_idx_gem5 is not None:
            row.append(fmt_int(orig_idx_gem5[ep["gem5_idx"]]) if ep["gem5_idx"] is not None else "-")
        row += [
            fmt_pc(ep["gem5_pc"]) if ep["gem5_pc"] is not None else "-",
            classify(ep["gem5_pc"]) if ep["gem5_pc"] is not None else "-",
        ]
        rows.append(row)
    lines.extend(render_table(headers, rows))

    lines.append("")
    dt, dg = r["divergent_test_worm"], r["divergent_gem5"]
    lines.append("Of just those divergence-starting branches, how many are kernel vs user:")
    lines.extend(render_table(
        ["Trace", "kernel", "user"],
        [
            ["test-worm", fmt_int(dt.get("kernel", 0)), fmt_int(dt.get("user", 0))],
            ["gem5", fmt_int(dg.get("kernel", 0)), fmt_int(dg.get("user", 0))],
        ],
    ))
    return lines


def section_run_positions(r, worm, gem5, orig_idx_worm=None, orig_idx_gem5=None) -> list:
    def run_row(label, run):
        if run is None:
            return [label, "-", "-", "-", "-", "-"]
        tw_start, g5_start, length = run
        return [label, fmt_int(length), fmt_int(tw_start), fmt_int(tw_start + length),
                fmt_int(g5_start), fmt_int(g5_start + length)]

    headers = ["Run", "length", "test-worm start", "test-worm end", "gem5 start", "gem5 end"]
    rows = [run_row("First run", r["first_run"]), run_row("Longest run", r["longest_run"]),
            run_row("Last run", r["last_run"])]
    lines = ["(positions below are [start, end) -- end is exclusive)"]
    lines.extend(render_table(headers, rows))

    if orig_idx_worm is not None:
        def orig_row(label, run):
            if run is None:
                return [label, "-", "-", "-", "-"]
            tw_start, g5_start, length = run
            tw_end_incl, g5_end_incl = tw_start + length - 1, g5_start + length - 1
            return [
                label,
                fmt_int(orig_idx_worm[tw_start]), fmt_int(orig_idx_worm[tw_end_incl]),
                fmt_int(orig_idx_gem5[g5_start]), fmt_int(orig_idx_gem5[g5_end_incl]),
            ]

        headers2 = ["Run", "test-worm start (orig)", "test-worm end (orig)", "gem5 start (orig)", "gem5 end (orig)"]
        rows2 = [orig_row("First run", r["first_run"]), orig_row("Longest run", r["longest_run"]),
                 orig_row("Last run", r["last_run"])]
        lines.append("")
        lines.append("Same runs, mapped back to positions in the ORIGINAL (unpruned) traces.")
        lines.append("Note: a pruned run is not necessarily contiguous in the original trace -- kernel")
        lines.append("branches may have been removed from in between; start/end below are inclusive.")
        lines.extend(render_table(headers2, rows2))

    for label, run in (("first run", r["first_run"]), ("longest run", r["longest_run"])):
        if run is None:
            continue
        tw_start, g5_start, length = run
        lines.append("")
        lines.append(f"{CONTEXT_WINDOW} branches immediately before the {label} starts (each side, own index):")
        before_rows = []
        for k in range(CONTEXT_WINDOW, 0, -1):
            tw_i, g5_i = tw_start - k, g5_start - k
            tw_cell = f"{fmt_int(tw_i)}: {fmt_pc(worm[tw_i])} ({classify(worm[tw_i])})" if tw_i >= 0 else "-"
            g5_cell = f"{fmt_int(g5_i)}: {fmt_pc(gem5[g5_i])} ({classify(gem5[g5_i])})" if g5_i >= 0 else "-"
            before_rows.append([f"-{k}", tw_cell, g5_cell])
        lines.extend(render_table(["Offset", "test-worm (idx: PC)", "gem5 (idx: PC)"], before_rows))

        lines.append("")
        show_n = min(CONTEXT_WINDOW, length)
        lines.append(f"First {show_n} branches INSIDE the {label} (identical on both sides by definition):")
        in_rows = []
        for k in range(show_n):
            tw_i, g5_i = tw_start + k, g5_start + k
            in_rows.append([k, fmt_int(tw_i), fmt_int(g5_i), fmt_pc(worm[tw_i]), classify(worm[tw_i])])
        lines.extend(render_table(["offset in run", "test-worm idx", "gem5 idx", "PC", "space"], in_rows))
    return lines


def build_report(worm_path, gem5_path, worm_full, gem5_full, full_r, worm_user, gem5_user,
                  orig_idx_worm, orig_idx_gem5, user_r) -> str:
    lines = []
    line = lines.append
    line("=" * 100)
    line("BRANCH-TRACE COMPARISON REPORT: test-worm (BXKraken) vs gem5")
    line("=" * 100)
    line(f"test-worm trace: {worm_path}")
    line(f"gem5 trace:      {gem5_path}")
    line(f"generated:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    line("")

    line("-" * 100)
    line("SECTION 1 -- TRACE COUNTS, FIRST OCCURRENCES, FIRST PCs (3.1 / 1.3.1 / 1.5)")
    line("-" * 100)
    lines.extend(section_counts(worm_full, gem5_full))
    line("")

    line("-" * 100)
    line("SECTION 2 -- FIRST DIVERGENCE, full trace, lockstep by position (3.2 / 1.2)")
    line("-" * 100)
    lines.extend(section_first_divergence(full_r, worm_full, gem5_full))
    line("")

    line("-" * 100)
    line("SECTION 3-5 -- COMMON CONTIGUOUS RUNS, full trace, order-preserving (3.3 / 3.4 / 3.5 / 1.3.2 / 1.4)")
    line("-" * 100)
    lines.extend(section_common_runs_summary(full_r))
    line("")
    lines.extend(section_divergence_episodes(full_r))
    line("")
    lines.extend(section_run_positions(full_r, worm_full, gem5_full))
    line("")

    line("=" * 100)
    line("SECTION 6 -- SAME ANALYSIS, KERNEL BRANCHES REMOVED FROM EACH TRACE INDEPENDENTLY (3.6)")
    line("=" * 100)
    line(f"test-worm user-space branches: {fmt_int(len(worm_user))} (of {fmt_int(len(worm_full))} total)")
    line(f"gem5 user-space branches:      {fmt_int(len(gem5_user))} (of {fmt_int(len(gem5_full))} total)")
    line("")

    line("-" * 100)
    line("SECTION 6.2 -- FIRST DIVERGENCE, user-only")
    line("-" * 100)
    lines.extend(section_first_divergence(user_r, worm_user, gem5_user, orig_idx_worm, orig_idx_gem5))
    line("")

    line("-" * 100)
    line("SECTION 6.3-6.5 -- COMMON CONTIGUOUS RUNS, user-only")
    line("-" * 100)
    lines.extend(section_common_runs_summary(user_r))
    line("")
    lines.extend(section_divergence_episodes(user_r, orig_idx_worm, orig_idx_gem5))
    line("")
    lines.extend(section_run_positions(user_r, worm_user, gem5_user, orig_idx_worm, orig_idx_gem5))
    line("")
    line("=" * 100)

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare BXKraken (test-worm) and gem5 branch-trace logs for the same checkpoint."
    )
    parser.add_argument("--test-worm-trace", required=True, help="Path to the test-worm branch_trace_core_N.log.")
    parser.add_argument("--gem5-trace", required=True, help="Path to the gem5 branch_trace_core_N.log.")
    parser.add_argument(
        "--report-dir", default=None,
        help=f"Directory to save the plain-text report into. Default: {RESULTS_DIR}",
    )
    parser.add_argument(
        "--output-json", default=None,
        help="Optional path to ALSO write the full structured result as JSON, for scripting.",
    )
    return parser.parse_args()


def _json_safe(r):
    out = {k: v for k, v in r.items() if k != "blocks"}
    fd = out.get("first_divergence")
    if fd:
        out["first_divergence"] = {**fd, "test_worm_pc": f"0x{fd['test_worm_pc']:x}", "gem5_pc": f"0x{fd['gem5_pc']:x}"}
    for key in ("first_run", "longest_run", "last_run"):
        run = out.get(key)
        if run:
            out[key] = {"test_worm_start": run[0], "gem5_start": run[1], "length": run[2]}
    out["divergence_episodes"] = [
        {
            "test_worm_idx": ep["test_worm_idx"],
            "test_worm_pc": f"0x{ep['test_worm_pc']:x}" if ep["test_worm_pc"] is not None else None,
            "gem5_idx": ep["gem5_idx"],
            "gem5_pc": f"0x{ep['gem5_pc']:x}" if ep["gem5_pc"] is not None else None,
        }
        for ep in out.get("divergence_episodes", [])
    ]
    return out


def main():
    args = parse_args()
    worm_path = Path(args.test_worm_trace).resolve()
    gem5_path = Path(args.gem5_trace).resolve()

    worm_full = load_branch_pcs(worm_path)
    gem5_full = load_branch_pcs(gem5_path)

    full_r = analyze_common_runs(worm_full, gem5_full)

    worm_user, orig_idx_worm = filter_user_space_with_map(worm_full)
    gem5_user, orig_idx_gem5 = filter_user_space_with_map(gem5_full)
    user_r = analyze_common_runs(worm_user, gem5_user)

    report_text = build_report(
        worm_path, gem5_path, worm_full, gem5_full, full_r,
        worm_user, gem5_user, orig_idx_worm, orig_idx_gem5, user_r,
    )
    print(report_text)

    report_dir = Path(args.report_dir).resolve() if args.report_dir else RESULTS_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"{path_tag(worm_path)}__vs__{path_tag(gem5_path)}__{stamp}.txt"
    report_path.write_text(report_text + "\n", encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    if args.output_json:
        json_result = {
            "test_worm_trace": str(worm_path),
            "gem5_trace": str(gem5_path),
            "counts": {
                "test_worm_total": len(worm_full), "gem5_total": len(gem5_full),
                "test_worm_split": classify_counts(worm_full), "gem5_split": classify_counts(gem5_full),
                "test_worm_first_occurrence": first_occurrence_by_space(worm_full),
                "gem5_first_occurrence": first_occurrence_by_space(gem5_full),
            },
            "full_comparison": _json_safe(full_r),
            "user_only_comparison": _json_safe(user_r),
            "user_only_counts": {"test_worm_user_total": len(worm_user), "gem5_user_total": len(gem5_user)},
        }
        output_path = Path(args.output_json).resolve()
        output_path.write_text(json.dumps(json_result, indent=2) + "\n", encoding="utf-8")
        print(f"JSON written to: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
