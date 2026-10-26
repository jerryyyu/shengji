#!/usr/bin/env python3
"""s68dev rehearsal read (NON-scientific): the lane reader's analyze() (s68dev_read.final.py) on each arm's 56-deal throwaway rehearsal
file (seeds 243570000..243570055, outside the reserved blocks), with the arm's seed0 replaced IN MEMORY and a synthetic status, as s67c's
rehearsal_read.py does.  Prints only the execution evidence per arm: validity verdict and reasons, fallbacks, worlds, decide_play
quantiles and max against the budgets, the exploiter's decisions past its own budget, row / deal counts.  The paired margin of a throwaway
block is not printed (it is not evidence of anything).  = s67c's rehearsal_read.py looped over the two arms.
Usage: python3 rehearsal_read.py <s68dev_read.final.py> <host dir> <wall_b> <wall_a> > rehearsal_read.txt"""
import importlib.util, json, sys, tempfile
from pathlib import Path
reader, hd, walls = sys.argv[1], Path(sys.argv[2]), dict(zip(('b', 'a'), sys.argv[3:5]))
spec = importlib.util.spec_from_file_location('s68dev_read', reader); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
TS = '2026-10-26T00:00:00Z'; SEED0 = 243570000; N = 56
for arm in rd.ARM_ORDER:
    a = dict(rd.ARM_SPEC[arm])
    duel = str(hd / arm / 'duel.jsonl')
    lines = [f'{TS} s68dev armed (pid 1, launcher sha256 {"0" * 64}) [synthetic status for the host rehearsal read]']
    for x in rd.ARM_ORDER:
        ax = rd.ARM_SPEC[x]
        lines += [f'{TS} s68dev DEV start {x}: defender {rd.DEF_NAME} (R48 as served) vs exploiter {ax["cand"]} (exploiter env: {ax["env"]}; defender at served budgets and widths); deals {N} seed0 {SEED0} [rehearsal]',
                  f'{TS} s68dev DEV END {x} rc=0 wall_s={walls[x]} maxrss_kb=1']
    lines.append(f'{TS} {rd.TERMINAL}')
    with tempfile.TemporaryDirectory(dir='/private/tmp') as tmp:
        st = Path(tmp) / 'status'; st.write_text('\n'.join(lines) + '\n')
        saved = rd.ARM_SPEC[arm]; rd.ARM_SPEC[arm] = dict(a, seed0=SEED0)
        try:
            o = rd.analyze(duel, arm=arm, status=str(st), deals=N, binding=rd.SYNTHETIC)
        finally:
            rd.ARM_SPEC[arm] = saved
    e, d = o['exploiter'], o['defender']; lat = o['latency_vs_r48']; v = o['validity']
    rows = [json.loads(l) for l in open(duel)]
    print(f"[{arm}] rows {len(rows)}, deals {len({r['seed'] for r in rows})} (seeds {min(r['seed'] for r in rows)}..{max(r['seed'] for r in rows)}); wall {walls[arm]} s")
    print(f"[{arm}] validity {v['verdict']} reasons {v['reasons'][:6]} checks {v['checks']}")
    print(f"[{arm}] decisions ex {e['decisions']} / def {d['decisions']}; play fallbacks {e['fallback']} / {d['fallback']}; belief fallbacks {e['belief_fallback']} / {d['belief_fallback']}; bury fallbacks {e['bury_fallback']} / {d['bury_fallback']} of {e['buries']} / {d['buries']}; declare abandons {e['declare_abandoned']} / {d['declare_abandoned']}; worlds mismatches {e['play_worlds_mismatch']} / {d['play_worlds_mismatch']}")
    print(f"[{arm}] decide_play s p50/p95/p99/max ex {[round(x, 3) for x in e['decide_play_p50_p95_p99_max']]} def {[round(x, 3) for x in d['decide_play_p50_p95_p99_max']]}")
    print(f"[{arm}] latency check {v['detail']['latency_inside_budget']}; own budget {o['exploiter_own_budget']}; share past 1/1.5/2/2.5/3 s ex {[round(o['time_use']['ex'][f'share_gt{t}s'], 4) for t in (1, 1.5, 2, 2.5, 3)]} def {[round(o['time_use']['r45'][f'share_gt{t}s'], 4) for t in (1, 1.5, 2, 2.5, 3)]}")
    print(f"[{arm}] play time ratio {o['play_time']['ratio_sum']:.3f}; belief_ms p50/p95/max ex {[round(x, 1) for x in e['belief_ms_p50_p95_p99_max']]}; swap rate entered/probed/leads {o['swap_rate']['entered']}/{o['swap_rate']['probed']}/{o['swap_rate']['leads']}")
