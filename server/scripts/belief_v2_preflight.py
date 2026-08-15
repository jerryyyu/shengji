"""Run or independently verify the score-free BELIEF-V1 V2 preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shengji.rl.belief_v2_preflight import (
    preflight_result_bytes,
    run_capture_preflight,
    verify_preflight_result,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run")
    verify = subparsers.add_parser("verify")
    verify.add_argument("result", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        print(preflight_result_bytes(run_capture_preflight()).decode("ascii"),
              end="")
    else:
        raw = args.result.read_bytes()
        result = json.loads(raw)
        verify_preflight_result(result)
        if preflight_result_bytes(result) != raw:
            raise SystemExit("preflight result is not canonical bytes")
        print("verified=true")


if __name__ == "__main__":
    main()
