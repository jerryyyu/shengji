"""Check SZ2-R against the seed-complete extracts in both saved lineage scans."""
import hashlib
import json
from pathlib import Path
import sys

from sz2r_archive_clear import key_for_seed, row_hash

SCANS = ("032e57f71382a82d244bdac7df178f31147041e33170b7cbee9198beb4c33b5a",
         "7349e5fec26113ecfbc9e337cc8c2e51c80da85ff7d15c9b7a510d210961de84")


def extract_ranges(path, digest):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("unexpected corpus scan")
    ranges = {}
    for directory, v in json.loads(raw)["dirs"].items():
        if "seed_min" not in v:
            if not v["kind"].startswith("Y partition"):
                raise ValueError(f"unrecognized directory: {directory}")
            continue
        lo, end = v["seed_min"], v["seed_max"] + 1
        if not (v["status"] == "complete" and not (v["missing"] or v["unlisted"] or v["hash_mismatch"])
                and v["rows"] == v["manifest_rows"] and v["no_seed_rows"] == v["recipe_mismatch"] == 0
                and v["recipe_pairs_checked"] == v["distinct_deals"] == v["distinct_pairs"] == end - lo):
            raise ValueError(f"cannot reconstruct deal keys for {directory}")
        ranges[directory] = (v["manifest_sha256"], lo, end, v["rows"])
    return ranges


def compare(recipe, rt4, ft500):
    if recipe["arm"] != "SZ2-R" or recipe["deals"] <= 0:
        raise ValueError("expected a nonempty SZ2-R screen")
    ranges = extract_ranges(rt4, SCANS[0])
    if not ranges or ranges != extract_ranges(ft500, SCANS[1]):
        raise ValueError("training corpus inputs differ")
    target = {row_hash(key_for_seed(s)) for s in range(recipe["seed0"], recipe["seed0"] + recipe["deals"])}
    if len(target) != recipe["deals"]:
        raise ValueError("screen deals are not distinct")
    seeds = set()
    for _, lo, end, _ in ranges.values():
        seeds.update(range(lo, end))
    overlaps = sum(row_hash(key_for_seed(s)) in target for s in seeds)
    return dict(seed0=recipe["seed0"], deals=len(target), extracts=len(ranges), distinct_training_seeds=len(seeds),
                rows=sum(row[3] for row in ranges.values()), matching_training_seeds=overlaps)


if __name__ == "__main__":
    result = compare(json.loads(Path(sys.argv[1]).read_bytes()), *sys.argv[2:])
    print(json.dumps(result, sort_keys=True))
    sys.exit(int(result["matching_training_seeds"] != 0))
