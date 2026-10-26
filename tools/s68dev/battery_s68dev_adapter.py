#!/usr/bin/env python3
"""adversarial_battery.py on the s68dev reader (= battery_s66b_adapter.py with the fixture arm passed through, the per-arm play
worlds and the lane name changed; run once per arm).  s66b's description: reader_lib's DuelAdapter (the exploit-duel family, unchanged) with the lane status bound
and the reader's OWN fault ceilings (zero play and zero belief fallbacks; bury 1%, declare 1%) used by both the case builder and the
validity.py guard oracle, since s66b's ceilings are not validity.py's defaults.  The reader is driven on the fixture's arm (sc8); the
clean status is the fixture's status_text() (armed, the S17 adoption, DEV start / END per arm, the exact terminal line); the ABORT case
is the battery's abort_status_text('s66b').  Everything else is DuelAdapter's.  = battery_s65dev_adapter.py with the play worlds per
side = the reader's PLAY_WORLDS (64 / 64: the candidate changes no knob); the fixture rows carry the adapter's 'sc8' probe entries, which
the battery's mutations leave in place (a play-fallback mutation on an exploiter decision leaves its probe entry: the reader then refuses
that pairing before validity, which the battery counts as REJECT either way).
Usage: python3 battery_s68dev_adapter.py <s68dev_read.py> <test_s68dev_read.py> <arm: b | a> [--out battery_s68dev.<arm>.out]"""
import argparse
import os
import sys

LIB = '/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/fl-pilot/reader_lib'
sys.path.insert(0, LIB)
import adversarial_battery as ab  # noqa: E402
va = ab.va


class S68devAdapter(ab.DuelAdapter):
    takes_status = True

    def __init__(self, reader, fixture, fixture_arm, **kw):
        """DuelAdapter.__init__ execs the fixture's generator with sys.argv = [fixture, reader]; the s68dev fixture takes its arm from
        argv[2], so for the duration of that call the battery module's `sys` is a proxy whose argv assignment appends the arm."""
        self.fixture_arm = fixture_arm
        real = ab.sys

        class _Sys:
            def __getattr__(self, k):
                return getattr(real, k)

            def __setattr__(self, k, val):
                if k == 'argv' and isinstance(val, list) and len(val) == 2:
                    val = val + [fixture_arm]
                setattr(real, k, val)
        ab.sys = _Sys()
        try:
            super().__init__(reader, fixture, **kw)
        finally:
            ab.sys = real
        sys.argv = [a for a in sys.argv]
        assert self.rd.ARM_ORDER and self._rows is not None
        src = open(self.fixture).read().split(self.T1_MARKER)[0]
        ns = {'__name__': 'battery_fixture_status', '__file__': self.fixture}
        saved = sys.argv
        sys.argv = [self.fixture, self.reader, self.fixture_arm]
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
        return ab.abort_status_text('s68dev')

    def fault_sites(self, rows, arm, kind):
        """the exploiter's play-fallback mutation also blanks the decision's probe entry, as the adapter writes a fallback record (no probe
        field -> [lead, None x5]); the other kinds and the defender are DuelAdapter's"""
        if kind != 'play_fallback' or arm != 'ex':
            return super().fault_sites(rows, arm, kind)
        sites = [(r, i) for r in rows for i, h in enumerate(r['dhist']['ex'])]

        def to_fallback(r, i):
            self._to_fallback(r['dhist']['ex'][i])
            r['sc8']['ex'][i] = [r['dhist']['ex'][i][9], None, None, None, None, None]
        return len(sites), [lambda r=r, i=i: to_fallback(r, i) for r, i in sites if r['dhist']['ex'][i][0] == ab.SEARCH_SCHEMA]

    def read(self, rows_path, status_path, tmp):
        return self.rd.analyze(rows_path, arm=self.arm, status=status_path, binding=self.rd.SYNTHETIC)   # r2: the reader's logic on fixture rows; the lane read binds through analyze_lane

    def guard(self, rows, tier='DEV'):
        """the reader's fault ceilings, re-judged independently: every kind at the reader's BAR on both sides, except that the exploiter's
        play fallbacks are judged at the arm's allowance (PLAY_FALLBACK_ALLOWANCE: arm a 0.1% of its decisions, arm b zero); the defender's
        stay at the BAR ceiling (zero)"""
        checks = self._guard_base(rows, tier=tier)
        share = self.rd.PLAY_FALLBACK_ALLOWANCE[self.arm]
        if share == self.ceilings['play_fallback']:
            return checks
        hs = [h for r in rows for h in r['dhist']['ex']]
        n, d = sum(h[0] == ab.FALLBACK_SCHEMA for h in hs), len(hs)
        reasons = [] if n <= int(share * d) else [f"oracle: exploiter play fallbacks {n} of {d} > {share:g} allowance ({int(share * d)})"]
        first = dict(checks[0])
        if any("'ex' play_fallback" in x for x in first['reasons']):
            first['reasons'] = [x for x in first['reasons'] if "'ex' play_fallback" not in x]
            first['verdict'] = va.VALID if not first['reasons'] else first['verdict']
        allowance = dict(check='play_fallback_allowance', verdict=va.VALID if not reasons else va.invalid_verdict(tier), reasons=reasons, n_reasons=len(reasons), detail={})
        return [first, allowance] + checks[1:]

    def _guard_base(self, rows, tier='DEV'):
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
                f'bury {100 * c["bury_fallback"]:g}% / declare {100 * c["declare_abandon"]:g}% on every arm, except the exploiter play-fallback allowance {100 * self.rd.PLAY_FALLBACK_ALLOWANCE[self.arm]:g}%; play worlds {self.play_worlds}; arm read {self.arm}')
        return h


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('reader'); p.add_argument('fixture'); p.add_argument('arm', choices=('b', 'a')); p.add_argument('--out')
    a = p.parse_args(argv)
    adapter = S68devAdapter(a.reader, a.fixture, a.arm, play_worlds={'ex': 1, 'r45': 1})
    assert adapter.arm == a.arm, (adapter.arm, a.arm)
    adapter.play_worlds = dict(adapter.rd.PLAY_WORLDS[a.arm])   # the arm's play worlds (b 64 / 64; a 96 / 64)
    header = adapter.header('DEV') + [f'adapter  {os.path.realpath(__file__)}  sha256 {ab.sha256_file(os.path.realpath(__file__))}  (DuelAdapter + the lane status + the reader\'s ceilings)']
    share = adapter.rd.PLAY_FALLBACK_ALLOWANCE[a.arm]
    if share != adapter.ceilings['play_fallback']:
        # the exploiter's two play-fallback cases at the arm's allowance (arm a: 0.1% of its decisions); every other case as built
        orig = ab.build_cases

        def build_cases(ad, ceilings):
            out = []
            for name, want, kind, build in orig(ad, ceilings):
                if name.startswith('exploiter play fallbacks '):
                    over = name.endswith('over ceiling by one')

                    def build(rows, over=over):
                        d, sites = ad.fault_sites(rows, 'ex', 'play_fallback')
                        k = ab._units_at_ceiling(share, d) + int(over)
                        for j in ab._spread(len(sites), k):
                            sites[j]()
                        return f'{k} of {d} (allowance {share:g})'
                    name = name + f' (arm {a.arm} allowance {share:g})'
                out.append((name, want, kind, build))
            return out
        ab.build_cases = build_cases
    results = ab.run_battery(adapter, ceilings=adapter.ceilings, tier='DEV')
    text, ok = ab.format_table(results, header)
    sys.stdout.write(text)
    if a.out:
        with open(a.out, 'x') as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
