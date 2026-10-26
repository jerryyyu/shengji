#!/usr/bin/env python3
"""s67c smoke read (local, throwaway): the lane reader's analyze() on the sc8p arm's 2-deal smoke file, with the arm's seed0 replaced IN
MEMORY by the smoke window 243160000 and a synthetic status (armed, the DEV start / END, the terminal; 'smoke' marked).  Every integrity
gate, the row schema, the sc8p gate (incl. the kind / pool / trace card-count rules), the trace gate, validity.py (zero play / belief
fallbacks, 64 / 64 worlds, latency inside the 3 s budget) and the paired premise run as on the lane output; the 2-deal numbers mean
nothing.  Plus the r48 control (R48 vs R48 through the adapter, no override): every deal's margin 0, both mirrors' traces identical, and
its sc8p lists EMPTY (no probe wrapper on a plain R48 exploiter).  = s66dev's smoke_read.py with the lane, key and start text changed.
Usage: python3 smoke_read.py <s67c_read.py> > smoke_read.txt"""
import importlib.util, json, sys, tempfile
from pathlib import Path
H = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('s67c_read', sys.argv[1]); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
TS = '2026-10-26T00:00:00Z'
lines = [f'{TS} s67c armed (pid 1, launcher sha256 {"0" * 64}) [synthetic status for the local smoke read]']
for arm in rd.ARM_ORDER:
    a = rd.ARM_SPEC[arm]
    lines += [f'{TS} s67c DEV start {arm}: defender {rd.DEF_NAME} (R48 as served) vs exploiter {a["cand"]} (S66_EXPLOITER=sc8p: the pair/tractor challenger, claude/s67-pair-challenger at 8a50fe8a; served budgets and widths on both sides); deals 2 seed0 243160000 [smoke]',
              f'{TS} s67c DEV END {arm} rc=0 wall_s=1.0 maxrss_kb=1']
lines.append(f'{TS} {rd.TERMINAL}')
with tempfile.TemporaryDirectory(dir='/private/tmp') as tmp:
    st = Path(tmp) / 'status'; st.write_text('\n'.join(lines) + '\n')
    for arm in rd.ARM_ORDER:
        rd.ARM_SPEC[arm] = dict(rd.ARM_SPEC[arm], seed0=243160000)
        o = rd.analyze(str(H / f'{arm}.jsonl'), arm=arm, status=str(st), deals=2, binding=rd.SYNTHETIC)   # fixture route; the lane read binds through analyze_lane
        e, d = o['exploiter'], o['defender']; sw = o['swap_rate']; lat = o['latency_vs_r48']
        print(f"{arm}: validity {o['validity']['verdict']} {o['validity']['reasons']} checks {o['validity']['checks']}; verdict {o['bar']['verdict']} levels {o['levels']}; decisions ex {e['decisions']} / def {d['decisions']}; "
              f"play fallbacks {e['fallback']} / {d['fallback']}; belief fallbacks {e['belief_fallback']} / {d['belief_fallback']}; worlds mismatches {e['play_worlds_mismatch']} / {d['play_worlds_mismatch']}; "
              f"decide_play p50/p95/p99/max ex {[round(x, 3) for x in e['decide_play_p50_p95_p99_max']]} def {[round(x, 3) for x in d['decide_play_p50_p95_p99_max']]}; "
              f"belief_ms ex {[round(x, 1) for x in e['belief_ms_p50_p95_p99_max']]} def {[round(x, 1) for x in d['belief_ms_p50_p95_p99_max']]}; "
              f"play-time ratio {o['play_time']['ratio_sum']:.2f}; first divergence {o['first_divergence']}; "
              f"swap: leads {sw['leads']} (>7: {sw['leads_gt7']}) probed {sw['probed']} entered {sw['entered']} chosen {sw['chosen']}; by kind {json.dumps(sw['by_kind'])}; leads by played kind {sw['leads_by_played_kind']}; latency ratios {[round(x, 2) for x in lat['ratio_p50_p95_p99_max']]} ex max/budget {lat['exploiter_max_over_budget']:.2f}; "
              f"latency check {o['validity']['detail']['latency_inside_budget']}; vs_s66b {json.dumps(o.get('vs_s66b'))}")
        for l in o['canonical_lines']:
            print('   ', l[:400])
rows = [json.loads(l) for l in open(H / 'r48.jsonl')]
by = {(r['seed'], r['mirror']): r for r in rows}
seeds = sorted({s for s, _ in by})
same = all(by[(s, 0)]['dtrace'] == by[(s, 1)]['dtrace'] for s in seeds)
margins = [(by[(s, 0)]['ex_levels'] + by[(s, 1)]['ex_levels']) / 2 for s in seeds]
names = {(r['defender'], r['exploiter_base']) for r in rows}
print(f"r48 control (R48 vs R48 through the adapter, no override): {len(seeds)} deals, mirror traces identical {same}, margins {margins}, names {[(a[-12:], b[-12:]) for a, b in names]} (defender == exploiter {all(a == b for a, b in names)}), sc8p lists {[len(r['sc8p']['ex']) for r in rows]} (empty: no probe wrapper)")
