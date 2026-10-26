#!/usr/bin/env python3
"""adversarial_battery.py on the s69r2 reader (= battery_s69_adapter.py with the lane s69r2; the reader's BAR now holds the common 0.1%
play-fallback ceiling, which the case builder and the guard take from it).  s69's text follows.
adversarial_battery.py on the s69 reader: reader_lib's DuelAdapter (the exploit-duel family, unchanged) with the lane status and the
reader's dispatch binding, and the reader's OWN fault ceilings (zero play and zero belief fallbacks; bury 1%, declare 1%; one mapping for
both arms) used by both the case builder and the validity.py guard oracle.  = battery_s65dev_adapter.py (Codex-PASSed) with the binding of
s69_read.analyze: each case's bytes are laid out as the launcher seals them (root/duel.jsonl + root/SHA256SUMS naming it, the status, a
reservation naming the lane / launcher sha / status / root) in a temp dir, and the reader is called with a trusted mapping naming that
layout.  The clean status is the fixture's status_text() (armed, the exact DEV start, the run line, DEV END rc=0, the exact terminal line);
the ABORT case is the battery's abort_status_text('s69r2').  The clean rows come from test_s69_read.py's generator (above '# ---- T1 ----').
Usage: python3 battery_s69_adapter.py <s69r2_read.py> <test_s69r2_read.py> [--out battery_s69r2.out]"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

LIB = os.path.dirname(os.path.realpath(__file__))   # the packet's pinned copies: adversarial_battery.py 0b490be0, validity.py ba84c408
sys.path.insert(0, LIB)
import adversarial_battery as ab  # noqa: E402
va = ab.va
LAUNCHER_SHA = 'a' * 64


class S69Adapter(ab.DuelAdapter):
    takes_status = True

    def __init__(self, reader, fixture, **kw):
        super().__init__(reader, fixture, **kw)
        src = open(self.fixture).read().split(self.T1_MARKER)[0]
        ns = {'__name__': 'battery_fixture_status', '__file__': self.fixture}
        saved = sys.argv
        sys.argv = [self.fixture, self.reader]
        try:
            exec(compile(src, self.fixture, 'exec'), ns)
        finally:
            sys.argv = saved
        self._status = ns['status_text']()
        self.ceilings = dict(self.rd.BAR['ceilings'])

    def clean_status(self):
        return self._status

    def abort_status(self):
        return ab.abort_status_text('s69r2')

    def read(self, rows_path, status_path, tmp):
        tmp = Path(tmp).resolve()
        root = tmp / 'vol-dev-claude-s69r2-r48-20261026'
        root.mkdir()
        data = Path(rows_path).read_bytes()
        (root / 'duel.jsonl').write_bytes(data)
        (root / 'SHA256SUMS').write_text(f'{hashlib.sha256(data).hexdigest()}  ./duel.jsonl\n')
        sp = tmp / 'claude_s69r2_screen.status'
        sp.write_bytes(Path(status_path).read_bytes())
        rp = tmp / 's69r2.json'
        rp.write_text(json.dumps(dict(schema='claude-reservation-v1', lane='s69r2', launcher_sha256=LAUNCHER_SHA, status=str(sp), output_root=str(root))))
        trusted = dict(self.rd.TRUSTED, launcher_sha256=LAUNCHER_SHA, root=str(root), status=str(sp), reservation=str(rp))
        return self.rd.analyze(str(root), status=str(sp), reservation=str(rp), trusted=trusted)

    def guard(self, rows, tier='DEV'):
        checks = super().guard(rows, tier=tier)
        assert checks[0]['check'] == 'arm_fault_ceilings', checks[0]['check']
        counts = {}
        for arm in self.arms:   # the same counts as DuelAdapter.guard, re-judged at the reader's ceilings
            hs = [h for r in rows for h in r['dhist'][arm]]
            search = [h for h in hs if h[0] == ab.SEARCH_SCHEMA]
            buries = [r['bury_rec'] for r in rows if r['bury_rec'][0] == arm]
            ds = [d for r in rows for d in r['declare_recs'][arm]]
            counts[arm] = dict(decisions=len(hs), play_fallback=sum(h[0] == ab.FALLBACK_SCHEMA for h in hs), search=len(search),
                               belief_fallback=sum(h[4] == 1 for h in search), buries=len(buries),
                               bury_fallback=sum(b[1] == ab.BURY_FALLBACK_SCHEMA for b in buries), declares=len(ds),
                               declare_abandon=sum(d[2] is False for d in ds))
        return [va.arm_fault_ceilings(counts, self.ceilings, arms=self.arms, tier=tier)] + checks[1:]

    def header(self, tier):
        h = super().header(tier)
        c = self.ceilings
        h[0] = (f'{ab.BATTERY_VERSION}  tier {tier}  ceilings (the reader\'s BAR) play {100 * c["play_fallback"]:g}% / belief {100 * c["belief_fallback"]:g}% / '
                f'bury {100 * c["bury_fallback"]:g}% / declare {100 * c["declare_abandon"]:g}% on every arm; play worlds {self.play_worlds}')
        return h


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('reader'); p.add_argument('fixture'); p.add_argument('--out')
    a = p.parse_args(argv)
    adapter = S69Adapter(a.reader, a.fixture, play_worlds={'ex': 1, 'r45': 1})
    adapter.play_worlds = dict(adapter.rd.PLAY_WORLDS)   # the reader's pinned play worlds per arm (exploiter 256, defender 64)
    header = adapter.header('DEV') + [f'adapter  {os.path.realpath(__file__)}  sha256 {ab.sha256_file(os.path.realpath(__file__))}  (DuelAdapter + the dispatch binding + the reader\'s ceilings)']
    results = ab.run_battery(adapter, ceilings=adapter.ceilings, tier='DEV')
    text, ok = ab.format_table(results, header)
    sys.stdout.write(text)
    if a.out:
        with open(a.out, 'x') as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
