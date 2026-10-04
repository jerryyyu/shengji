import copy
import random
from types import SimpleNamespace
from pathlib import Path

import pytest

from shengji.eval import tactical
from shengji.eval.public_refusal_history import (
    public_root_with_ledger, public_root_with_observation_schedule,
)


@pytest.fixture(scope="module")
def fixtures():
    return tactical.load_fixtures(Path(__file__).parent / "tactical/public_observations.jsonl")


@pytest.mark.parametrize("fixture_id,fresh,primed", [
    ("pvr8-c1-m0-p23-pair-preservation", 0, 1),
    ("pvr8-c2-m0-p62-joker-control", 0, 10),
    ("pvr8-c3-m0-p47-ace-control", 1, 5),
    ("pvr8-c2-m0-p43-partner-overtake-control", 1, 6),
])
@pytest.mark.parametrize("fill_seed", [0, 1])
def test_explicit_modes_preserve_root_and_reproduce_actor_ledger_census(
        fixtures, fixture_id, fresh, primed, fill_seed):
    fixture = next(fx for fx in fixtures if fx.id == fixture_id)
    before = copy.deepcopy(fixture.to_json())
    root, ledger, receipt = public_root_with_ledger(fixture, mode="fresh-root", fill_seed=fill_seed)
    primed_root, primed_ledger, primed_receipt = public_root_with_ledger(
        fixture, mode="history-primed", fill_seed=fill_seed)
    assert len(receipt["retained_refusals"]) == fresh
    assert len(primed_receipt["retained_refusals"]) == primed
    assert len(ledger.observe(root)) == fresh
    # The returned root's exact deck key must not reset the reconstructed ledger.
    assert len(primed_ledger.observe(primed_root)) == primed
    assert primed_ledger.key == tuple(primed_root.deck)
    assert root.hands == primed_root.hands and root.history == primed_root.history
    assert root.trick == primed_root.trick and root.notice == primed_root.notice
    assert fixture.to_json() == before
    assert receipt["actor_turn_observations"] == 1
    assert primed_receipt["actor_turn_observations"] > 1
    assert primed_receipt["hidden_hands_are_placeholders"]
    assert not primed_receipt["live_rng_state_reconstructed"]
    assert not primed_receipt["provenance_verified"]


@pytest.mark.parametrize("mode", [None, "auto", "", True])
def test_no_implicit_mode(fixtures, mode):
    with pytest.raises(ValueError):
        public_root_with_ledger(fixtures[0], mode=mode)


def test_mode_cannot_be_omitted(fixtures):
    with pytest.raises(TypeError):
        public_root_with_ledger(fixtures[0])


def test_replay_drift_refused(fixtures, monkeypatch):
    original = tactical.round_from_setup
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        root = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            root.attacker_points += 1
        return root
    monkeypatch.setattr(tactical, "round_from_setup", changed)
    with pytest.raises(ValueError, match="differs"):
        public_root_with_ledger(fixtures[0], mode="history-primed")


def _synthetic_sampler_bot(monkeypatch, *, worlds=2, seed=17,
                           refusal_constraints=True):
    from shengji.ai.mcbot import MCBot
    from shengji.ai.refusal import RefusalLedger
    from shengji.train.pv_search_policy import PVSearchBot

    sampler = object.__new__(MCBot)
    sampler.seed = seed
    sampler.rng = random.Random(seed)
    config = SimpleNamespace(
        worlds=worlds, refusal_constraints=refusal_constraints,
        checkpoint_sha256="a" * 64)
    bot = object.__new__(PVSearchBot)
    bot.config = config
    bot.worlds = worlds
    bot.seed = seed
    bot.sampler = sampler
    bot.refusal_constraints = refusal_constraints
    bot.checkpoint_sha256 = "a" * 64
    bot._refusals = RefusalLedger()
    bot._last_sampling = {}
    return bot


def _patch_synthetic_public_root(monkeypatch, mode_seen, ledger):
    from shengji.eval import public_refusal_tape as module
    root = SimpleNamespace(deck=["D2", "H2"])

    def build(fixture, *, mode, fill_seed=0):
        mode_seen.append((mode, fill_seed))
        ledger.key = tuple(root.deck)
        return root, ledger, {
            "schema": "public-refusal-ledger-v1", "fixture_id": fixture.id,
            "mode": mode, "fill_seed": fill_seed,
            "retained_refusals": [], "hidden_hands_are_placeholders": True,
            "live_rng_state_reconstructed": False, "provenance_verified": False,
        }

    monkeypatch.setattr(module, "public_root_with_ledger", build)
    return root


@pytest.mark.parametrize("mode", ["fresh-root", "history-primed"])
def test_public_refusal_tape_dispatches_explicit_mode_and_binds_same_ledger(
        monkeypatch, mode):
    from shengji.ai.refusal import RefusalLedger
    from shengji.eval.public_refusal_tape import sample_public_refusal_tape
    from shengji.train.pv_search_policy import PVSearchBot

    mode_seen, ledger, calls = [], RefusalLedger(), []
    root = _patch_synthetic_public_root(monkeypatch, mode_seen, ledger)
    bot = _synthetic_sampler_bot(monkeypatch)
    fixture = SimpleNamespace(id="synthetic", seat=1)

    def worlds(self, rnd, seat, check_budget=None):
        calls.append((rnd, seat, self._refusals, check_budget))
        self._last_sampling = {"refusal_observations": 2, "refusal_rejections": 1}
        return [["world-0"], ["world-1"]], 3

    monkeypatch.setattr(PVSearchBot, "_worlds", worlds)
    returned_root, sampled, receipt = sample_public_refusal_tape(
        bot, fixture, mode=mode, seed=17, fill_seed=4)
    assert returned_root is root and sampled == [["world-0"], ["world-1"]]
    assert mode_seen == [(mode, 4)]
    assert calls == [(root, 1, ledger, None)]
    assert receipt["schema"] == "public-refusal-tape-v1"
    assert receipt["ledger_receipt"]["schema"] == "public-refusal-ledger-v1"
    assert receipt["ledger_receipt"]["mode"] == mode
    assert receipt["seed"] == 17 and receipt["fill_seed"] == 4
    assert receipt["world_count"] == 2 and receipt["attempts"] == 3
    assert receipt["last_sampling"] == bot._last_sampling
    assert receipt["sampler_record"]["refusal_rejections"] == 1
    assert receipt["checkpoint_sha256"] == "a" * 64
    assert not receipt["checkpoint_hash_verified"]
    assert not receipt["provenance_verified"]
    assert not receipt["model_verified"]
    assert not receipt["live_rng_state_reconstructed"]
    bot._last_sampling.clear()
    assert receipt["last_sampling"]["refusal_rejections"] == 1
    with pytest.raises(ValueError, match="already consumed"):
        sample_public_refusal_tape(bot, fixture, mode=mode, seed=17)


def test_public_refusal_tape_forwards_budget_and_consumes_after_failure(monkeypatch):
    from shengji.ai.refusal import RefusalLedger
    from shengji.eval import public_refusal_tape as module
    from shengji.eval.public_refusal_tape import sample_public_refusal_tape
    from shengji.train.pv_search_policy import PVSearchBot

    mode_seen, ledger = [], RefusalLedger()
    root = _patch_synthetic_public_root(monkeypatch, mode_seen, ledger)
    bot = _synthetic_sampler_bot(monkeypatch)
    fixture = SimpleNamespace(id="synthetic", seat=1)
    budget = object()
    seen = []

    def fail(self, rnd, seat, check_budget=None):
        seen.append((rnd, seat, check_budget))
        raise RuntimeError("sentinel sampler failure")

    monkeypatch.setattr(PVSearchBot, "_worlds", fail)
    with pytest.raises(RuntimeError, match="sentinel"):
        sample_public_refusal_tape(bot, fixture, mode="fresh-root", seed=17,
                                   check_budget=budget)
    assert seen == [(root, 1, budget)]
    with pytest.raises(ValueError, match="already consumed"):
        sample_public_refusal_tape(bot, fixture, mode="fresh-root", seed=17)


@pytest.mark.parametrize("change", [
    "ruleoff", "config", "seed", "rng", "ledger", "worlds", "checkpoint",
    "badseed", "badworldcount", "override", "sampler_type", "draw_override",
    "completion_override", "rng_type", "hash_format",
])
def test_public_refusal_tape_rejects_stale_or_noncanonical_bot_before_sampler(
        monkeypatch, change):
    from shengji.ai.refusal import RefusalLedger
    from shengji.eval import public_refusal_tape as module
    from shengji.eval.public_refusal_tape import sample_public_refusal_tape
    from shengji.train.pv_search_policy import PVSearchBot

    bot = _synthetic_sampler_bot(monkeypatch)
    fixture = SimpleNamespace(id="synthetic", seat=1)
    if change == "ruleoff":
        bot.refusal_constraints = False
    elif change == "config":
        bot.config.refusal_constraints = False
    elif change == "seed":
        bot.sampler.seed = 18
    elif change == "rng":
        bot.sampler.rng.random()
    elif change == "ledger":
        bot._refusals.key = ("stale",)
    elif change == "worlds":
        bot.config.worlds = 3
    elif change == "checkpoint":
        bot.checkpoint_sha256 = "b" * 64
    elif change == "badseed":
        pass
    elif change == "badworldcount":
        bot.worlds = 3
    elif change == "override":
        bot._worlds = lambda *args: (_ for _ in ()).throw(AssertionError("called"))
    elif change == "sampler_type":
        bot.sampler = SimpleNamespace(seed=17, rng=random.Random(17))
    elif change == "draw_override":
        bot.sampler._sample_hands = lambda *args: None
    elif change == "completion_override":
        bot.sampler._complete_determinized_hands = lambda *args: None
    elif change == "rng_type":
        bot.sampler.rng = SimpleNamespace(getstate=lambda: random.Random(17).getstate())
    elif change == "hash_format":
        bot.checkpoint_sha256 = bot.config.checkpoint_sha256 = "not-a-hash"
    monkeypatch.setattr(module, "public_root_with_ledger",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("adapter called")))
    if change == "badseed":
        with pytest.raises(ValueError):
            sample_public_refusal_tape(bot, fixture, mode="fresh-root", seed=True)
    else:
        with pytest.raises(ValueError):
            sample_public_refusal_tape(bot, fixture, mode="fresh-root", seed=17)


def test_public_refusal_tape_rejects_invalid_mode_fill_seed_and_results(monkeypatch):
    from shengji.ai.refusal import RefusalLedger
    from shengji.eval import public_refusal_tape as module
    from shengji.eval.public_refusal_tape import sample_public_refusal_tape
    from shengji.train.pv_search_policy import PVSearchBot

    fixture = SimpleNamespace(id="synthetic", seat=1)
    for mode, fill_seed in [("auto", 0), ("fresh-root", -1), ("fresh-root", True)]:
        bot = _synthetic_sampler_bot(monkeypatch)
        with pytest.raises(ValueError):
            sample_public_refusal_tape(bot, fixture, mode=mode, seed=17,
                                       fill_seed=fill_seed)

    ledger = RefusalLedger()
    _patch_synthetic_public_root(monkeypatch, [], ledger)
    bot = _synthetic_sampler_bot(monkeypatch)

    def short(self, rnd, seat, check_budget=None):
        return [["only"]], 1

    monkeypatch.setattr(PVSearchBot, "_worlds", short)
    with pytest.raises(ValueError, match="world count"):
        sample_public_refusal_tape(bot, fixture, mode="fresh-root", seed=17)


@pytest.mark.parametrize("mode,expected,count", [
    ("fresh-root", "plain", 0), ("history-primed", "refusal-aware", 1),
])
def test_real_pv_dispatch_uses_reconstructed_ledger_without_drawing(
        fixtures, monkeypatch, mode, expected, count):
    from test_refusal_constraints import served
    from shengji.eval.public_refusal_tape import sample_public_refusal_tape
    from shengji.train import pv_search_policy as pv

    fx = next(f for f in fixtures if f.id == "pvr8-c1-m0-p23-pair-preservation")
    bot = served(seed=17, worlds=2, refusal_constraints=True)
    calls = []
    def stop(kind):
        def intercept(sampler, root, seat, n, *args, **kwargs):
            calls.append(kind)
            assert sampler is bot.sampler and seat == fx.seat and n == 2
            assert bot._refusals.key == tuple(root.deck)
            assert len(bot._refusals.refusals) == count
            if kind == "refusal-aware":
                assert args[0] == bot._refusals.refusals
            raise RuntimeError("stopped before scientific sampling")
        return intercept
    monkeypatch.setattr(pv, "sample_worlds", stop("plain"))
    monkeypatch.setattr(pv, "sample_worlds_refusal_aware", stop("refusal-aware"))
    with pytest.raises(RuntimeError, match="before scientific"):
        sample_public_refusal_tape(bot, fx, mode=mode, seed=17)
    assert calls == [expected]


@pytest.mark.parametrize("fill_seed", [0, 1])
@pytest.mark.parametrize("fixture_index", range(4))
def test_schedules_match_existing_modes(fixtures, fixture_index, fill_seed):
    fx = fixtures[fixture_index]
    original = copy.deepcopy(fx.to_json())
    actor_indices = [i for i, p in enumerate(fx.plays) if p["seat"] == fx.seat]
    for mode, indices in [("fresh-root", []), ("history-primed", actor_indices)]:
        root, _, expected = public_root_with_ledger(fx, mode=mode, fill_seed=fill_seed)
        scheduled, ledger, receipt = public_root_with_observation_schedule(
            fx, observed_play_indices=indices, fill_seed=fill_seed)
        assert receipt["retained_refusals"] == expected["retained_refusals"]
        assert receipt["historical_observations"] == [
            {"play_index": i, "seat": fx.plays[i]["seat"]} for i in indices]
        assert receipt["final_root_observation"] == {"play_index": len(fx.plays), "seat": fx.seat}
        assert scheduled.hands == root.hands and scheduled.history == root.history
        assert scheduled.trick == root.trick and scheduled.notice == root.notice
        assert len(ledger.observe(scheduled)) == len(expected["retained_refusals"])
        assert not receipt["observation_schedule_verified"]
        assert not receipt["provenance_verified"]
        assert not receipt["live_rng_state_reconstructed"]
        assert receipt["hidden_hands_are_placeholders"]
    assert fx.to_json() == original


@pytest.mark.parametrize("fill_seed", [0, 1])
def test_explicit_all_turns_adds_two_notices_without_inferred_ownership(fixtures, fill_seed):
    fx = next(f for f in fixtures if f.id == "pvr8-c2-m0-p43-partner-overtake-control")
    _, _, actor = public_root_with_ledger(fx, mode="history-primed", fill_seed=fill_seed)
    _, _, all_turns = public_root_with_observation_schedule(
        fx, observed_play_indices=tuple(range(len(fx.plays))), fill_seed=fill_seed)
    assert (len(actor["retained_refusals"]), len(all_turns["retained_refusals"])) == (6, 8)
    assert len(all_turns["historical_observations"]) == len(fx.plays)


def test_changing_seat_schedule_is_explicit_and_copied(fixtures):
    fx = fixtures[0]
    indices = [0, 2, 5]
    _, _, receipt = public_root_with_observation_schedule(fx, observed_play_indices=indices)
    indices.append(6)
    assert receipt["historical_observations"] == [
        {"play_index": i, "seat": fx.plays[i]["seat"]} for i in (0, 2, 5)]
    assert len({o["seat"] for o in receipt["historical_observations"]}) > 1


@pytest.mark.parametrize("indices", [None, "all", True, {0}, [True], [0.0], [-1],
                                      [100000], [1, 0], [0, 0]])
def test_invalid_schedule_refused_before_root_replay(fixtures, indices, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid schedule reached root construction")
    monkeypatch.setattr(tactical, "public_round", forbidden)
    with pytest.raises(ValueError):
        public_root_with_observation_schedule(fixtures[0], observed_play_indices=indices)


def test_schedule_is_required_and_final_root_is_not_a_historical_index(fixtures):
    with pytest.raises(TypeError):
        public_root_with_observation_schedule(fixtures[0])
    with pytest.raises(ValueError):
        public_root_with_observation_schedule(
            fixtures[0], observed_play_indices=[len(fixtures[0].plays)])


def test_schedule_replay_drift_refused(fixtures, monkeypatch):
    original = tactical.round_from_setup
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        rnd = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            rnd.attacker_points += 1
        return rnd
    monkeypatch.setattr(tactical, "round_from_setup", changed)
    with pytest.raises(ValueError, match="differs"):
        public_root_with_observation_schedule(fixtures[0], observed_play_indices=[])
