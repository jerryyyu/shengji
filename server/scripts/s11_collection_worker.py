"""Private S11 worker; dry-run default, separately released phases only.

The owning controller supplies frozen runtime and containment. This is not a
host scheduler. Both phase outputs/logs remain private until parent acceptance;
full scientific interpretation remains a separate sealed readout.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal


def validate_packet(raw, pin):
    from shengji.eval.s11_input_bundle import _unique, _bad_constant
    from shengji.eval.s11_handoff import _pin
    from shengji.eval.s11_phases import COST, FULL
    if (type(raw) is not bytes or not 0 < len(raw) <= 65536
            or hashlib.sha256(raw).hexdigest() != _pin(pin)):
        raise ValueError('collection packet digest/size refused')
    config = json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
    if (type(config) is not dict or set(config) != {
            'schema', 'recipe', 'accepted_input', 'bundle', 'model', 'directory', 'phases'}
            or config['schema'] != 's11-collection-packet-v1'
            or config['recipe'] != 'release38-unbudgeted-card-play-seed0-fill0'):
        raise ValueError('collection packet schema/recipe refused')

    def path(value):
        if (type(value) is not str or '\x00' in value or not Path(value).is_absolute()
                or str(Path(value).resolve()) != value):
            raise ValueError('canonical collection paths required')

    for key in ('accepted_input', 'bundle', 'model'):
        fields = {'path', 'sha256'} | ({'source_checkpoint_sha256'} if key == 'model' else set())
        if type(config[key]) is not dict or set(config[key]) != fields:
            raise ValueError('collection artifact reference refused')
        path(config[key]['path'])
        for field in fields - {'path'}:
            _pin(config[key][field])
    path(config['directory'])
    if type(config['phases']) is not dict or set(config['phases']) != {COST, FULL}:
        raise ValueError('both phase definitions required')
    outputs = [config['directory']]
    for phase in config['phases'].values():
        if type(phase) is not dict or set(phase) != {'release', 'output', 'control', 'limits'}:
            raise ValueError('collection phase fields refused')
        for key in ('release', 'output', 'control'):
            path(phase[key])
        outputs.extend([phase['output'], phase['control']])
        limits = phase['limits']
        if (type(limits) is not dict or set(limits) != {
                'wall_seconds', 'rss_threshold_bytes', 'sample_seconds', 'term_grace_seconds'}
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                       for v in limits.values())):
            raise ValueError('explicit positive finite guard limits required')
    if len(set(outputs)) != len(outputs) or any(
            Path(a) in Path(b).parents for a in outputs for b in outputs if a != b):
        raise ValueError('collection output trees must be disjoint')
    if config['phases'][COST]['release'] == config['phases'][FULL]['release']:
        raise ValueError('distinct phase release paths required')
    for ref in [config[k]['path'] for k in ('accepted_input', 'bundle', 'model')] + [
            p['release'] for p in config['phases'].values()]:
        if any(ref == out or Path(out) in Path(ref).parents for out in outputs):
            raise ValueError('input/release cannot live in output trees')
    return config


def authenticate_inputs(config):
    from shengji.eval.s11_admission_once import _manifest
    from shengji.eval.s11_handoff import authenticate_s11_input
    raw = _manifest(config['bundle']['path'], 64 << 20)
    slots, receipt = authenticate_s11_input(
        accepted_raw=_manifest(config['accepted_input']['path'], 65536),
        accepted_sha256=config['accepted_input']['sha256'],
        bundle_raw=raw, bundle_sha256=config['bundle']['sha256'])
    return raw, next(s for s in slots if s['status'] == 'valid')


def authenticate_pilot(config, pin, phase, first, cost_path, cost_sha):
    from shengji.eval.s11_admission_once import _manifest
    from shengji.eval.s11_cost_handoff import authenticate_cost
    from shengji.eval.s11_phases import COST
    if phase == COST:
        if cost_path is not None or cost_sha is not None:
            raise ValueError('cost phase cannot import a parent acceptance')
        return None, None
    expected = str(Path(config['phases'][COST]['control']) / 'accepted.json')
    if str(cost_path) != expected:
        raise ValueError('accepted pilot must be the fixed cost parent output')
    raw = _manifest(Path(config['phases'][COST]['output']) / 'result.json', 65536)
    digest = authenticate_cost(accepted_raw=_manifest(cost_path, 65536),
        accepted_sha256=cost_sha, result_raw=raw, packet_sha256=pin,
        bundle_sha256=config['bundle']['sha256'], first_slot=first,
        limits=config['phases'][COST]['limits'])
    return raw, digest


def run_worker(config, pin, phase, cost_path=None, cost_sha=None):
    from shengji.eval.s11_phases import run_s11_phase, require_phase_release
    selected = config['phases'][phase]
    require_phase_release(selected['release'], pin, phase)
    os.nice(10)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, selected['limits']['wall_seconds'])
    raw, first = authenticate_inputs(config)
    pilot_raw, pilot_pin = authenticate_pilot(config, pin, phase, first, cost_path, cost_sha)
    from shengji.eval.s11_model import make_s11_model_factory
    model = config['model']
    factory = make_s11_model_factory(model['path'], sha256=model['sha256'],
                                    source_checkpoint_sha256=model['source_checkpoint_sha256'])
    return run_s11_phase(phase=phase, release_path=selected['release'], packet_sha256=pin,
        bundle_raw=raw, bundle_sha256=config['bundle']['sha256'], directory=config['directory'],
        output_dir=selected['output'], bot_factory=factory,
        cost_receipt_raw=pilot_raw, cost_receipt_sha256=pilot_pin)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--phase', required=True, choices=['cost-first-valid-slot', 'full-schedule'])
    parser.add_argument('--accepted-cost')
    parser.add_argument('--accepted-cost-sha256')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    try:
        for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
            os.environ[key] = '1'
        from shengji.eval.s11_admission_once import _manifest
        config = validate_packet(_manifest(args.packet, 65536), args.sha256)
        if args.run:
            run_worker(config, args.sha256, args.phase,
                       args.accepted_cost, args.accepted_cost_sha256)
    except Exception:
        print('{"status":"incomplete","reason":"private collection worker refused"}')
        return 1
    print(json.dumps({'status': 'private-complete' if args.run else 'unarmed'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
