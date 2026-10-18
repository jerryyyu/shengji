"""Benchmark an explicitly authorized DEV follow capture against its journal.

No collection, launch or serving change. Reuse an existing output rather than
running this benchmark again. Timings are a simulation, not serving latency.
"""
import argparse
import json
from pathlib import Path

from shengji.train.lead_root_capture import summarize_follow_prefix_collection


def read_rows(path):
    rows = []
    total = 0
    with open(path) as source:
        for index in range(100001):
            line = source.readline(8_000_001)
            if not line:
                return rows
            total += len(line.encode('utf-8'))
            if index == 100000 or len(line) > 8_000_000 or total > 256_000_000:
                raise ValueError('collection input limit exceeded')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('expected object row')
            rows.append(row)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture')
    parser.add_argument('journal')
    parser.add_argument('output')
    parser.add_argument('--budget-seconds', type=float, required=True)
    parser.add_argument('--min-worlds', type=int, default=16)
    parser.add_argument('--time-scale', type=float, default=1.0)
    parser.add_argument('--max-hand-size', type=int, default=8)
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    result = summarize_follow_prefix_collection(
        read_rows(args.capture), read_rows(args.journal),
        budget_seconds=args.budget_seconds, min_worlds=args.min_worlds,
        time_scale=args.time_scale, max_hand_size=args.max_hand_size)
    with open(args.output, 'x') as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write('\n')


if __name__ == '__main__':
    main()
