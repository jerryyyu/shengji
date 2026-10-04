import pytest
from pathlib import Path

from shengji.train.ballot_opportunity import summarize_opportunities as summarize


def test_missing_pair_contrast_and_duplicate_invariance():
    hand = ["S6", "S6", "C4", "C9", "S8"]
    legal = [["C4", "S6", "S6"], ["C4", "C9", "S8"], ["C4", "S6", "S8"]]
    result = summarize(hand, legal, [legal[0]], legal_complete=True)
    assert result["cards"]["S6"]["legal_spent"] == [0, 1, 2]
    assert result["pair_opportunities"]["0_vs_2"] == {"available_cards": 1, "covered_cards": 0}
    assert result == summarize(hand[::-1], legal + [legal[0][::-1]],
                               [legal[0], legal[0][::-1]], legal_complete=True)
    covered = summarize(hand, legal, legal[:2], legal_complete=True)
    assert covered["pair_opportunities"]["0_vs_2"]["covered_cards"] == 1
    assert covered["pair_opportunities"]["0_vs_1"]["covered_cards"] == 0


def test_no_opportunity_is_not_missing_coverage():
    result = summarize(["S6", "S6", "C4"], [["S6", "S6"]], [], legal_complete=True)
    assert result["cards"]["S6"]["contrasts"] == []
    assert result["cards"]["C4"]["legal_spent"] == [0]
    assert result["pair_opportunities"]["0_vs_2"] == {"available_cards": 0, "covered_cards": 0}
    assert result["strategic_quality_assessed"] is False


@pytest.mark.parametrize("complete", [False, None, 1, "true"])
def test_partial_or_nonboolean_refuses(complete):
    with pytest.raises(ValueError, match="complete"):
        summarize(["S6"], [["S6"]], [], legal_complete=complete)


@pytest.mark.parametrize("hand,legal,ballot", [
    (["S6"], [], []),
    (["S6"], [["S6", "S6"]], []),
    (["S6", "C4"], [["S6"]], [["C4"]]),
    (["S6"], [["S6"]], [["XX"]]),
    (["S6"] * 3, [["S6"]], []),
])
def test_invalid_inputs_refuse(hand, legal, ballot):
    with pytest.raises(ValueError):
        summarize(hand, legal, ballot, legal_complete=True)


@pytest.mark.parametrize("index", range(4))
def test_saved_public_fixture_opportunities_are_hidden_fill_invariant(index):
    from shengji.eval import tactical as T
    from shengji.harvest.legal import enumerate_legal
    fx = T.load_fixtures(Path(__file__).parent / "tactical/public_observations.jsonl")[index]
    reports = []
    for seed in (0, 1, 99):
        rnd = T.public_round(fx, fill_seed=seed)
        legal = enumerate_legal(rnd, fx.seat, cap=None)
        reports.append(summarize(fx.hand, legal.actions, fx.observed["admitted"],
                                 legal_complete=legal.complete))
    assert reports[0] == reports[1] == reports[2]
    report = reports[0]
    if index == 0:
        assert report["legal_unique_actions"] == 712
        assert report["cards"]["S6"]["legal_spent"] == [0, 1, 2]
        assert report["cards"]["S6"]["ballot_spent"] == [2]
    if index == 1:
        assert report["cards"]["BJ"]["legal_spent"] == [0, 1]
        assert report["cards"]["BJ"]["ballot_spent"] == [0, 1]
    if index == 2:
        assert report["cards"]["DA"]["ballot_spent"] == [0, 1]
    assert report["strategic_quality_assessed"] is False
