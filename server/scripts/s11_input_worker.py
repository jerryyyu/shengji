"""Single-use Mini admission worker, dry-run by default.

The reviewed outer controller must run this through s11_input_guard, freeze
source/runtime and own transport/RELEASE gates. Output is PRIVATE staging,
not a published bundle. Only the controller may promote after guard success.
This worker never transports files, launches children, retries or loads models.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal


def validate_packet(raw, pin):
    if (type(raw) is not bytes or len(raw) > 65536 or
            type(pin) is not str or not re.fullmatch('[0-9a-f]{64}', pin) or
            hashlib.sha256(raw).hexdigest() != pin):
        raise ValueError('worker packet digest/size refused')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate packet field')
            result[key] = value
        return result
    config = json.loads(raw, object_pairs_hook=unique)
    if (type(config) is not dict or set(config) != {
            'schema', 'manifest_path', 'manifest_sha256', 'root', 'output',
            'wall_seconds', 'max_manifest_bytes'} or
            config['schema'] != 's11-mini-input-worker-v1'):
        raise ValueError('worker packet schema refused')
    for key in ('manifest_path', 'root', 'output'):
        value = config[key]
        if (type(value) is not str or not Path(value).is_absolute() or
                '\x00' in value or '..' in Path(value).parts):
            raise ValueError('canonical absolute worker paths required')
    if (type(config['manifest_sha256']) is not str or
            not re.fullmatch('[0-9a-f]{64}', config['manifest_sha256'])):
        raise ValueError('manifest pin refused')
    for key, exact in (('wall_seconds', 900), ('max_manifest_bytes', 8 << 20)):
        if type(config[key]) is not int or config[key] != exact:
            raise ValueError('worker packet limits differ from accepted design')
    return config


def run_worker(config, pin):
    # Dedicated child only. Set process-local limits before importing reader.
    # Memory supervision belongs to the parent: RLIMIT_AS is not a Mac cap.
    os.environ['OMP_NUM_THREADS'] = '1'
    os.nice(10)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, config['wall_seconds'])
    from shengji.eval.s11_admission_once import admit_s11_inputs_once
    admit_s11_inputs_once(config['manifest_path'], config['root'], config['output'],
        manifest_sha256=config['manifest_sha256'], packet_sha256=pin,
        max_manifest_bytes=config['max_manifest_bytes'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    try:
        # Set before the metadata helper imports the admission module graph;
        # numerical libraries may initialize their thread pools on import.
        os.environ['OMP_NUM_THREADS'] = '1'
        from shengji.eval.s11_admission_once import _manifest
        config = validate_packet(_manifest(args.packet, 65536), args.sha256)
        if args.run:
            if os.path.lexists(args.packet.parent / 'HOLD'):
                raise ValueError('worker held')
            if _manifest(args.packet.parent / 'RELEASE', 65) != (args.sha256 + '\n').encode('ascii'):
                raise ValueError('worker not released')
            run_worker(config, args.sha256)
    except Exception:
        # Never serialize exception values or input-derived records.
        print('{"status":"failed","reason":"input worker refused or incomplete"}')
        return 1
    print(json.dumps(dict(status='private-staging-complete' if args.run else 'unarmed',
                          packet_sha256=args.sha256), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
