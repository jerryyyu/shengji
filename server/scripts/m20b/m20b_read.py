#!/usr/bin/env python3
"""M20b selection (SELECT only) and the one holdout read (PREDECLARE.md).

  m20b_read.py select ROOT     -> ROOT/select.json   (needs eval/select/{served,ARM-eN}.npz)
  m20b_read.py holdout ROOT    -> ROOT/eval/holdout/*.npz, ROOT/holdout_results.json, table on stdout (refuses if it exists)
"""
import json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import m20b_train as MT
import m20b_cal as MC

FABLE_SERVED_END_MIX, FABLE_SERVED_END_TRUE = 0.9366, 0.8605


def means(z, tag):
    return float(z[f'{tag}_true'].mean()), float(z[f'{tag}_mix'].mean())


def cmd_select(root):
    root = Path(root); ev = root / 'eval' / 'select'
    s = np.load(ev / 'served.npz'); st, sm = means(s, 'end')
    rows = []
    for arm in ('P', 'PS', 'C') + MC.ARMS:
        for ep in range(1, MT.EPOCHS + 1):
            f = ev / f'{arm}-e{ep}.npz'
            if not f.exists():
                continue
            z = np.load(f); ct, cm = means(z, 'end'); kt, km = means(z, 'k0')
            rows.append(dict(arm=arm, ep=ep, end_true=ct, end_mix=cm, d_true=ct - st, d_mix=cm - sm,
                             k0_d_true=kt - means(s, 'k0')[0], k0_d_mix=km - means(s, 'k0')[1]))
    def rule(cands):
        el = [r for r in cands if r['d_true'] <= 0.002]
        if el:
            best = min(r['end_mix'] for r in el)
            tied = [r for r in el if r['end_mix'] <= best + 0.0005]
            return sorted(tied, key=lambda r: (r['ep'], {'RT': 0, 'RTW': 1, 'PS': 2, 'P': 3, 'C': 4, 'RT0': 5}[r['arm']]))[0], 'eligible'
        return min(cands, key=lambda r: r['d_true']), 'none-eligible: lowest d_true'
    pick, why = rule([r for r in rows if r['arm'] in ('P', 'PS', 'RT', 'RTW')])
    cpick, cwhy = rule([r for r in rows if r['arm'] == 'C']) if any(r['arm'] == 'C' for r in rows) else (None, None)
    c0pick, c0why = rule([r for r in rows if r['arm'] == 'RT0']) if any(r['arm'] == 'RT0' for r in rows) else (None, None)
    out = dict(served=dict(end_true=st, end_mix=sm, gap=sm - st), candidates=rows, pick=pick, pick_rule=why, c_pick=cpick, c_rule=cwhy,
               c0_pick=c0pick, c0_rule=c0why)
    (root / 'select.json').write_text(json.dumps(out, indent=1))
    print(f"SELECT served end true {st:.4f} mix {sm:.4f} gap {sm - st:+.4f}")
    for r in rows:
        print(f"{r['arm']:>2} e{r['ep']}: d_true {r['d_true']:+.4f} d_mix {r['d_mix']:+.4f} (closure {-r['d_mix'] / (sm - st):+.1%}) | k0 d_true {r['k0_d_true']:+.4f} d_mix {r['k0_d_mix']:+.4f}")
    print('PICK', pick['arm'], pick['ep'], why, '| C', cpick and (cpick['arm'], cpick['ep']), cwhy, '| RT0', c0pick and (c0pick['arm'], c0pick['ep']), c0why)


def boot(cl, cols, fn, n=10000, seed=1):
    """Deal-cluster bootstrap of fn(per-column means)."""
    uc, inv = np.unique(cl, return_inverse=True)
    sums = np.stack([np.bincount(inv, weights=c, minlength=len(uc)) for c in cols], 1)
    cnt = np.bincount(inv, minlength=len(uc)).astype(float)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        w = np.bincount(rng.integers(0, len(uc), len(uc)), minlength=len(uc)).astype(float)
        m = (w @ sums) / (w @ cnt)
        vals.append(fn(m))
    return np.percentile(np.array(vals), [2.5, 97.5], axis=0)


def table(s, c, tag, mask=None):
    m = np.ones(len(s[f'{tag}_true']), bool) if mask is None else mask
    st, sm, ct, cm = (x[m] for x in (s[f'{tag}_true'], s[f'{tag}_mix'], c[f'{tag}_true'], c[f'{tag}_mix']))
    cl = s[f'{tag}_cluster'][m]
    G = sm.mean() - st.mean(); ds = cm.mean() - sm.mean(); dt = ct.mean() - st.mean()
    ci_ds, ci_dt, ci_cl = boot(cl, [st, sm, ct, cm], lambda v: np.array([v[3] - v[1], v[2] - v[0], -(v[3] - v[1]) / (v[1] - v[0])])).T
    return dict(n=int(m.sum()), served_true=float(st.mean()), served_mix=float(sm.mean()), cand_true=float(ct.mean()), cand_mix=float(cm.mean()),
                gap=float(G), d_mix=float(ds), d_mix_ci=ci_ds.tolist(), d_true=float(dt), d_true_ci=ci_dt.tolist(),
                closure=float(-ds / G), closure_ci=ci_cl.tolist(),
                perworld_served=float(s[f'{tag}_perworld'][m].mean()), perworld_cand=float(c[f'{tag}_perworld'][m].mean()),
                lvl_corr=float(np.corrcoef(s[f'{tag}_lvl'][m], c[f'{tag}_lvl'][m])[0, 1]),
                lvl_mad=float(np.abs(s[f'{tag}_lvl'][m] - c[f'{tag}_lvl'][m]).mean()))


def cmd_holdout(root):
    root = Path(root); ev = root / 'eval' / 'holdout'
    if (root / 'holdout_results.json').exists():
        sys.exit('REFUSING: holdout already read')
    sel = json.loads((root / 'select.json').read_text())
    data = MT.load_set(root, 'holdout')
    served = MT.evaluate(root, 'holdout', data=data); MT.save_eval(root, 'holdout', 'served', served)
    s = {f'{t}_{k}': v for t, o in served.items() for k, v in o.items()}
    rt, rm = s['end_true'].mean(), s['end_mix'].mean()
    repro = abs(rt - FABLE_SERVED_END_TRUE) <= 0.002 and abs(rm - FABLE_SERVED_END_MIX) <= 0.002
    print(f"REPRO served end true {rt:.4f} (UT {FABLE_SERVED_END_TRUE}) mix {rm:.4f} (UT {FABLE_SERVED_END_MIX}) n={len(s['end_true'])} -> {'OK' if repro else 'FAIL'}")
    res = dict(repro=dict(end_true=float(rt), end_mix=float(rm), n=int(len(s['end_true'])), ok=bool(repro)))
    if not repro:
        (root / 'holdout_results.json').write_text(json.dumps(res, indent=1)); sys.exit('STOP: reproduction failed')
    for key, pk in (('pick', sel['pick']), ('c_pick', sel['c_pick']), ('c0_pick', sel.get('c0_pick'))):
        if pk is None:
            continue
        if pk['arm'] in MC.ARMS:
            o = MC.evaluate(root, 'holdout', pk['arm'], pk['ep'], data)
        else:
            o = MT.evaluate(root, 'holdout', pk['arm'], pk['ep'], data=data); MT.save_eval(root, 'holdout', f"{pk['arm']}-e{pk['ep']}", o)
        c = {f'{t}_{k}': v for t, o2 in o.items() for k, v in o2.items()}
        r = dict(cand=f"{pk['arm']}-e{pk['ep']}")
        for tag in ('end', 'k0'):
            r[tag] = dict(all=table(s, c, tag),
                          lead=table(s, c, tag, s[f'{tag}_lead'].astype(bool)), follow=table(s, c, tag, ~s[f'{tag}_lead'].astype(bool)),
                          le7=table(s, c, tag, s[f'{tag}_cards'] <= 7), gt7=table(s, c, tag, s[f'{tag}_cards'] > 7))
        res[key] = r
    p = res['pick']; e = p['end']['all']; k = p['k0']['all']
    PASS = e['closure'] >= 0.25 and e['d_mix_ci'][1] < 0 and e['d_true'] <= 0.002 and k['d_mix'] <= 0
    KILL = e['closure'] < 0.10
    res['verdict'] = 'PASS' if PASS else ('KILL' if KILL else 'FAIL')
    (root / 'holdout_results.json').write_text(json.dumps(res, indent=1))
    for key in ('pick', 'c_pick', 'c0_pick'):
        if key not in res:
            continue
        for tag in ('end', 'k0'):
            for st, t in res[key][tag].items():
                print(f"{key:6} {res[key]['cand']:6} {tag:3} {st:6} n={t['n']:6} served true {t['served_true']:.4f} mix {t['served_mix']:.4f} gap {t['gap']:+.4f} | "
                      f"d_true {t['d_true']:+.4f} [{t['d_true_ci'][0]:+.4f},{t['d_true_ci'][1]:+.4f}] d_mix {t['d_mix']:+.4f} [{t['d_mix_ci'][0]:+.4f},{t['d_mix_ci'][1]:+.4f}] "
                      f"closure {t['closure']:+.1%} [{t['closure_ci'][0]:+.1%},{t['closure_ci'][1]:+.1%}] perworld {t['perworld_served']:.4f}/{t['perworld_cand']:.4f} lvl r={t['lvl_corr']:.3f} mad={t['lvl_mad']:.3f}")
    print('VERDICT', res['verdict'])


if __name__ == '__main__':
    {'select': cmd_select, 'holdout': cmd_holdout}[sys.argv[1]](sys.argv[2])
