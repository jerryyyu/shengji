from synthetic_slots import clean_slot

import pytest

import readout


@pytest.fixture
def slots(monkeypatch):
    monkeypatch.setattr(readout, "FIRST_SEED", 100)
    monkeypatch.setattr(readout, "DEALS", 2)
    return {100 + i: clean_slot(i) for i in range(2)}


def test_both_teams_regret_and_inclusive_time_bar(slots):
    result = readout.analyze(slots, arm_name="fixture")
    assert result["verdict"] == "PASS"
    assert result["regret"]["served"]["upper95"] == -5
    assert result["regret"]["full"]["upper95"] == 0
    slots[100]["eligible"][0]["stage_seconds"] += .001
    assert readout.analyze(slots, arm_name="fixture")["verdict"] == "FAIL"


@pytest.mark.parametrize("change", [
    lambda s: s.pop(100),
    lambda s: s.update({100: {}}),
    lambda s: s[100].update(status="fault"),
    lambda s: s[100].update(seed=101),
    lambda s: s[100].update(world_counts={"63": 60}),
    lambda s: s[100].update(belief_fallbacks=2),
    lambda s: s[100].update(level_change=3),
    lambda s: s[100]["declares"][0].update(completed=5),
    lambda s: s[100]["eligible"][0].update(attacker=False),
    lambda s: s[100]["eligible"][0].update(full=None, full_censored=True),
    lambda s: s[100]["eligible"][0].update(completed_worlds=11),
    lambda s: s[100]["eligible"][0].update(stage_seconds=float("nan")),
    lambda s: s[100]["eligible"].extend(s[100]["eligible"][:1]),
])
def test_invalid_slot_never_produces_interval(slots, change, monkeypatch):
    change(slots)
    monkeypatch.setattr(readout, "_interval", lambda *_: pytest.fail("outcome opened"))
    assert readout.analyze(slots, arm_name="fixture")["verdict"] == "INVALID"


def test_censor_and_abandon_denominators(slots):
    for rec in slots.values():
        sample, = rec["eligible"]
        rec["eligible"] = [dict(sample, play_index=i) for i in range(50)]
    rows = slots[100]["eligible"]
    rows[0].update(full=None, full_censored=True)
    for row in rows[1:3]:
        row.update(abandoned="soft_budget", completed_worlds=11, arm=0)
    result = readout.analyze(slots, arm_name="fixture")
    assert result["eligible"] == 100 and result["full_censored"] == 1
    assert result["abandons"] == 2
    assert result["regret"]["served"]["mean"] == pytest.approx(-4.9)
    assert result["regret"]["full"]["mean"] == pytest.approx(10 / 99)
    assert result["verdict"] == "FAIL"
    rows[1].update(full=None, full_censored=True)
    assert readout.analyze(slots, arm_name="fixture")["verdict"] == "INVALID"
