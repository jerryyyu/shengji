"""s69r2: read-only listing of every /root/claude_reservations/*.json record (its lane, seed span) with any overlap against the s69r2 lane window (and, reported, the consumed s69 block and the rehearsal window),
plus a raw token grep of the s69r2 band (312xxxxxx) in record bodies and in /root/ and /root/*/ directory names.  stdin: ssh <host> python3 - (writes nothing)."""
import glob, json, os, re
W = [(312060910, 600, 'lane s69r2'), (311060910, 600, 'lane s69 (consumed)'), (311960000, 36, 'rehearsal')]
TOK = re.compile(r'(?<![0-9])312[0-9]{6}(?![0-9])')
n_rec, spans, hits = 0, [], []
for p in sorted(glob.glob('/root/claude_reservations/*.json')):
    raw = open(p).read()
    try:
        r = json.loads(raw)
    except Exception:
        print('unreadable', p); continue
    n_rec += 1
    seeds = [s for s in (r.get('seeds') or ([r['seed0']] if 'seed0' in r else [])) if isinstance(s, int)]
    n = int(r.get('count') or r.get('clusters') or r.get('deals') or 0)
    for a in seeds:
        spans.append((a, a + max(n, 1), r.get('lane'), p.split('/')[-1]))
        for b, m, lab in W:
            if a < b + m and b < a + max(n, 1):
                hits.append((p, lab, a, n))
    t = TOK.findall(raw)
    if t:
        print('TOKEN', p, t[:5])
names = [d for d in os.listdir('/root') if TOK.search(d)]
for d in sorted(glob.glob('/root/*/')):
    try:
        names += [d + x for x in os.listdir(d) if TOK.search(x)]
    except OSError:
        pass
spans.sort()
print('records', n_rec, 'seed spans', len(spans))
print('highest 8 spans:', spans[-8:])
print('overlaps with s69 windows:', hits)
print('names with an s69-band token:', names[:20])
print('done')
