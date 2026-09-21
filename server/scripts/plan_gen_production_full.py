"""Held gen4/gen3 full-screen packet; no execution or filesystem writes.

Qualification recipes are not sealed yet. This plan cannot launch even if
called with --run. Release requires a reviewed change pinning those recipes,
their runtime evidence, the full-family reader, and host handover guards.
"""
import argparse
import json
from pathlib import Path

from policy_abc_launcher import (
    DEALS, GEN3_PRODUCTION_SUITE, GEN4_PRODUCTION_SUITE,
    PRODUCTION_SHA256, PV_PRODUCTION_SCREEN_SEED, REFERENCE_SOURCE,
    WORKERS, commands,
)


def packet(python, gen4, gen3, production, output):
    """Build the exact intended duel argv without reading models or results."""
    arms = []
    for suite, checkpoint in ((GEN4_PRODUCTION_SUITE, gen4),
                              (GEN3_PRODUCTION_SUITE, gen3)):
        name, argv = commands(python, checkpoint, Path(output), qualify=True,
                              suite=suite, production=production,
                              production_worlds=64)[0]
        # Full-screen window is matched to M1/G1, NOT the qualification window.
        argv[argv.index('--seed0') + 1] = str(PV_PRODUCTION_SCREEN_SEED)
        argv[argv.index('--deals') + 1] = str(DEALS)
        arms.append({'name': name, 'command': argv})
    return {
        'schema': 'held-gen-production-full-v1',
        'launch_hold': True,
        'source_git_sha': REFERENCE_SOURCE,
        'production_checkpoint_sha256': PRODUCTION_SHA256,
        'engine': 'pure', 'arms': arms, 'execution_order': 'gen4 then gen3',
        'expected_pairs_per_arm': DEALS, 'seed0': PV_PRODUCTION_SCREEN_SEED,
        'workers': WORKERS, 'move_timeout_seconds': 300,
        # This is a proposed ceiling, not qualified runtime or an ETA.
        'proposed_arm_timeout_seconds': 21600,
        'proposed_supervisor_timeout_seconds': 43500,
        'scope': 'card play only; shared heuristic declaration and bury',
        'analysis': {
            'primary': 'paired signed levels versus identical production control',
            'family': ['JS_M1_W64_K8', 'JS_G1_W64_K8',
                       'GEN4_W64_K8', 'GEN3_W64_K8'],
            'family_size': 4, 'primary_confidence': 0.9875,
            'bootstrap_seed': 20260921, 'bootstrap_replicates': 10000,
            'unit': 'matched deal, both seat mirrors averaged',
            'pairwise_model_contrasts': 'exploratory common-opponent, not direct duels',
            'qualification_rows_excluded': True,
            'optional_extension': False,
            'null_is_equivalence': False,
        },
        'release_requirements': [
            'both model qualifications sealed with clean complete pairs',
            'exact qualification recipe hashes frozen in reviewed reader and launcher',
            'measured qualification runtime supports reviewed full-arm ceilings',
            'four-model reader validates every frozen recipe and shared seed window',
            'review and CI at released head; named host free and reservation verified',
            'fresh output, source/model hashes, lock and owned-child cleanup guards',
        ],
        'automatic_retry': False, 'automatic_promotion': False,
        'production_deployment': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True)
    parser.add_argument('--gen4-checkpoint', required=True)
    parser.add_argument('--gen3-checkpoint', required=True)
    parser.add_argument('--production-checkpoint', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if args.run:
        raise RuntimeError('launch held: sealed qualification pins and reviewed release required')
    print(json.dumps(packet(args.python, args.gen4_checkpoint, args.gen3_checkpoint,
                            args.production_checkpoint, args.out), indent=2))
    return 0


if __name__ == '__main__':
    main()
