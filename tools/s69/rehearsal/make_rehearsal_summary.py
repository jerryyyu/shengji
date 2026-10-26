#!/usr/bin/env python3
"""s69: builds rehearsal/host/rehearsal_summary.json (schema lane-host-rehearsal-summary-v1, fl-pilot/rehearsal_summary.template.json) from
the copied-back host rehearsal: the status log (rehearse.log), duel.jsonl, duel.time and the peak group RSS file.  Every number is read from
those files: wall_s from the 'DEV END rc=0 wall_s=' line, deals from the rows (36 deals x 2 mirrors), peak_rss_kb = the sampler's peak of
the whole process group, the terminal line = the log's last line minus its stamp; the faults and the decide times through the reader's
analyze_rows (bound=None: non-lane rows; the margins of these throwaway deals are not reported).  projected_full_wall_s = s_per_deal x 600 x
1.25 (a straggler margin over the linear projection; 36 deals on 12 workers end in a tail that a 600-deal run amortizes).
Usage: python3 make_rehearsal_summary.py   (from tools/s69/rehearsal/)"""
import hashlib
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.realpath(__file__))
HD = os.path.join(HERE, 'host')
PKT = os.path.dirname(HERE)
log = open(os.path.join(HD, 'rehearse.log')).read().rstrip('\n').split('\n')
end = [l for l in log if re.search(r' s69 DEV END rc=0 wall_s=([0-9.]+) maxrss_kb=([0-9]+)$', l)]
assert len(end) == 1, end
wall = float(re.search(r'wall_s=([0-9.]+)', end[0]).group(1))
maxrss_one = int(re.search(r'maxrss_kb=([0-9]+)', end[0]).group(1))
term = log[-1].split(' ', 1)[1]
assert term.startswith('s69 REHEARSAL DONE rc=0'), term
peak = int(open(os.path.join(HD, 'peak_rss_kb')).read().strip())
rows = [json.loads(x) for x in open(os.path.join(HD, 'duel.jsonl'))]
seeds = sorted({r['seed'] for r in rows})
deals = len(seeds)
assert len(rows) == 2 * deals and seeds == list(range(311960000, 311960000 + deals)), (len(rows), seeds[:3])
spec = importlib.util.spec_from_file_location('s69_read', os.path.join(PKT, 's69_read.py')); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
out = rd.analyze_rows(os.path.join(HD, 'duel.jsonl'), bound=None, seed0=311960000, deals=deals)
e, d = out['exploiter'], out['defender']
cap = 28800
spd = wall / deals
proj = round(spd * 600 * 1.25, 1)
cleanup = [l for l in log if 'REHEARSAL cleanup' in l]
assert len(cleanup) == 1
summary = {
    'schema': 'lane-host-rehearsal-summary-v1', 'host': 'shengji-cloud', 'workers': 12, 'deals': deals, 'wall_s': wall,
    's_per_deal': round(spd, 3), 'full_run_deals': 600, 'projected_full_wall_s': proj, 'cap_s': cap, 'peak_rss_kb': peak,
    'terminal_line': term, 'cleanup': cleanup[0].split(' ', 1)[1], 'log': 'rehearse.log',
    'note': (f'the lane child form (run_child of launcher e3c25940) on the throwaway window 311960000+{deals}; projection = s/deal x 600 x 1.25 '
             f'(straggler margin; the stop {cap} s is {cap / proj:.1f}x it); largest single process (time -v) {maxrss_one} kB; validity on these rows '
             f"{out['validity']['verdict']}; play fallbacks ex {e['fallback']} / def {d['fallback']}, belief fallbacks ex {e['belief_fallback']} / def {d['belief_fallback']}, "
             f"bury fallbacks ex {e['bury_fallback']} / def {d['bury_fallback']}, declare abandons ex {e['declare_abandoned']} / def {d['declare_abandoned']}; decide_play max ex {e['decide_play_p50_p95_p99_max'][3]} s "
             f"(p50/p95/p99 {e['decide_play_p50_p95_p99_max'][:3]}) / def {d['decide_play_p50_p95_p99_max'][3]} s; exploiter 8-card exact leads {e['d8_lead_complete']}/{e['d8_lead']} complete, "
             f"follows {e['d8_follow_complete']}/{e['d8_follow_attempted']}; bury s max ex {e['bury_seconds_p50_p99_max'][2]} / def {d['bury_seconds_p50_p99_max'][2]}; "
             f"declare s max ex {e['declare_seconds_p50_p99_max'][2]} / def {d['declare_seconds_p50_p99_max'][2]}"),
}
with open(os.path.join(HD, 'rehearsal_summary.json'), 'w') as fh:
    json.dump(summary, fh, indent=1)
    fh.write('\n')
detail = dict(validity=out['validity'], exploiter={k: e[k] for k in ('decisions', 'search', 'fallback', 'belief_fallback', 'buries', 'bury_fallback', 'declares', 'declare_abandoned',
                                                                    'd8_lead', 'd8_lead_complete', 'd8_lead_abandoned', 'd8_follow_attempted', 'd8_follow_complete', 'd8_follow_abandoned',
                                                                    'decide_play_p50_p95_p99_max', 'decide_play_maxhand8_p50_p95_p99_max', 'bury_seconds_p50_p99_max', 'declare_seconds_p50_p99_max', 'failed_throws')},
              defender={k: d[k] for k in ('decisions', 'search', 'fallback', 'belief_fallback', 'buries', 'bury_fallback', 'declares', 'declare_abandoned',
                                          'decide_play_p50_p95_p99_max', 'bury_seconds_p50_p99_max', 'declare_seconds_p50_p99_max', 'failed_throws')},
              attribution_status=(out.get('attribution') or {}).get('status'), rows_sha256=hashlib.sha256(open(os.path.join(HD, 'duel.jsonl'), 'rb').read()).hexdigest())
with open(os.path.join(HD, 'rehearsal_faults.json'), 'w') as fh:
    json.dump(detail, fh, indent=1, sort_keys=True)
    fh.write('\n')
print(json.dumps(summary, indent=1))
