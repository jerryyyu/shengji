"""s67c: read-only listing of every /root/claude_reservations/*.json record with a deal seed in [140000000, 1e9), its window span, and any
overlap with the s67c windows (arm sc8p [243260910, +3920); smoke [243160000, +2)); plus
a raw grep of the token band 2431xxxxx-2432xxxxx; plus a listing of /root/*/ and /root/vol-* directory names carrying a
token in that band.  = s66b's reservations_high.py (itself s65dev's) with the windows and the band changed.
stdin: ssh <host> python3 -   (nothing is written)"""
import glob, json, os, re
W = [(243260910, 3920), (243160000, 2)]
TOK = re.compile(r'(?<![0-9])243[12][0-9]{5}(?![0-9])')
n_rec = 0
for p in sorted(glob.glob('/root/claude_reservations/*.json')):
    raw = open(p).read()
    try:
        r = json.loads(raw)
    except Exception:
        print('unreadable', p); continue
    n_rec += 1
    seeds = [s for s in (r.get('seeds') or ([r['seed0']] if 'seed0' in r else [])) if isinstance(s, int) and 140000000 <= s < 1e9]
    n = int(r.get('count') or r.get('clusters') or 0)
    if seeds:
        over = [(a, b) for a in seeds for b, m in W if a < b + m and b < a + n]
        print(p.split('/')[-1], 'lane', r.get('lane'), 'span', min(seeds), max(seeds) + n, 'n', len(seeds), 'overlap', over)
    t = TOK.findall(raw)
    if t:
        print('TOKEN', p, t[:5])
names = [d for d in os.listdir('/root') if TOK.search(d)]
for d in sorted(glob.glob('/root/*/')):
    try:
        names += [d + x for x in os.listdir(d) if TOK.search(x)]
    except OSError:
        pass
print('records', n_rec, '| names with a band token', names[:20])
print('done')
