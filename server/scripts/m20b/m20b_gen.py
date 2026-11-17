#!/usr/bin/env python3
"""M20b row generator: per play decision, release 52's served bot draws its own 64 belief worlds (B1a proposal, sampler
seeded per decision, refusal ledger per (round, seat)) exactly as the S134/UT value gate does; for the true world and a
subset of the sampled worlds it builds the value leaf for two leaf kinds (``end``: the recorded play applied and the trick
finished by the heuristic, the leaves release 52's play search scores; ``k0``: the play's own afterstate, G9's rows), and
stores the served value's (f4f4127e) trunk features, its probability of the realised outcome, and the world's plausibility
features under the decision's B1a proposal:

  ll_q   = sum over hidden copies of log Q[card, receiver]   (Q = the proposal's size-projected per-copy marginals,
           the distribution the served draw samples from)
  ll_p   = the same under the model's raw marginals P (row-normalised over the public mask)
  per-card surprise s[c] = sum_r W[c, r] log Q[c, r]  (54)
and per decision: the 54 x 4 projected marginals Q, its entropy / top-mass summary, the hidden-copy count, and the
mean / std of ll_q over the 64 sampled worlds (a world's relative plausibility is (ll_q - logmeanexp ll_q) at serve time).

  m20b_gen.py OUT_DIR --store STORE --clusters FILE --salt SALT --k K --worker I --workers N [--limit N]
K = 0 keeps all 64 sampled worlds.  Output: OUT_DIR/w{I}-c{cluster}.npz per cluster (resumable per cluster).
Reads decks only; no repo-state change.  DEV, tier i.
"""
import argparse, hashlib, json, os, sys, time
from collections import defaultdict
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('out'); ap.add_argument('--store', required=True); ap.add_argument('--clusters', required=True)
ap.add_argument('--salt', required=True); ap.add_argument('--k', type=int, default=16)
ap.add_argument('--pkgdir', default='/Users/jerryyu/shengji-archive/2026-09-13/readouts/RD1-AV1/av1/models')
ap.add_argument('--worker', type=int, default=0); ap.add_argument('--workers', type=int, default=1)
ap.add_argument('--limit', type=int, default=0); ap.add_argument('--h16', action='store_true')
a = ap.parse_args()

SERVER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER))
from shengji import releases
from shengji.ai import belief_numpy
from shengji.eval import served_config

SERVED_VALUE = 'f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd'
R52 = ('pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-vdef-lgf-lgfx-'
       'lgfd2000-ed7-els1600-xf7-xfcompactlevel-r12e81e0c-bury-hybrid-bwv-bbw-7a9a430fe690-sc8')

m = releases.load(52)
paths = releases.package_paths(m, a.pkgdir)
env = releases.local_env(m, paths)                           # refuses a sha mismatch
process = {k: v for k, v in env.items() if k not in releases.PROCESS_KEYS}
ctx = served_config.process_env(process); ctx.__enter__()
_, bot = releases._build(process, set(paths) == set(m['packages']), 1)
belief_numpy.PREP_SECONDS = 60.0                            # as G9 / the UT value gate
ev = bot.evaluator
assert ev.checkpoint_sha256 == SERVED_VALUE, ev.checkpoint_sha256
assert bot.worlds == 64 and bot.belief_worlds and bot.world_history_legal and bot.refusal_constraints
assert bot.name == R52 if hasattr(bot, 'name') else True

from shengji.ai.cwv_policy import afterstate
from shengji.ai.refusal import RefusalLedger
from shengji.harvest.rebuild import state_for_record
from shengji.rl.encode import CARD_INDEX
from shengji.rl.value_afterstate import signed_level_category

# capture the decision's proposal (the served draw builds it inside _belief_worlds and drops it)
_CAP = {}
_Base = belief_numpy.BeliefProposal


class _Capturing(_Base):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        _CAP['p'] = self


belief_numpy.BeliefProposal = _Capturing

MODEL = ev.model
W_HEAD = MODEL._math_weights['head_weight']; B_HEAD = MODEL._math_weights['head_bias']
seed_of = lambda ref: int(hashlib.sha256((a.salt + '|' + ref).encode()).hexdigest()[:15], 16)
store = Path(a.store)
clusters = [int(x) for x in Path(a.clusters).read_text().split()]
mine = clusters[a.worker::a.workers]
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)


def counts(seat, hands, buried, kitty_hidden):
    """(54, 4) copy counts per receiver (next, partner, previous, kitty) in the actor's frame."""
    C = np.zeros((54, 4))
    for rel in (1, 2, 3):
        for c in hands[(seat + rel) % 4]:
            C[CARD_INDEX[c], rel - 1] += 1
    if kitty_hidden:
        for c in buried:
            C[CARD_INDEX[c], 3] += 1
    return C


def plaus(prop, C):
    """(ll_q, ll_p, per-card surprise) of a world's hidden copies under the proposal."""
    inp = prop.inp
    Wc = C.copy()
    Wc[:, :3] -= inp['K'][:, :3]
    Wc = np.clip(Wc, 0, None)
    Wc[inp['n_c'] == 0] = 0
    logq = np.log(np.maximum(prop.Q, 1e-6))
    P = np.where(prop.M, np.maximum(prop.P, 1e-9), 0.0)
    P = P / np.maximum(P.sum(-1, keepdims=True), 1e-12)
    logp = np.log(np.maximum(P, 1e-6))
    s = (Wc * logq).sum(-1)
    return float(s.sum()), float((Wc * logp).sum()), s


n_dec = 0
t_start = time.time()
for cl in mine:
    fn = out / f'w{a.worker}-c{cl:06d}.npz'
    if fn.exists():
        continue
    recs = [json.loads(l) for l in open(store / 'shards' / f'cluster-{cl:06d}.jsonl')]
    plays = sorted((r for r in recs if r['decision_kind'] == 'play'), key=lambda r: (r['source_ref'].rsplit(':', 2)[0], r['ply']))
    ledgers = defaultdict(RefusalLedger)
    acc = {t: defaultdict(list) for t in ('end', 'k0')}
    dec = defaultdict(list)
    for rec in plays:
        ref = rec['source_ref']; rk = ref.rsplit(':', 2)[0]; seat = int(rec['seat'])
        root = state_for_record(rec)
        assert root.phase == 'play' and root.turn == seat, ref
        bot._refusals = ledgers[(rk, seat)]
        bot.sampler.rng.seed(seed_of(ref))
        _CAP.clear()
        worlds, attempts = bot._worlds(root, seat)
        samp = dict(bot._last_sampling or {})
        bot._refusals.observe(root)
        prop = _CAP.get('p')
        if prop is None or samp.get('belief_fallback'):
            dec['skipped_fallback'].append(ref)
            continue
        o = rec['outcome']
        role_att = (seat % 2) != (int(rec['setup']['banker']) % 2)
        target = signed_level_category(int(o['attacker_points']), role_att)
        action = list(rec['action'])
        true_world = ([list(h) for h in root.hands], list(root.buried))
        allw = [true_world] + list(worlds)
        PL = [plaus(prop, counts(seat, h, b, prop.kitty_hidden)) for h, b in allw]
        llq = np.array([p[0] for p in PL]); llp = np.array([p[1] for p in PL]); S = np.stack([p[2] for p in PL])
        copies = float(prop.inp['n_c'].sum())
        smp = llq[1:]
        lme = float(np.log(np.mean(np.exp(smp - smp.max()))) + smp.max())
        rng = np.random.default_rng(seed_of(ref) ^ 0x5EED)
        pick = np.arange(64) if a.k == 0 else np.sort(rng.choice(64, size=a.k, replace=False))
        idx = np.concatenate([[0], 1 + pick])
        did = len(dec['ref'])
        Q = prop.Q * (prop.inp['n_c'][:, None] > 0)
        ent = -(np.where(Q > 0, Q * np.log(np.maximum(Q, 1e-12)), 0)).sum(-1)
        ok_any = False
        for tag, finish in (('end', True), ('k0', False)):
            leaves = [afterstate(root, seat, allw[i][0], allw[i][1], action, finish_trick=finish) for i in idx]
            if any(l.phase == 'round_end' for l in leaves):
                continue
            rows = [ev.encoder(l, seat) for l in leaves]
            pub = np.stack([r.public for r in rows]); wor = np.stack([r.world for r in rows]); per = np.stack([r.perspective for r in rows])
            P = ev.probabilities_stacked(pub, wor, per)
            x = np.concatenate((pub, wor.reshape(len(rows), -1), per), axis=1).astype(np.float64)
            H = MODEL._trunk(x)
            z = H @ W_HEAD.T + B_HEAD
            z = z - z.max(1, keepdims=True); pz = np.exp(z); pz /= pz.sum(1, keepdims=True)
            assert np.abs(pz - P).max() < 1e-6, ('trunk-reproduction', ref, float(np.abs(pz - P).max()))
            A = acc[tag]
            A['H'].append(H.astype(np.float16 if a.h16 else np.float32)); A['p_served'].append(P[:, target].astype(np.float64))
            A['dec'].append(np.full(len(idx), did, np.int32)); A['widx'].append(idx.astype(np.int16))
            A['llq'].append(llq[idx]); A['llp'].append(llp[idx]); A['surp'].append(S[idx].astype(np.float16))
            ok_any = True
        if not ok_any:
            continue
        dec['ref'].append(ref); dec['cluster'].append(cl); dec['target'].append(int(target)); dec['seat'].append(seat)
        dec['cards_left'].append(len(root.hands[seat])); dec['lead'].append(not root.trick.plays)
        dec['role_att'].append(role_att); dec['copies'].append(copies); dec['lme_q'].append(lme)
        dec['mean_q'].append(float(smp.mean())); dec['std_q'].append(float(smp.std()))
        dec['mean_p'].append(float(llp[1:].mean())); dec['std_p'].append(float(llp[1:].std()))
        dec['ent'].append(float(ent.sum() / max(copies, 1)) if copies else 0.0)
        dec['top'].append(float((prop.inp['n_c'] * Q.max(-1)).sum() / max(copies, 1)))
        dec['Q'].append(Q.astype(np.float16).reshape(-1)); dec['attempts'].append(int(attempts))
        n_dec += 1
        if a.limit and n_dec >= a.limit:
            break
    save = {}
    for k, v in dec.items():
        if k == 'skipped_fallback':
            save[k] = np.array(v)
        elif k == 'Q':
            save['dec_Q'] = np.stack(v) if v else np.zeros((0, 216), np.float16)
        else:
            save['dec_' + k] = np.array(v)
    for tag, A in acc.items():
        for k, v in A.items():
            save[f'{tag}_{k}'] = np.concatenate(v) if v else np.zeros((0,))
    tmp = out / f'.w{a.worker}-c{cl:06d}.tmp.npz'
    np.savez(tmp, **save)
    os.replace(tmp, fn)
    print(json.dumps(dict(worker=a.worker, cluster=cl, decisions=len(dec['ref']), total=n_dec, secs=round(time.time() - t_start, 1))), flush=True)
    if a.limit and n_dec >= a.limit:
        break
print(json.dumps(dict(kind='worker_done', worker=a.worker, clusters=len(mine), decisions=n_dec)), flush=True)
