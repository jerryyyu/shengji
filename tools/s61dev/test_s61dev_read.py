#!/usr/bin/env python3
"""s61dev reader end-to-end check on SYNTHETIC rows (no deal is played).  A generator writes duel.jsonl rows in exploit_duel_s61.py's record
form for 600 deals x 2 mirrors: s60dev's dhist (19 fields; exact_deep_cards 8 on the exploiter, 7 on the defender; the side's play worlds),
declare_recs / bury_rec at the side's world counts, engine-consistent round results (validity.engine_level_outcome), and a dtrace of 100
deal-time declare calls, 4 final calls, the bury and 25 single-card tricks.  The two mirrors' traces agree up to one divergent entry per
deal (declare / bury / a play), where only the cards differ.  Each deal's margin is (L0 + L1) / 2 with L1 = -L0 + delta: delta is balanced noise
(+1 on 60 deals, -1 on 60) plus a planted +1 (effect > 0) or -1 (effect < 0) on round(2 |effect| N) deals, so the mean is about the effect.
  T1  the clean file at +0.06: EXPLOITER_AHEAD, validity VALID, ATTRIBUTION_OK, the cells sum to the mean, the canonical lines.
  T2  the read: effect 0 -> NO_RESOLVED_GAP; -0.06 -> DEFENDER_AHEAD; a planted +0.04 loss cell (follow, tricks 16+, first round) is the
      top loss cell and flagged at both levels; the fault ceilings on BOTH arms (validity.py) -> DEV_INVALID with no outcome; an undiverged
      deal with a nonzero margin -> ATTRIBUTION_INVALID (the head-to-head kept, no flag); an undiverged deal at 0 accepted; a failed throw
      (2 cards chosen, 1 played) accepted.
  T3  refusals: the binding (ABORT line, no terminal, DEV END rc=1, a wrong exploiter in the start line, SHA256SUMS mismatch; a matching
      SHA256SUMS accepted), the trace form and its reconciliations, the divergence form, and s60dev's integrity and row-schema cases.
  usage: cd /private/tmp && nice -n 15 python3 test_s61dev_read.py <s61dev_read.py>
"""
import copy
import hashlib
import importlib.util
import json
import random
import sys
import tempfile
from pathlib import Path

READER = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location('s61dev_read', READER); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
va = rd.va
SEED0, DEALS = rd.SEED0, rd.DEALS
TS0 = '2026-10-22T01:00:00Z'


def status_text(*, cand=None, rc=0, terminal=True, abort=False):
    lines = [f'{TS0} s61dev armed (pid 4242, launcher sha256 {"0" * 64})',
             f'{TS0} s61dev DEV start: defender {rd.R46} (release 46 as served) vs exploiter {cand or rd.CAND} (S61 exploiter: ...); deals {DEALS} seed0 {SEED0}',
             f'{TS0} s61dev DEV END rc={rc} wall_s=5000.0 maxrss_kb=1000000']
    if abort:
        lines.append(f'{TS0} ABORT: s61dev run group 4242 exited rc 1; no LANE DONE')
    if terminal:
        lines.append(f'{TS0} {rd.TERMINAL}')
    return '\n'.join(lines) + '\n'


def decision(rng, side, maxh, lead, abandon_rate=0.1):
    """one dhist entry (19 fields) + its seconds: s60dev's fixture form"""
    secs = round(rng.uniform(0.05, 0.25), 4)
    cap = 8 if side == 'ex' else 7
    lst, lar, lch, xfa, xfb, xfc = 'ineligible', None, False, None, None, None
    if maxh <= cap:
        if lead:
            if rng.random() < abandon_rate:
                lst, lar = 'abandoned', 'soft_budget'
            else:
                lst, lch = 'complete', rng.random() < 0.3
        else:
            xfa = True
            if rng.random() < abandon_rate:
                xfb, xfc = 'soft_budget', False
            else:
                xfb, xfc = None, rng.random() < 0.2
    return ['-decision-v1', 0, 0, 64, 0, 12.5, 60, None, maxh, lead, cap, lst, lar, lch, xfa, xfb, xfc, secs, rd.PLAY_WORLDS[side]], secs


def declare_rec(rng, side):
    w = rd.DECLARE_WORLDS[side]
    secs = round(rng.uniform(0.02, 0.3), 4)
    return ['pv-value-declare-decision-v1', None, True, w, w, secs, secs]


def bury_rec(rng, side):
    return [side, 'cwv-bury-policy-v1', None, rng.randint(19, rd.BURY_K[side]), rd.BURY_WORLDS[side], round(rng.uniform(0.2, 3.0), 4)]


def outcome(rng, banker, ex_team, L):
    """an engine-consistent round result in which the exploiter team's level change is L"""
    bt = banker % 2
    if L > 0:
        winner, lc = ex_team, L
    elif L < 0:
        winner, lc = 1 - ex_team, -L
    else:
        winner, lc = 1 - bt, 0
    if winner != bt:
        ap = 80 + 40 * lc + 5 * rng.randint(0, min(7, (200 - 80 - 40 * lc) // 5))
    else:
        ap = 0 if lc == 3 else 5 * (rng.randint(1, 7) if lc == 2 else rng.randint(8, 15))
    assert va.engine_level_outcome(ap, banker) == (winner, lc), (ap, banker, winner, lc)
    ex_attacks = ex_team != bt
    return dict(attacker_points=ap, kitty_points=0, kitty_bonus=0, last_trick_winner=banker, winner_team=winner, level_change=lc,
                ex_levels=lc if winner == ex_team else -lc, ex_attacker_points_signed=ap if ex_attacks else -ap)


def base_trace(rng, banker, failed_first=False):
    """D x100, F x4, B, then 25 single-card tricks (failed_first: the first lead chooses 2 cards and plays 1)"""
    t = [['D', k % 4, None, None, k // 4 + 1, ['S2'] if k == 41 else []] for k in range(100)]
    t += [['F', s, None, None, 25, []] for s in range(4)]
    t.append(['B', banker, None, None, 33, sorted(f'K{j}' for j in range(8))])
    leader = rng.randint(0, 3)
    for trick in range(25):
        for pos in range(4):
            seat = (leader + pos) % 4
            cards = [f'{"HDCS"[seat]}{trick:02d}']
            if failed_first and trick == 0 and pos == 0:
                cards = sorted(cards + ['XJ'])
            t.append(['P', seat, trick, pos == 0, 25 - trick, cards])
        leader = rng.randint(0, 3)
    return t


def deal_rows(rng, seed, delta, div, failed_first=False):
    """both mirrors of one deal; div: None (no divergence) or (phase, play index)"""
    kind, rank, planned = rd.round_plan(seed - SEED0)
    b = planned if planned is not None else rng.randint(0, 3)
    t0 = base_trace(rng, b, failed_first)
    t1 = copy.deepcopy(t0)
    if div is not None:
        ph, p = div
        i = 41 if ph == 'D' else (104 if ph == 'B' else 105 + p)
        if ph == 'D':
            t1[i][5] = []
        elif ph == 'B':
            t1[i][5] = sorted([f'K{j}' for j in range(7)] + ['KX'])
        else:
            t1[i][5] = [t1[i][5][0] + 'x'] if len(t1[i][5]) == 1 else t1[i][5][:1]
    a = rng.choice([-1, 1])
    Ls = (a, max(-3, min(3, -a + delta)))
    out = []
    for m, t in ((0, t0), (1, t1)):
        plays = t[105:]
        hist, secs = {'ex': [], 'r45': []}, {'ex': [], 'r45': []}
        for e in plays:
            side = 'ex' if e[1] % 2 == m else 'r45'
            h, sec = decision(rng, side, e[4], e[3]); hist[side].append(h); secs[side].append(sec)
        declares = [[e[1], list(e[5]), 42, e[0] == 'F'] for e in t[:104] if e[5]]
        bside = 'ex' if b % 2 == m else 'r45'
        r = dict(arm='identity', seed=seed, mirror=m, ex_team=m, round_kind=kind, trump_rank=rank, planned_banker=planned, banker=b,
                 ex_role='banker' if b % 2 == m else 'attacker', trump='S', declaration=None, declares=declares,
                 failed_throws=[[0, t[105][1], t[105][1] % 2 == m]] if failed_first else [],
                 fired={'declare': 0, 'bury': 0, 'play': 0}, hyp={}, play_secs=9.0, defender=rd.R46, exploiter_base=rd.CAND,
                 dsecs=secs, dhist=hist, declare_recs={s: [declare_rec(rng, s) for _ in range(rng.randint(1, 3))] for s in ('ex', 'r45')},
                 bury_rec=bury_rec(rng, bside), dtrace=t)
        r.update(outcome(rng, b, m, Ls[m]))
        out.append(r)
    return out


def rows(effect=0.06, seed=7, plant=0.0, undiverged=(), failed_first=()):
    """600 deals x 2 mirrors.  plant: a loss cell of this contribution on 'follow | tricks 16+ | first round (rank 2)'.  undiverged:
    {deal index: delta} deals whose mirrors never diverge (their delta is forced).  failed_first: deal indices with a failed first lead."""
    rng = random.Random(seed)
    n_eff = round(2 * abs(effect) * DEALS)
    eff_idx = set(rng.sample(range(DEALS), n_eff))
    firsts = [i for i in range(DEALS) if rd.round_plan(i)[0] == 'first' and i not in eff_idx]
    plant_idx = set(firsts[:round(2 * plant * DEALS)])
    order = rng.sample(range(DEALS), DEALS)
    noise_of = {i: (1 if k < DEALS // 10 else (-1 if k < DEALS // 5 else 0)) for k, i in enumerate(order)}   # balanced: 60 deals +1, 60 deals -1
    out = []
    for i in range(DEALS):
        noise = noise_of[i]
        delta = noise + ((1 if effect > 0 else -1) if i in eff_idx else 0)
        if i in plant_idx:
            delta, div = 1, ('P', 4 * 20 + 1)          # a follow in trick 21
        elif i in undiverged:
            delta, div = undiverged[i], None
        else:
            u = rng.random()
            div = ('D', None) if u < 0.1 else (('B', None) if u < 0.2 else ('P', rng.randint(0, 99)))
            if div[0] == 'P' and rd.round_plan(i)[0] == 'first' and div[1] >= 60 and div[1] % 4:
                div = ('P', div[1] - 60)                 # keep the planted cell clean of unplanted first-round late follows
        out += deal_rows(rng, SEED0 + i, delta, div, failed_first=i in failed_first)
    return out


def write(rs, tmp, name='duel.jsonl'):
    p = Path(tmp) / name
    with open(p, 'w') as fh:
        for r in rs:
            fh.write(json.dumps(r) + '\n')
    return str(p)


fails = 0
def check(label, ok, detail=''):
    global fails
    print(('PASS' if ok else 'FAIL'), label, str(detail)[:300]); fails += int(not ok)


def run(rs, status=None, sums=None):
    with tempfile.TemporaryDirectory(prefix='s61dev-e2e-', dir='/private/tmp') as tmp:
        p = write(rs, tmp)
        sp = Path(tmp) / 'lane.status'; sp.write_text(status if status is not None else status_text())
        kw = {}
        if sums is not None:
            q = Path(tmp) / 'SHA256SUMS'; q.write_text(sums(hashlib.sha256(Path(p).read_bytes()).hexdigest())); kw['sums'] = str(q)
        return rd.analyze(p, status=str(sp), **kw)


def refused(label, want, rs, **kw):
    try:
        run(rs, **kw)
    except SystemExit as e:
        check(label, str(e).startswith('REFUSING: ') and want in str(e), str(e)[:200])
    else:
        check(label, False, 'read accepted')


# ---- T1 ----
base = rows()
out = run(base)
m, lo, hi = out['levels']
at = out['attribution']
check('T1 clean read: EXPLOITER_AHEAD at a +0.06 synthetic effect, validity VALID, 600 deals', out['bar']['verdict'] == 'EXPLOITER_AHEAD' and out['validity']['verdict'] == 'VALID' and out['deals'] == DEALS and abs(m - 0.06) < 0.02 and lo > 0, f'{m:+.4f} [{lo:+.4f}, {hi:+.4f}]')
check('T1 ATTRIBUTION_OK, every deal diverged, the cells sum to the head-to-head mean at every level', at['status'] == 'ATTRIBUTION_OK' and at['deals_diverged'] == DEALS
      and all(abs(sum(c['contribution'] for c in at['tables'][lv]) - m) < 1e-9 for lv in at['tables']), {lv: sum(c['contribution'] for c in at['tables'][lv]) for lv in at['tables']})
want_cls = {'declare': 0, 'bury': 0, 'lead': 0, 'follow': 0}
for i in range(DEALS):
    r0, r1 = base[2 * i], base[2 * i + 1]
    j = next(j for j, (a, b) in enumerate(zip(r0['dtrace'], r1['dtrace'])) if a != b)
    e = r0['dtrace'][j]
    want_cls[{'D': 'declare', 'F': 'declare', 'B': 'bury'}.get(e[0]) or ('lead' if e[3] else 'follow')] += 1
check('T1 the class counts equal an independent recount of the first divergences', {c['cell']: c['deals'] for c in at['tables']['class']} == want_cls, want_cls)
check('T1 the top decile holds ceil(N/10) deals and 20 listed wins with both actions', at['top_decile']['deals'] == 60 and len(at['top_decile']['largest_wins']) == 20
      and all(w['exploiter_action'] != w['release46_action'] for w in at['top_decile']['largest_wins'] if w['diverged']))
cl = out['canonical_lines']
check('T1 canonical lines carry the numbers, the verdict and the attribution', any(f'{m:+.4f}' in l for l in cl) and any('Verdict EXPLOITER_AHEAD' in l for l in cl) and any(l.startswith('Top-3 loss cells') for l in cl), cl[:2])
for l in cl:
    print('  ', l[:260])

# ---- T2: the read ----
o = run(rows(effect=0.0)); check('T2 effect 0 -> NO_RESOLVED_GAP', o['bar']['verdict'] == 'NO_RESOLVED_GAP' and o['levels'][1] <= 0 <= o['levels'][2], o['levels'])
o = run(rows(effect=-0.06)); check('T2 effect -0.06 -> DEFENDER_AHEAD', o['bar']['verdict'] == 'DEFENDER_AHEAD' and o['levels'][2] < 0, o['levels'])
o = run(rows(effect=0.0, plant=0.04))
top = o['attribution']['top_loss_cells'][0]; fl = {(f['level'], f['cell']) for f in o['bar']['flags']}
check('T2 a planted +0.04 loss cell is the top loss cell, flagged at the joint and the class x trick level, resolved',
      top['cell'] == 'follow | tricks 16+ | first round (rank 2)' and abs(top['contribution'] - 0.04) < 0.006 and ('class_trick_rank', top['cell']) in fl
      and ('class_trick', 'follow | tricks 16+') in fl and all(f['resolved'] for f in o['bar']['flags'] if f['cell'] == top['cell']), (top, sorted(fl)))
o = run(rows(effect=0.0)); check('T2 no planted cell -> no flag', o['bar']['flags'] == [], o['bar']['flags'])

def to_fallback(h):
    h[0] = '-fallback-v1'; h[1:8] = [None] * 7; h[10:19] = [None] * 9
for side, who in (('ex', 'exploiter'), ('r45', 'defender')):
    rs = rows(); to_fallback(rs[10]['dhist'][side][3])
    o = run(rs); check(f'T2 one {who} play fallback (<= 0.1%) -> still read, reported', o['bar']['verdict'] == 'EXPLOITER_AHEAD' and o['exploiter' if side == 'ex' else 'defender']['fallback'] == 1, o['bar']['reasons'])
    rs = rows()
    for r in rs[:200]:
        to_fallback(r['dhist'][side][1])
    o = run(rs); check(f'T2 200 {who} play fallbacks -> DEV_INVALID naming the {who}, no outcome', o['bar']['verdict'] == 'DEV_INVALID' and o['levels'] is None and o['attribution'] is None
                       and any(f"arm '{side}' play_fallback: 200 of" in x for x in o['bar']['reasons']), o['bar']['reasons'][:2])
    rs = rows()
    for r in rs:
        for h in r['dhist'][side]:
            h[4], h[7] = 1, 'BeliefNumpyError'
    o = run(rs); check(f'T2 {who} belief fallbacks everywhere -> DEV_INVALID', o['bar']['verdict'] == 'DEV_INVALID' and any(f"arm '{side}' belief_fallback" in x for x in o['bar']['reasons']), o['bar']['reasons'][:2])
    rs = rows()
    for r in rs:
        if r['bury_rec'][0] == side:
            b = r['bury_rec']; r['bury_rec'] = [side, 'cwv-bury-fallback-v1', 'budget', b[3], None, b[5]]
    o = run(rs); check(f'T2 every {who} bury a fallback -> DEV_INVALID', o['bar']['verdict'] == 'DEV_INVALID' and any(f"arm '{side}' bury_fallback" in x for x in o['bar']['reasons']), o['bar']['reasons'][:2])
    rs = rows()
    for r in rs:
        for d in r['declare_recs'][side]:
            d[1], d[2] = 'hard_budget', False
    o = run(rs); check(f'T2 every {who} declare abandoned -> DEV_INVALID', o['bar']['verdict'] == 'DEV_INVALID' and any(f"arm '{side}' declare_abandon" in x for x in o['bar']['reasons']), o['bar']['reasons'][:2])
    rs = rows(); h = next(h for h in rs[5]['dhist'][side] if h[0] == '-decision-v1'); h[18] = rd.PLAY_WORLDS['r45' if side == 'ex' else 'ex']
    o = run(rs); check(f'T2 one {who} search record off its play worlds -> DEV_INVALID', o['bar']['verdict'] == 'DEV_INVALID' and any('worlds_delivered' in x for x in o['bar']['reasons']), o['bar']['reasons'][:2])
rs = rows(); r = next(r for r in rs if r['level_change'] >= 1); r['attacker_points'] = 0 if r['winner_team'] != r['banker'] % 2 else 195; r['ex_attacker_points_signed'] = r['attacker_points'] * (1 if r['ex_team'] != r['banker'] % 2 else -1)
o = run(rs); check('T2 an impossible score row (the winner disagrees with the points) -> DEV_INVALID by outcome_consistency', o['bar']['verdict'] == 'DEV_INVALID' and any('outcome_consistency' in x for x in o['bar']['reasons']), o['bar']['reasons'][:2])
o = run(rows(undiverged={7: 1}))
check('T2 an undiverged deal with a nonzero margin -> ATTRIBUTION_INVALID, the head-to-head kept, no flag', o['bar']['attribution_status'] == 'ATTRIBUTION_INVALID' and o['bar']['verdict'] == 'EXPLOITER_AHEAD'
      and o['attribution']['not_diverged_nonzero_seeds'] == [SEED0 + 7] and o['bar']['flags'] == [], o['attribution']['status'])
finding_keys = {'cells_sum', 'top_loss_cells', 'top_gain_cells', 'tables', 'top_decile'}
finding_lines = ('Top-3 loss cells', 'Flag (contribution', 'Class x trick', 'Top decile')
check('T2 ATTRIBUTION_INVALID suppresses structured attribution findings but keeps head-to-head and diagnostics',
      not (finding_keys & o['attribution'].keys()) and o['levels'] is not None and o['points'] is not None
      and o['attribution']['not_diverged_nonzero'] == 1 and o['bar']['flags'] == [], o['attribution'])
check('T2 ATTRIBUTION_INVALID suppresses rendered attribution findings but keeps the read diagnostic',
      any(l.startswith('s61dev DEV head-to-head') for l in o['canonical_lines'])
      and any('Attribution ATTRIBUTION_INVALID' in l for l in o['canonical_lines'])
      and not any(any(fragment in l for fragment in finding_lines) for l in o['canonical_lines']), o['canonical_lines'])
o = run(rows(undiverged={7: 0, 9: 0}))
check('T2 undiverged deals at margin 0 -> ATTRIBUTION_OK, counted', o['bar']['attribution_status'] == 'ATTRIBUTION_OK' and o['attribution']['deals_not_diverged'] == 2, o['attribution']['deals_not_diverged'])
o = run(rows(failed_first=(3, 4)))
check('T2 a failed throw (2 cards chosen, 1 played; listed in failed_throws) accepted, counted per side', o['bar']['verdict'] == 'EXPLOITER_AHEAD' and o['exploiter']['failed_throws'] + o['defender']['failed_throws'] == 4, o['bar']['verdict'])

# ---- T3: refusals ----
rs = rows()
refused('T3 an ABORT line in the status refused', 'terminal: the lane failed', rs, status=status_text(abort=True))
refused('T3 no terminal line refused', 'exact terminal lines', rs, status=status_text(terminal=False))
refused('T3 DEV END rc=1 refused', 'status: need one DEV start line', rs, status=status_text(rc=1))
refused('T3 a start line naming another exploiter refused', 'status: need one DEV start line', rs, status=status_text(cand=rd.R46))
refused('T3 a SHA256SUMS whose duel.jsonl line differs refused', 'SHA256SUMS', rs, sums=lambda h: f'{"0" * 64}  ./duel.jsonl\n')
o = run(rs, sums=lambda h: f'{"1" * 64}  ./fly.toml\n{h}  ./duel.jsonl\n'); check('T3 a matching SHA256SUMS accepted and recorded', o['binding']['sums_sha256'] is not None and o['input_sha256'] == o['binding']['input_sha256'])
rs = rows(); del rs[4]['dtrace']; refused('T3 a row without dtrace refused', 'dtrace form', rs)
rs = rows(); rs[4]['dtrace'][3] = rs[4]['dtrace'][3][:5]; refused('T3 a 5-field trace entry refused', 'dtrace entry form', rs)
rs = rows(); rs[4]['dtrace'][110][5] = ['Z9', 'A1']; refused('T3 unsorted cards refused', 'dtrace entry form', rs)
rs = rows(); rs[4]['dtrace'][110][2] = None; refused('T3 a play without a trick index refused', 'dtrace entry form', rs)
rs = rows(); rs[4]['dtrace'][3][2] = 0; refused('T3 a declare call with a trick index refused', 'dtrace entry form', rs)
rs = rows(); rs[4]['dtrace'][110][3] = 1; refused('T3 an int lead flag refused', 'dtrace entry form', rs)
rs = rows(); del rs[4]['dtrace'][50]; refused('T3 99 deal-time declare calls refused', 'dtrace order', rs)
rs = rows(); rs[4]['dtrace'][101][1] = 3; refused('T3 final declare calls out of seat order refused', 'dtrace declare calls', rs)
rs = rows(); rs[4]['dtrace'][104][1] = (rs[4]['banker'] + 1) % 4; refused('T3 a bury by a seat other than the banker refused', 'dtrace bury', rs)
rs = rows(); rs[4]['dtrace'][104][5] = rs[4]['dtrace'][104][5][:7]; refused('T3 a bury of 7 cards refused', 'dtrace bury', rs)
rs = rows(); rs[4]['declares'] = []; refused('T3 declares disagreeing with the trace refused', 'dtrace declares', rs)
rs = rows(); e = rs[4]['dtrace'][106]; e[1] = (e[1] + 1) % 4; refused('T3 a follow by the wrong seat refused', 'dtrace tricks', rs)
rs = rows(); rs[4]['dtrace'][109][4] = 25; refused('T3 a hand that did not fall by the cards played refused', 'dtrace hand', rs)
rs = rows(); rs[4]['dtrace'] = rs[4]['dtrace'][:-4]; refused('T3 a trace whose seats end with cards refused', 'dtrace', rs)
rs = rows(); rs[4]['failed_throws'] = [[5, (rs[4]['dtrace'][110][1] + 1) % 4, False]]; refused('T3 a failed throw naming the wrong seat refused', 'failed_throws form', rs)
rs = rows(); p = rs[4]['dtrace'][110]; rs[4]['failed_throws'] = [[5, p[1], p[1] % 2 == rs[4]['mirror']]]; refused('T3 a failed throw on a single-card play refused (its next hand is not bounded)', 'dtrace hand', rs)
rs = rows(); side = 'ex'; rs[4]['dhist'][side].pop(); rs[4]['dsecs'][side].pop(); refused('T3 dhist one entry short of the trace refused', 'dtrace vs dhist', rs)
rs = rows(); h = rs[4]['dhist']['ex'][0]; h[9] = not h[9]; refused('T3 a dhist lead flag disagreeing with the trace refused', 'dtrace vs dhist', rs)
rs = rows()
i = next(i for i in range(DEALS) if rs[2 * i]['dtrace'][41] != rs[2 * i + 1]['dtrace'][41])
rs[2 * i + 1]['dtrace'][41][4] = 24
refused('T3 a first divergence that differs in state, not only in cards, refused', 'divergence form', rs)
rs = rows(); rs[7]['defender'] = rd.CAND; refused('T3 a wrong defender name refused', 'defender', rs)
rs = rows(); rs[7]['exploiter_base'] = rd.R46; refused('T3 a wrong exploiter name refused', 'the S61 exploiter', rs)
rs = rows(); rs.append(copy.deepcopy(rs[3])); refused('T3 a duplicate row refused', 'duplicate row', rs)
rs = rows(); del rs[7]; refused('T3 a missing mirror refused', 'deals:', rs)
rs = rows(); rs[2]['dhist']['ex'][0][10] = 7; refused('T3 an exploiter search decision with exact_deep_cards 7 refused', 'field 10=7 fails one_of(8,)', rs)
rs = rows(); r = next(r for r in rs if r['bury_rec'][0] == 'ex'); r['bury_rec'][4] = 128; refused('T3 an exploiter bury record off its configured worlds refused', 'row schema: ex bury_rec', rs)
rs = rows(); r = rs[3]; r['declare_recs']['ex'][0][4] = 0; refused('T3 an evaluated exploiter declare with 0 worlds completed refused', 'row schema: ex declare_recs', rs)
o = run(rows())
check("T3 control: the unchanged fixture reads T1's verdict and numbers", o['bar']['verdict'] == out['bar']['verdict'] and o['levels'] == out['levels'] and o['attribution']['tables'] == out['attribution']['tables'])
check("T3 control: valid structured and rendered output remains unchanged", o['attribution'] == out['attribution'] and o['bar'] == out['bar'] and o['canonical_lines'] == out['canonical_lines'])
print('ALL PASS' if not fails else f'{fails} FAILED')
sys.exit(int(bool(fails)))
