#!/usr/bin/env python3
"""adversarial_battery.py on the s67c reader: reader_lib's DuelAdapter (the exploit-duel family, unchanged) with the lane status bound
and the reader's OWN fault ceilings (zero play and zero belief fallbacks; bury 1%, declare 1%) used by both the case builder and the
validity.py guard oracle, since s67c's ceilings are not validity.py's defaults.  The reader is driven on the fixture's arm (sc8p); the
clean status is the fixture's status_text() (armed, the S17 adoption, DEV start / END per arm, the exact terminal line); the ABORT case
is the battery's abort_status_text('s67c').  Everything else is DuelAdapter's.  = battery_s66b_adapter.py with the lane, the row key
('sc8p') and the 9-field fallback form (the exploiter's play-fallback mutation blanks the seven probe fields and keeps the lead flag and
the played kind, as the adapter writes a fallback record); the play worlds per side = the reader's PLAY_WORLDS (64 / 64: the candidate
changes no knob).  The battery's other mutations leave the probe entries in place; a mutation the reader refuses before validity counts as
REJECT either way.
Usage: python3 battery_s67c_adapter.py <s67c_read.py> <test_s67c_read.py> [--out battery_s67c.out]"""
import argparse
import os
import sys

LIB = '/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/reader_lib'
sys.path.insert(0, LIB)
import adversarial_battery as ab  # noqa: E402
va = ab.va


class S67cAdapter(ab.DuelAdapter):
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
        self.arm = ns['ARM']
        self.ceilings = dict(self.rd.BAR['ceilings'])

    def clean_status(self):
        return self._status

    def abort_status(self):
        return ab.abort_status_text('s67c')

    def fault_sites(self, rows, arm, kind):
        """the exploiter's play-fallback mutation also blanks the decision's probe entry, as the adapter writes a fallback record (no probe
        field -> [lead, None x7, played_kind]); the other kinds and the defender are DuelAdapter's"""
        if kind != 'play_fallback' or arm != 'ex':
            return super().fault_sites(rows, arm, kind)
        sites = [(r, i) for r in rows for i, h in enumerate(r['dhist']['ex'])]

        def to_fallback(r, i):
            self._to_fallback(r['dhist']['ex'][i])
            r['sc8p']['ex'][i] = [r['dhist']['ex'][i][9], None, None, None, None, None, None, None, r['sc8p']['ex'][i][8]]
        return len(sites), [lambda r=r, i=i: to_fallback(r, i) for r, i in sites if r['dhist']['ex'][i][0] == ab.SEARCH_SCHEMA]

    def read(self, rows_path, status_path, tmp):
        return self.rd.analyze(rows_path, arm=self.arm, status=status_path, binding=self.rd.SYNTHETIC)   # the reader's logic on fixture rows; the lane read binds through analyze_lane

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
                f'bury {100 * c["bury_fallback"]:g}% / declare {100 * c["declare_abandon"]:g}% on every arm; play worlds {self.play_worlds}; arm read {self.arm}')
        return h


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('reader'); p.add_argument('fixture'); p.add_argument('--out')
    a = p.parse_args(argv)
    adapter = S67cAdapter(a.reader, a.fixture, play_worlds={'ex': 1, 'r45': 1})
    adapter.play_worlds = dict(adapter.rd.PLAY_WORLDS)   # 64 / 64: both sides are R48's recipe
    header = adapter.header('DEV') + [f'adapter  {os.path.realpath(__file__)}  sha256 {ab.sha256_file(os.path.realpath(__file__))}  (DuelAdapter + the lane status + the reader\'s ceilings)']
    results = ab.run_battery(adapter, ceilings=adapter.ceilings, tier='DEV')
    text, ok = ab.format_table(results, header)
    sys.stdout.write(text)
    if a.out:
        with open(a.out, 'x') as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
