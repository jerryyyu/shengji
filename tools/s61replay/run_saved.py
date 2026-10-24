"""Run a bound continuation diagnostic from an existing projected prefix only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))


def checked_bytes(path, expected_sha, limit):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular unaliased input required')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('input size or digest mismatch')
    return raw


def run_saved(prefix_path, prefix_sha, output, make_bot, *, policy_identity, seed,
              locator=None):
    """Validate the saved projection before policy calls; never open raw duel data."""
    from diagnostic import diagnose_pair
    from extract import LOCATOR
    locator = LOCATOR if locator is None else locator
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('saved result exists; reuse it')
    raw = checked_bytes(prefix_path, prefix_sha, 1024 * 1024)
    prefix = json.loads(raw)
    if (not isinstance(prefix, dict) or prefix.get('schema') != 's61-same-root-prefix-v1'
            or prefix.get('locator') != locator):
        raise ValueError('saved prefix identity mismatch')
    result = diagnose_pair(prefix['rows'], make_bot, policy_identity=policy_identity,
                           seed=seed, tricks=2, locator=locator)
    result['input_sha256'] = prefix_sha
    encoded = json.dumps(result, sort_keys=True, allow_nan=False) + '\n'
    with output.open('x') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prefix', 'prefix-sha', 'output', 'recipe', 'recipe-sha',
                 'play-package', 'belief-package', 'policy-identity'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args()
    env = tomllib.loads(checked_bytes(args.recipe, args.recipe_sha, 128 * 1024).decode())['env']
    env = {k: str(v) for k, v in env.items() if k.startswith('SHENGJI_PV_')}
    env.update(SHENGJI_PV_CKPT=args.play_package, SHENGJI_PV_BELIEF_CKPT=args.belief_package)
    fast = os.environ.get('SHENGJI_FAST')
    for key in list(os.environ):
        if key.startswith('SHENGJI_'):
            del os.environ[key]
    os.environ.update(env)
    if fast is not None:
        os.environ['SHENGJI_FAST'] = fast
    from shengji.train import pv_search_policy as pv
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    if list(entries) != [args.policy_identity]:
        raise ValueError('bound policy identity mismatch')
    factory = entries[args.policy_identity]
    probe = factory(seed=args.seed)
    if probe.worlds != 64 or not probe.belief_worlds or probe.serving_budget_seconds != 3:
        raise ValueError('requires belief-enabled W64 served-budget policy')
    run_saved(args.prefix, args.prefix_sha, args.output, factory,
              policy_identity=args.policy_identity, seed=args.seed)
    print(json.dumps(dict(status='DIAGNOSTIC_SAVED', output=args.output)))


if __name__ == '__main__':
    main()
