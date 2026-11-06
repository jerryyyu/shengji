"""Combine every declared, completed calibration shard without pooling identities.

The manifest fixes seeds and round counts before collection. Each shard must pass
its original journal validator before aggregation; only seat RNG seeds may differ.
"""
import argparse
import copy
import json
from pathlib import Path

from scripts.throw_calibration_summary import summarize, validated_summary


def aggregate(shards):
    if not shards:
        raise ValueError('empty shard plan')
    seeds, combined, identities = set(), [], []
    recipe = None
    for seed, rounds, rows, journal in shards:
        if type(seed) is not int or seed in seeds:
            raise ValueError('invalid or duplicate shard seed')
        if type(rounds) is not int or rounds <= 0:
            raise ValueError('invalid planned rounds')
        seeds.add(seed)
        result = validated_summary(rows, journal)
        terminal = result['terminal']
        if journal[0]['seed'] != seed:
            raise ValueError('unplanned seed')
        if (terminal['reason'] != 'max_rounds' or terminal.get('rounds') != rounds
                or journal[0].get('max_rounds') != rounds):
            raise ValueError('planned rounds not completed')
        if len([r for r in journal if r.get('kind') == 'decision' and r.get('lead')]) != len(rows):
            raise ValueError('missing captured leads')
        identity = copy.deepcopy(result['collection'])
        if identity.pop('seat_seeds', None) != [seed * 10 + s for s in range(4)]:
            raise ValueError('seat seed binding drift')
        if recipe is None:
            recipe = identity
        elif identity != recipe:
            raise ValueError('mixed policy or runtime identities')
        identities.append(dict(seed=seed, rounds=rounds, collection=result['collection']))
        # Aggregation removes only the differing seat seeds from comparison;
        # each decision retains its original seed/game/round cluster key.
        combined.extend(dict(row, collection=identity) for row in rows)
    result = summarize(combined)
    result['shards'] = identities
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('output')
    args = parser.parse_args(argv)
    path = Path(args.manifest)
    plan = json.loads(path.read_text())
    if plan.get('schema') != 'throw-calibration-shards-v1':
        raise ValueError('invalid shard manifest')
    entries = plan['shards']
    files, shards = set(), []
    for entry in entries:
        pair = []
        for key in ('rows', 'journal'):
            source = (path.parent / entry[key]).resolve()
            if source in files:
                raise ValueError('duplicate shard input path')
            files.add(source)
            with source.open() as stream:
                pair.append([json.loads(line) for line in stream if line.strip()])
        shards.append((entry['seed'], entry['rounds'], *pair))
    result = aggregate(shards)
    with open(args.output, 'x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')


if __name__ == '__main__':
    main()
