"""Outcome-validity guards for DEV and screen readers.  Standard library only (Python 3.9+).

A reader calls these BEFORE it computes any outcome (mean, CI, verdict), on every arm, and lets an invalid result replace
its verdict:

    import validity as va
    checks = [
        va.arm_fault_ceilings(per_arm_counts, arms=('ex', 'r45'), tier='DEV'),           # the SAME ceilings on every arm
        va.worlds_delivered(search_records, {'ex': 256, 'r45': 64}, tier='DEV'),
        va.completion_shape(declare_records, tier='DEV'),
        va.outcome_consistency(rows, tier='DEV'),
    ]
    v = va.combine(checks, tier='DEV')
    if v['verdict'] != va.VALID:
        verdict = v['verdict']            # 'DEV_INVALID' / 'SCREEN_INVALID'; v['reasons'] names each arm and check
    else:
        ...                                # only now compute the outcome

Every function returns dict(check=<name>, verdict='VALID' | '<TIER>_INVALID', reasons=[...], detail={...}).  There is no
silent pass: a missing arm, a missing field, a wrong type (True is not 1), an empty denominator and an unknown status are each
a named reason.  A malformed CALL (unknown tier, a ceiling outside [0, 1)) raises ValidityUsageError, a programming error in
the reader, not a property of the data.

Four DEV readers failed open on this class of defect: the validity bar applied only to the exploiter (61,200 of 61,200
defender fallbacks read OPEN_LANE), an evaluated declaration with incomplete worlds, no worlds-delivered check, and an
impossible row (attacker_points < kitty_bonus) read DEV_PASS.  adversarial_battery.py beside this file exercises a reader
against all of them.
"""
from fractions import Fraction

__all__ = ['VALID', 'TIERS', 'DEFAULT_CEILINGS', 'DENOMINATORS', 'ValidityUsageError', 'arm_fault_ceilings', 'worlds_delivered',
           'completion_shape', 'outcome_consistency', 'engine_level_outcome', 'combine', 'invalid_verdict',
           'TOTAL_POINTS', 'KITTY_MAX_POINTS', 'HAND_SIZE', 'KITTY_MULTIPLIER', 'CORE_OUTCOME_FIELDS']

VALID = 'VALID'
TIERS = ('DEV', 'SCREEN')

#: fault kind -> the largest allowed share of its denominator (fault count <= share x denominator, exact rational arithmetic)
DEFAULT_CEILINGS = dict(play_fallback=0.001, belief_fallback=0.01, bury_fallback=0.01, declare_abandon=0.01)
#: fault kind -> the count it is a share of
DENOMINATORS = dict(play_fallback='decisions', belief_fallback='search', bury_fallback='buries', declare_abandon='declares')

#: engine constants (server/shengji/engine: cards.make_deck is two decks, 200 card points; round.KITTY_SIZE 8 cards, HAND_SIZE 25,
#: KITTY_MULTIPLIER 2 x the final play's card count).  tests/test_validity.py checks them against the engine.
TOTAL_POINTS = 200
KITTY_MAX_POINTS = 80
HAND_SIZE = 25
KITTY_MULTIPLIER = 2
CORE_OUTCOME_FIELDS = ('banker', 'attacker_points', 'kitty_bonus', 'winner_team', 'level_change')
#: optional fields: checked whenever present in a row, and a reader names them in `require` when its producer writes them
OPTIONAL_OUTCOME_FIELDS = ('kitty_points', 'last_trick_winner', 'ex_team', 'ex_levels', 'ex_attacker_points_signed', 'ex_role')


class ValidityUsageError(TypeError):
    """The reader called a guard wrongly (a programming error, raised rather than reported)."""


def invalid_verdict(tier):
    if tier not in TIERS:
        raise ValidityUsageError(f'validity: tier must be one of {TIERS}, got {tier!r}')
    return f'{tier}_INVALID'


def _result(check, tier, reasons, detail, max_reasons=20):
    bad = invalid_verdict(tier)
    shown = list(reasons[:max_reasons])
    if len(reasons) > max_reasons:
        shown.append(f'... and {len(reasons) - max_reasons} more')
    return dict(check=check, verdict=bad if reasons else VALID, reasons=shown, n_reasons=len(reasons), detail=detail)


def _is_int(v):
    return type(v) is int


def _share(c, kind):
    if isinstance(c, bool) or not isinstance(c, (int, float, Fraction)) or not (0 <= c < 1):
        raise ValidityUsageError(f'validity: ceiling {kind} must be a number in [0, 1), got {c!r}')
    return Fraction(str(c)) if isinstance(c, float) else Fraction(c)


def arm_fault_ceilings(per_arm_counts, ceilings=None, *, arms, tier='DEV'):
    """The SAME fault ceilings applied to EVERY arm.

    per_arm_counts: {arm: {count name: int}} with, for each fault kind in `ceilings`, the fault count (the kind's name) and its
        denominator (DENOMINATORS[kind]): decisions / play_fallback, search / belief_fallback, buries / bury_fallback,
        declares / declare_abandon.
    ceilings: {kind: share}, default DEFAULT_CEILINGS.  A kind set to None is explicitly not applicable to this lane (listed in
        detail['not_applicable']); a kind cannot be dropped for one arm only, because there is one ceilings mapping for all.
    arms: the arm names the lane ran (from the launcher's config, never from the counts).  The counts must name exactly these
        arms, so a reader that passes only one arm's counts gets INVALID, not a pass.
    INVALID reasons: an arm missing or unexpected, a count missing or not an int (bool refused), a negative count, a fault count
    above its denominator, an empty denominator, and a fault count above share x denominator (named by arm and kind)."""
    ceilings = dict(DEFAULT_CEILINGS if ceilings is None else ceilings)
    unknown = sorted(set(ceilings) - set(DENOMINATORS))
    if unknown:
        raise ValidityUsageError(f'validity: unknown fault kinds {unknown} (known: {sorted(DENOMINATORS)})')
    shares = {k: _share(c, k) for k, c in ceilings.items() if c is not None}
    arms = tuple(arms)
    if not arms or len(set(arms)) != len(arms):
        raise ValidityUsageError(f'validity: arms must be a non-empty list of distinct names, got {arms!r}')
    reasons, table = [], {}
    if not isinstance(per_arm_counts, dict):
        return _result('arm_fault_ceilings', tier, [f'per-arm counts are a {type(per_arm_counts).__name__}, not a mapping'], {})
    for a in sorted(set(per_arm_counts) - set(arms), key=repr):
        reasons.append(f'arm {a!r}: counts for an arm the lane did not run')
    for arm in arms:
        counts = per_arm_counts.get(arm)
        if not isinstance(counts, dict):
            reasons.append(f'arm {arm!r}: no fault counts (every arm is checked; a guard on one arm only is the defect this catches)')
            continue
        for kind, share in shares.items():
            den_name = DENOMINATORS[kind]
            n, d = counts.get(kind), counts.get(den_name)
            if not _is_int(n) or not _is_int(d):
                reasons.append(f'arm {arm!r} {kind}: counts {kind}={n!r} {den_name}={d!r} are not both ints')
                continue
            if n < 0 or d < 0 or n > d:
                reasons.append(f'arm {arm!r} {kind}: {n} of {d} {den_name} is not a count (negative, or above its denominator)')
                continue
            if d == 0:
                reasons.append(f'arm {arm!r} {kind}: 0 {den_name} (an empty denominator never qualifies; set the kind to None if '
                               f'the lane has none by design)')
                continue
            limit = share * d
            table[(arm, kind)] = (n, d, float(share))
            if n > limit:
                reasons.append(f'arm {arm!r} {kind}: {n} of {d} {den_name} ({100 * n / d:.3f}%) > ceiling {100 * float(share):g}% '
                               f'(at most {int(limit)} allowed)')
    detail = dict(arms=list(arms), ceilings={k: float(v) for k, v in shares.items()},
                  not_applicable=sorted(k for k, c in ceilings.items() if c is None),
                  counts={f'{a}/{k}': list(v) for (a, k), v in sorted(table.items())})
    return _result('arm_fault_ceilings', tier, reasons, detail)


SEARCH, FALLBACK = 'search', 'fallback'


def worlds_delivered(records, expected_by_arm, *, tier='DEV'):
    """Every successful search record reports its arm's configured world count.

    records: an iterable of (arm, status, worlds) or (where, arm, status, worlds); status 'search' (a successful search record,
        whose worlds must be exactly expected_by_arm[arm], an int) or 'fallback' (no search ran; worlds must be None).
    expected_by_arm: {arm: configured worlds}, from the arm's recipe pin.  Every arm must have at least one search record: an arm
        with none has not shown that it got its compute.
    INVALID reasons: a malformed record, an unknown arm or status, a search record with any other world count (a string '256' is
    not 256), a fallback carrying worlds, an arm with no search record."""
    if not isinstance(expected_by_arm, dict) or not expected_by_arm or not all(_is_int(w) and w >= 1 for w in expected_by_arm.values()):
        raise ValidityUsageError(f'validity: expected_by_arm must map each arm to a positive int, got {expected_by_arm!r}')
    reasons, n = [], 0
    searched = {a: 0 for a in expected_by_arm}
    wrong = {a: 0 for a in expected_by_arm}
    for rec in records:
        n += 1
        if isinstance(rec, (list, tuple)) and len(rec) == 4:
            where, arm, status, worlds = rec
        elif isinstance(rec, (list, tuple)) and len(rec) == 3:
            (arm, status, worlds), where = rec, n - 1
        else:
            reasons.append(f'record {n - 1}: malformed {rec!r:.80}')
            continue
        if arm not in expected_by_arm:
            reasons.append(f'record {where!r}: unknown arm {arm!r}')
        elif status == SEARCH:
            searched[arm] += 1
            if not (_is_int(worlds) and worlds == expected_by_arm[arm]):
                wrong[arm] += 1
                if wrong[arm] <= 3:
                    reasons.append(f'arm {arm!r} record {where!r}: a search record reports {worlds!r} worlds, configured {expected_by_arm[arm]}')
        elif status == FALLBACK:
            if worlds is not None:
                reasons.append(f'arm {arm!r} record {where!r}: a fallback record carries worlds {worlds!r}')
        else:
            reasons.append(f'record {where!r}: unknown status {status!r} (search / fallback)')
    for arm, k in wrong.items():
        if k > 3:
            reasons.append(f'arm {arm!r}: {k} search records off {expected_by_arm[arm]} worlds in all')
    for arm, k in searched.items():
        if k == 0:
            reasons.append(f'arm {arm!r}: no successful search record (delivery of {expected_by_arm[arm]} worlds unproven)')
    return _result('worlds_delivered', tier, reasons, dict(records=n, search=searched, off_worlds=wrong, expected=dict(expected_by_arm)))


def completion_shape(declare_records, *, tier='DEV', expected_worlds_by_arm=None):
    """evaluated => completed == worlds; abandoned => 0 <= completed <= worlds (inclusive: OptionalStage.publish's final hard check can
    fail after the last world completed).

    declare_records: an iterable of dicts with keys evaluated (bool), worlds (int >= 1), completed (int), and optionally arm and
        where.  expected_worlds_by_arm: {arm: worlds} to also pin the configured count per arm (records then need `arm`).
    INVALID reasons: a field missing or of the wrong type (evaluated must be a bool, not 1 or 'true'), an evaluated record short of
    (or above) its worlds, an abandoned one outside 0..worlds, a world count other than the arm's."""
    reasons, n, ev, ab = [], 0, 0, 0
    for rec in declare_records:
        where = rec.get('where', n) if isinstance(rec, dict) else n
        n += 1
        if not isinstance(rec, dict):
            reasons.append(f'declare record {where!r}: not a mapping')
            continue
        e, w, c = rec.get('evaluated'), rec.get('worlds'), rec.get('completed')
        if type(e) is not bool or not _is_int(w) or w < 1 or not _is_int(c):
            reasons.append(f'declare record {where!r}: evaluated={e!r} worlds={w!r} completed={c!r} (bool, int >= 1, int)')
            continue
        if expected_worlds_by_arm is not None:
            arm = rec.get('arm')
            if arm not in expected_worlds_by_arm:
                reasons.append(f'declare record {where!r}: unknown arm {arm!r}')
            elif w != expected_worlds_by_arm[arm]:
                reasons.append(f'declare record {where!r} arm {arm!r}: {w} worlds, configured {expected_worlds_by_arm[arm]}')
        if e:
            ev += 1
            if c != w:
                reasons.append(f'declare record {where!r}: evaluated with {c} of {w} worlds completed (evaluated needs all)')
        else:
            ab += 1
            if not 0 <= c <= w:
                reasons.append(f'declare record {where!r}: abandoned with {c} of {w} worlds completed (outside 0..{w})')
    return _result('completion_shape', tier, reasons, dict(records=n, evaluated=ev, abandoned=ab))


def engine_level_outcome(attacker_points, banker):
    """(winner_team, level_change) by Game.finish_round (server/shengji/engine/game.py): attacker_points (which already include the
    kitty bonus) >= 80 -> the attacking team wins with gain (p - 80) // 40, which is 0 for 80..119; below 80 the banker's team wins
    3 at 0, 2 below 40, else 1.  The level cap at A changes new_levels, never level_change."""
    banker_team = banker % 2
    if attacker_points >= 80:
        return 1 - banker_team, (attacker_points - 80) // 40
    return banker_team, (3 if attacker_points == 0 else (2 if attacker_points < 40 else 1))


def _rows_with_where(rows):
    for i, item in enumerate(rows):
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], dict):
            yield item
        else:
            yield i, item


def outcome_consistency(rows, *, tier='DEV', require=CORE_OUTCOME_FIELDS):
    """Per-row invariants of an engine round result, from the engine's rule.

    rows: an iterable of row dicts, or (where, row) pairs.  require: the fields every row must carry (CORE_OUTCOME_FIELDS by default;
        add the OPTIONAL_OUTCOME_FIELDS the producer writes).  Optional fields present in a row are checked too.
    Invariants: banker / last_trick_winner seats in 0..3, winner_team / ex_team in {0, 1}; attacker_points and kitty_bonus ints >= 0,
    multiples of 5; attacker_points >= kitty_bonus (the engine's total includes the bonus); trick points (attacker_points - kitty_bonus)
    <= TOTAL_POINTS - kitty_points; kitty_points 0..KITTY_MAX_POINTS; a bonus only when the attacking team took the last trick with a
    non-empty kitty, then kitty_points x 2 x n for some final-play size n in 1..HAND_SIZE, and always a bonus in that case;
    (winner_team, level_change) = engine_level_outcome(attacker_points, banker); ex_levels = +-level_change by whether winner_team is
    ex_team; ex_attacker_points_signed = +-attacker_points by whether ex_team attacks; ex_role 'banker' / 'attacker' by banker % 2."""
    require = tuple(require)
    unknown = sorted(set(require) - set(CORE_OUTCOME_FIELDS) - set(OPTIONAL_OUTCOME_FIELDS))
    if unknown:
        raise ValidityUsageError(f'validity: outcome_consistency cannot check fields {unknown}')
    reasons, n, bad_rows = [], 0, 0
    for where, r in _rows_with_where(rows):
        n += 1
        why = _row_reasons(r, require)
        if why:
            bad_rows += 1
            if bad_rows <= 5:
                reasons.append(f'row {where!r}: ' + '; '.join(why))
    if bad_rows > 5:
        reasons.append(f'{bad_rows} of {n} rows inconsistent in all')
    if n == 0:
        reasons.append('no rows (an empty denominator never qualifies)')
    return _result('outcome_consistency', tier, reasons, dict(rows=n, inconsistent=bad_rows, required=list(require)))


def _row_reasons(r, require):
    if not isinstance(r, dict):
        return [f'not a mapping ({type(r).__name__})']
    why = [f'{f} missing' for f in require if f not in r]
    if why:
        return why
    g = r.get
    ints = [f for f in CORE_OUTCOME_FIELDS + OPTIONAL_OUTCOME_FIELDS[:-1] if f in r and not _is_int(r[f])]
    if ints:
        return [f'{f}={r[f]!r} is not an int' for f in ints]
    seat = lambda f: f not in r or 0 <= r[f] <= 3
    team = lambda f: f not in r or r[f] in (0, 1)
    if not (seat('banker') and seat('last_trick_winner') and team('winner_team') and team('ex_team')):
        return [f'seat / team out of range (banker {g("banker")!r}, last_trick_winner {g("last_trick_winner")!r}, '
                f'winner_team {g("winner_team")!r}, ex_team {g("ex_team")!r})']
    ap, kb = g('attacker_points'), g('kitty_bonus')
    if ap is None or kb is None:
        return why    # the reader did not require the points: nothing further is decidable
    if ap < 0 or kb < 0 or ap % 5 or kb % 5:
        why.append(f'attacker_points {ap} / kitty_bonus {kb} not non-negative multiples of 5')
    if ap < kb:
        why.append(f'attacker_points {ap} < kitty_bonus {kb} (the engine total includes the bonus)')
    kp = g('kitty_points')
    if kp is not None:
        if not (0 <= kp <= KITTY_MAX_POINTS and kp % 5 == 0):
            why.append(f'kitty_points {kp} outside 0..{KITTY_MAX_POINTS} in steps of 5')
        elif ap - kb > TOTAL_POINTS - kp:
            why.append(f'trick points {ap - kb} > {TOTAL_POINTS} - kitty {kp}')
    if 'banker' in r:
        attackers_last = None if 'last_trick_winner' not in r else (r['last_trick_winner'] % 2 != r['banker'] % 2)
        if kb:
            if attackers_last is False:
                why.append(f'kitty bonus {kb} with the banker team on the last trick')
            if kp is not None and (kp == 0 or kb % (KITTY_MULTIPLIER * kp) or kb // (KITTY_MULTIPLIER * kp) > HAND_SIZE):
                why.append(f'kitty bonus {kb} is not kitty_points {kp} x {KITTY_MULTIPLIER} x a final play of 1..{HAND_SIZE} cards')
        elif attackers_last and kp:
            why.append(f'no kitty bonus although the attackers took the last trick over a {kp}-point kitty')
        if not why and 'winner_team' in r and 'level_change' in r:
            want = engine_level_outcome(ap, r['banker'])
            if (r['winner_team'], r['level_change']) != want:
                why.append(f'(winner_team, level_change) {(r["winner_team"], r["level_change"])} but {ap} attacker points with banker '
                           f'{r["banker"]} give {want} by the engine rule')
        if 'ex_team' in r:
            ex_attacks = r['ex_team'] != r['banker'] % 2
            if 'ex_role' in r and r['ex_role'] != ('attacker' if ex_attacks else 'banker'):
                why.append(f'ex_role {r["ex_role"]!r} disagrees with banker {r["banker"]} and ex_team {r["ex_team"]}')
            if 'ex_attacker_points_signed' in r and r['ex_attacker_points_signed'] != (ap if ex_attacks else -ap):
                why.append(f'ex_attacker_points_signed {r["ex_attacker_points_signed"]} is not {"+" if ex_attacks else "-"}{ap}')
            if 'ex_levels' in r and 'winner_team' in r and 'level_change' in r:
                lc = r['level_change']
                if r['ex_levels'] != (lc if r['winner_team'] == r['ex_team'] else -lc):
                    why.append(f'ex_levels {r["ex_levels"]} is not +-level_change {lc} by winner_team {r["winner_team"]}')
    return why


def combine(results, *, tier='DEV'):
    """One verdict over several guard results: VALID only when every one is VALID and there is at least one.  The reasons are prefixed
    with their check's name.  A result of another tier, or not a guard result, is itself a reason."""
    bad = invalid_verdict(tier)
    reasons, names = [], []
    results = list(results)
    if not results:
        reasons.append('combine: no checks were run')
    for r in results:
        if not isinstance(r, dict) or r.get('verdict') not in (VALID, bad) or 'check' not in r:
            reasons.append(f'combine: {r!r:.80} is not a {tier} guard result')
            continue
        names.append(r['check'])
        reasons += [f'{r["check"]}: {x}' for x in r['reasons']]
    return dict(check='combine', verdict=bad if reasons else VALID, reasons=reasons, checks=names)
