#!/usr/bin/env python3
"""Adversarial fixture battery for DEV and screen readers.  Standard library only (Python 3.9+); the reader under test brings its own
dependencies.

It synthesizes the standard bad inputs from a lane's own clean fixture and requires the reader to refuse each one or return an INVALID
verdict, and to accept the clean fixture:

  clean fixture                           ACCEPT
  all <arm> plays fallback                REJECT   (each arm)
  <arm> <fault> over ceiling by one       REJECT   (each arm x play / belief / bury / declare: floor(ceiling x denominator) + 1)
  <arm> <fault> at ceiling                ACCEPT   (the same arms and kinds at floor(ceiling x denominator): one ceiling for all arms)
  <arm> wrong world count on one record   REJECT   (each arm; a record form without a world count FAILS: delivery is unproven)
  <arm> evaluated declare short of worlds REJECT   (each arm: evaluated with 0 of its worlds completed, as in the s60dev HOLD)
  impossible score row                    REJECT   (attacker_points 0 under a kitty bonus, as in the s53dev HOLD)
  duplicate seed / missing seed           REJECT
  truncated last row                      REJECT
  ABORT terminal                          REJECT   (n/a, listed as such, when the reader takes no status)

REJECT passes on REFUSED (SystemExit 'REFUSING: ...' or a ValueError such as ReaderRefusal / RowSchemaRefusal / JSONDecodeError), on an
INVALID verdict, or on any other exception (CRASH: closed, but listed).  ACCEPT passes only on a verdict outside the INVALID set.  For
every content case the battery also runs validity.py on the same rows (the GUARD column) and requires it to agree with the case's
intent, so a fixture mutation that did not take is a battery error, never a reader pass.

Usage (the exploit-duel family: s59dev / s60dev / s53dev-style duel.jsonl rows):

  python3 adversarial_battery.py duel --reader <lane>_read.py --fixture test_<lane>_read.py [--play-worlds ex=256,r45=64]
                                      [--invoke module|argv] [--tier DEV] [--out battery.txt]

--fixture is the lane's reviewed e2e test; its generator (everything above its '# ---- T1 ----' line) builds the clean rows, and
the battery replaces each row's round result with an engine-consistent one (consistent_outcome).  Exit 0 = BATTERY PASS.

From Python, any row format:  run_battery(adapter) -> results;  format_table(results, header) -> the pasteable text.  An adapter
implements the attributes and methods of DuelAdapter's "adapter interface" block.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from fractions import Fraction

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import validity as va  # noqa: E402

BATTERY_VERSION = 'adversarial-battery-v1'
FAULT_KINDS = ('play_fallback', 'belief_fallback', 'bury_fallback', 'declare_abandon')
FAULT_LABEL = dict(play_fallback='play fallbacks', belief_fallback='belief fallbacks', bury_fallback='bury fallbacks',
                   declare_abandon='declare abandons')
ACCEPT, REJECT = 'ACCEPT', 'REJECT'
TS0 = '2026-10-17T01:00:00Z'


def sha256_file(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class CaseResult:
    def __init__(self, name, want, outcome, detail, guard, passed, note=''):
        self.name, self.want, self.outcome, self.detail, self.guard, self.passed, self.note = name, want, outcome, detail, guard, passed, note

    def as_dict(self):
        return dict(name=self.name, want=self.want, outcome=self.outcome, detail=self.detail, guard=self.guard, passed=self.passed, note=self.note)


def _classify_exception(e):
    if isinstance(e, SystemExit):
        msg = str(e)
        return ('REFUSED', msg) if msg.startswith('REFUSING') else ('CRASH', f'SystemExit({msg[:120]!r})')
    if isinstance(e, ValueError):
        return 'REFUSED', f'{type(e).__name__}: {e}'
    return 'CRASH', f'{type(e).__name__}: {e}'


def run_reader(adapter, rows_bytes, status_text):
    """(outcome, detail): outcome is REFUSED / CRASH / the reader's verdict string."""
    with tempfile.TemporaryDirectory(prefix='battery-', dir=os.path.realpath(tempfile.gettempdir())) as tmp:
        rows_path = os.path.join(tmp, adapter.rows_name)
        with open(rows_path, 'wb') as fh:
            fh.write(rows_bytes)
        status_path = None
        if status_text is not None:
            status_path = os.path.join(tmp, 'lane.status')
            with open(status_path, 'w') as fh:
                fh.write(status_text)
        try:
            result = adapter.read(rows_path, status_path, tmp)
        except BaseException as e:   # noqa: BLE001  every exit of the reader is classified
            if isinstance(e, KeyboardInterrupt):
                raise
            return _classify_exception(e)
    try:
        v = adapter.verdict(result)
    except Exception as e:   # noqa: BLE001
        return 'CRASH', f'verdict unreadable: {type(e).__name__}: {e}'
    return (v, adapter.verdict_detail(result)) if isinstance(v, str) else ('CRASH', f'verdict {v!r} is not a string')


def _spread(n, k):
    """k distinct indices spread evenly over range(n)."""
    if k > n:
        raise ValueError(f'need {k} fault sites, the fixture has {n}')
    return sorted({(i * n) // k for i in range(k)}) if k else []


def _units_at_ceiling(share, denominator):
    return math.floor(Fraction(str(share)) * denominator)


def build_cases(adapter, ceilings):
    """[(name, want, kind, build)]: kind 'content' (build(rows) mutates rows; the guard runs), 'bytes' (build(rows) -> bytes),
    'status' (build() -> status text) or 'na' (build() -> the reason)."""
    cases = [('clean fixture', ACCEPT, 'content', lambda rows: 'unchanged')]
    for arm in adapter.arms:
        who = adapter.arm_label[arm]

        def all_play(rows, arm=arm):
            d, sites = adapter.fault_sites(rows, arm, 'play_fallback')
            for s in sites:
                s()
            return f'{len(sites)} of {d} decisions'
        cases.append((f'all {who} plays fallback', REJECT, 'content', all_play))
    for arm in adapter.arms:
        who = adapter.arm_label[arm]
        for kind in FAULT_KINDS:
            if ceilings.get(kind) is None:
                continue
            for over in (True, False):
                def inject(rows, arm=arm, kind=kind, over=over):
                    d, sites = adapter.fault_sites(rows, arm, kind)
                    k = _units_at_ceiling(ceilings[kind], d) + int(over)
                    for j in _spread(len(sites), k):
                        sites[j]()
                    return f'{k} of {d}'
                cases.append((f'{who} {FAULT_LABEL[kind]} {"over ceiling by one" if over else "at ceiling"}',
                              REJECT if over else ACCEPT, 'content', inject))
    for arm in adapter.arms:
        def worlds(rows, arm=arm):
            return adapter.wrong_worlds(rows, arm)
        cases.append((f'{adapter.arm_label[arm]} wrong world count on one record', REJECT, 'content', worlds))
    for arm in adapter.arms:
        def short(rows, arm=arm):
            return adapter.incomplete_evaluation(rows, arm)
        cases.append((f'{adapter.arm_label[arm]} evaluated declare short of worlds', REJECT, 'content', short))
    cases.append(('impossible score row', REJECT, 'content', adapter.impossible_score))
    cases.append(('duplicate seed', REJECT, 'content', adapter.duplicate_seed))
    cases.append(('missing seed', REJECT, 'content', adapter.missing_seed))

    def truncated(rows):
        data = adapter.dump(rows)
        cut = data.rstrip(b'\n')
        return cut[:-max(8, len(cut.rsplit(b'\n', 1)[-1]) // 3)]
    cases.append(('truncated last row', REJECT, 'bytes', truncated))
    if adapter.takes_status:
        cases.append(('ABORT terminal', REJECT, 'status', adapter.abort_status))
    else:
        cases.append(('ABORT terminal', REJECT, 'na', lambda: 'the reader takes no status input; the terminal gate is outside it'))
    return cases


def run_battery(adapter, *, ceilings=None, tier='DEV'):
    ceilings = dict(va.DEFAULT_CEILINGS if ceilings is None else ceilings)
    out = []
    for name, want, kind, build in build_cases(adapter, ceilings):
        guard, note = '-', ''
        status = adapter.clean_status() if adapter.takes_status else None
        if kind == 'na':
            out.append(CaseResult(name, want, 'N/A', build(), '-', None, 'not applicable'))
            continue
        if kind == 'status':
            rows = adapter.clean_rows()
            data, status, note = adapter.dump(rows), build(), 'ABORT line, no LANE DONE'
        elif kind == 'bytes':
            rows = adapter.clean_rows()
            data, note = build(rows), 'last line cut'
        else:
            rows = adapter.clean_rows()
            note = build(rows)
            if note is False or note is None:
                out.append(CaseResult(name, want, 'NOT CHECKABLE', adapter.no_worlds_reason, '-', False,
                                      'the records carry no world count'))
                continue
            data = adapter.dump(rows)
            if name not in ('duplicate seed', 'missing seed'):
                g = va.combine(adapter.guard(rows, tier=tier), tier=tier)
                guard = g['verdict']
                if (guard == va.VALID) != (want == ACCEPT):
                    out.append(CaseResult(name, want, 'BATTERY ERROR', f'guard {guard} disagrees with the case: {g["reasons"][:2]}', guard,
                                          False, note))
                    continue
        outcome, detail = run_reader(adapter, data, status)
        if want == ACCEPT:
            passed = outcome not in ('REFUSED', 'CRASH') and outcome not in adapter.invalid_verdicts
        else:
            passed = outcome in ('REFUSED', 'CRASH') or outcome in adapter.invalid_verdicts
        out.append(CaseResult(name, want, outcome, detail, guard, passed, note))
    return out


def format_table(results, header_lines):
    w = max(len(r.name) for r in results)
    lines = list(header_lines)
    lines.append(f'{"#":>2}  {"case":<{w}}  {"want":<6}  {"reader outcome":<14}  {"guard":<12}  {"result":<6}  injected / detail')
    for i, r in enumerate(results, 1):
        res = 'n/a' if r.passed is None else ('PASS' if r.passed else 'FAIL')
        info = r.note if r.passed is not False else f'{r.note}; {r.detail}'
        if r.outcome == 'CRASH':
            info = f'{r.note}; closed by {r.detail}'
        lines.append(f'{i:>2}  {r.name:<{w}}  {r.want:<6}  {r.outcome[:14]:<14}  {r.guard[:12]:<12}  {res:<6}  {info[:150]}')
    failed = [r.name for r in results if r.passed is False]
    na = [r.name for r in results if r.passed is None]
    crashed = [r.name for r in results if r.outcome == 'CRASH']
    applicable = len(results) - len(na)
    verdict = 'BATTERY PASS' if not failed else 'BATTERY FAIL'
    tail = f'{verdict}: {applicable - len(failed)} of {applicable} applicable cases pass'
    if failed:
        tail += f'; FAILED: {"; ".join(failed)}'
    if na:
        tail += f'; not applicable: {"; ".join(na)}'
    if crashed:
        tail += f'; closed by a crash, not a refusal: {"; ".join(crashed)}'
    lines.append(tail)
    return '\n'.join(lines) + '\n', not failed


# The exploit-duel family: duel.jsonl rows with dhist / bury_rec / declare_recs.

SEARCH_SCHEMA, FALLBACK_SCHEMA = '-decision-v1', '-fallback-v1'
BURY_FALLBACK_SCHEMA = 'cwv-bury-fallback-v1'


def consistent_outcome(rng, banker, ex_team):
    """An engine-consistent round result for a row (the fields exploit_duel_s6x.py writes from Game.finish_round), sampled."""
    attackers = [(banker + 1) % 4, (banker + 3) % 4]
    defenders = [banker, (banker + 2) % 4]
    kp = 5 * rng.randint(0, 8)
    attackers_last = rng.random() < 0.5
    ltw = rng.choice(attackers if attackers_last else defenders)
    kb = kp * va.KITTY_MULTIPLIER * rng.choice((1, 2, 4)) if attackers_last and kp else 0
    trick = 5 * rng.randint(0, (va.TOTAL_POINTS - kp) // 5)
    ap = trick + kb
    winner, gain = va.engine_level_outcome(ap, banker)
    ex_attacks = ex_team != banker % 2
    return dict(attacker_points=ap, kitty_points=kp, kitty_bonus=kb, last_trick_winner=ltw, winner_team=winner, level_change=gain,
                ex_levels=gain if winner == ex_team else -gain, ex_attacker_points_signed=ap if ex_attacks else -ap)


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DuelAdapter:
    """Adapter for the exploit-duel reader family: duel.jsonl rows with dhist {ex, r45} (18 fields, or 19 with the play worlds at
    index 18), bury_rec [side, schema, reason, candidates, model_worlds, secs] and declare_recs {side: [schema, reason, evaluated,
    worlds, completed, secs, wall]}; analyze(path) -> result with result['bar']['verdict'].

    reader: the lane reader's path.  fixture: the lane's e2e test, whose generator (above '# ---- T1 ----') takes the reader path as
    sys.argv[1] and defines rows(effect=..., seed=...).  play_worlds: {arm: configured play worlds}; declare / bury world counts
    come from the reader's DECLARE_WORLDS / BURY_WORLDS."""

    # adapter interface: arms, arm_label, takes_status, rows_name, invalid_verdicts, no_worlds_reason; clean_rows(), clean_status(),
    # dump(rows), read(rows_path, status_path, tmp), verdict(result), verdict_detail(result), fault_sites(rows, arm, kind),
    # wrong_worlds(rows, arm), incomplete_evaluation(rows, arm), impossible_score(rows), duplicate_seed(rows), missing_seed(rows), abort_status(), guard(rows, tier)
    arms = ('ex', 'r45')
    arm_label = {'ex': 'exploiter', 'r45': 'defender'}
    takes_status = False
    rows_name = 'duel.jsonl'
    invalid_verdicts = frozenset({'DEV_INVALID', 'SCREEN_INVALID'})
    no_worlds_reason = 'dhist search records carry no play world count (18-field form): the reader cannot check delivery'
    T1_MARKER = '# ---- T1 ----'

    def __init__(self, reader, fixture, *, play_worlds, invoke='module', fixture_seed=7):
        self.reader, self.fixture, self.invoke = os.path.realpath(reader), os.path.realpath(fixture), invoke
        self.play_worlds = dict(play_worlds)
        src = open(self.fixture).read()
        if self.T1_MARKER not in src:
            raise SystemExit(f'battery: {self.fixture} has no {self.T1_MARKER!r} line to cut its generator at')
        ns = {'__name__': 'battery_fixture', '__file__': self.fixture}
        saved = sys.argv
        sys.argv = [self.fixture, self.reader]
        try:
            exec(compile(src.split(self.T1_MARKER)[0], self.fixture, 'exec'), ns)
        finally:
            sys.argv = saved
        self.rd = ns['rd']
        self._rows = ns['rows']
        self.fixture_seed = fixture_seed
        self._clean = None

    def clean_rows(self):
        if self._clean is None:
            rows = self._rows(effect=0.0, seed=self.fixture_seed)
            rng = random.Random(self.fixture_seed + 1)
            for r in rows:
                r.update(consistent_outcome(rng, r['banker'], r['ex_team']))
            self._clean = rows
        return copy.deepcopy(self._clean)

    def clean_status(self):
        return None

    def abort_status(self):
        return None

    def dump(self, rows):
        return ''.join(json.dumps(r) + '\n' for r in rows).encode()

    def read(self, rows_path, status_path, tmp):
        if self.invoke == 'module':
            return self.rd.analyze(rows_path)
        out = os.path.join(tmp, 'out.json')
        p = subprocess.run([sys.executable, '-B', self.reader, rows_path, out], capture_output=True, text=True)
        if p.returncode != 0:
            text = (p.stderr.strip().splitlines() or p.stdout.strip().splitlines() or [''])[-1]
            raise SystemExit(text if text.startswith('REFUSING') else f'rc {p.returncode}: {text}')
        return json.load(open(out))

    def verdict(self, result):
        return result['bar']['verdict']

    def verdict_detail(self, result):
        return '; '.join(result['bar'].get('reasons') or []) or f"levels {result.get('levels')}"

    # -- fault sites: (denominator, [one-unit mutations])
    def fault_sites(self, rows, arm, kind):
        if kind == 'play_fallback':
            hs = [h for r in rows for h in r['dhist'][arm]]
            return len(hs), [lambda h=h: self._to_fallback(h) for h in hs if h[0] == SEARCH_SCHEMA]
        if kind == 'belief_fallback':
            hs = [h for r in rows for h in r['dhist'][arm] if h[0] == SEARCH_SCHEMA]

            def belief(h):
                h[4], h[7] = 1, 'BeliefNumpyError'
            return len(hs), [lambda h=h: belief(h) for h in hs if h[4] == 0]
        if kind == 'bury_fallback':
            rs_ = [r for r in rows if r['bury_rec'][0] == arm]

            def bury(r):
                b = r['bury_rec']
                r['bury_rec'] = [arm, BURY_FALLBACK_SCHEMA, 'budget', b[3], None, b[5]]
            return len(rs_), [lambda r=r: bury(r) for r in rs_ if r['bury_rec'][1] != BURY_FALLBACK_SCHEMA]
        if kind == 'declare_abandon':
            ds = [d for r in rows for d in r['declare_recs'][arm]]

            def abandon(d):
                d[1], d[2] = 'hard_budget', False
            return len(ds), [lambda d=d: abandon(d) for d in ds if d[2] is True]
        raise ValueError(kind)

    @staticmethod
    def _to_fallback(h):
        h[0] = FALLBACK_SCHEMA
        h[1:8] = [None] * 7
        h[10:] = [None] * (len(h) - 10)

    def wrong_worlds(self, rows, arm):
        h = next(h for h in rows[5]['dhist'][arm] if h[0] == SEARCH_SCHEMA)
        if len(h) < 19:
            return False
        other = [w for a, w in self.play_worlds.items() if a != arm and w != self.play_worlds[arm]]
        h[18] = other[0] if other else self.play_worlds[arm] // 2
        return f'one {arm} search record reports {h[18]} worlds, configured {self.play_worlds[arm]}'

    def incomplete_evaluation(self, rows, arm):
        d = next(d for r in rows for d in r['declare_recs'][arm] if d[2] is True)
        d[4] = 0
        return f'one evaluated {arm} declare with 0 of {d[3]} worlds completed'

    def impossible_score(self, rows):
        r = next(r for r in rows if r['kitty_bonus'] > 0)
        r['attacker_points'] = 0
        return f'seed {r["seed"]} mirror {r["mirror"]}: attacker_points 0 < kitty_bonus {r["kitty_bonus"]}'

    def duplicate_seed(self, rows):
        rows.append(copy.deepcopy(rows[3]))
        return f'seed {rows[3]["seed"]} mirror {rows[3]["mirror"]} twice'

    def missing_seed(self, rows):
        s = rows[len(rows) // 2]['seed']
        rows[:] = [r for r in rows if r['seed'] != s]
        return f'seed {s} (both mirrors) removed'

    # -- the guard oracle: validity.py on the same rows
    def guard(self, rows, tier='DEV'):
        counts, worlds, declares = {}, [], []
        for arm in self.arms:
            hs = [h for r in rows for h in r['dhist'][arm]]
            search = [h for h in hs if h[0] == SEARCH_SCHEMA]
            buries = [r['bury_rec'] for r in rows if r['bury_rec'][0] == arm]
            ds = [d for r in rows for d in r['declare_recs'][arm]]
            counts[arm] = dict(decisions=len(hs), play_fallback=sum(h[0] == FALLBACK_SCHEMA for h in hs), search=len(search),
                               belief_fallback=sum(h[4] == 1 for h in search), buries=len(buries),
                               bury_fallback=sum(b[1] == BURY_FALLBACK_SCHEMA for b in buries), declares=len(ds),
                               declare_abandon=sum(d[2] is False for d in ds))
            worlds += [(arm, 'search' if h[0] == SEARCH_SCHEMA else 'fallback', h[18]) for h in hs if len(h) > 18]
            declares += [dict(arm=arm, evaluated=d[2], worlds=d[3], completed=d[4]) for d in ds]
        req = va.CORE_OUTCOME_FIELDS + ('kitty_points', 'last_trick_winner', 'ex_team', 'ex_levels', 'ex_attacker_points_signed', 'ex_role')
        # an 18-field dhist carries no play worlds: the worlds case itself then FAILS (NOT CHECKABLE); the guard checks the rest
        return [va.arm_fault_ceilings(counts, arms=self.arms, tier=tier)] + \
               ([va.worlds_delivered(worlds, self.play_worlds, tier=tier)] if worlds else []) + [
                va.completion_shape(declares, tier=tier, expected_worlds_by_arm=getattr(self.rd, 'DECLARE_WORLDS', None)),
                va.outcome_consistency(rows, tier=tier, require=req)]

    def header(self, tier):
        return [f'{BATTERY_VERSION}  tier {tier}  ceilings play {100 * va.DEFAULT_CEILINGS["play_fallback"]:g}% / belief '
                f'{100 * va.DEFAULT_CEILINGS["belief_fallback"]:g}% / bury {100 * va.DEFAULT_CEILINGS["bury_fallback"]:g}% / declare '
                f'{100 * va.DEFAULT_CEILINGS["declare_abandon"]:g}% on every arm; play worlds {self.play_worlds}',
                f'reader   {self.reader}  sha256 {sha256_file(self.reader)}  (invoke {self.invoke})',
                f'fixture  {self.fixture}  sha256 {sha256_file(self.fixture)}  (generator above {self.T1_MARKER!r}, seed {self.fixture_seed}, '
                f'engine-consistent outcomes)',
                f'battery  {os.path.realpath(__file__)}  sha256 {sha256_file(os.path.realpath(__file__))}',
                f'validity {os.path.join(HERE, "validity.py")}  sha256 {sha256_file(os.path.join(HERE, "validity.py"))}']


def clean_status_text(lane, terminal):
    """A launcher-shaped status ending in its terminal line (reader_testkit.status_text), for adapters whose reader takes the status."""
    import reader_testkit
    return reader_testkit.status_text(lane, terminal)


def abort_status_text(lane):
    """The armed line, then an ABORT line and no LANE DONE: the form a failed launcher leaves."""
    return (f'{TS0} {lane} armed (pid 4242, launcher sha256 {"0" * 64})\n'
            f'{TS0} ABORT: {lane} run group 4242 exited rc 1; no LANE DONE\n')


def _parse_worlds(text):
    out = {}
    for part in text.split(','):
        k, v = part.split('=')
        out[k.strip()] = int(v)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='family', required=True)
    d = sub.add_parser('duel', help='the exploit-duel family (duel.jsonl)')
    d.add_argument('--reader', required=True)
    d.add_argument('--fixture', required=True)
    d.add_argument('--play-worlds', default='ex=256,r45=64')
    d.add_argument('--invoke', choices=('module', 'argv'), default='module')
    d.add_argument('--tier', choices=va.TIERS, default='DEV')
    d.add_argument('--out')
    a = ap.parse_args(argv)
    adapter = DuelAdapter(a.reader, a.fixture, play_worlds=_parse_worlds(a.play_worlds), invoke=a.invoke)
    header = adapter.header(a.tier)      # hashed before the run, so the shas are those of the code that ran
    results = run_battery(adapter, tier=a.tier)
    text, ok = format_table(results, header)
    sys.stdout.write(text)
    if a.out:
        with open(a.out, 'x') as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
