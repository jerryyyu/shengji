"""Compare completed micro4/micro8 capacity workers in repeated A/B order."""
import argparse
import json
import math
from pathlib import Path

from sz3_joint_recipe import smoke_result


METRICS = {"belief", "q", "policy", "leaf_value", "leaf_value_k0", "leaf_value_end", "reply", "belief_ll"}


def compare(legs):
    if len(legs) != 4:
        raise ValueError("expected micro4, micro8, micro4, micro8")
    specs = []
    work = []
    records = []
    for (directory, wall), micro in zip(legs, (4, 8, 4, 8)):
        identity = json.loads((directory / "run.json").read_text())
        if (identity.pop("microbatch_rounds", None) != micro or identity.get("fused_adamw", False)
                or identity.get("rounds_per_batch") != 16 or identity.get("device") != "mps"):
            raise ValueError("wrong trainer recipe")
        specs.append(identity)
        result = smoke_result(directory, required_batch_rounds=16)
        cap, cal = result["capacity"], result["calibration"]
        work.append((cap["rows"], cap["steps"]))
        if set(cal) != METRICS or not all(type(v) in (int, float) and math.isfinite(v) for v in cal.values()):
            raise ValueError("invalid calibration")
        if not math.isfinite(wall) or wall + 1 < cap["train_seconds"] or wall <= 0:
            raise ValueError("invalid whole-worker duration")
        records.append(dict(**result, wall_seconds=wall))
    if any(s != specs[0] for s in specs) or any(w != work[0] for w in work):
        raise ValueError("mismatched trainer settings or completed work")

    def delta(i, j):
        a, b = records[i]["calibration"], records[j]["calibration"]
        return max(abs(a[k] - b[k]) / max(1, abs(a[k]), abs(b[k])) for k in METRICS)

    a, b, c, d = records
    seconds = [r["capacity"]["train_seconds"] for r in records]
    return dict(legs=records, rows_per_leg=work[0][0], steps_per_leg=work[0][1],
                pooled_train_speedup=(seconds[0] + seconds[2]) / (seconds[1] + seconds[3]),
                pooled_worker_speedup=(a["wall_seconds"] + c["wall_seconds"]) / (b["wall_seconds"] + d["wall_seconds"]),
                paired_calibration_delta=[delta(0, 1), delta(2, 3)], base_repeat_delta=delta(0, 2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="contains A1/B1/A2/B2 with wall_seconds from the supervisor")
    root = parser.parse_args().root
    legs = [(root / leg / f"RT4-M-A-micro{micro}-smoke/train", float((root / leg / "wall_seconds").read_text()))
            for leg, micro in (("A1", 4), ("B1", 8), ("A2", 4), ("B2", 8))]
    if len({directory.resolve() for directory, _ in legs}) != 4:
        raise ValueError("comparison requires four distinct workers")
    print(json.dumps(compare(legs), indent=2, allow_nan=False))
