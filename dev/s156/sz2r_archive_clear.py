"""Compare the SZ2-R deck keys with the four archived exposure indexes."""
import hashlib
import json
from pathlib import Path
import sys

from shengji.train.seed_clearance import key_for_seed

ARCHIVE = Path.home() / "shengji-archive"
INDEXES = {
    "Y": ("2026-11-03-exact-deal-clearance/results/y_scan_cloud.out.json",
          "c9711279eb0c11ab9334a0e6d55043076431aa11775c683afa833360fb06d8d8"),
    "S17": ("2026-11-03-exact-deal-clearance/results/s17_scan_perf.out.json",
            "721a1fb7d595b89d5a49fe9706c39af37d0d675d802c1756df1dd61b64ef2ef6"),
    "M17/live": ("2026-11-03-ultra-screens/bbw50U/exposure_r2/s58_clearance/cloud_scan.out.json",
                 "9dc6a89c55a735a645b8e0c9b7d3f0334ba4ae547091142ff73f41d9e1ea2a1b"),
    "live decks": ("2026-11-03-exact-deal-clearance/results/live_clear.json",
                   "746200831793811f0fdcf822ae2655f38f2f4b511fac4ad935d63e5aa98c5073"),
}


def row_hash(key):
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)


def compare(recipe):
    if recipe["arm"] != "SZ2-R":
        raise ValueError("expected SZ2-R recipe")
    lo, n = recipe["seed0"], recipe["deals"]
    keys = {key_for_seed(seed) for seed in range(lo, lo + n)}
    hashes = {row_hash(k) for k in keys}
    if not n or len(keys) != n or len(hashes) != n:
        raise ValueError("empty or nonunique screen block")
    result = {}
    for name, (rel, expected) in INDEXES.items():
        raw = (ARCHIVE / rel).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"archive digest mismatch: {rel}")
        index = json.loads(raw)
        if name == "live decks":
            deals = {r["deal_key"] for r in index["per_round"].values()}
            result[name] = dict(groups=1, entries=len(deals), overlaps=len(keys & deals))
            continue
        groups = list(index.values()) if name != "M17/live" else [*index["m17"].values(), *index["live"].values()]
        entries = overlaps = controls = 0
        for group in groups:
            deals = set(map(int, group["distinct_deals"]))
            if group.get("pairs"):
                seed, stored = map(int, group["pairs"][0])
                if row_hash(key_for_seed(seed)) != stored or stored not in deals:
                    raise ValueError(f"positive control failed: {name} seed {seed}")
                controls += 1
            entries += len(deals)
            overlaps += len(deals & hashes)
        result[name] = dict(groups=len(groups), entries=entries, controls=controls, overlaps=overlaps)
    return dict(seed0=lo, deals=n, indexes=result)


if __name__ == "__main__":
    report = compare(json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps(report, sort_keys=True))
    sys.exit(int(any(v["overlaps"] for v in report["indexes"].values())))
