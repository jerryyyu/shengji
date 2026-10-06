"""One-pass S11 saved-summary readout; dry-run by default.

The reviewed invocation must pin the complete interpreter/import runtime and
terminal parent receipts and establish exclusive ownership before --run. The
entrypoint SHA check below is additional, not a substitute for that runtime pin.
No collection RELEASE, host handover, model or capture access occurs here.
"""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.s11_collection_worker import validate_packet, authenticate_pilot
from shengji.eval.s11_admission_once import _manifest
from shengji.eval.s11_handoff import authenticate_s11_input
from shengji.eval.s11_phases import COST, FULL, _pin
from shengji.eval.s11_saved_readout import read_saved_s11
from shengji.luna.benchmark_readout_receipt import run_once


def read_once(*, packet_path, packet_sha256, cost_parent_sha256,
              full_parent_sha256, reader_sha256, output, execute=False):
    """Pins originate in the reviewed terminal handoff, never adjacent files."""
    for pin in (packet_sha256, cost_parent_sha256, full_parent_sha256, reader_sha256):
        _pin(pin)
    if hashlib.sha256(_manifest(Path(__file__), 1 << 20)).hexdigest() != reader_sha256:
        raise ValueError('reader entrypoint digest refused')
    if not Path(packet_path).is_absolute() or str(Path(packet_path).resolve()) != str(packet_path):
        raise ValueError('canonical packet path required')
    config = validate_packet(_manifest(packet_path, 65536), packet_sha256)
    destination = Path(output)
    if (not destination.is_absolute() or str(destination.resolve()) != str(output)):
        raise ValueError('canonical readout destination required')
    # A readout never publishes into any collection/input/gate tree, and cannot
    # contain one. run_once additionally checks parents and refuses reuse.
    protected = [Path(packet_path), Path(config['directory'])]
    protected += [Path(config[k]['path']) for k in ('accepted_input', 'bundle', 'model')]
    protected += [Path(p[k]) for p in config['phases'].values() for k in ('output', 'control')]
    protected += [Path(p['release']).parent for p in config['phases'].values()]
    if any(destination == p or destination in p.parents or p in destination.parents
           for p in protected):
        raise ValueError('readout must be disjoint from collection artifacts')
    if not execute:
        return {'status': 'unarmed'}
    identity = dict(packet_sha256=packet_sha256, cost_parent_sha256=cost_parent_sha256,
                    full_parent_sha256=full_parent_sha256, reader_sha256=reader_sha256)

    def read():
        try:
            slots, _ = authenticate_s11_input(
                accepted_raw=_manifest(config['accepted_input']['path'], 65536),
                accepted_sha256=config['accepted_input']['sha256'],
                bundle_raw=_manifest(config['bundle']['path'], 64 << 20),
                bundle_sha256=config['bundle']['sha256'])
            first = next(s for s in slots if s['status'] == 'valid')
            cost_path = str(Path(config['phases'][COST]['control']) / 'accepted.json')
            _, cost_receipt_sha = authenticate_pilot(config, packet_sha256, FULL,
                first, cost_path, cost_parent_sha256)
            full = config['phases'][FULL]
            # read_saved_s11 authenticates this parent/guard before invoking
            # the only callback that opens scientific outcome bytes.
            return read_saved_s11(
                accepted_raw=_manifest(Path(full['control']) / 'accepted.json', 65536),
                accepted_sha256=full_parent_sha256, packet_sha256=packet_sha256,
                bundle_sha256=config['bundle']['sha256'],
                cost_parent_sha256=cost_parent_sha256, cost_receipt_sha256=cost_receipt_sha,
                limits=full['limits'], scheduled_root_ids=[s['root_id'] for s in slots],
                refused_root_ids=[s['root_id'] for s in slots if s['status'] == 'refused'],
                read_result=lambda: _manifest(Path(full['output']) / 'result.json', 64 << 20))
        except Exception:
            pass
        raise ValueError('sealed S11 read refused; preserve artifacts, no automatic retry')

    return run_once(destination, identity, read)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True)
    parser.add_argument('--packet-sha256', required=True)
    parser.add_argument('--cost-parent-sha256', required=True)
    parser.add_argument('--full-parent-sha256', required=True)
    parser.add_argument('--reader-sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = read_once(packet_path=args.packet, packet_sha256=args.packet_sha256,
            cost_parent_sha256=args.cost_parent_sha256, full_parent_sha256=args.full_parent_sha256,
            reader_sha256=args.reader_sha256, output=args.output, execute=args.run)
        # Scientific payload remains in the exclusive result, never stdout.
        print(json.dumps({'status': 'complete' if args.run else result['status']}))
        return 0
    except Exception:
        print('{"status":"refused","reason":"preserve artifacts; no automatic retry"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
