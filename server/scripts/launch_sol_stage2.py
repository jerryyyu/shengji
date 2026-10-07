"""Stage-two packet entry: require accepted stage-one publication before launch.

The reviewer must pin the accepted result/receipt and actual predecessor PIDs
in the campaign's predecessor_publication field. This verifies those bytes,
not scientific approval. No raw result references are followed. The existing
launcher still owns RELEASE, HOLD, memory, reservation and source fences.
"""
import argparse
import hashlib
import os
from pathlib import Path

from scripts import launch_production_llm_panel as launcher
from scripts.run_sealed_panel_readout import decode
from shengji.luna.benchmark_panel_seals import _metadata, _require
from shengji.luna.benchmark_retention import _hex, _strict_equal


def require_predecessor(config):
    _require(config.get('schema') == launcher.STAGE2_SCHEMA, 'stage-two recipe required')
    refs = config.get('predecessor_publication')
    _require(type(refs) is dict and set(refs) == {'result', 'receipt', 'pids'},
             'pinned predecessor publication required')
    pids = refs['pids']
    _require(type(pids) is list and len(pids) == 3
             and all(type(p) is int and p > 0 for p in pids) and len(set(pids)) == 3,
             'three distinct predecessor PIDs required')
    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except OSError as exc:
            raise ValueError('predecessor process state unresolved') from exc
        raise ValueError('predecessor process still exists')
    receipt = _metadata(refs['receipt'], 'stage-one publication receipt')
    result = _metadata(refs['result'], 'accepted stage-one readout')
    _require(receipt.get('status') == 'complete'
             and receipt.get('result_sha256') == refs['result']['sha256'],
             'stage-one publication incomplete or mismatched')
    _require(result.get('schema') == 'sol-feedback-on-stage1-readout-v1'
             and result.get('treatment') == 'feedback-ON'
             and result.get('status') in ('complete', 'partial')
             and result.get('benchmark_ids') == list(launcher.STAGE1_ROWS)
             and type(result.get('panel_size')) is int and result['panel_size'] == 2
             and type(result.get('policies')) is dict
             and set(result['policies']) == set(launcher.STAGE1_ROWS)
             and type(result.get('terminal_accounting')) is dict
             and set(result['terminal_accounting']) == set(launcher.STAGE1_ROWS)
             and type(result.get('seals')) is dict
             and result.get('seals', {}).get('metadata_and_content_validated') is True,
             'accepted terminal stage-one readout required')
    _hex(config.get('prepared_roots_sha256'), 'prepared root digest')
    seeds = config.get('seeds')
    _require(type(seeds) is list and len(seeds) == 10
             and all(type(seed) is int for seed in seeds) and len(set(seeds)) == 10,
             'ten distinct prepared seeds required')
    _require(_strict_equal(result.get('seeds'), seeds)
             and type(result.get('prepared_roots')) is dict
             and result.get('prepared_roots', {}).get('source_result_sha256')
             == config.get('prepared_roots_sha256'), 'predecessor root/schedule mismatch')


def run(config_path, expected, *, arm=False):
    config_path = Path(config_path)
    raw = config_path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected, 'campaign config hash mismatch')
    require_predecessor(decode(raw))
    # Normal launcher rechecks the config and validates source/models once.
    return launcher.run(config_path, expected, arm=arm)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--arm', action='store_true')
    args = parser.parse_args()
    run(args.config, args.sha256, arm=args.arm)


if __name__ == '__main__':
    main()
