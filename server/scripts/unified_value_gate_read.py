#!/usr/bin/env python3
"""Validate offline unified gate rows before calculating any outcome or verdict.

Both models score the same sampled worlds. The shared belief-fallback ceiling
and worlds-delivered checks therefore apply to both arms. There are no declare
or bury decisions in this play-only gate. Execution still requires a reviewed,
sealed, named-reader handoff; this CLI supplies no such authority.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# Isolated CLI execution must use the validation and model code beside this reader.
SCRIPTS = Path(__file__).resolve().parent
sys.path[:0] = [str(SCRIPTS / "expert_labels"), str(SCRIPTS), str(SCRIPTS.parent)]

import numpy as np
import validity as va
from unified_value_gate import REPLAY
from shengji.rl.value_afterstate import signed_level_category

GATE_V, KILL_V, GATE_R, REPS = 0.002, 0.010, -0.01, 10_000
ARMS = ('mlp', 'readout')
IDENTITY = ('replay', 'readout', 'value', 'bot', 'view', 'manifest', 'adapter', 'words', 'workers')


def validate_rows(rows, want):
    reasons = []
    if not rows or {r.get('cluster') for r in rows} != set(want):
        reasons.append('rows must cover exactly the nonempty chosen clusters')
    refs = [r.get('ref') for r in rows]
    if any(not isinstance(ref, str) or not ref for ref in refs) or len(set(refs)) != len(refs):
        reasons.append('missing or duplicate source_ref')
    identity = {k: rows[0].get(k) for k in IDENTITY} if rows else {}
    if identity.get('replay') != REPLAY or any(v is None for v in identity.values()):
        reasons.append('missing or incompatible producer identity')
    faults = 0
    outcomes = []
    for i, row in enumerate(rows):
        if any(row.get(k) != identity.get(k) for k in IDENTITY):
            reasons.append(f'row {i}: mixed producer identity')
        flag = row.get('belief_fallback')
        if type(flag) is not int or flag not in (0, 1):
            reasons.append(f'row {i}: missing/malformed belief_fallback')
        else:
            faults += flag
        outcome = row.get('outcome')
        outcome = dict(outcome) if isinstance(outcome, dict) else {}
        outcome['banker'] = row.get('banker')
        outcomes.append(outcome)
        try:
            seat, banker = row['seat'], row['banker']
            if type(seat) is not int or not 0 <= seat < 4 or type(banker) is not int or not 0 <= banker < 4:
                raise ValueError('invalid seat')
            if type(row['target']) is not int or row['target'] != signed_level_category(outcome['attacker_points'], seat % 2 != banker % 2):
                raise ValueError('target drift')
            if type(row['lead']) is not bool or type(row['cards_left']) is not int or not 1 <= row['cards_left'] <= 25:
                raise ValueError('invalid root strata')
            for tag in ('end', 'k0'):
                value = row[tag]
                if value is None:
                    continue
                for model in ('mlp', 'ro'):
                    for world in ('true', 'mix'):
                        p = value[f'{model}_{world}']
                        if type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1:
                            raise ValueError('invalid probability')
                    level = value[f'{model}_lvl']
                    if type(level) not in (int, float) or not math.isfinite(level):
                        raise ValueError('invalid expected level')
            for reply in row['reply']:
                n = reply['n_legal']
                if type(n) is not int or n < 2:
                    raise ValueError('invalid reply count')
                if (type(reply['top1_same']) is not bool
                        or type(reply['top4_overlap']) is not int
                        or not 0 <= reply['top4_overlap'] <= min(4, n)
                        or type(reply['frame_pos']) is not int or not 0 <= reply['frame_pos'] <= 2):
                    raise ValueError('invalid reply summary')
                for key in ('rank_ft1', 'rank_ro'):
                    if type(reply[key]) is not int or not 0 <= reply[key] < n:
                        raise ValueError('invalid reply rank')
        except (KeyError, TypeError, ValueError, OverflowError):
            reasons.append(f'row {i}: malformed model row or target')
    for tag in ('end', 'k0'):
        if not any(isinstance(r.get(tag), dict) for r in rows):
            reasons.append(f'no nonterminal {tag} rows')
    if not any(isinstance(r.get('reply'), list) and r['reply'] for r in rows):
        reasons.append('no reply rows (empty recall denominator)')
    checks = [
        dict(check='gate_schema', verdict='DEV_INVALID' if reasons else va.VALID, reasons=reasons),
        va.arm_fault_ceilings({a: dict(search=len(rows), belief_fallback=faults) for a in ARMS},
                             ceilings={'belief_fallback': va.DEFAULT_CEILINGS['belief_fallback']}, arms=ARMS),
        va.worlds_delivered([(r.get('ref'), a, 'search', r.get('worlds')) for r in rows for a in ARMS],
                            {a: 64 for a in ARMS}),
        va.outcome_consistency(outcomes),
    ]
    return va.combine(checks)


def boot(pairs):
    """pairs: list of (cluster, value); mean and a cluster-bootstrap 95% interval."""
    if not pairs:
        return dict(n=0, clusters=0, mean=None, ci95=None)
    by = defaultdict(list)
    for c, v in pairs:
        by[c].append(v)
    s = np.array([sum(v) for v in by.values()]); n = np.array([len(v) for v in by.values()])
    idx = np.random.default_rng(1).integers(0, len(s), size=(REPS, len(s)))
    m = s[idx].sum(1) / n[idx].sum(1)
    return dict(n=int(n.sum()), clusters=len(s), mean=float(s.sum() / n.sum()), ci95=[float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))])


def analyze(rows, want):
    validity = validate_rows(rows, want)
    if validity["verdict"] != va.VALID:
        return dict(schema="utv-gate-read-r2", validity=validity)
    fallbacks = sum(r["belief_fallback"] for r in rows)
    short = 0
    nll = lambda p: -np.log(max(p, 1e-300))
    res = dict(schema="utv-gate-read-r2", validity=validity, decisions=len(rows), clusters=len(want), belief_fallbacks=fallbacks, decisions_without_64_worlds=short, value={}, reply={})
    for tag in ("end", "k0"):
        rs = [r for r in rows if r[tag] is not None]
        v = {}
        for world in ("mix", "true"):
            v[f"mlp_{world}"] = boot([(r["cluster"], nll(r[tag][f"mlp_{world}"])) for r in rs])
            v[f"readout_{world}"] = boot([(r["cluster"], nll(r[tag][f"ro_{world}"])) for r in rs])
            v[f"readout_minus_mlp_{world}"] = boot([(r["cluster"], nll(r[tag][f"ro_{world}"]) - nll(r[tag][f"mlp_{world}"])) for r in rs])
        for name, sel in (("lead", lambda r: r["lead"]), ("follow", lambda r: not r["lead"]), ("cards_le7", lambda r: r["cards_left"] <= 7), ("cards_gt7", lambda r: r["cards_left"] > 7)):
            v[f"readout_minus_mlp_mix_{name}"] = boot([(r["cluster"], nll(r[tag]["ro_mix"]) - nll(r[tag]["mlp_mix"])) for r in rs if sel(r)])
        lv = np.array([(r[tag]["mlp_lvl"], r[tag]["ro_lvl"]) for r in rs])
        v["expected_level_corr"] = (float(np.corrcoef(lv[:, 0], lv[:, 1])[0, 1])
                                         if len(lv) > 1 and all(np.ptp(lv, axis=0) > 0) else None); v["expected_level_mean_abs_diff"] = float(np.abs(lv[:, 0] - lv[:, 1]).mean())
        v["excluded_terminal"] = len(rows) - len(rs)
        res["value"][tag] = v
    d = res["value"]["end"]["readout_minus_mlp_mix"]["mean"]
    res["value"]["gate"] = dict(metric="trick-end leaves, mixture NLL over the 64 sampled worlds, readout - served", delta=d, bar=GATE_V, kill=KILL_V,
                                verdict="PASS" if d <= GATE_V else ("KILL" if d > KILL_V else "FAIL"))
    rep = [(r["cluster"], x) for r in rows for x in r["reply"]]
    if rep:
        R = res["reply"]
        for k in (1, 4):
            R[f"ft1_recall@{k}"] = boot([(c, float(x["rank_ft1"] < k)) for c, x in rep])
            R[f"readout_recall@{k}"] = boot([(c, float(x["rank_ro"] < k)) for c, x in rep])
            R[f"readout_minus_ft1_recall@{k}"] = boot([(c, float(x["rank_ro"] < k) - float(x["rank_ft1"] < k)) for c, x in rep])
        R["top4_overlap_mean"] = boot([(c, x["top4_overlap"] / min(4, x["n_legal"])) for c, x in rep])
        R["top1_same"] = boot([(c, float(x["top1_same"])) for c, x in rep])
        for p in (0, 1, 2):
            sub = [(c, float(x["rank_ro"] < 4) - float(x["rank_ft1"] < 4)) for c, x in rep if x["frame_pos"] == p]
            if sub:
                R[f"readout_minus_ft1_recall@4_frame_pos{p}"] = boot(sub)
        d = R["readout_minus_ft1_recall@4"]["mean"]
        R["gate"] = dict(metric="recall@4 of the played follow among >= 2 legal follows, true world, readout - FT1", delta=d, bar=GATE_R, verdict="PASS" if d >= GATE_R else "FAIL")
    return res


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('out'); parser.add_argument('chosen'); parser.add_argument('rows', nargs='+')
    args = parser.parse_args(argv)
    if Path(args.out).exists():
        raise ValueError('output already exists; this reader is one-shot')
    want = set(json.loads(Path(args.chosen).read_text())['clusters'])
    rows, terminals = [], []
    for path in args.rows:
        records = [json.loads(line) for line in Path(path).read_text().splitlines()]
        if not records or records[-1].get('kind') != 'worker_done' or any(r.get('kind') == 'worker_done' for r in records[:-1]):
            raise ValueError('missing or misplaced terminal marker')
        terminal = records[-1]
        if type(terminal.get('rows')) is not int or terminal['rows'] != len(records) - 1:
            raise ValueError('terminal row count differs from completed decisions')
        worker, workers = terminal.get('worker'), terminal.get('workers')
        if type(worker) is not int or type(workers) is not int or workers != len(args.rows) or not 0 <= worker < workers:
            raise ValueError('incomplete or duplicated worker partitions')
        expected = set(sorted(want)[worker::workers])
        if (type(terminal.get('clusters')) is not int or terminal['clusters'] != len(expected)
                or any(type(r.get('cluster')) is not int for r in records[:-1])
                or {r['cluster'] for r in records[:-1]} != expected):
            raise ValueError('worker cluster coverage differs from chosen partition')
        if any(any(r.get(k) != terminal.get(k) for k in IDENTITY + ('worker',)) for r in records[:-1]):
            raise ValueError('terminal and row identity differ')
        rows.extend(records[:-1]); terminals.append(terminal)
    if (any(t.get('workers') != len(terminals) for t in terminals)
            or sorted(t.get('worker', -1) for t in terminals) != list(range(len(terminals)))):
        raise ValueError('incomplete or duplicated worker partitions')
    if any(any(t.get(k) != terminals[0].get(k) for k in IDENTITY) for t in terminals[1:]):
        raise ValueError("mixed worker identity, including empty partitions")
    result = analyze(rows, want)
    serialized = json.dumps(result, indent=1, allow_nan=False)
    with open(args.out, 'x') as stream:
        stream.write(serialized)
    summary = {'validity': result['validity']['verdict'], 'decisions': len(rows),
               'replay': REPLAY}
    # Downstream model comparisons consume these gates from the stdout summary.
    # Invalid evidence must expose no numeric gate for those comparisons.
    if result['validity']['verdict'] == va.VALID:
        summary.update(value_gate=result['value']['gate'], reply_gate=result['reply']['gate'])
    print(json.dumps(summary, allow_nan=False))
    return 0 if result["validity"]["verdict"] == va.VALID else 1


if __name__ == '__main__':
    raise SystemExit(main())
