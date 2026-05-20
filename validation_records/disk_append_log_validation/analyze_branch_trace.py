#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

def count_hits(path: Path, pc: str):
    hits = 0
    first_line = None
    with path.open() as fh:
        for idx, line in enumerate(fh, 1):
            if line.startswith(pc + ','):
                hits += 1
                if first_line is None:
                    first_line = idx
    return hits, first_line

def main() -> int:
    ap = argparse.ArgumentParser(description='Analyze disk-smoke branch trace verdict PCs.')
    ap.add_argument('trace', type=Path)
    ap.add_argument('--success-pc', required=True)
    ap.add_argument('--failure-pc', required=True)
    ap.add_argument('--json-out', type=Path)
    args = ap.parse_args()

    success_pc = args.success_pc.lower().removeprefix('0x')
    failure_pc = args.failure_pc.lower().removeprefix('0x')
    success_hits, success_first = count_hits(args.trace, success_pc)
    failure_hits, failure_first = count_hits(args.trace, failure_pc)
    verdict = 'success' if success_hits > 0 and failure_hits == 0 else 'failure_or_inconclusive'
    out = {
        'trace': str(args.trace),
        'success_pc': args.success_pc,
        'failure_pc': args.failure_pc,
        'success_hits': success_hits,
        'success_first_line': success_first,
        'failure_hits': failure_hits,
        'failure_first_line': failure_first,
        'verdict': verdict,
    }
    text = json.dumps(out, indent=2) + '\n'
    if args.json_out:
        args.json_out.write_text(text)
    else:
        print(text, end='')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
