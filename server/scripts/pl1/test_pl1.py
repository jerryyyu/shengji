"""PL1 checks on the S112 PILOT points (never the main sample): fast inputs == decision_inputs on a root clone,
torch policy logits == UnifiedNumpy.policy_logits, and the per-point timing."""
import json, sys, time, random
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pl1lib as L
import numpy as np

PILOT = "/Users/jerryyu/shengji-archive/2026-11-06-s113-belief-teacher-b1a/data/pilot_points.jsonl"
CAND = Path("/Users/jerryyu/.claude/jobs/d0498cda/tmp/pl1/phase1/pilot/cands")


def load_cands(pid, m):
    z = np.load(CAND / f"{pid}.npz")
    return [([[L.CODES[i] for i in z[f"h{q}"][k]] for q in range(4)], [L.CODES[i] for i in z["b"][k]]) for k in range(m)]


def main():
    model = L.TorchPolicy(threads=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    pts = [json.loads(l) for l in open(PILOT)]
    rng = random.Random(1)
    worstX, allM, worstL, nchk = 0.0, True, 0.0, 0
    for pt in pts:
        rec = pt["record"]
        states, rnd = L.point_states(rec, pt.get("attempts"))
        assert [sorted(h) for h in rnd.hands] == pt["true_hands"]
        cands = load_cands(pt["point_id"], 8)
        prefix = rec["plays_prefix"]
        for (t, s, chosen, rnd_t, refs) in states:
            if s == rec["seat"] or rng.random() > 0.25:
                continue
            st = L.SeatState(rnd_t, s, refs)
            add = Counter()
            for p in prefix[t:]:
                if int(p["seat"]) == s:
                    add.update(p["cards"])
            hl, bl = [], []
            for hands, b in cands:
                hl.append([list(hands[q]) + ([] if q != s else list(add.elements())) for q in range(4)])
                # the other seats' hands at t also get their later plays back
                for q in range(4):
                    if q != s:
                        hl[-1][q] = list(hands[q]) + [c for p in prefix[t:] if int(p["seat"]) == q for c in p["cards"]]
                bl.append(b)
            own = np.stack([L.counts(h[s]) for h in hl]); bur = np.stack([L.counts(b) for b in bl])
            wx, eq = L.fast_inputs_check(st, own, bur, hl, bl)
            worstX = max(worstX, wx); allM &= eq; nchk += len(hl)
            X, M, rc, ok = st.batch(own, bur)
            enc = model.enc(st.inp)
            lt = model.card_logits(st.inp, enc, X, M, rc)
            for k in range(len(hl)):
                ref = L.slow_inputs(rnd_t, s, refs, hl[k], bl[k])
                ln = model.u.policy_logits(ref)
                worstL = max(worstL, float(np.abs(ln - lt[k]).max()))
    print(json.dumps({"inputs_checked": nchk, "max_abs_X_diff": worstX, "M_and_row_card_equal": allM,
                      "max_abs_logit_diff_torch_vs_numpy": worstL}))
    assert worstX == 0.0 and allM and worstL < 1e-3


if __name__ == "__main__":
    main()
