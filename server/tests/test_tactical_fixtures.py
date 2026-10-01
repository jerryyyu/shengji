"""Tactical regression fixtures (tests/tactical/, #677 strategy 4, #676) against
the REAL served bot: `pv_env_recipe` -> `pv_registry_entries` -> `decide_play`
on the production package.

Diagnostic, not a gate.  Fixtures whose ``current_bot`` is recorded as "fail"
for the production bot are ``xfail(strict=False)``: the suite stays green while
``-rxX`` lists every fixture's outcome, and a fixture that starts passing shows
up as XPASS.  The package-free tests prove the fixture set itself: it loads,
every position rebuilds from the public view alone, the categories are
populated, and the predicates judge the OBSERVED actions as intended.

Needs ``SHENGJI_PV_CKPT`` + ``SHENGJI_PV_SHA256`` (a local copy of the served
package) for the bot tests; the other ``SHENGJI_PV_*`` knobs default to the
production recipe (`tactical.PRODUCTION_PLAY_ENV`) and may be overridden.
``TACTICAL_SEED`` picks the bot seed (default 0); ``TACTICAL_REPORT`` names the
report file (default: a pytest temp dir, path printed at the end).
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from shengji.engine.cards import total_points
from shengji.eval import tactical as T

FIXTURES = T.load_fixtures()
SEED = int(os.environ.get("TACTICAL_SEED", "0"))
REPORT: list = []
BOT_NAME: list = []


def _environ():
    ckpt, sha = os.environ.get("SHENGJI_PV_CKPT"), os.environ.get("SHENGJI_PV_SHA256")
    if not ckpt or not sha:
        return None
    if not Path(ckpt).is_file():
        return None
    env = T.production_environ(ckpt, sha)
    for key, value in os.environ.items():
        if key.startswith("SHENGJI_PV_"):
            env[key] = value
    return env


@pytest.fixture(scope="module")
def environ():
    env = _environ()
    if env is None:
        pytest.skip("SHENGJI_PV_CKPT/SHENGJI_PV_SHA256 not set to a local served package; "
                    "tactical fixtures need the real pv-search bot")
    name, _ = T.bot_from_environ(env, seed=SEED)
    BOT_NAME.append(name)
    return env


@pytest.fixture(scope="module", autouse=True)
def _report(request, tmp_path_factory):
    yield
    if not REPORT:
        return
    name = BOT_NAME[0] if BOT_NAME else None
    table = T.format_table(REPORT, name)
    target = os.environ.get("TACTICAL_REPORT")
    path = Path(target) if target else tmp_path_factory.mktemp("tactical") / "report.txt"
    path.write_text(table + "\n")
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"tactical fixtures: report written to {path}")
        for line in table.splitlines()[-2:]:
            reporter.write_line("tactical fixtures: " + line)


# ------------------------------------------------- the set itself (no package)

def test_set_is_populated_per_category():
    assert len(FIXTURES) >= 8
    per = Counter(fx.category for fx in FIXTURES)
    assert set(per) == set(T.CATEGORIES), per
    assert all(n >= 2 for n in per.values()), per


@pytest.mark.parametrize("fx", FIXTURES, ids=[fx.id for fx in FIXTURES])
def test_fixture_rebuilds_from_the_public_view(fx):
    """Only the acting seat's hand (and its own burial as banker) is stored; the
    position replays to the seat's turn with that hand, and the hidden cards are
    placeholders that change with the fill seed while the public state does not."""
    assert fx.setup.get("buried") is None or fx.seat == fx.setup["banker"]
    a, b = T.public_round(fx, 0), T.public_round(fx, 1)
    for rnd in (a, b):
        assert rnd.phase == "play" and rnd.turn == fx.seat
        assert sorted(rnd.hands[fx.seat]) == sorted(fx.hand)
        assert len(rnd.history) == fx.trick and len(rnd.trick.plays) == fx.position
        assert fx.observed["action"] and set(fx.observed["action"]) <= set(fx.hand)
    assert [p.cards for p in a.trick.plays] == [p.cards for p in b.trick.plays]
    assert [t.winner for t in a.history] == [t.winner for t in b.history]
    hidden_a = [sorted(a.hands[s]) for s in range(4) if s != fx.seat]
    hidden_b = [sorted(b.hands[s]) for s in range(4) if s != fx.seat]
    assert [len(h) for h in hidden_a] == [len(h) for h in hidden_b]
    assert hidden_a != hidden_b, "two fill seeds produced the same hidden hands"


def _context(fx, action, worlds=(), record=None):
    rnd = T.public_round(fx)
    return T.Context(rnd=rnd, seat=fx.seat, action=list(action), record=record,
                     worlds=list(worlds), fixture=fx)


@pytest.mark.parametrize("fx", [fx for fx in FIXTURES if fx.predicate ==
                                "no_point_donation_when_zero_point_alternative_exists"],
                         ids=lambda fx: fx.id)
def test_point_donation_predicate_judges_the_observed_action(fx):
    ctx = _context(fx, fx.observed["action"])
    ok, detail = T.PREDICATES[fx.predicate](ctx, **fx.args)
    assert not ok, detail
    zero = next(a for a in T._legal_actions(ctx) if total_points(a) == 0)
    ok, detail = T.PREDICATES[fx.predicate](_context(fx, zero), **fx.args)
    assert ok, detail


@pytest.mark.parametrize("fx", [fx for fx in FIXTURES if fx.predicate ==
                                "wins_point_trick_when_available"], ids=lambda fx: fx.id)
def test_missed_win_predicate_judges_the_observed_action(fx):
    ctx = _context(fx, fx.observed["action"])
    ok, detail = T.PREDICATES[fx.predicate](ctx, **fx.args)
    assert not ok, detail
    table = [(p.seat, p.cards) for p in ctx.rnd.trick.plays]
    winner = next(a for a in T._legal_actions(ctx)
                  if T._same_team(T._trick_winner(table + [(fx.seat, a)], ctx.rnd.ordering), fx.seat))
    ok, detail = T.PREDICATES[fx.predicate](_context(fx, winner), **fx.args)
    assert ok, detail


@pytest.mark.parametrize("fx", [fx for fx in FIXTURES if fx.predicate ==
                                "not_a_throw_refuted_by_public_refusal"], ids=lambda fx: fx.id)
def test_refusal_predicate_reads_the_public_history(fx):
    """The refusal arguments are derivable from the stored public plays; a
    single-component lead always passes; the observed throw is judged by whether
    the refuted component is still refuted (a beating card played since voids it)."""
    assert T.refusal_args(fx.plays, fx.seat, T.public_round(fx).ordering) == fx.args
    ctx = _context(fx, fx.observed["action"])
    ok, detail = T.PREDICATES[fx.predicate](ctx, **fx.args)
    assert ok == (fx.current_bot == "pass"), detail
    single = [fx.observed["action"][0]]
    ok, detail = T.PREDICATES[fx.predicate](_context(fx, single), **fx.args)
    assert ok, detail


@pytest.mark.parametrize("fx", [fx for fx in FIXTURES if fx.predicate == "not_a_doomed_throw"],
                         ids=lambda fx: fx.id)
def test_doomed_throw_predicate_counts_refusing_worlds(fx):
    """Judged on the worlds handed in: worlds where no other seat holds the led
    suit cannot refuse the throw (pass); worlds that put every unseen card of the
    suit in one hand refuse it when that hand can beat a component (the fixtures'
    observed throws all were refused in the real deal)."""
    rnd = T.public_round(fx)
    o = rnd.ordering
    action = fx.observed["action"]
    suit = o.eff_suit(action[0])
    hands, buried = T.placeholder_hands(fx, 0)
    # the start-of-play placeholder minus what each seat has played = current placeholder hands
    current = [list(rnd.hands[s]) for s in range(4)]
    off_suit = [[c for c in current[s] if o.eff_suit(c) != suit] if s != fx.seat else current[s]
                for s in range(4)]
    ok, detail = T.not_a_doomed_throw(_context(fx, action, worlds=[(off_suit, buried)] * 4))
    assert ok, detail
    in_suit = sorted(c for s in range(4) if s != fx.seat for c in current[s] if o.eff_suit(c) == suit)
    one_hand = [list(h) for h in off_suit]
    other = next(s for s in range(4) if s != fx.seat)
    one_hand[other] = one_hand[other] + in_suit
    ok, detail = T.not_a_doomed_throw(_context(fx, action, worlds=[(one_hand, buried)] * 4))
    assert "refused in" in detail
    ok, detail = T.not_a_doomed_throw(_context(fx, action, worlds=[]))
    assert not ok


def test_crowded_ballot_predicate_reads_the_admitted_list():
    fx = next(fx for fx in FIXTURES if fx.predicate == "admitted_ballot_not_crowded")
    record = {"work_complete": True, "admitted": fx.observed["admitted"]}
    ok, detail = T.admitted_ballot_not_crowded(_context(fx, fx.observed["action"], record=record),
                                               **fx.args)
    assert not ok and "7/8" in detail, detail
    record = {"work_complete": True, "admitted": fx.observed["admitted"][:4]}
    ok, _ = T.admitted_ballot_not_crowded(_context(fx, fx.observed["action"], record=record), **fx.args)
    assert ok


# ------------------------------------------------------------ the served bot

def test_the_env_builds_the_production_bot(environ):
    name, bot = T.bot_from_environ(environ, seed=SEED)
    from shengji.train import pv_search_policy as pv
    assert isinstance(bot, pv.PVSearchBot) and bot.policy_name == name
    if environ["SHENGJI_PV_SHA256"].startswith("491ee4bf") and not any(
            k.startswith("SHENGJI_PV_") for k in os.environ if k not in ("SHENGJI_PV_CKPT", "SHENGJI_PV_SHA256")):
        assert name == T.PRODUCTION_BOT


def test_decision_is_invariant_to_the_placeholder_fill(environ):
    """The hidden placeholder never reaches the search: a fresh bot (same seed)
    plays the same cards, admits the same ballot and prices it identically on
    two different fills."""
    fx = next(fx for fx in FIXTURES if fx.category == "doomed-throw")
    seen = []
    for fill in (0, 1):
        _, bot = T.bot_from_environ(environ, seed=SEED)
        res = T.run_fixture(bot, fx, fill_seed=fill)
        assert res.error is None, res.detail
        seen.append((res.action, res.record["admitted"], res.record["value_means"]))
    assert seen[0] == seen[1]


def _params():
    for fx in FIXTURES:
        marks = []
        if fx.current_bot == "fail":
            marks.append(pytest.mark.xfail(strict=False,
                                           reason=f"{fx.category}: recorded FAIL for {T.PRODUCTION_BOT}"))
        yield pytest.param(fx, id=fx.id, marks=marks)


@pytest.mark.parametrize("fx", list(_params()))
def test_fixture(environ, fx, record_property):
    _, bot = T.bot_from_environ(environ, seed=SEED)
    res = T.run_fixture(bot, fx)
    REPORT.append(res)
    record_property("tactical", f"{res.status} {'+'.join(res.action or [])} {res.detail}")
    assert res.error is None, f"{fx.id}: {res.error}: {res.detail}"
    assert res.passed, (f"{fx.id} [{fx.category}] played {'+'.join(res.action)} "
                        f"(observed {'+'.join(fx.observed['action'])}): {res.detail}")
