"""DEV-only, read-only archived R4 inference in a separate Python process.

Run this file directly with --archive-server pointing at the retained PR179
source. Do not import it into a current-engine process: the archived contract
uses exact Python types. Inputs contain only the actor observation, not labels
or full hidden worlds. Outputs are ownership marginals, NOT a joint posterior.
No training, test opening, gameplay or production registration occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-server", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--actor", type=Path, required=True,
                        help="actor JSON or an already-opened PR179 DEV shard")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError("choose a fresh inference output; retained results are immutable")
    if "shengji" in sys.modules:
        raise RuntimeError("run bridge as a standalone process, not a current-engine module")
    source = args.archive_server.resolve()
    if not (source / "shengji/rl/belief_policy_models.py").is_file():
        raise ValueError("archived PR179 server source is required")
    raw = args.actor.read_bytes()
    payload = json.loads(raw)
    if "actor" in payload:
        if payload.get("r4_test_opened") is not False:
            raise ValueError("wrapped input must be an already-opened DEV shard")
        payload = payload["actor"]
    sys.path.insert(0, str(source))
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    from shengji.rl.belief_policy_models import _load_cohort
    from shengji.rl.belief_reopen import actor_observation_from_dict_allow_incomplete
    from shengji.rl.belief_v2_common_surface import build_common_surface_tensors
    from shengji.rl.belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
    from shengji.rl.belief_v2_scoring import predict_v2_cohort_ownership

    actor = actor_observation_from_dict_allow_incomplete(payload)
    common = build_common_surface_tensors(actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    result = {"schema": "r4-inference-bridge-dev-v1", "archive_server": str(source),
              "input_file_sha256": hashlib.sha256(raw).hexdigest(),
              "actor_sha256": hashlib.sha256(actor.canonical_bytes()).hexdigest(),
              "joint_posterior": False, "arms": {}}
    identities = []
    for name in ("synthetic-primary", "hard-geometry-label-permutation"):
        root = args.training_root / name
        stage = json.loads((root / "manifest.json").read_bytes())
        identities.append((stage["freeze_sha256"], stage["admission_sha256"],
                           stage["common_calibration_sha256"]))
        if identities[-1] != identities[0]:
            raise ValueError("primary/control training provenance mismatch")
        started = time.monotonic()
        # Reuse archive checkpoint/manifest validation without resurrecting the
        # expired execution admission or requiring the old absolute /opt path.
        cohort, calibration_sha, trained_sha = _load_cohort(
            root, cohort_id=name, freeze_sha256=stage["freeze_sha256"],
            admission_sha256=stage["admission_sha256"])
        loaded = time.monotonic()
        _, ownership = predict_v2_cohort_ownership(actor, common, cohort)
        result["arms"][name] = {
            "model_sha256s": list(cohort.model_sha256s),
            "trained_manifest_sha256": trained_sha,
            "common_calibration_sha256": calibration_sha,
            "load_wall_s": loaded - started,
            "inference_wall_s": time.monotonic() - loaded,
            "ownership": ownership.to_dict(),
        }
        print(json.dumps({"completed_cohort": name,
                          "load_wall_s": result["arms"][name]["load_wall_s"],
                          "inference_wall_s": result["arms"][name]["inference_wall_s"]}), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
