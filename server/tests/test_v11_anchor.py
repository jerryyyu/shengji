"""Executable contract for the frozen v11 current/anchor lane."""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import v11_revalidate as V11  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.ballot import ballot_for_policy, policy_ballots  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


class _ChooseSecond:
    def __init__(self, delta=0.10):
        self.delta = delta

    def value_candidates(self, obs, actions):
        del obs
        return [0.0, self.delta] + [-0.5] * (len(actions) - 2)


def _play_state(seed=41):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    smart = SmartBot()
    for seat in range(4):
        cards = smart.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, smart.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play" and rnd.turn is not None
    return rnd, rnd.turn


def _keys(actions):
    return [tuple(sorted(action)) for action in actions]


def test_protected_anchor_reorders_only_and_preserves_world_rng():
    from shengji.rl.torch_policy import MCV11ProtectedAnchor

    rnd, seat = _play_state()
    bot = MCV11ProtectedAnchor(seed=17)
    bot.net = _ChooseSecond()
    original = MCBot._candidates(bot, rnd, seat)
    assert len(original) > 1
    assert tuple(sorted(original[0])) == \
        tuple(sorted(SmartBot().decide_play(rnd, seat))), \
        "protected-anchor semantics require literal Smart candidate 0"
    rng_before = bot.rng.getstate()

    anchored = bot._candidates(rnd, seat)

    assert Counter(_keys(anchored)) == Counter(_keys(original))
    assert anchored[0] == original[1]
    assert bot.rng.getstate() == rng_before, \
        "root proposal must not advance the common-world stream"
    rec = bot._pending_anchor_record
    assert rec["smart"] == original[0]
    assert rec["v11"] == original[1]
    assert rec["protected"] == original[1]
    assert rec["v11_predicted_delta"] == pytest.approx(0.10)
    assert rec["v11_triggered"] is True
    assert rec["proposal_reason"] == "v11_threshold_override"


def test_threshold_fallback_is_literal_smart_anchor():
    from shengji.rl.torch_policy import MCV11ProtectedAnchor

    rnd, seat = _play_state()
    bot = MCV11ProtectedAnchor(seed=18)
    bot.net = _ChooseSecond(delta=0.019)
    original = MCBot._candidates(bot, rnd, seat)
    anchored = bot._candidates(rnd, seat)
    assert anchored == original
    assert bot._pending_anchor_record["v11"] == original[1]
    assert bot._pending_anchor_record["v11_triggered"] is False
    assert bot._pending_anchor_record["protected"] == original[0]
    assert bot._pending_anchor_record["proposal_reason"] == \
        "v11_below_threshold_keep_smart"


def test_same_trigger_random_control_is_seeded_and_world_stream_independent():
    from shengji.rl.torch_policy import MCV11RandomAnchor

    rnd, seat = _play_state()
    a, b = MCV11RandomAnchor(seed=99), MCV11RandomAnchor(seed=99)
    a.net = b.net = _ChooseSecond()
    full = MCBot._candidates(a, rnd, seat)
    state_a, state_b = a.rng.getstate(), b.rng.getstate()
    ca, cb = a._candidates(rnd, seat), b._candidates(rnd, seat)
    assert ca == cb
    assert Counter(_keys(ca)) == Counter(_keys(full))
    assert ca[0] != full[0], "random control changes anchor only when v11 fires"
    assert a._pending_anchor_record["v11_triggered"] is True
    assert a._pending_anchor_record["mode"] == "same_trigger_random"
    assert a._pending_anchor_record["proposal_reason"] == \
        "same_trigger_random_anchor"
    assert a.rng.getstate() == state_a and b.rng.getstate() == state_b


def test_anchor_decision_record_names_model_mc_and_actual_choices():
    from shengji.rl.torch_policy import MCV11ProtectedAnchor

    rnd, seat = _play_state()
    bot = MCV11ProtectedAnchor(seed=20)
    bot.net = _ChooseSecond()
    candidates = bot._candidates(rnd, seat)
    # The v11 proposal is now index 0; Smart moved to index 1.
    bot.last_decision_record = {"means": [9.0, 4.0] +
                               [0.0] * (len(candidates) - 2)}
    bot._finalise_record(candidates, 1, "below_fixed_margin")
    rec = bot.last_decision_record["protected_anchor"]
    assert rec["protected_index"] == 0
    assert rec["smart_index"] == 1
    assert rec["v11_index"] == 0
    assert rec["mc_v11_minus_smart"] == pytest.approx(5.0)
    assert rec["mc_protected_minus_smart"] == pytest.approx(5.0)
    assert rec["played"] == candidates[1]
    assert rec["played_index"] == 1
    assert rec["reason"] == "below_fixed_margin"


@pytest.mark.parametrize(("anchor_name", "random_name", "base_name"), [
    ("mc-v11anchor", "mc-v11anchor-random", "mc-strong"),
    ("mc-v11anchor-s0-report-lcb",
     "mc-v11anchor-s0-report-lcb-random", "mc-s0-report-lcb"),
    ("mc-v11anchor-s0-adaptive",
     "mc-v11anchor-s0-adaptive-random", "mc-s0-adaptive"),
])
def test_anchor_contract_exactly_matches_named_search_base(
        anchor_name, random_name, base_name):
    anchor = make_bot(anchor_name, seed=7)
    random_control = make_bot(random_name, seed=7)
    base = make_bot(base_name, seed=7)
    excluded = {"ANCHOR_MODE", "V11_NPZ_SHA256", "V11_THRESHOLD"}
    expected = {
        name: getattr(base, name) for name in dir(base)
        if name.isupper() and name not in excluded
    }
    for bot in (anchor, random_control):
        assert bot.anchor_search_base_policy == base_name
        assert {name: getattr(bot, name) for name in expected} == expected
        assert type(bot.rollout_policy) is type(base.rollout_policy)
        assert ballot_for_policy(bot.policy_name).digest == \
            ballot_for_policy(base_name).digest


def test_s0_anchor_preserves_report_and_adaptive_mechanisms():
    report = make_bot("mc-v11anchor-s0-report-lcb", seed=7)
    adaptive = make_bot("mc-v11anchor-s0-adaptive", seed=7)
    assert report.N_DETERMINIZATIONS == adaptive.N_DETERMINIZATIONS == 30
    assert report.MARGIN == adaptive.MARGIN == 5.0
    assert report.REPORT_RULE == adaptive.REPORT_RULE == "lcb"
    assert report.REPORT_FOLD_WORLDS == adaptive.REPORT_FOLD_WORLDS == 300
    assert report.ADAPTIVE_ALLOCATION is False
    assert adaptive.ADAPTIVE_ALLOCATION is True
    assert report.REQUIRE_EXACT_WORK is adaptive.REQUIRE_EXACT_WORK is True


def test_anchor_refuses_a_misnamed_or_s3_enabled_search_base():
    from shengji.rl.torch_policy import MCV11ProtectedAnchor

    adaptive = make_bot("mc-s0-adaptive", seed=7)
    with pytest.raises(RuntimeError, match="object/name identity"):
        MCV11ProtectedAnchor(
            seed=7, search_base=adaptive,
            search_base_policy="mc-s0-report-lcb")

    unsafe = make_bot("mc-strong", seed=7)
    unsafe.EXACT_ENDGAME = True
    with pytest.raises(RuntimeError, match="every S3 feature off"):
        MCV11ProtectedAnchor(
            seed=7, search_base=unsafe, search_base_policy="mc-strong")


def test_override_manifest_binds_the_mc_ballot_the_net_actually_scores():
    stages = policy_ballots("rl-override-v11pair")
    assert set(stages) == {"root", "model"}
    assert stages["root"].digest == stages["model"].digest
    assert stages["model"].name == "mc_candidates"
    assert ballot_for_policy("rl-override-v11pair").digest == \
        ballot_for_policy("mc-strong").digest


def test_real_corrected_encoder_checkpoint_has_named_non_inert_witness():
    """An implementation that returns Smart before scoring must fail here."""
    rnd, seat = _play_state(seed=2)
    smart = SmartBot().decide_play(rnd, seat)
    bot = make_bot("rl-override-v11pair", seed=2)
    played = bot.decide_play(rnd, seat)

    assert smart == ["DA"]
    assert played == ["S10", "S10"]
    assert sorted(played) != sorted(smart)
    assert bot.v11_influence_telemetry() == {
        "schema": "v11-influence-telemetry-v1",
        "mode": "direct",
        "totals": {
            "decision_entries": 1,
            "single_candidate_returns": 0,
            "smart_absent_returns": 0,
            "model_scored": 1,
            "model_triggers": 1,
            "model_selected_non_smart": 1,
            "model_kept_smart": 0,
            "search_proposals": 0,
            "direct_overrides": 1,
        },
    }


@pytest.mark.parametrize("bad_value", [True, 1.0, 1.9, -1])
def test_v11_influence_receipt_refuses_non_integer_or_negative_counters(
        bad_value):
    bot = make_bot("rl-override-v11pair", seed=2)
    bot._v11_influence_totals["decision_entries"] = bad_value
    with pytest.raises(RuntimeError, match="malformed V11 influence"):
        bot.v11_influence_telemetry()


def test_v11_override_checkpoint_identity_is_absolute_and_cwd_independent(
        tmp_path, monkeypatch):
    fake = tmp_path / "snapshots_v11pair"
    fake.mkdir()
    (fake / "ep07.npz").write_bytes(b"cwd lookalike must never be loaded")
    monkeypatch.chdir(tmp_path)
    bot = make_bot("rl-override-v11pair", seed=7)
    assert Path(bot.checkpoint_path) == V11.CHECKPOINT.resolve()
    assert bot.checkpoint_sha256 == V11.CHECKPOINT_SHA256
    contract = V11.policy_contract("rl-override-v11pair")
    assert contract["checkpoint_path"] == str(V11.CHECKPOINT.resolve())
    assert contract["checkpoint_sha256"] == V11.CHECKPOINT_SHA256


def test_frozen_checkpoint_is_required_not_a_silent_fallback(tmp_path):
    from shengji.rl.torch_policy import MCV11ProtectedAnchor

    with pytest.raises(RuntimeError, match="unavailable"):
        MCV11ProtectedAnchor(str(tmp_path / "missing.npz"), seed=1)
    changed = tmp_path / "changed.npz"
    changed.write_bytes(b"not the frozen net")
    with pytest.raises(RuntimeError, match="digest"):
        MCV11ProtectedAnchor(str(changed), seed=1)


def test_npnet_is_cached_across_fresh_round_bots():
    a = make_bot("rl-override-v11pair", seed=1)
    b = make_bot("rl-override-v11pair", seed=2)
    assert a.net is b.net, "revalidation must not reload 2 MB per seat/round"
    assert all(not value.flags.writeable for value in a.net.w.values()), \
        "a process-wide checkpoint cache must be immutable"


def test_revalidation_protocol_is_frozen_and_uses_real_n30_null():
    assert V11.SEED0 == 121_000_000
    assert V11.SEED_HI == 121_002_047
    assert V11.TOTAL_CLUSTERS == 2_048
    assert V11.SHARD_COUNT == 8 and V11.CLUSTERS_PER_SHARD == 256
    assert V11.LABELS == {
        "arm": "rl-override-v11pair",
        "null": "mc-strong-null",
        "reference": "mc-strong",
    }
    assert V11.protocol_problems() == []


def test_revalidation_gate_requires_two_superiority_lcbs_and_clean_null():
    def c(mean, half):
        return {"mean": mean, "half_width_95": half}

    passing = {
        "arm-reference": c(0.30, 0.20),
        "arm-null": c(0.28, 0.20),
        "null-reference": c(0.01, 0.10),
    }
    assert V11.gate_criteria(passing)["all"] is True
    for key in ("arm-reference", "arm-null"):
        failed = {name: dict(value) for name, value in passing.items()}
        failed[key] = c(0.10, 0.20)
        assert V11.gate_criteria(failed)["all"] is False
    failed = {name: dict(value) for name, value in passing.items()}
    failed["null-reference"] = c(0.20, 0.10)
    assert V11.gate_criteria(failed)["all"] is False


def test_revalidation_record_gate_refuses_any_sampler_or_work_failure():
    clean = {"sample_attempts": 30, "accepted_worlds": 30,
             "failed_worlds": 0, "rejected_worlds": 0,
             "short_searches": 0, "zero_world": 0, "void_fallbacks": 0}
    rows = {
        label: [{"seed": 1, "flip": flip,
                 "arm": dict(clean), "opp": dict(clean)}
                for flip in (0, 1)]
        for label in V11.LABELS
    }
    assert V11.record_problems(rows) == []
    rows["arm"][0]["opp"]["rejected_worlds"] = 1
    assert "arm/opp: nonzero rejected_worlds" in V11.record_problems(rows)
