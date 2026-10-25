"""Read one adjudicated missing-mirror PT panel; never recover a call."""
import hashlib
import json
from pathlib import Path
import random
import statistics

ROOT = Path('/root/vol-dev-codex-pt-r46-429-20261021')
PACKET = Path('/root/codex-pt-packet-1cae46e5')
SOURCE = Path('/root/codex-pt-analysis-1cae46e5-bound/source')
OUTPUT = Path('/root/codex-pt-missing-panel-output')
KEY = 'sol-perfect-seed142060913-flip0'
TERMINAL_SHA = '4efb92095ab5535ce64b10dd823f29e18fe509f6449ec08ad66693d928f6249e'
RESULT_SHA = 'e2d102b794f3667c2fa544ebf46f07f732f00b3d43f9e4054cfc7ae4a068787f'
CONFIG_SHA = 'f552db701407e68a56d956f8b90646bf2fabfb2da5a2f42e4fb69743e3211e55'
MIRROR_SHA = 'c98331895f0649e84086f219b71e7a87432b6d743ef94ff0043a789d6f5f0e89'
PRODUCER_PIDS = (2340757, 2340760)
SOURCE_PINS = {'shengji/__init__.py': '41e9be4cf2d1d1319bd49eab822bb1f361373e858ccfbdebaf247eceaba9fcaa', 'shengji/luna/__init__.py': '717cc429cae89841a1924d65121dbf90ef328385189e7aff2b3b0bb8aed2b3d1', 'shengji/luna/benchmark_terminal.py': 'b7e4ba913464c9cd9e3b5bb1f454e6026773cfd92844a4bf86a5bc7198206023', 'shengji/luna/benchmark_failure_protocol.py': '6c23f2b91fafe062720c9f826ca2dd64d0dcaa7626767f32faddfb8cfb814168'}


def require(ok):
    if not ok:
        raise ValueError('PT missing-panel validity refused')


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result
    def constant(_):
        raise ValueError('nonfinite JSON refused')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def analyze(report, config, missing, validator):
    """Validate the full schedule before computing complete-pair diagnostics."""
    eq = validator._strict_equal
    require(type(report) is dict and type(config) is dict and eq(report.get('config'), config))
    require(report.get('schema') == 'w32-llm-benchmark-v1' and report.get('mode') == 'run')
    seeds = validator._seeds(config.get('seeds'))
    require(config.get('models') == ['sol'] and config.get('information') == ['perfect'])
    require(config.get('failure_protocol') == 'preserve-model-illegal-v1'
            and type(config.get('illegal_failure_limit')) is int and config['illegal_failure_limit'] == 8
            and config.get('retained_attempts') is None)
    recipe = config.get('baseline_recipe', {})
    require(recipe.get('benchmark_id') == recipe.get('policy') == 'release46-pv'
            and recipe.get('play_only') is True and type(config.get('policy')) is str and bool(config['policy']))
    prepared = config.get('prepared_roots_from', {})
    roots = prepared.get('root_hashes')
    digest = lambda x: type(x) is str and len(x) == 64 and set(x) <= set('0123456789abcdef')
    require(type(roots) is dict and set(roots) == {str(s) for s in seeds}
            and all(digest(v) for v in roots.values()) and digest(prepared.get('result_sha256')))
    require(eq(report.get('roots'), roots) and eq(report.get('prepared_roots', {}).get('root_hashes'), roots)
            and report.get('prepared_roots', {}).get('result_sha256') == prepared['result_sha256'])
    schedule = [(f'sol-perfect-seed{s}-flip{f}', s, f) for s in seeds for f in (0, 1)]
    rows = report.get('mirrors')
    require(type(rows) is list and len(rows) == 20 and all(type(r) is dict for r in rows))
    require(all(type(r.get('key')) is str for r in rows))
    by_key = {r['key']: r for r in rows}
    require(len(by_key) == 20 and set(by_key) == {k for k, _, _ in schedule} and KEY in by_key)
    require(eq(by_key[KEY], missing))
    counts = {'complete': 0, 'retained-model-failure': 0, 'unattempted': 0, 'adjudicated-missing': 0}
    stopped = False
    for key, seed, flip in schedule:
        row = by_key[key]
        require('lineage' not in row)
        if key == KEY:
            require(not stopped and row.get('complete') is False and 'signed_levels' not in row
                    and row.get('schema') == 'w32-llm-benchmark-mirror-v1'
                    and row.get('arm') == 'sol-perfect' and row.get('model') == 'sol'
                    and row.get('information') == 'perfect'
                    and type(row.get('seed')) is int and row['seed'] == seed
                    and type(row.get('flip')) is int and row['flip'] == flip)
            require(any(c.get('error') == 'CodexTurnTransportError: Codex trace event forbidden'
                        for c in row.get('calls', []) if type(c) is dict))
            kind = 'adjudicated-missing'
            stopped = True
        else:
            kind = validator._validate_row(row, key=key, seed=seed, mode='perfect', flip=flip)
            require((kind == 'unattempted') == stopped)
        counts[kind] += 1
        if counts['retained-model-failure'] == 8:
            stopped = True
    # An orphan mirror never enters the deal-paired endpoint.
    values, kept, excluded = [], [], []
    for seed in seeds:
        pair = [by_key[f'sol-perfect-seed{seed}-flip{f}'] for f in (0, 1)]
        if all(r.get('complete') is True for r in pair):
            kept.append(seed)
            values.append(-statistics.fmean(r['signed_levels'] for r in pair))
        else:
            excluded.append(seed)
    ci = None
    if len(values) >= 2:
        rng = random.Random(20261002)
        means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(2000))
        ci = [means[49], means[1950]]
    return {'schema': 's47pt-adjudicated-missing-readout-v1', 'quality': 'INCOMPLETE',
            'accounting': counts, 'scheduled_mirrors': 20, 'scheduled_deals': 10,
            'missing_key': KEY, 'complete_pair_seeds': kept, 'excluded_pair_seeds': excluded,
            'complete_pair_count': len(values), 'policy_minus_pt_mean': statistics.fmean(values) if values else None,
            'conditional_deal_cluster_ci95': ci,
            'interpretation': 'Complete-pair descriptive diagnostic only; missingness may be informative. '
                              'No full-panel estimate, superiority, equivalence, R48 gain, or imputed forfeit.'}


def pinned(path, sha, limit):
    require(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file())
    before = path.stat()
    require(before.st_size <= limit)
    raw = path.read_bytes()
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns))
    require(hashlib.sha256(raw).hexdigest() == sha)
    return raw


def run():
    import sys
    for folder in (ROOT, PACKET, OUTPUT.parent, SOURCE.parent, Path(__file__).resolve().parent):
        require(not any(p.is_symlink() for p in (folder, *folder.parents)))
        require(not any((folder / n).exists() for n in ('HOLD', 'READOUT_HOLD')))
    require(not any(Path('/proc', str(pid)).exists() for pid in PRODUCER_PIDS))
    pinned(ROOT/'terminal.json', TERMINAL_SHA, 16384)
    for name, sha in SOURCE_PINS.items():
        pinned(SOURCE/name, sha, 128 * 1024)
    require(not any(SOURCE.rglob('*.pyc')))
    require(not any(n == 'shengji' or n.startswith('shengji.') for n in sys.modules))
    sys.path.insert(0, str(SOURCE))
    from shengji.luna import benchmark_terminal as validator
    for name, module in list(sys.modules.items()):
        if name == 'shengji' or name.startswith('shengji.'):
            path = Path(module.__file__).resolve()
            require(path.is_relative_to(SOURCE) and path.relative_to(SOURCE).as_posix() in SOURCE_PINS)
    config = decode(pinned(PACKET/'expected-config.json', CONFIG_SHA, 1024 * 1024))
    OUTPUT.mkdir()
    try:
        report = decode(pinned(ROOT/'benchmark/result.json', RESULT_SHA, 64 * 1024 * 1024))
        missing = decode(pinned(ROOT/'benchmark/mirror-sol-perfect-142060913-0.json', MIRROR_SHA, 32 * 1024 * 1024))
        result = analyze(report, config, missing, validator)
        with (OUTPUT/'result.json').open('x') as f:
            json.dump(result, f, sort_keys=True, allow_nan=False, indent=2)
    except Exception:
        raise ValueError('PT read refused; private details suppressed') from None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args()
    run()
