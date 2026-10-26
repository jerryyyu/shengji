#!/usr/bin/env python3
"""s69: the local smoke's rows (throwaway window 311970000+4) through the reader's analyze_rows (no binding: not lane output), as a code
witness that the real producer's rows pass every gate; never a read.  Usage: python3 read_smoke.py <s69_read.py> <duel.jsonl> <seed0> <deals>"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('s69_read', sys.argv[1]); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
out = rd.analyze_rows(sys.argv[2], bound=None, seed0=int(sys.argv[3]), deals=int(sys.argv[4]))
print('validity', out['validity']['verdict'], out['validity']['reasons'])
print('exploiter', {k: out['exploiter'][k] for k in ('decisions', 'search', 'fallback', 'belief_fallback', 'd8_lead', 'd8_lead_complete', 'd8_follow_attempted', 'd8_follow_complete', 'decide_play_p50_p95_p99_max', 'buries', 'bury_fallback', 'declares', 'declare_abandoned')})
print('defender', {k: out['defender'][k] for k in ('decisions', 'search', 'fallback', 'belief_fallback', 'decide_play_p50_p95_p99_max', 'buries', 'bury_fallback', 'declares', 'declare_abandoned')})
if out.get('attribution'):
    print('attribution', out['attribution']['status'], [(c['cell'], c['deals']) for c in out['attribution'].get('tables', {}).get('class_trick_rank', [])])
for l in out['canonical_lines']:
    print('  ', l[:220])
