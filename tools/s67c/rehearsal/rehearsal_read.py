#!/usr/bin/env python3
"""s67c rehearsal read (NON-scientific): the lane reader's analyze() (s67c_read.final.py) on the 56-deal throwaway rehearsal file
(seeds 243170000..243170055, outside the reserved block), with the arm's seed0 replaced IN MEMORY and a synthetic status, as smoke_read.py
does for the smoke.  Prints only the execution evidence: validity verdict and reasons, fallbacks, worlds, decide_play quantiles and max
against the 3 s budget, row / deal counts.  The paired margin of a throwaway block is not printed (it is not evidence of anything).
Usage: python3 rehearsal_read.py <s67c_read.final.py> <duel.jsonl> <wall_s> > rehearsal_read.txt"""
import importlib.util, json, sys, tempfile
from pathlib import Path
reader, duel, wall = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location('s67c_read', reader); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
TS = '2026-10-26T00:00:00Z'; SEED0 = 243170000; N = 56
arm = rd.ARM_ORDER[0]; a = rd.ARM_SPEC[arm]
lines = [f'{TS} s67c armed (pid 1, launcher sha256 {"0" * 64}) [synthetic status for the host rehearsal read]',
         f'{TS} s67c DEV start {arm}: defender {rd.DEF_NAME} (R48 as served) vs exploiter {a["cand"]} (S66_EXPLOITER=sc8p: the pair/tractor challenger, claude/s67-pair-challenger at 8a50fe8a; served budgets and widths on both sides); deals {N} seed0 {SEED0} [rehearsal]',
         f'{TS} s67c DEV END {arm} rc=0 wall_s={wall} maxrss_kb=1', f'{TS} {rd.TERMINAL}']
with tempfile.TemporaryDirectory(dir='/private/tmp') as tmp:
    st = Path(tmp) / 'status'; st.write_text('\n'.join(lines) + '\n')
    rd.ARM_SPEC[arm] = dict(a, seed0=SEED0)
    o = rd.analyze(duel, arm=arm, status=str(st), deals=N, binding=rd.SYNTHETIC)
e, d = o['exploiter'], o['defender']; lat = o['latency_vs_r48']; v = o['validity']
rows = [json.loads(l) for l in open(duel)]
print(f"rows {len(rows)}, deals {len({r['seed'] for r in rows})} (seeds {min(r['seed'] for r in rows)}..{max(r['seed'] for r in rows)})")
print(f"validity {v['verdict']} reasons {v['reasons']} checks {v['checks']}")
print(f"decisions ex {e['decisions']} / def {d['decisions']}; play fallbacks {e['fallback']} / {d['fallback']}; belief fallbacks {e['belief_fallback']} / {d['belief_fallback']}; worlds mismatches {e['play_worlds_mismatch']} / {d['play_worlds_mismatch']}")
print(f"decide_play s p50/p95/p99/max ex {[round(x, 3) for x in e['decide_play_p50_p95_p99_max']]} def {[round(x, 3) for x in d['decide_play_p50_p95_p99_max']]}")
print(f"latency check {v['detail']['latency_inside_budget']}; exploiter max / budget {lat['exploiter_max_over_budget']:.3f}; share past 2/2.5/3 s ex {[round(o['time_use']['ex'][f'share_gt{t}s'], 4) for t in (2, 2.5, 3)]} def {[round(o['time_use']['r45'][f'share_gt{t}s'], 4) for t in (2, 2.5, 3)]}")
print(f"belief_ms p50/p95/p99/max ex {[round(x, 1) for x in e['belief_ms_p50_p95_p99_max']]} def {[round(x, 1) for x in d['belief_ms_p50_p95_p99_max']]}")
