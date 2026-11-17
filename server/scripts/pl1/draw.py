#!/usr/bin/env python3
"""PL1 phase 1 (R51 tree 7fc61e95, S113's exact draw streams): per point, base and B1a 64 worlds and the
M = 2,048 B1a candidates S113 drew, scored against the true deal. Writes one row per point (acc_base, acc_b1a,
must equal S113's main_rows bit for bit) and an npz with the candidates and their per-candidate agreement.
usage: draw.py POINTS OUTDIR WORKER NWORKERS"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s113lib as L

points_path, outdir, worker, nworkers = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
M = 2048
L.setup_process()
L.verify_packages()
import numpy as np
from shengji.rl.encode import CARD_INDEX
from shengji.train import pv_soft_oracle as SOFT
bots = L.Bots()
(outdir / "cands").mkdir(parents=True, exist_ok=True)
rows_path = outdir / f"part-{worker}.jsonl"
done = {json.loads(l)["point_id"] for l in open(rows_path)} if rows_path.exists() else set()
out = open(rows_path, "a")
for k, line in enumerate(open(points_path)):
    if k % nworkers != worker:
        continue
    pt = json.loads(line)
    if pt["point_id"] in done:
        continue
    rec = pt["record"]
    t0 = time.perf_counter()
    rnd = L.point_round(rec, pt.get("attempts"), bots)
    seat = rec["seat"]
    assert [sorted(h) for h in rnd.hands] == pt["true_hands"] and sorted(rnd.buried) == pt["true_buried"]
    lay = L.layout_for(bots, rnd, seat)
    pseed = pt["point_id"]
    bots.reseed(pseed)
    base = L.draw(bots.c, rnd, seat, L.WORLDS)
    b1a = L.draw(bots.r51, rnd, seat, L.WORLDS)
    cands = L.draw(bots.r51, rnd, seat, M)
    row = {"point_id": pt["point_id"], "deal": pt["deal"], "seat": seat, "ply": pt["ply"], "trick": pt["trick"],
           "kind": pt["kind"], "hidden": lay.hidden, "M": M,
           "n_past_other_plays": sum(1 for p in rec["plays_prefix"] if p["seat"] != seat)}
    arrays = {}
    for s in range(4):
        arrays[f"h{s}"] = np.asarray([[CARD_INDEX[c] for c in sorted(h[s])] for h, _ in cands], np.uint8).reshape(M, -1)
    arrays["b"] = np.asarray([[CARD_INDEX[c] for c in sorted(b)] for _, b in cands], np.uint8).reshape(M, -1)
    if lay.hidden:
        row["acc_base"] = L.world_acc(lay, base)
        row["acc_b1a"] = L.world_acc(lay, b1a)
        arrays["agree"] = np.asarray([SOFT.agreement(lay, h, b)[0] / lay.hidden for h, b in cands], np.float64)
        row["acc_cands"] = float(arrays["agree"].mean())
    # exact candidate identity check: re-encoding must give back the drawn multisets
    row["cand_sha256"] = __import__("hashlib").sha256(b"".join(arrays[f"h{s}"].tobytes() for s in range(4)) + arrays["b"].tobytes()).hexdigest()
    np.savez_compressed(outdir / "cands" / f"{pt['point_id']}.npz", **arrays)
    row["secs"] = round(time.perf_counter() - t0, 3)
    out.write(json.dumps(row) + "\n")
    out.flush()
print("WORKER DONE", worker, flush=True)
