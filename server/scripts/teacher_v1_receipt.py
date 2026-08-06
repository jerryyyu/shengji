"""Create a pre-label, write-once producer-run receipt for teacher-v1.

The receipt is not cryptographic attestation against a malicious repository
owner.  It is an immutable orchestration boundary: all eight workers in one
population must bind the exact same pre-existing receipt bytes, and Stage A's
primary and rerun populations must bind receipts with different roles/nonces.
Copying or reserializing label artifacts alone can therefore never manufacture
an independent rerun.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import teacher_v1_label as label                                  # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, EXPERIMENT,    # noqa: E402
                                PRODUCER_RECEIPT_SCHEMA,
                                STATE_SET_SCHEMA, TeacherProtocolError,
                                capture_packet, is_run_id, is_sha256,
                                stable_digest)


ROLE_CONTRACT = {
    "stage-a-primary": ("a", "cheap"),
    "stage-a-rerun": ("a", "cheap"),
    "stage-b-cheap": ("b", "cheap"),
    "stage-b-gold": ("b", "gold"),
}


def write_exclusive(path: str, payload: dict) -> None:
    partial = path + ".partial"
    if os.path.exists(path) or os.path.exists(partial):
        raise TeacherProtocolError(f"refusing to overwrite {path}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(partial, "x") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, path)
    except Exception:
        if os.path.exists(partial):
            os.remove(partial)
        raise


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--role", choices=tuple(ROLE_CONTRACT), required=True)
    ap.add_argument("--state-set", required=True)
    ap.add_argument("--expected-state-set-sha256", required=True)
    ap.add_argument("--out", required=True)
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        if not is_run_id(args.run_id):
            raise TeacherProtocolError("run id must contain 8-128 safe characters")
        if not is_sha256(args.expected_state_set_sha256):
            raise TeacherProtocolError("expected state-set SHA-256 syntax")
        if label.sha256_file(args.state_set) != args.expected_state_set_sha256:
            raise TeacherProtocolError("state-set exact byte hash mismatch")
        with open(args.state_set) as fh:
            state_set = json.load(fh)
        stage, mode = ROLE_CONTRACT[args.role]
        if (state_set.get("schema") != STATE_SET_SCHEMA
                or state_set.get("experiment_id") != EXPERIMENT
                or state_set.get("stage") != stage
                or state_set.get("complete") is not True
                or state_set.get("states_digest")
                != stable_digest(state_set.get("states", []))):
            raise TeacherProtocolError("state-set identity/stage/completion")
        if (state_set.get("packet_id") != CAPTURE_PACKET_ID
                or state_set.get("capture_packet") != capture_packet()):
            raise TeacherProtocolError("state-set capture packet drift")
        runtime = label.runtime_contract(False)
        sources = label.source_digests()
        payload = {
            "schema": PRODUCER_RECEIPT_SCHEMA,
            "experiment_id": EXPERIMENT,
            "packet_id": CAPTURE_PACKET_ID,
            "capture_packet": capture_packet(),
            "complete": True,
            "run_id": args.run_id,
            "role": args.role,
            "stage": stage,
            "mode": mode,
            "state_set": {
                "path": args.state_set,
                "sha256": args.expected_state_set_sha256,
            },
            "nonce": secrets.token_hex(32),
            "created_time_ns": time.time_ns(),
            "creator_pid": os.getpid(),
            **runtime,
            "source_digests": sources,
        }
        write_exclusive(args.out, payload)
        print(f"wrote producer receipt {args.out}", flush=True)
    except (OSError, ValueError, TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
