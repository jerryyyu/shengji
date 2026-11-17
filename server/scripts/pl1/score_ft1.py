#!/usr/bin/env python3
"""PL1 control (R51 tree): S113's FT1-prior log-likelihood (s113lib.teacher_loglik, unchanged) of the same first M candidates.
usage: score_ft1.py POINTS CANDDIR OUTDIR WORKER NWORKERS M"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s113lib as L
points, canddir, outdir, worker, nworkers, M = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
L.setup_process(); L.verify_packages()
import numpy as np
from shengji.rl.encode import CARD_INDEX
CODES = [None] * 54
for c, i in CARD_INDEX.items():
    CODES[i] = c
bots = L.Bots()
(outdir / "ll").mkdir(parents=True, exist_ok=True)
rows = outdir / f"part-{worker}.jsonl"
done = {json.loads(l)["point_id"] for l in open(rows)} if rows.exists() else set()
out = open(rows, "a")
for k, line in enumerate(open(points)):
    if k % nworkers != worker:
        continue
    pt = json.loads(line); pid = pt["point_id"]
    if pid in done:
        continue
    rec = pt["record"]; t0 = time.perf_counter()
    rnd = L.point_round(rec, pt.get("attempts"), bots)
    z = np.load(canddir / f"{pid}.npz")
    cands = [([[CODES[i] for i in z[f"h{q}"][j]] for q in range(4)], [CODES[i] for i in z["b"][j]]) for j in range(M)]
    ll, nlegal = L.teacher_loglik(bots, rec, rnd, rec["seat"], cands, attempts=pt.get("attempts"))
    np.save(outdir / "ll" / f"{pid}.npy", ll)
    out.write(json.dumps({"point_id": pid, "M": M, "n_zero": int((~np.isfinite(ll)).sum()), "ess_tau1": L.ess(ll),
                          "secs": round(time.perf_counter() - t0, 3)}) + "\n"); out.flush()
print("WORKER DONE", worker, flush=True)
