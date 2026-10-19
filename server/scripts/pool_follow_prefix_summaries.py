"""Pool saved DEV summaries without reopening captures or running solvers.

The caller verifies seals and the expected input manifest before invocation.
Output describes a simulated diagnostic, never gameplay strength.
"""
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path


def pool(summaries, expected_files):
    if type(expected_files) is not int or expected_files < 1 or len(summaries) != expected_files:
        raise ValueError('missing or extra summary files')
    keys = ('max_hand_size', 'budget_seconds', 'min_worlds', 'time_scale', 'engine',
            'capture_on', 'true_deal')
    config = {k: summaries[0][k] for k in keys}
    if config['true_deal'] is not True or config['capture_on'] is not True:
        raise ValueError('requires true-deal capture summaries')
    counts = Counter()
    full = prefix = 0.0
    inputs, seen_capture, seen_journal = [], set(), set()
    for summary in summaries:
        if (summary.get('schema') != 'exact-follow-prefix-summary-dev-v1'
                or {k: summary[k] for k in keys} != config):
            raise ValueError('incompatible summary configuration')
        for kind, seen in (('capture', seen_capture), ('journal', seen_journal)):
            identity = summary['inputs'][kind]
            digest = identity['sha256']
            if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                    or type(identity['bytes']) is not int or identity['bytes'] <= 0
                    or digest in seen):
                raise ValueError('invalid or duplicate input identity')
            seen.add(digest)
        c = summary['counts']
        required = ('observed', 'no_capture', 'unpublished', 'measured', 'served',
                    'fallback', 'served_agrees', 'fallback_agrees')
        if (any(type(c.get(k)) is not int or c[k] < 0 for k in required)
                or c['observed'] != c['no_capture'] + c['unpublished'] + c['measured']
                or c['measured'] != c['served'] + c['fallback']
                or c['served_agrees'] > c['served'] or c['fallback_agrees'] > c['fallback']):
            raise ValueError('inconsistent counts')
        gains = [summary[k] for k in ('full_gain_sum', 'prefix_gain_sum')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in gains):
            raise ValueError('invalid signed gains')
        if not c['measured'] and any(gains):
            raise ValueError('gain without measured rows')
        counts.update({k: c[k] for k in required})
        full += gains[0]
        prefix += gains[1]
        inputs.append(summary['inputs'])
    if not math.isfinite(full) or not math.isfinite(prefix):
        raise ValueError('nonfinite pooled gain')
    return dict(schema='exact-follow-prefix-pool-dev-v1', files=expected_files,
                configuration=config, inputs=inputs, counts=dict(counts),
                served_fraction_observed=(counts['served']/counts['observed'] if counts['observed'] else None),
                served_agreement=(counts['served_agrees']/counts['served'] if counts['served'] else None),
                full_gain_sum=full, prefix_gain_sum=prefix,
                prefix_gain_ratio=(prefix/full if full > 0 else None),
                claim='Pooled simulated diagnostic only; no hard-expiry, serving-latency or gameplay-strength claim.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('summaries', nargs='+')
    parser.add_argument('--expected-files', type=int, required=True)
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        raise FileExistsError(args.output)
    summaries = []
    for path in args.summaries:
        with open(path, 'rb') as source:
            data = source.read(64_000_001)
        if len(data) > 64_000_000:
            raise ValueError('summary exceeds input limit')
        summaries.append(json.loads(data))
    result = pool(summaries, args.expected_files)
    with open(args.output, 'x') as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write('\n')


if __name__ == '__main__':
    main()
