#!/usr/bin/env python3
"""PL1 phase 2: S136 log-likelihood of every past opponent play for the first M of S113's B1a candidates.
usage: score_s136.py POINTS CANDDIR OUTDIR WORKER NWORKERS M"""
import json, sys, time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pl1lib as L
import numpy as np

points, canddir, outdir, worker, nworkers, M = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
(outdir / "ll").mkdir(parents=True, exist_ok=True)
model = L.TorchPolicy(threads=1)
rows = outdir / f"part-{worker}.jsonl"
done = {json.loads(l)["point_id"] for l in open(rows)} if rows.exists() else set()
out = open(rows, "a")
for k, line in enumerate(open(points)):
    if k % nworkers != worker:
        continue
    pt = json.loads(line)
    pid = pt["point_id"]
    if pid in done:
        continue
    rec = pt["record"]
    t0 = time.perf_counter()
    states, rnd = L.point_states(rec, pt.get("attempts"))
    assert [sorted(h) for h in rnd.hands] == pt["true_hands"]
    z = np.load(canddir / f"{pid}.npz")
    cands = [([[L.CODES[i] for i in z[f"h{q}"][j]] for q in range(4)], [L.CODES[i] for i in z["b"][j]]) for j in range(M)]
    tm = Counter()
    ll, nplays = L.s136_loglik(model, rec["plays_prefix"], states, rec["seat"], cands, timing=tm)
    np.save(outdir / "ll" / f"{pid}.npy", ll)
    out.write(json.dumps({"point_id": pid, "M": M, "nplays": nplays, "n_zero": int((~np.isfinite(ll)).sum()),
                          "ess_tau1": L.ess(ll), "secs": round(time.perf_counter() - t0, 3),
                          "secs_parts": {a: round(b, 3) for a, b in tm.items()}}) + "\n")
    out.flush()
print("WORKER DONE", worker, flush=True)
