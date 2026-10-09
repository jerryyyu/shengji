"""DEV (tier i) lead-admission width diagnostic for release 42 (follow-up to leaddiag-r42-20261008).

Self-play with four release-42 pv-search bots (div rc tb la dts, W64 K8, no serving budget, heuristic bury).  Play
always continues with the release-42 move.  At every LEAD with >= 2 legal actions, after the served decision:

  a   served: K=8 admission, 64 worlds, the bot's own _select (captured from the decision itself)
  k16/k24/k32  the REAL admission (`_admission` -> `_admit` -> `_admit_diverse`, lead_anchor slot 0) with
               bot.candidates = K, scored on the same 64 base worlds, the bot's own _select
  p16/p24  value prefilter: every legal lead on the first 8 base worlds; top-N by that mean U the served admitted
           set (served admission order first, so slot 0 / the anchor keeps the exact-tie retention), scored on all
           64 base worlds, _select
  g   full legal set on the 64 base worlds (served admitted first), _select -- upper reference only
Each variant is executed for real and timed (admission + value pass + select, single thread).  The decision's shared
cost (worlds, policy scores, heuristic anchor, doomed-throw swap) = served seconds - served admission/value/select time.
ref = 512 fresh worlds (independent sampler) on the union of every variant pick (selected and pure-argmax) and the
full-set (64w) top 3.  regret(v) = ref(ref_best) - ref(pick_v): the value head's own expectation, NOT game value.
Yields to /root/.claude-host.lock between positions and before every value batch.
Prepared collector integration; no run is authorized by this file. Replay payloads include the
full hidden deal for DEV reconstruction only, never as policy input. It does not restore bot RNG.
Origin: archived leaddiag2-r42-20261008/lead_diag2.py; scientific diagnostic unchanged.
Usage: python -m scripts.lead_admission_diagnostic <package.npz> <sha256> <seed> <max_positions> <deadline_unix> <out.jsonl> <lock> <stop>
"""
import copy
import json, os, random, sys, time
from shengji.train.lead_root_capture import LeadCapture
import numpy as np
from shengji.engine.game import Game
from shengji.ai import env
from shengji.train.pv_search_policy import PVSearchBot, make_pv_search_bot
from shengji.train.policy_value_search import leading

R42 = dict(admission_diversity=True, refusal_constraints=True, tiebreak_points=True,
           lead_anchor=True, doomed_throw_swap=True)
REF, TOP_REF, PRE_W = 512, 3, 8
KS = (16, 24, 32)
PRES = (16, 24)


class Yield(Exception):
    pass


def check():
    if os.path.exists(LOCK):
        raise Yield("host_lock")
    if os.path.exists(STOP):
        raise Yield("stop_file")
    if time.time() > DEADLINE:
        raise Yield("deadline")


class Probe(PVSearchBot):
    def _admission(self, rnd, seat, actions, preferences, anchor_index, worlds, check_budget=None):
        t = time.perf_counter()
        out = super()._admission(rnd, seat, actions, preferences, anchor_index, worlds, check_budget)
        self._t["adm"] = time.perf_counter() - t
        self._cap = (list(actions), np.array(preferences, dtype=np.float64), int(anchor_index), list(worlds), list(out))
        return out

    def _value_means(self, rnd, seat, actions, worlds, check_budget=None):
        t = time.perf_counter()
        matrix, sums, batches = self.value_matrix(rnd, seat, actions, worlds, check_budget)
        self._t["val"] = time.perf_counter() - t
        self._probe = (list(actions), list(worlds), matrix, sums)
        return sums / len(worlds), batches

    def _select(self, *a, **kw):
        t = time.perf_counter()
        out = super()._select(*a, **kw)
        self._t["sel"] = self._t.get("sel", 0.0) + time.perf_counter() - t
        return out


def key(a):
    return tuple(sorted(a))


def draw(bot, sampler, rnd, seat, n):
    own, own_w = bot.sampler, bot.worlds
    try:
        bot.sampler, bot.worlds = sampler, n
        worlds, _ = bot._worlds(rnd, seat, check)
    finally:
        bot.sampler, bot.worlds = own, own_w
    return worlds


def vm(bot, rnd, seat, actions, worlds):
    m, sums, _ = bot.value_matrix(rnd, seat, [list(a) for a in actions], worlds, check)
    return m, sums / len(worlds)


def run_ballot(bot, rnd, seat, acts, idx, prefs, base, t_adm):
    """value pass on 64 base worlds + _select over actions[idx]; returns (pick idx, argmax idx, matrix, times)."""
    cand = [acts[i] for i in idx]
    t = time.perf_counter()
    m, means = vm(bot, rnd, seat, cand, base)
    t_val = time.perf_counter() - t
    t = time.perf_counter()
    w = bot._select(rnd, seat, [list(c) for c in cand], means, worlds=base, check_budget=check,
                    priors=[float(prefs[i]) for i in idx])
    t_sel = time.perf_counter() - t
    return idx[w], idx[int(np.argmax(means))], m, {"adm": t_adm, "val": t_val, "sel": t_sel,
                                                    "spec": t_adm + t_val + t_sel}


def analyze(bot, rnd, seat, rec, served_t, samplers):
    acts, prefs, anchor_raw, base, chosen = bot._cap
    assert [key(acts[i]) for i in chosen] == [key(a) for a in rec["admitted"]]
    nW, nL = len(base), len(acts)
    L = [key(a) for a in acts]
    sel_a = rec["selected_index"]
    mA, sumsA = bot._probe[2], bot._probe[3]
    argmax_a = chosen[int(np.argmax(sumsA / nW))]
    common = rec["seconds"] - served_t.get("adm", 0.0) - served_t.get("val", 0.0) - served_t.get("sel", 0.0)
    T0 = time.time()
    V = {"a": {"pick": sel_a, "argmax": argmax_a, "ballot": list(chosen), "evals": nW * len(chosen),
               "t": {"adm": served_t.get("adm", 0.0), "val": served_t.get("val", 0.0),
                     "sel": served_t.get("sel", 0.0)}}}
    V["a"]["t"]["spec"] = sum(V["a"]["t"].values())
    cols = {}
    # --- wider policy admissions through the real admission code
    own_k = bot.candidates
    try:
        for K in [8] + list(KS):
            bot.candidates = K
            t = time.perf_counter()
            idx = [int(i) for i in super(Probe, bot)._admission(rnd, seat, acts, prefs, anchor_raw, base, check)]
            t_adm = time.perf_counter() - t
            if K == 8:
                assert idx == list(chosen), "K=8 re-admission does not reproduce the served ballot"
                continue
            p, am, m, tt = run_ballot(bot, rnd, seat, acts, idx, prefs, base, t_adm)
            V[f"k{K}"] = {"pick": p, "argmax": am, "ballot": idx, "evals": nW * len(idx), "t": tt,
                          "lead_anchor_to": (bot._lead_anchor or {}).get("lead_anchor_to")}
            for j, i in enumerate(idx):
                cols[i] = m[:, j]
    finally:
        bot.candidates = own_k
    # --- value prefilter on the first 8 base worlds
    t = time.perf_counter()
    m8, means8 = vm(bot, rnd, seat, acts, base[:PRE_W])
    t_pre = time.perf_counter() - t
    order8 = sorted(range(nL), key=lambda i: (-means8[i], i))
    for N in PRES:
        t = time.perf_counter()
        top = set(order8[:N])
        idx = list(chosen) + [i for i in order8[:N] if i not in set(chosen)]
        t_sel_pre = time.perf_counter() - t
        p, am, m, tt = run_ballot(bot, rnd, seat, acts, idx, prefs, base, t_pre + t_sel_pre)
        tt["prefilter"] = t_pre
        V[f"p{N}"] = {"pick": p, "argmax": am, "ballot": idx, "evals": PRE_W * nL + nW * len(idx),
                      "evals_reuse": PRE_W * nL + (nW - PRE_W) * len(idx), "t": tt}
        for j, i in enumerate(idx):
            cols.setdefault(i, m[:, j])
    # --- full set (served admitted first)
    idx = list(chosen) + [i for i in range(nL) if i not in set(chosen)]
    p, am, mF, tt = run_ballot(bot, rnd, seat, acts, idx, prefs, base, 0.0)
    V["g"] = {"pick": p, "argmax": am, "ballot_n": len(idx), "evals": nW * len(idx), "t": tt}
    meansF = np.empty(nL)
    meansF[idx] = mF.mean(axis=0)
    # sanity: the same leaf on the same world scores the same in every pass (batch composition may differ)
    full_col = {i: mF[:, j] for j, i in enumerate(idx)}
    maxdiff = max([float(np.max(np.abs(c - full_col[i]))) for i, c in cols.items()]
                  + [float(np.max(np.abs(mA[:, j] - full_col[i]))) for j, i in enumerate(chosen)])
    orderF = sorted(range(nL), key=lambda i: (-meansF[i], i))
    fb = orderF[0]
    ranked = sorted(range(nL), key=lambda i: (-prefs[i], i))
    pol_rank = {i: r + 1 for r, i in enumerate(ranked)}
    pre_rank = {i: r + 1 for r, i in enumerate(order8)}
    # --- reference
    picks = {}
    for v, d in V.items():
        picks[v] = d["pick"]
        picks[v + "0"] = d["argmax"]
    Rset = list(dict.fromkeys(list(picks.values()) + orderF[:TOP_REF]))
    rw = draw(bot, samplers[1], rnd, seat, REF)
    mR, meansR = vm(bot, rnd, seat, [acts[i] for i in Rset], rw)
    rb = int(np.argmax(meansR))
    ri = {i: j for j, i in enumerate(Rset)}
    ja = ri[sel_a]
    out = {}
    for v, i in picks.items():
        j = ri[i]
        d = mR[:, rb] - mR[:, j]
        da = mR[:, j] - mR[:, ja]
        e = {"pick": " ".join(acts[i]), "ncards": len(acts[i]), "regret": float(meansR[rb] - meansR[j]),
             "se": float(np.std(d, ddof=1) / np.sqrt(len(d))) if j != rb else 0.0,
             "diff_vs_a": float(da.mean()), "diff_vs_a_se": float(np.std(da, ddof=1) / np.sqrt(len(da))),
             "changed_vs_a": i != sel_a, "in_served_ballot": i in set(chosen),
             "policy_rank": pol_rank[i], "full64_rank": orderF.index(i) + 1}
        if not v.endswith("0"):
            d0 = V[v]
            e.update({"evals": d0["evals"], "evals_reuse": d0.get("evals_reuse", d0["evals"]),
                      "ballot": d0.get("ballot_n", len(d0.get("ballot", []))),
                      "t_spec": d0["t"]["spec"], "t_total": common + d0["t"]["spec"], "t_parts": d0["t"],
                      "full_best_in_ballot": (fb in set(d0["ballot"])) if "ballot" in d0 else True})
        out[v] = e
    return {
        "legal": nL, "legal_count": rec["legal_count"], "legal_complete": rec["legal_complete"],
        "served": " ".join(acts[sel_a]), "served_ncards": len(acts[sel_a]), "played": " ".join(rec["played"]),
        "anchor_raw": " ".join(acts[anchor_raw]), "slot0": " ".join(acts[chosen[0]]),
        "full_best": " ".join(acts[fb]), "full_best_ncards": len(acts[fb]),
        "full_best_policy_rank": pol_rank[fb], "full_best_pre8_rank": pre_rank[fb],
        "full_best_in_served": fb in set(chosen),
        "full_top3_policy_rank": [pol_rank[i] for i in orderF[:3]],
        "full_top3_pre8_rank": [pre_rank[i] for i in orderF[:3]],
        "served_full64_rank": orderF.index(sel_a) + 1,
        "ref_set": len(Rset), "ref_best": " ".join(acts[Rset[rb]]), "ref_best_policy_rank": pol_rank[Rset[rb]],
        "ref_best_pre8_rank": pre_rank[Rset[rb]], "ref_best_full64_rank": orderF.index(Rset[rb]) + 1,
        "common_seconds": common, "served_seconds": rec["seconds"], "max_leaf_diff": maxdiff,
        "variants": out, "t_analysis": time.time() - T0}


def main(argv=None):
    global PKG, SHA, SEED, MAXPOS, DEADLINE, OUT, LOCK, STOP
    args = sys.argv[1:] if argv is None else argv
    PKG, SHA, SEED, MAXPOS, DEADLINE, OUT, LOCK, STOP = (
        args[0], args[1], int(args[2]), int(args[3]), float(args[4]), args[5], args[6], args[7])
    bots = [make_pv_search_bot(PKG, sha256=SHA, seed=SEED * 10 + s, bot_factory=Probe, **R42) for s in range(4)]
    sampler_cls = type(bots[0].sampler)
    samplers = [[sampler_cls(seed=SEED * 10 + s + 7_000_000), sampler_cls(seed=SEED * 10 + s + 9_000_000)]
                for s in range(4)]
    out = open(OUT, "x")  # a fresh DEV collection; never append a duplicate prefix
    game, gid = Game(random.Random(SEED)), 0
    t0, n, r, reason = time.time(), 0, 0, "max_positions"
    try:
        while n < MAXPOS:
            check()
            if game.game_over:
                game, gid = Game(random.Random(SEED * 1000 + r)), gid + 1
            rnd = env.prepare_round(game, bots)
            capture = LeadCapture(rnd)
            trick = 0
            while rnd.phase == "play":
                seat = rnd.turn
                bot = bots[seat]
                bot._probe, bot._cap, bot._t = None, None, {}
                is_lead = bool(leading(rnd))
                if is_lead:
                    trick += 1
                    check()
                cards = bot.decide_play(rnd, seat)
                rec = bot.last_decision_record
                served_t = dict(bot._t)
                if is_lead and n < MAXPOS and rec and rec.get("work_complete") and bot._cap is not None \
                        and bot._probe is not None and len(bot._cap[0]) >= 2:
                    row = {"seed": SEED, "round": r, "game": f"{SEED}:{gid}", "trick": trick,
                           "seat": seat, "hand": len(rnd.hands[seat]), "is_attacker": bool(rnd.is_attacker(seat))}
                    row["replay"] = capture.capture(rnd, ledger=bot._refusals, decision=rec)
                    # Analysis mutates diagnostic fields; retain the actual decision first.
                    row.update(analyze(bot, rnd, seat, copy.deepcopy(rec), served_t, samplers[seat]))
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    n += 1
                rnd.play(seat, cards)
                capture.committed(rnd, seat, cards)
                env.observe_committed_play(rnd, bots)
            game.finish_round()
            r += 1
            print(f"round {r} positions {n} {time.time() - t0:.0f}s", flush=True)
    except Yield as exc:
        reason = str(exc)
    finally:
        out.close()
    print(f"EXIT reason={reason} positions={n} rounds={r} seconds={time.time() - t0:.0f}", flush=True)


if __name__ == "__main__":
    main()
