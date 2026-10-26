#!/usr/bin/env python3
"""s69 r3: builds rehearsal/host/rehearsal_summary.json (schema lane-host-rehearsal-summary-v1) from the copied-back --history
re-rehearsal of launcher r2 (726a8af0; 12 deals 311960000..311960011, the same child form), and measures --history's impact against the
r2 rehearsal (launcher r1 e3c25940, no --history; 36 deals from the same seed0, in host-r2/) ON THE SAME 12 DEALS: duel.jsonl bytes per
row and the decision-time totals of those deals.  Every number is read from the copied files; wall_s from 'DEV END rc=0 wall_s=', peak RSS
from the group sampler, the terminal = the log's last line minus its stamp; faults through the reader's analyze_rows (bound=None: non-lane
rows; the history gate runs on these rows).  projected_full_wall_s = max(r3, r2) s/deal x 600 x 1.25 (12 deals on 12 workers is one
straggler-bound batch, so r3's s/deal over-states a 600-deal run; the max keeps the projection conservative).
Usage: python3 make_rehearsal_summary.py   (from tools/s69/rehearsal/)"""
import hashlib, importlib.util, json, os, re
HERE = os.path.dirname(os.path.realpath(__file__))
HD, R2 = os.path.join(HERE, 'host'), os.path.join(HERE, 'host-r2')
PKT = os.path.dirname(HERE)


def end_line(path):
    log = open(path).read().rstrip('\n').split('\n')
    end = [l for l in log if re.search(r' s69 DEV END rc=0 wall_s=([0-9.]+) maxrss_kb=([0-9]+)$', l)]
    assert len(end) == 1, end
    return log, float(re.search(r'wall_s=([0-9.]+)', end[0]).group(1)), int(re.search(r'maxrss_kb=([0-9]+)', end[0]).group(1))


log, wall, maxrss_one = end_line(os.path.join(HD, 'rehearse.log'))
_, wall2, _ = end_line(os.path.join(R2, 'rehearse.log'))
term = log[-1].split(' ', 1)[1]
assert term.startswith('s69 REHEARSAL DONE rc=0'), term
peak = int(open(os.path.join(HD, 'peak_rss_kb')).read().strip())
raw3 = open(os.path.join(HD, 'duel.jsonl'), 'rb').read().splitlines()
raw2 = open(os.path.join(R2, 'duel.jsonl'), 'rb').read().splitlines()
rows3 = [json.loads(x) for x in raw3]
deals = len({r['seed'] for r in rows3})
assert len(rows3) == 2 * deals and sorted({r['seed'] for r in rows3}) == list(range(311960000, 311960000 + deals))
assert all('history' in r and 'buried' in r and 'failed_detail' in r for r in rows3), 'an r3 row without --history fields'
key3 = {(r['seed'], r['mirror']): len(x) + 1 for r, x in zip(rows3, raw3)}
rows2 = [json.loads(x) for x in raw2]
key2 = {(r['seed'], r['mirror']): len(x) + 1 for r, x in zip(rows2, raw2) if (r['seed'], r['mirror']) in key3}
assert set(key2) == set(key3) and not any('history' in r for r in rows2)
b3, b2 = sum(key3.values()), sum(key2.values())
secs = lambda rows, keys: sum(x for r in rows if (r['seed'], r['mirror']) in keys for s in ('ex', 'r45') for x in r['dsecs'][s])
dec3, dec2 = secs(rows3, key3), secs(rows2, key3)
spec = importlib.util.spec_from_file_location('s69_read', os.path.join(PKT, 's69_read.py')); rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)
out = rd.analyze_rows(os.path.join(HD, 'duel.jsonl'), bound=None, seed0=311960000, deals=deals)
e, d = out['exploiter'], out['defender']
cap = 28800
spd, spd2 = wall / deals, wall2 / 36
proj = round(max(spd, spd2) * 600 * 1.25, 1)
cleanup = [l for l in log if 'REHEARSAL cleanup' in l]
assert len(cleanup) == 1
full_bytes = b3 / (2 * deals) * 1200
summary = {
    'schema': 'lane-host-rehearsal-summary-v1', 'host': 'shengji-cloud', 'workers': 12, 'deals': deals, 'wall_s': wall,
    's_per_deal': round(spd, 3), 'full_run_deals': 600, 'projected_full_wall_s': proj, 'cap_s': cap, 'peak_rss_kb': peak,
    'terminal_line': term, 'cleanup': cleanup[0].split(' ', 1)[1], 'log': 'rehearse.log',
    'note': (f'r3 = the --history re-rehearsal of launcher r2 726a8af0 (run_child with --history) on 311960000+{deals}; projection = max(r3 {spd:.2f}, r2 {spd2:.2f} s/deal) x 600 x 1.25 '
             f'(the stop {cap} s is {cap / proj:.1f}x it). --history impact on the SAME {deals} deals vs r2 (no --history, host-r2/): duel.jsonl {b3:,} vs {b2:,} bytes '
             f'(x{b3 / b2:.3f}, +{(b3 - b2) / (2 * deals):,.0f} bytes/row; full run ~{full_bytes / 1e6:.1f} MB vs ~{b2 / (2 * deals) * 1200 / 1e6:.1f} MB); summed decide_play seconds {dec3:.1f} vs {dec2:.1f} '
             f'(x{dec3 / dec2:.3f}; the history list is appended per play, no search change); wall r3 {wall} s for {deals} deals vs r2 {wall2} s for 36. Validity on r3 rows '
             f"{out['validity']['verdict']} (history gate passed); play fallbacks ex {e['fallback']} / def {d['fallback']}, belief ex {e['belief_fallback']} / def {d['belief_fallback']}; "
             f"decide_play max ex {e['decide_play_p50_p95_p99_max'][3]} s / def {d['decide_play_p50_p95_p99_max'][3]} s; largest single process {maxrss_one} kB"),
}
with open(os.path.join(HD, 'rehearsal_summary.json'), 'w') as fh:
    json.dump(summary, fh, indent=1)
    fh.write('\n')
detail = dict(history_impact=dict(deals=deals, bytes_r3_history=b3, bytes_r2_same_deals=b2, ratio=b3 / b2, bytes_per_row_added=(b3 - b2) / (2 * deals),
                                  projected_full_run_bytes=full_bytes, decide_play_seconds_r3=dec3, decide_play_seconds_r2_same_deals=dec2),
              validity=out['validity'], attribution_status=(out.get('attribution') or {}).get('status'),
              exploiter={k: e[k] for k in ('decisions', 'fallback', 'belief_fallback', 'bury_fallback', 'declare_abandoned', 'decide_play_p50_p95_p99_max', 'd8_lead', 'd8_lead_complete', 'd8_follow_attempted', 'd8_follow_complete')},
              defender={k: d[k] for k in ('decisions', 'fallback', 'belief_fallback', 'bury_fallback', 'declare_abandoned', 'decide_play_p50_p95_p99_max')},
              rows_sha256=hashlib.sha256(open(os.path.join(HD, 'duel.jsonl'), 'rb').read()).hexdigest())
with open(os.path.join(HD, 'rehearsal_faults.json'), 'w') as fh:
    json.dump(detail, fh, indent=1, sort_keys=True)
    fh.write('\n')
print(json.dumps(summary, indent=1))
