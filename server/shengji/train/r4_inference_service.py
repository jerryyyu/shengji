"""Standalone DEV R4 inference service. Actor JSON only; no engine state RPC.

Invoked by absolute script path so archived exact-type imports stay isolated.
The retained checkpoint loader runs once; every response is actor-hash bound.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


def serve(predict, identity, incoming, outgoing):
    def emit(payload):
        outgoing.write(json.dumps(payload, sort_keys=True, allow_nan=False)+'\n')
        outgoing.flush()
    emit({'ready': True, 'identity': identity})
    for line in incoming:
        request = json.loads(line)
        if set(request) != {'request_id', 'actor'} or type(request['request_id']) is not int:
            raise ValueError('actor-only inference request required')
        started = time.monotonic()
        response = predict(request['actor'])
        emit({'request_id': request['request_id'], **response,
              'inference_wall_s': time.monotonic()-started})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-server', type=Path, required=True)
    parser.add_argument('--training-root', type=Path, required=True)
    args = parser.parse_args(argv)
    if 'shengji' in sys.modules:
        raise RuntimeError('inference service must run standalone')
    sys.path.insert(0, str(args.archive_server.resolve()))
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    from shengji.rl.belief_policy_models import _load_cohort
    from shengji.rl.belief_reopen import actor_observation_from_dict_allow_incomplete
    from shengji.rl.belief_v2_common_surface import build_common_surface_tensors
    from shengji.rl.belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
    from shengji.rl.belief_v2_scoring import predict_v2_cohort_ownership

    cohorts, identity, provenance = {}, {}, []
    for name in ('synthetic-primary', 'hard-geometry-label-permutation'):
        root = args.training_root/name
        stage = json.loads((root/'manifest.json').read_bytes())
        provenance.append(tuple(stage[k] for k in ('freeze_sha256', 'admission_sha256', 'common_calibration_sha256')))
        if provenance[-1] != provenance[0]:
            raise ValueError('primary/control training provenance mismatch')
        cohort, calibration_sha, trained_sha = _load_cohort(
            root, cohort_id=name, freeze_sha256=stage['freeze_sha256'], admission_sha256=stage['admission_sha256'])
        cohorts[name] = cohort
        identity[name] = {'model_sha256s': list(cohort.model_sha256s),
                          'trained_manifest_sha256': trained_sha,
                          'common_calibration_sha256': calibration_sha}

    def predict(payload):
        actor = actor_observation_from_dict_allow_incomplete(payload)
        common = build_common_surface_tensors(actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
        return {'actor_sha256': actor.sha256(), 'joint_posterior': False,
                'arms': {name: {'ownership': predict_v2_cohort_ownership(actor, common, cohort)[1].to_dict()}
                         for name, cohort in cohorts.items()}}

    serve(predict, identity, sys.stdin, sys.stdout)


if __name__ == '__main__':
    main()
