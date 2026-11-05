"""Release 50 with its opt-in rules off is main's release 50, name and decisions.

The served bot is built from the repo's ``fly.toml`` env exactly as the server
builds it (`test_release50_fly_config.served_bot`) on the hash-pinned
release-50 packages, and decides the ten fixed production positions of
`r50_flag_positions`.  Its played cards, base worlds and decision record (less
the fields that measure the run) must match ``fixtures/r50_flag_off_decisions.json``. Structure and discrete
values are exact; finite float values allow 1e-12 absolute/relative roundoff. The fixture
holds the same projection computed on the main tree named in it, on the
pure and the compiled engine alike.  Every rule flag the env leaves unset may
also be set to ``0`` explicitly without changing the recipe or a decision.

A correctness and identity witness of the flag-off path only; no strength claim.
"""
import json
import math

import pytest

import r50_flag_positions as P
from test_release46_fly_config import fly_env
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA,  # noqa: F401
                                       PRIOR_VOLUME_PATH, RELEASE50, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages, served_bot)

PINS = json.loads(P.PINNED.read_text())


def unset_rule_flags_at_zero(env) -> dict:
    """Every pv-search rule flag ``env`` leaves unset, set to ``0``."""
    from shengji.train import pv_search_policy as pv

    return {pv.ENV_PREFIX + suffix: "0" for suffix in pv.RULE_FLAGS
            if pv.ENV_PREFIX + suffix not in env}


def test_the_pins_are_release50_on_every_position():
    assert PINS["name"] == RELEASE50
    assert len(PINS["main"]) == 40
    assert sorted(PINS["decisions"]) == sorted(P.label(*position) for position in P.POSITIONS)


def test_unset_rule_flags_at_zero_keep_the_recipe_and_the_name(monkeypatch):
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv

    env = fly_env()
    zeros = unset_rule_flags_at_zero(env)
    assert len(zeros) >= 10
    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    recipe = pv.pv_env_recipe(env)
    assert pv.pv_env_recipe({**env, **zeros}) == recipe
    assert list(pv.singleton_registry_entries(**recipe)) == [RELEASE50]
    assert list(pv.singleton_registry_entries(**pv.pv_env_recipe({**env, **zeros}))) == [RELEASE50]


@pytest.mark.parametrize("key,trick,pos", P.POSITIONS, ids=[P.label(*p) for p in P.POSITIONS])
def test_flag_off_decisions_are_mains(release50_packages, monkeypatch, key, trick, pos):
    name, bot = served_bot(release50_packages, monkeypatch, seed=P.SEED)
    assert name == bot.policy_name == RELEASE50
    got = P.decision(P.lift(bot), P.replay(key, trick, pos))
    assert_decision(got, PINS["decisions"][P.label(key, trick, pos)])


def test_flag_off_at_zero_decides_as_main(release50_packages, monkeypatch):
    env = fly_env()
    name, bot = served_bot(release50_packages, monkeypatch, env={**env, **unset_rule_flags_at_zero(env)},
                           seed=P.SEED)
    assert name == bot.policy_name == RELEASE50
    position = ("SDUS2", 14, 0)
    assert_decision(P.decision(P.lift(bot), P.replay(*position)),
                    PINS["decisions"][P.label(*position)])


def assert_decision(actual, expected, path='decision'):
    """Keep structure/discrete values exact; permit only tiny numeric roundoff."""
    assert type(actual) is type(expected), f'{path}: type differs'
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), f'{path}: keys differ'
        for key in expected:
            assert_decision(actual[key], expected[key], f'{path}.{key}')
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f'{path}: length differs'
        for index, (got, want) in enumerate(zip(actual, expected)):
            assert_decision(got, want, f'{path}[{index}]')
    elif isinstance(expected, float):
        assert math.isfinite(actual) and math.isfinite(expected), f'{path}: nonfinite value'
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), (
            f'{path}: {actual!r} != {expected!r}')
    else:
        assert actual == expected, f'{path}: {actual!r} != {expected!r}'


def test_record_comparison_accepts_roundoff_but_rejects_meaning_changes():
    import copy
    expected = {'cards': ['D3'], 'worlds': 'world-id',
                'record': {'value_means': [0.123], 'selected_index': 0, 'complete': True}}
    roundoff = copy.deepcopy(expected)
    roundoff['record']['value_means'][0] += 1e-15
    assert_decision(roundoff, expected)
    for key, value in [('value_means', [0.123001]), ('value_means', [float('nan')]),
                       ('selected_index', 1), ('selected_index', 0.0), ('complete', False)]:
        changed = copy.deepcopy(expected)
        changed['record'][key] = value
        with pytest.raises(AssertionError, match='decision.record'):
            assert_decision(changed, expected)
    for key, value in [('cards', ['HQ']), ('worlds', 'other')]:
        changed = {**expected, key: value}
        with pytest.raises(AssertionError):
            assert_decision(changed, expected)
    with pytest.raises(AssertionError, match='keys differ'):
        assert_decision({**expected, 'extra': 1}, expected)


def test_record_projection_removes_nested_runtime_without_rounding():
    record = {'seconds': 1.0, 'stage': {'work_nodes': 42, 'mean': 0.1234567890123},
              'rows': ({'elapsed_ms': 5.0, 'selected_index': 2},)}
    assert P._canonical(record) == {
        'stage': {'mean': 0.1234567890123}, 'rows': [{'selected_index': 2}]}
