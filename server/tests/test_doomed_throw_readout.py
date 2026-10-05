import pytest

from shengji.eval.doomed_throw_readout import (
    empty_doomed_throw_census,
    observe_doomed_throw,
    summarize_doomed_throw,
)


class _TraceBot:
    def __init__(self, cards):
        self.cards = cards
        self.last_decision_record = {"schema": "pv-search-decision-v1", "played": cards}

    def decide_play(self, _round, _seat):
        return list(self.cards)


class _Round:
    history = []


def _shard(*, failed=(False, False), mismatch=False, swap=None):
    records = []
    traces = []
    for mirror in (0, 1):
        seats = [0, 2] if mirror == 0 else [1, 3]
        history = [[seat, [f"C{seat + 2}"]] for seat in seats]
        history += [[1 - mirror, ["D2"]], [3 - mirror, ["D3"]]]
        records.append({
            "mirror": mirror,
            "arm_seats": seats,
            "committed_history": history,
        })
        decisions = []
        for index, seat in enumerate(seats):
            decision = {"seat": seat, "played": ["C2"] * (2 if failed[mirror] and index == 0 else 1)}
            if swap is not None and mirror == 0 and index == 0:
                decision.update(swap)
            decisions.append(decision)
        if mismatch and mirror == 1:
            decisions.pop()
        traces.extend([
            {"mirror": mirror, "side": "arm", "decisions": [decisions[0]]},
            {"mirror": mirror, "side": "arm", "decisions": decisions[1:]},
        ])
    return {"records": records, "decision_traces": traces}


def test_candidate_counts_swap_fields_and_refused_ratio():
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, _shard(swap={
        "doomed_throw_swap_applied": True,
        "doomed_throw_swap_from": "C2 D6 D6",
        "doomed_throw_swap_worlds": 16,
        "doomed_throw_swap_refused_worlds": 16,
    }), candidate=True)

    assert census["swap_applied"] == 1
    assert census["swap_applied_field_records"] == 1
    assert census["budget_abandoned"] == 0
    assert census["multi_card_lead_records"] == 1
    assert census["refused_world_ratio_distribution"] == {"16/16": 1}


@pytest.mark.parametrize("abandoned", ["budget", "unexpected", None])
def test_abandoned_lead_is_separate_and_never_a_zero_ratio(abandoned):
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, _shard(swap={
        "doomed_throw_swap_from": "C2 C2",
        "doomed_throw_swap_worlds": 64,
        "doomed_throw_swap_refused_worlds": 0,
        "doomed_throw_swap_abandoned": abandoned,
    }), candidate=True)
    assert census["multi_card_lead_records"] == 1
    assert census["abandoned_multi_card_lead_records"] == 1
    assert census["budget_abandoned"] == int(abandoned == "budget")
    assert census["refused_world_ratio_distribution"] == {}


@pytest.mark.parametrize("position", [1, 2, 3, 4])
def test_ratio_uses_chronological_lead_position_not_seat_or_trace_index(position):
    swap = {"doomed_throw_swap_from": "C2 C2",
            "doomed_throw_swap_worlds": 64,
            "doomed_throw_swap_refused_worlds": 0}
    shard = _shard(swap=swap)
    history = shard["records"][0]["committed_history"]
    first = history.pop(0)
    if position == 4:
        # A second turn by an arm seat; a later lead, not trace index zero.
        history.insert(0, [0, ["C3"]])
        shard["decision_traces"][0]["decisions"].insert(0, {"seat": 0, "played": ["C3"]})
    history.insert(position, first)
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census["aligned_rounds"] == 2
    assert census["multi_card_lead_records"] == int(position == 4)
    assert census["refused_world_ratio_distribution"] == ({"0/64": 1} if position == 4 else {})


def test_unaligned_round_excludes_lead_ratio_but_preserves_field_telemetry():
    shard = _shard(swap={"doomed_throw_swap_from": "C2 C2",
                         "doomed_throw_swap_worlds": 64,
                         "doomed_throw_swap_refused_worlds": 0})
    # Failure after the lead was aligned must invalidate the whole round.
    shard["decision_traces"][1]["decisions"][0]["played"] = []
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census["swap_field_records"] == 1
    assert census["unaligned_rounds"] == 1
    assert census["multi_card_lead_records"] == 0
    assert census["refused_world_ratio_distribution"] == {}


def test_comparator_swap_fields_are_contamination_not_swap_estimates():
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, _shard(swap={
        "doomed_throw_swap_applied": True,
        "doomed_throw_swap_unexpected": 1,
    }), candidate=False)

    assert census["swap_applied"] == 0
    assert census["comparator_contamination_records"] == 1
    assert census["comparator_contamination_fields"]["doomed_throw_swap_applied"] == 1
    assert census["comparator_contamination_fields"]["doomed_throw_swap_unexpected"] == 1


def test_failed_throw_alignment_uses_both_mirrors_and_engine_history():
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, _shard(failed=(True, False)), candidate=True)

    assert census["aligned_rounds"] == 2
    assert census["unaligned_rounds"] == 0
    assert census["aligned_arm_plays"] == 4
    assert census["failed_throws"] == 1
    assert census["failed_throw_rounds"] == 1
    result = summarize_doomed_throw([census])
    assert result["failed_throw_rate_per_1000_aligned_arm_plays"] == 250
    assert result["failed_throw_round_share"] == pytest.approx(0.5)
    assert result["alignment"]["coverage"] == 1


def test_committed_history_groups_repeated_turns_by_seat():
    shard = _shard()
    shard["records"][0]["committed_history"] = [
        [0, ["C2"]], [1, ["D2"]], [2, ["C4"]],
        [0, ["C5"]], [3, ["D3"]], [2, ["C6"]],
    ]
    shard["decision_traces"][0]["decisions"].append({"seat": 0, "played": ["C5", "C5"]})
    shard["decision_traces"][1]["decisions"].append({"seat": 2, "played": ["C6"]})
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census["aligned_rounds"] == 2
    assert census["failed_throws"] == 1


def test_alignment_accepts_canonical_played_card_lists():
    shard = _shard(failed=(True, False))
    for trace in shard["decision_traces"]:
        for decision in trace["decisions"]:
            decision["played__len"] = len(decision["played"])
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census["aligned_rounds"] == 2
    assert census["failed_throws"] == 1


def test_alignment_consumes_real_timed_policy_trace_shape():
    from shengji.train.search_screen import TimedPolicy

    shard = _shard()
    for trace in shard["decision_traces"]:
        seat = trace["decisions"][0]["seat"]
        policy = TimedPolicy(_TraceBot([f"C{seat + 2}"]))
        policy.decide_play(_Round(), seat)
        trace["decisions"] = policy.decisions
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census["aligned_rounds"] == 2
    assert census["aligned_arm_plays"] == 4


def test_mirror_count_mismatch_is_unaligned_and_never_imputed():
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, _shard(failed=(True, True), mismatch=True), candidate=True)

    assert census["aligned_rounds"] == 1
    assert census["unaligned_rounds"] == 1
    assert census["aligned_arm_plays"] == 2
    assert census["failed_throws"] == 1


def test_summary_merges_ratio_distribution_and_counters_before_rates():
    first = empty_doomed_throw_census()
    second = empty_doomed_throw_census()
    observe_doomed_throw(first, _shard(swap={
        "doomed_throw_swap_from": "C2 D2",
        "doomed_throw_swap_worlds": 8,
        "doomed_throw_swap_refused_worlds": 4,
    }), candidate=True)
    observe_doomed_throw(second, _shard(swap={
        "doomed_throw_swap_from": "C2 D2",
        "doomed_throw_swap_worlds": 8,
        "doomed_throw_swap_refused_worlds": 8,
    }), candidate=True)

    result = summarize_doomed_throw([first, second])
    assert result["counts"]["multi_card_lead_records"] == 2
    assert result["refused_world_ratio_distribution"] == {"4/8": 1, "8/8": 1}
    assert result["alignment"]["aligned_rounds"] == 4


def test_mixed_arm_census_is_rejected():
    candidate = empty_doomed_throw_census()
    comparator = empty_doomed_throw_census()
    observe_doomed_throw(candidate, _shard(), candidate=True)
    observe_doomed_throw(comparator, _shard(), candidate=False)
    with pytest.raises(ValueError, match="mixed"):
        summarize_doomed_throw([candidate, comparator])


@pytest.mark.parametrize("bad", [
    {"played": []}, {"played": None}, {"played": "C2"},
    {"played": ["C2"], "played__len": 2},
    {"played": ["C2"], "played__len": True},
])
def test_bad_attempt_excludes_entire_round(bad):
    shard = _shard(failed=(True, True))
    shard['decision_traces'][0]['decisions'][0].update(bad)
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census['unaligned_rounds'] == 1
    assert census['failed_throws'] == 1


def test_attempt_shorter_than_commit_is_unaligned():
    shard = _shard()
    shard['records'][0]['committed_history'][0][1] = ['C2', 'C3']
    census = empty_doomed_throw_census()
    observe_doomed_throw(census, shard, candidate=True)
    assert census['unaligned_rounds'] == 1
