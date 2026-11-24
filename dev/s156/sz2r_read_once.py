"""Read a reserved SZ2-R pilot or screen using the published handoff digest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from sz2r_producer import run_inputs
from sz2r_stage1 import stage1

HERE = Path(__file__).resolve()
SOURCES = (HERE.name, "sz2r_stage1.py", "sz2r_producer.py", "sz2r_recipe.py",
           "sz2r_checkpoint_exposure.json", "sz2r_preflight_exposure.json")
PAYLOADS = {"duel.jsonl", "duel.jsonl.resume.json", "duel.time", "manifest.json", "run.log"}
TS = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"


def regular(path):
    if path != path.resolve() or not path.is_file():
        raise ValueError(f"expected canonical regular file {path}")
    return path


def verified(path, digest):
    data = regular(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"digest mismatch for {path}")
    return data


def saved(claim, handoff_sha):
    receipt = json.loads(regular(claim / "receipt.json").read_bytes())
    if receipt["handoff_sha256"] != handoff_sha:
        raise ValueError("saved read belongs to another handoff")
    return json.loads(verified(claim / "result.json", receipt["result_sha256"]))


def read_once(path, digest):
    h = json.loads(verified(path, digest))
    lane = Path(h["lane"])
    mode = h["mode"]
    if (mode not in ("pilot", "screen") or h["reader"] != "codex" or h["reader_path"] != str(HERE)
            or path != lane / f"{mode}.handoff.json" or set(h["sources"]) != set(SOURCES)):
        raise ValueError("wrong reader, sources or reservation")
    for name in SOURCES:
        verified(HERE.with_name(name), h["sources"][name])
    def check_holds():
        for hold in (lane / "HOLD", lane / "READOUT.HOLD", *map(Path, h["hold_paths"])):
            if not hold.is_absolute() or os.path.lexists(hold):
                raise ValueError(f"invalid or active readout HOLD {hold}")
    check_holds()
    recipe = json.loads(verified(lane / "recipe.json", h["recipe_sha256"]))
    seed0, deals, root = run_inputs(recipe, mode, lane)
    name = root.name
    status = verified(lane / f"{name}.status", h["status_sha256"]).decode().splitlines()
    rsha, sums = h["recipe_sha256"], h["sums_sha256"]
    forms = [fr"START {TS} mode={name} arm=SZ2-R pid=\d+ seed0={seed0} deals={deals} workers=[1-9]\d* recipe={rsha}",
             fr"LOCKED {TS} after \d+s.*", fr"NAMES {TS} ok", fr"PRODUCER {TS} .*",
             fr"DONE {TS} recipe={rsha} rows={2*deals} sums={sums} rc=0", fr"UNLOCKED {TS}.*"]
    if len(status) != len(forms) or not all(re.fullmatch("UTD " + f, s) for f, s in zip(forms, status)):
        raise ValueError("status does not seal the reserved arm")
    entries = {}
    for line in verified(root / "SHA256SUMS", sums).decode().splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  \./([^/]+)", line)
        if not m or m[2] in entries:
            raise ValueError("invalid seal entry")
        entries[m[2]] = m[1]
    if set(entries) != PAYLOADS or {p.name for p in root.iterdir()} != PAYLOADS | {"SHA256SUMS"}:
        raise ValueError("unexpected sealed file set")
    for filename in PAYLOADS:
        regular(root / filename)

    if mode == "screen":
        pilot_path = lane / "pilot.handoff.json"
        pilot_sha = h["pilot_handoff_sha256"]
        pilot = json.loads(verified(pilot_path, pilot_sha))
        if pilot["recipe_sha256"] != rsha or pilot["sources"] != h["sources"] or pilot["lane"] != str(lane):
            raise ValueError("screen and pilot reservations differ")
        # Revalidate pilot metadata and the saved receipt without starting a missing pilot.
        regular(lane / "pilot.read" / "receipt.json")
        verified(lane / "pilot.read" / "result.json", h["pilot_result_sha256"])
        result = read_once(pilot_path, pilot_sha)
        if result["mode"] != "pilot" or result["validity"] != "VALID":
            raise ValueError("screen requires a valid saved pilot")
    claim = lane / f"{mode}.read"
    check_holds()
    if os.path.lexists(claim):
        return saved(claim, digest)
    claim.mkdir()
    with tempfile.TemporaryDirectory(dir=claim) as tmp:
        snapshot = Path(tmp)
        expected = dict(schema="utd-manifest-r1", mode=name, arm="SZ2-R", recipe_sha256=rsha,
                        seed0=seed0, deals=deals, tree_head=recipe["head"], rc=0)
        if json.loads(verified(root / "manifest.json", entries["manifest.json"])) != expected:
            raise ValueError("manifest differs from reservation")
        for filename in sorted(PAYLOADS - {"manifest.json"}):
            check_holds()
            with (root / filename).open("rb") as src:
                if filename == "duel.jsonl":
                    hashed = hashlib.sha256()
                    with (snapshot / filename).open("xb") as dst:
                        while chunk := src.read(1024 * 1024):
                            hashed.update(chunk)
                            dst.write(chunk)
                else:
                    hashed = hashlib.file_digest(src, "sha256")
            if hashed.hexdigest() != entries[filename]:
                raise ValueError(f"changed sealed file {filename}")
        check_holds()
        result = stage1(recipe, mode, lane, verified_rows_dir=snapshot)
    check_holds()
    data = json.dumps(result, allow_nan=False, sort_keys=True).encode()
    (claim / "result.json").write_bytes(data)
    receipt = dict(handoff_sha256=digest, result_sha256=hashlib.sha256(data).hexdigest())
    temp = claim / "receipt.tmp"
    temp.write_text(json.dumps(receipt))
    temp.rename(claim / "receipt.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("sha256")
    args = parser.parse_args()
    print(json.dumps(read_once(args.handoff, args.sha256), sort_keys=True))
