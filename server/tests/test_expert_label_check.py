"""The expert-label rows checker (``scripts/expert_labels/m28lab_check.py``) on served moves outside the ballot.

Release 49's lead confirmation replaces the base winner by a challenger priced on fresh worlds: the challenger rides in the recorded
ballot with no base-pass mean, so the served record has no ballot selection (``cards`` None, the move in ``played``) and the live seat's
decision has no self row (counted in the deal row's ``self_skipped``).  Under the Y profile such a decision is a valid label row, counted
per rule; under the release-48 profile, which registers no rule, it reads INVALID.  The replay comparison holds an unpriced slot to an
unpriced slot.  Synthetic rows only: no package, engine or host.
"""
import copy
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "expert_labels"))
import m28lab_check as ck  # noqa: E402

CAPS_LIFTED = dict(ck.LIFTED_CAPS)
CAPS_EXPERT = dict(ck.EXPERT_CAPS)
BALLOT = [[1], [2], [3]]
CHALLENGER = [9, 9]
DIGEST = "a" * 64


def search_record(caps, worlds, **extra):
    return dict(schema=ck.RECORD_SCHEMA, worlds=worlds, belief_fallback=0, caps=dict(caps), **extra)


def served_on_ballot():
    return search_record(CAPS_LIFTED, 64, cards=[2], played=[2], admitted=copy.deepcopy(BALLOT), admitted_indices=[0, 1, 2],
                         selected_index=1, value_means=[0.1, 0.3, 0.2], lead_confirm_status="rejected", lead_confirm_applied=False)


def served_lcc_applied():
    """The challenger is the recorded ballot's last slot, selected, with no base-pass mean."""
    return search_record(CAPS_LIFTED, 64, cards=None, played=list(CHALLENGER), admitted=copy.deepcopy(BALLOT) + [list(CHALLENGER)],
                         admitted_indices=[0, 1, 2, 7], selected_index=7, value_means=[0.1, 0.3, 0.2, None],
                         lead_confirm_status="applied", lead_confirm_applied=True)


def decision(deal, index, served, lead=True):
    expert = search_record(CAPS_EXPERT, 256, dropped=False, drop_reason=None, cards=[3], admitted=copy.deepcopy(BALLOT),
                           value_means=[0.0, 0.1, 0.5], policy_log_odds_admitted=[0.0, 0.0, 0.0], action_type="single")
    return dict(row="decision", deal=deal, index=index, seat=0, lead=lead, trick_no=0, hand_size=25,
                expert=expert, served=served, live=search_record(CAPS_LIFTED, 64, cards=[2]), expert_in_r48_ballot=True,
                worlds_digest=dict(served=DIGEST, expert=DIGEST, expert_prefix=DIGEST), secs=dict(expert=1.0, served=0.1))


def live(deal, index, self_row, **extra):
    return dict(row="live", deal=deal, index=index, seat=1, lead=True, trick_no=1, self_row=self_row, skipped_single=False,
                cards=[4], live_secs=0.1, **search_record(CAPS_LIFTED, 64, **extra))


def deal_rows(served, *, lcc_live=False, self_skipped=None):
    recs = [decision(7, 0, served), live(7, 1, True)]
    if lcc_live:
        recs.append(live(7, 2, False, lead_confirm_status="applied", lead_confirm_applied=True))
    skipped = int(lcc_live) if self_skipped is None else self_skipped
    dd = dict(row="deal_done", deal=7, decisions=len(recs), labelled=[0], expert_dropped=0, self_rows=1, self_skipped=skipped,
              declare_recs=dict(live=[[ck.DECLARE_SCHEMA, None, True, 64, 64, 0.1]]), bury_rec=dict(live=[ck.BURY_SCHEMA, None, 10, 64]))
    return {7: dict(row=dd, dec=[recs[0]], recs=recs)}


def run_validity(pins, deals):
    p = dict(seed0=7, deals=1, shards=1, late_lead_prob=1.0, prob_follow=0.2, record_capsule=False)
    reasons, report, kept = ck.validity("train", p, pins, dict(ck.BAR, floors={}), deals)
    return reasons, report


def test_an_on_ballot_served_move_is_its_selection():
    assert ck.served_comparison(served_on_ballot(), ("lcc_applied",)) == ([2], False, None)
    assert ck.served_comparison(served_on_ballot(), ()) == ([2], False, None)


def test_an_applied_lead_confirmation_is_a_valid_off_ballot_move():
    assert ck.served_comparison(served_lcc_applied(), ck.Y_PINS["off_ballot_rules"]) == (CHALLENGER, True, "lcc_applied")


def test_release_48_registers_no_off_ballot_rule():
    assert "off_ballot_rules" not in ck.PINS and ck.PROFILES["r48"] is ck.PINS
    assert ck.served_comparison(served_lcc_applied(), ()) == (None, False, "unexplained")


@pytest.mark.parametrize("edit", [
    lambda r: r.update(lead_confirm_status="rejected"),
    lambda r: r.update(lead_confirm_applied=False),
    lambda r: r.update(played=[2]),                                   # the played move is not the selected slot
    lambda r: r.update(value_means=[0.1, 0.3, 0.2, 0.4]),             # the selected slot is priced
    lambda r: r.update(value_means=[0.1, None, 0.2, None]),           # another slot is unpriced
    lambda r: r.update(selected_index=5),                             # the selection is outside the recorded ballot
    lambda r: r.update(played=None),
])
def test_a_selectionless_record_off_the_rule_is_unexplained(edit):
    rec = served_lcc_applied()
    edit(rec)
    assert ck.served_comparison(rec, ("lcc_applied",)) == (None, False, "unexplained")


def test_a_fallback_record_is_left_to_the_fallback_ceiling():
    rec = dict(schema=ck.FALLBACK_SCHEMA, worlds=None, belief_fallback=None, caps={}, cards=None, played=[2])
    assert ck.served_comparison(rec, ("lcc_applied",)) == (None, False, "fallback")


def test_served_taken_is_the_selection_or_none_off_the_ballot():
    idx = {1: 11, 2: 12, 3: 13, 9: 19}
    assert ck.served_taken_matches(dict(served_taken=[12]), served_on_ballot(), ("lcc_applied",), idx) == (True, False)
    assert ck.served_taken_matches(dict(served_taken=[13]), served_on_ballot(), ("lcc_applied",), idx) == (False, False)
    assert ck.served_taken_matches(dict(served_taken=None), served_lcc_applied(), ("lcc_applied",), idx) == (True, True)
    assert ck.served_taken_matches(dict(served_taken=[19, 19]), served_lcc_applied(), ("lcc_applied",), idx) == (False, True)
    assert ck.served_taken_matches(dict(served_taken=None), served_lcc_applied(), (), idx) == (True, False)


def test_y_counts_off_ballot_rows_per_rule_and_stays_valid():
    reasons, report = run_validity(ck.Y_PINS, deal_rows(served_lcc_applied(), lcc_live=True))
    assert reasons == []
    assert report["off_ballot"] == dict(rules=["lcc_applied"], served={"lcc_applied": 1}, self_skipped_by_rule={"lcc_applied": 1})
    assert report["kept"] == 1 and report["self_rows"] == 1


def test_release_48_reads_the_same_rows_invalid():
    reasons, report = run_validity(ck.PINS, deal_rows(served_lcc_applied(), lcc_live=True))
    assert any("no ballot selection under no registered off-ballot rule" in r for r in reasons)
    assert any("self_skipped" in r for r in reasons)
    assert "off_ballot" not in report


def test_release_48_rows_without_off_ballot_moves_report_as_before():
    reasons, report = run_validity(ck.PINS, deal_rows(served_on_ballot()))
    assert reasons == [] and "off_ballot" not in report


@pytest.mark.parametrize("self_skipped", [0, 2, None])
def test_a_self_skip_count_off_the_live_rows_is_invalid(self_skipped):
    deals = deal_rows(served_lcc_applied(), lcc_live=True, self_skipped=self_skipped)
    if self_skipped is None:
        deals[7]["row"].pop("self_skipped")
    reasons, _ = run_validity(ck.Y_PINS, deals)
    assert any("self_skipped" in r for r in reasons)


def test_a_self_skip_off_any_rule_is_invalid():
    deals = deal_rows(served_on_ballot(), lcc_live=True)
    deals[7]["recs"][-1]["lead_confirm_status"] = "no_challenger"
    reasons, _ = run_validity(ck.Y_PINS, deals)
    assert any("self_skipped" in r for r in reasons)


def test_the_replay_holds_an_unpriced_slot_to_an_unpriced_slot():
    assert ck.slot_diff([0.1, 0.3, None], [0.1, 0.3, None]) == 0.0
    assert ck.slot_diff([0.1, 0.3 + 1e-12, None], [0.1, 0.3, None]) == pytest.approx(1e-12, abs=1e-15)
    assert math.isinf(ck.slot_diff([0.1, 0.3, 0.2], [0.1, 0.3, None]))
    assert math.isinf(ck.slot_diff([0.1, 0.3], [0.1, 0.3, None]))
    assert ck.slot_diff(None, None) == 0.0 and ck.slot_diff([], []) == 0.0


def test_the_replay_difference_on_priced_listings_is_the_r48_formula():
    g, w = [0.25, -1.5, 3.0], [0.25, -1.5 + 2e-15, 3.0 - 1e-15]
    assert ck.slot_diff(g, w) == max(abs(float(x) - float(y)) for x, y in zip(g, w))


def test_the_rows_mode_phase_spec():
    assert ck.parse_phase("heldout=311110000,1080,1080,1.0,0.2,1") == (
        "heldout", dict(seed0=311110000, deals=1080, shards=1080, late_lead_prob=1.0, prob_follow=0.2, record_capsule=True))
    for bad in ("train=1,3,2,0.3,0.1,0", "train=1,2,2,0.3,0.1,2", "train:1,2,2,0.3,0.1,0"):
        with pytest.raises(SystemExit):
            ck.parse_phase(bad)


def test_the_y_profile_pins_the_y_producer_and_the_m28_expert():
    y = ck.PROFILES["y"]
    assert y["served_name"].endswith("-sc8") and "-lcc32-" in y["served_name"]
    assert y["expert_name"] == ck.PINS["expert_name"]
    assert dict(map(tuple, y["expert_env"])) == {**dict(map(tuple, ck.EXPERT_ENV)), "SHENGJI_PV_LEAD_CONFIRM": "", "SHENGJI_PV_SINGLETON_CHALLENGER": ""}
    assert {k: v for k, v in y.items() if k not in ("served_name", "expert_env", "source_sha256", "harness_sha256", "served_base_sha256", "workers",
                                                    "phases", "off_ballot_rules", "phase_extras")} == \
        {k: v for k, v in ck.PINS.items() if k not in ("served_name", "expert_env", "source_sha256", "harness_sha256", "workers", "phases")}


def stub_rows_pipeline(monkeypatch):
    """Every rows-mode stage stubbed to a clean phase (check_rows as its zero-replay pass returns: no reasons), so only the replay count
    decides the read.  The real check_rows loads the served package at import, which this synthetic test does not have."""
    monkeypatch.setattr(ck, "shard_listing", lambda root, name, n: [])
    monkeypatch.setattr(ck, "load_phase", lambda root, name, p, pins, listed, subset=None: ([], None, {}))
    monkeypatch.setattr(ck, "check_identity", lambda *a, **k: None)
    monkeypatch.setattr(ck, "check_coverage", lambda name, shards: {})
    monkeypatch.setattr(ck, "check_row_schema", lambda name, deals: None)
    monkeypatch.setattr(ck, "validity", lambda name, p, pins, bar, deals: ([], {}, []))
    monkeypatch.setattr(ck, "timing", lambda deals, shards: {})
    monkeypatch.setattr(ck, "check_rows", lambda name, p, pins, shards, deals, kept, replay_make, replay_per_shard: ([], dict(rows={}, tags={})))


def rows_phase(capsule):
    return dict(seed0=7, deals=1, shards=1, late_lead_prob=1.0, prob_follow=0.2, record_capsule=capsule)


@pytest.mark.parametrize("replay", [0, -1])
def test_rows_mode_refuses_a_capsule_phase_with_no_replay(monkeypatch, replay):
    stub_rows_pipeline(monkeypatch)
    with pytest.raises(ck.CheckRefusal, match="replay_per_shard"):
        ck.analyze_rows("unused", phases=dict(train=rows_phase(False), heldout=rows_phase(True)), pins=ck.PROFILES["y"],
                        replay_make=object(), replay_per_shard=replay)


def test_rows_mode_reads_a_replayed_capsule_phase_and_a_capsule_free_phase(monkeypatch):
    stub_rows_pipeline(monkeypatch)
    res, _ = ck.analyze_rows("unused", phases=dict(heldout=rows_phase(True)), pins=ck.PROFILES["y"], replay_make=object(), replay_per_shard=1)
    assert res["validity"] == "VALID"
    res, _ = ck.analyze_rows("unused", phases=dict(train=rows_phase(False)), pins=ck.PROFILES["y"], replay_per_shard=0)
    assert res["validity"] == "VALID"


def test_the_rows_cli_refuses_replay_zero_on_a_capsule_phase(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        ck.main_rows([str(tmp_path / "root"), str(tmp_path / "out.json"), "--profile", "y", "--phase", "heldout=7,1,1,1.0,0.2,1", "--replay-per-shard", "0"])
    assert exc.value.code == 3 and "REFUSING: replay_per_shard 0" in capsys.readouterr().out
    assert not (tmp_path / "out.json").exists()
