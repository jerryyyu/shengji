"""Engine-only classification of an explicitly authorized lead capture.

No model calls, resampling, continuation rollout, or strength verdict. The
input contains private deals; the output contains classifications, not hands.
Usage: python -m scripts.lead_finish_classify input.jsonl output.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from shengji.train.lead_root_capture import classify_finish_lead


def summarize(rows):
    counts = Counter(all_roots=0, eligible_roots=0)
    results, seen = [], set()
    for row in rows:
        identity = tuple(row[k] for k in ('game', 'round', 'trick', 'seat'))
        if identity in seen:
            raise ValueError('duplicate lead identity')
        seen.add(identity)
        result = classify_finish_lead(row)
        counts['all_roots'] += 1
        for field in ('work_complete', 'eligible'):
            counts[f'{field}:{result[field]}'] += 1
        if result['eligible']:
            counts['eligible_roots'] += 1
            for field in ('pool_present', 'admitted', 'whole_hand_refused_true_deal', 'whole_hand_played'):
                counts[f'eligible:{field}:{result[field]}'] += 1
        # Do not export private forced-component cards to the summary.
        result.pop('forced_component')
        results.append(dict(identity=list(identity), **result))
    return dict(schema='lead-finish-classification-dev-v1', counts=dict(counts), rows=results,
                limits=['True-deal refusal is hindsight, not policy information.',
                        'Missing evidence is unknown, not absence.',
                        'No model ranking, horizon, prevalence or strength conclusion.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args(argv)
    if Path(args.output).exists():
        raise FileExistsError(args.output)  # reuse saved output; do not reopen input

    def rows():
        with open(args.input) as source:
            for index in range(10001):
                line = source.readline(2_000_001)
                if not line:
                    return
                if index == 10000 or len(line) > 2_000_000:
                    raise ValueError('capture input limit exceeded')
                yield json.loads(line)

    result = summarize(rows())
    with open(args.output, 'x') as output:
        json.dump(result, output, sort_keys=True, indent=2, allow_nan=False)
        output.write('\n')


if __name__ == '__main__':
    main()
