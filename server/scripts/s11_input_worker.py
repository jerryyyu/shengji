"""Single-use Mini admission worker, dry-run by default.

The reviewed outer controller must run this through s11_input_guard, freeze
source/runtime and own transport/RELEASE gates. Output is PRIVATE staging,
not a published bundle. Only the controller may promote after guard success.
An explicitly pinned stage_from_perf packet adds only the bounded fixed-frame
transport; its SSH/rsync children remain in this worker's guarded group. It
never retries or loads models.
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
            'wall_seconds', 'max_manifest_bytes', 'stage_from_perf'} or
            config['schema'] != 's11-mini-input-worker-v2'):
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
    if type(config['stage_from_perf']) is not bool:
        raise ValueError('explicit transport mode required')
    if config['stage_from_perf'] and Path(config['manifest_path']) != Path(config['root']) / 'manifest.json':
        raise ValueError('transport manifest must be inside fresh staging root')
    if config['stage_from_perf'] and Path(config['root']) == Path(config['output']):
        raise ValueError('transport staging and admission output must differ')
    return config


def stage_inputs(config):
    from scripts.s11_input_transfer import transfer_manifest, transfer_shards
    from shengji.eval.s11_admission_once import _manifest, plan_s11_staging
    from shengji.eval.s11_schedule import _owned_directory
    import stat
    root = _owned_directory(config['root'])
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or any(root.iterdir()):
        raise ValueError('fresh private staging root required; no implicit retry')
    # Even an empty log from a crash makes staging nonempty and prevents reentry.
    with (root / 'transfer.log').open('xb') as log:
        log.flush()
        os.fsync(log.fileno())
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        transfer_manifest(config['manifest_path'], log=log)
        raw = _manifest(config['manifest_path'], config['max_manifest_bytes'])
        plan = plan_s11_staging(raw, manifest_sha256=config['manifest_sha256'])
        transfer_shards(plan, root / 'transfer-files', root, log=log)


def run_worker(config, pin):
    # Dedicated child only. Set process-local limits before importing reader.
    # Memory supervision belongs to the parent: RLIMIT_AS is not a Mac cap.
    os.environ['OMP_NUM_THREADS'] = '1'
    os.nice(10)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, config['wall_seconds'])
    if config['stage_from_perf']:
        stage_inputs(config)
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
