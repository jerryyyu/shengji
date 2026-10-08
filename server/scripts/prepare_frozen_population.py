"""Project an authenticated completed receipt into an M5 frozen input.

Run only after the packet owner verifies terminal status. This utility neither
checks process liveness nor grants training authority. It opens no raw corpus.
"""
import argparse
import hashlib
import json
from pathlib import Path

from shengji.train.frozen_population import contract_from_receipt


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate receipt field")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    for part in ("train", "val", "test"):
        parser.add_argument(f"--{part}-sha256", required=True)
    parser.add_argument("--added-store", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError("output already exists")
    if args.receipt.stat().st_size > 1024 ** 3:
        raise ValueError("receipt exceeds the 1 GiB input limit")
    raw = args.receipt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.receipt_sha256:
        raise ValueError("base receipt sha256 mismatch")
    receipt = json.loads(raw, object_pairs_hook=_unique_pairs)
    pins = {part: getattr(args, f"{part}_sha256") for part in ("train", "val", "test")}
    contract = contract_from_receipt(receipt, expected_digests=pins,
                                     added_stores=args.added_store)
    encoded = (json.dumps(contract, indent=2, sort_keys=True) + "\n").encode()
    with args.out.open("xb") as output:
        output.write(encoded)
    print(json.dumps({"output": str(args.out), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "receipt_sha256": args.receipt_sha256, "status": "prepared-not-authorized"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
