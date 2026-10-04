import copy
import pytest
from shengji.eval.fixed_tape_panel import collect_fixed_tape_panel
from shengji.eval.fixed_tape_capture import capture_fixed_tape
from shengji.eval.ballot_full_pool import summarize_full_pool_matrix
from test_pv_tiebreak_points import last_position, served

ACTIONS = [["DK"], ["D6"], ["H4"]]


def inputs():
    root = last_position()
    return root, [(copy.deepcopy(root.hands), list(root.buried)) for _ in range(3)]


def test_three_passes_same_tape_order_and_exact_accumulators():
    bots = []
    def factory():
        bot = served(tiebreak_points=True)
        bots.append(bot)
        return bot
    root, tape = inputs()
    original = copy.deepcopy(tape)
    control, treatment = [ACTIONS[1], ACTIONS[0]], [ACTIONS[2], ACTIONS[1]]
    result = collect_fixed_tape_panel(factory, root, root.turn, ACTIONS, control, treatment, tape)
    assert len(bots) == 3
    assert result["captures"]["control"]["actions"] == control
    assert result["captures"]["treatment"]["actions"] == treatment
    assert tape == original
    means, _ = bots[0]._value_means(root, root.turn, ACTIONS, tape)
    assert result["captures"]["full_pool"]["serving_value_means"] == means.tolist()
    assert result["captures"]["control"]["signed_trick_points"] == [[-10, -20]] * 3
    assert not result["provenance_verified"]


def test_separate_schedule_views_expose_batch_effects():
    def factory():
        bot = served()
        bot.evaluator.score = lambda leaves, seat: [
            .5 + (.01 if len(leaves) == 9 and "D6" not in leaf.hands[seat] else 0)
            for leaf in leaves]
        return bot
    root, tape = inputs()
    result = collect_fixed_tape_panel(factory, root, root.turn, ACTIONS,
                                     ACTIONS[:2], ACTIONS[1:], tape)
    assert result["shared_matrix_points_replay"]["control"]["raw_index"] == 1
    assert result["ballot_schedule_points_replay"]["control"]["raw_index"] == 0
    assert result["ballot_minus_full_schedule_value_deltas"]["control"][1] == pytest.approx(-.01)


def test_reused_bot_is_refused():
    bot = served()
    root, tape = inputs()
    with pytest.raises(ValueError, match="fresh dedicated"):
        collect_fixed_tape_panel(lambda: bot, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)


def test_mutate_then_restore_leaf_override_refused_before_call():
    bot = served()
    calls = []
    original = bot._leaf
    def mutating(root, seat, hands, buried, action, world_index):
        calls.append(1)
        saved = copy.deepcopy(hands)
        hands[seat].clear()
        try:
            return original(root, seat, hands, buried, action, world_index)
        finally:
            hands[:] = saved
    bot._leaf = mutating
    root, tape = inputs()
    with pytest.raises(ValueError, match="canonical production leaf"):
        collect_fixed_tape_panel(lambda: bot, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)
    assert calls == []


def test_missing_ballot_member_refused_before_factory():
    def fail():
        pytest.fail("factory called before validation")
    root, tape = inputs()
    with pytest.raises(ValueError, match="absent"):
        collect_fixed_tape_panel(fail, root, root.turn, ACTIONS, [["BJ"]], ACTIONS[:1], tape)


@pytest.mark.parametrize("tape", [[], [None], [([],)], "not a tape"])
def test_malformed_tape_refused_before_factory(tape):
    def fail():
        pytest.fail("factory called before validation")
    root, _ = inputs()
    with pytest.raises(ValueError):
        collect_fixed_tape_panel(fail, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)


def test_failed_second_pass_stops_third_and_restores_inputs():
    bots, evaluators = [], []
    def factory():
        bot = served()
        if bots:
            def fail(*args):
                raise RuntimeError("second pass failed")
            bot.evaluator.score = fail
        bots.append(bot)
        evaluators.append(bot.evaluator)
        return bot
    root, tape = inputs()
    original = copy.deepcopy(tape)
    with pytest.raises(RuntimeError, match="second pass"):
        collect_fixed_tape_panel(factory, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)
    assert len(bots) == 2
    assert all(bot.evaluator is evaluator for bot, evaluator in zip(bots, evaluators))
    assert tape == original


def test_inconsistent_point_evidence_is_refused(monkeypatch):
    from shengji.eval import fixed_tape_panel as module
    original = module.capture_fixed_tape
    calls = 0
    def corrupted(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            result["signed_trick_points"][0][0] += 5
        return result
    monkeypatch.setattr(module, "capture_fixed_tape", corrupted)
    root, tape = inputs()
    with pytest.raises(ValueError, match="resolved points differ"):
        collect_fixed_tape_panel(served, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)


def test_history_primed_panel_has_one_full_capture_and_projected_union():
    bots, scored_cells = [], []

    def factory():
        bot = served(tiebreak_points=True)
        original_score = bot.evaluator.score

        def score(leaves, seat):
            scored_cells.append(len(leaves))
            return original_score(leaves, seat)

        bot.evaluator.score = score
        bots.append(bot)
        return bot

    root, tape = inputs()
    original = copy.deepcopy((root.hands, root.buried, root.history, tape))
    actions = [ACTIONS[2], ACTIONS[0], ACTIONS[1]]
    control, treatment = [ACTIONS[1], ACTIONS[2]], [ACTIONS[0], ACTIONS[2]]
    from shengji.eval.fixed_tape_panel import collect_history_primed_panel
    result = collect_history_primed_panel(
        factory, root, root.turn, actions, control, treatment, tape)

    assert len(bots) == 1
    assert sum(scored_cells) == len(tape) * len(actions)
    assert result["schema"] == "fixed-tape-history-primed-panel-v1"
    assert result["full_pool_capture"]["actions"] == actions
    assert result["union_is_projection"] is True
    assert result["saved_ballots_generated_under_this_sampler"] is False
    assert result["sampler_mode_verified"] is False
    assert result["provenance_verified"] is False
    assert result["strategic_quality_assessed"] is False
    assert "ballot_schedule_points_replay" not in result
    assert (root.hands, root.buried, root.history, tape) == original

    summary = summarize_full_pool_matrix(
        actions, control, treatment, result["full_pool_capture"]["value_matrix"])
    assert result["shared_matrix_summary"] == summary
    assert result["shared_matrix_summary"]["union_summary"]["actions"] == [
        ["H4"], ["D6"], ["DK"]]


def test_history_primed_capture_preserves_caller_action_column_order(monkeypatch):
    from shengji.eval import fixed_tape_panel as module
    from shengji.eval.fixed_tape_panel import collect_history_primed_panel

    seen = {}

    def synthetic_capture(bot, root, seat, actions, worlds, **kwargs):
        seen["actions"] = copy.deepcopy(actions)
        return {
            "value_matrix": [[float(i) for i in range(len(actions))]
                             for _ in worlds],
        }

    monkeypatch.setattr(module, "capture_fixed_tape", synthetic_capture)
    root, tape = inputs()
    actions = [["D6", "H4"], ["BJ"]]
    control, treatment = [actions[1]], [actions[0]]
    result = collect_history_primed_panel(
        served, root, root.turn, actions, control, treatment, tape)
    assert seen["actions"] == actions
    assert result["shared_matrix_summary"]["union_summary"]["actions"] == [
        ["H4", "D6"], ["BJ"]]


def test_history_primed_capture_matches_direct_full_pool_capture():
    root, tape = inputs()
    direct_bot = served(tiebreak_points=True)
    direct = capture_fixed_tape(
        direct_bot, copy.deepcopy(root), root.turn, ACTIONS, copy.deepcopy(tape))

    from shengji.eval.fixed_tape_panel import collect_history_primed_panel
    result = collect_history_primed_panel(
        lambda: served(tiebreak_points=True), root, root.turn, ACTIONS,
        ACTIONS[:2], ACTIONS[1:], tape)
    captured = result["full_pool_capture"]
    assert captured["value_matrix"] == direct["value_matrix"]
    assert captured["signed_trick_points"] == direct["signed_trick_points"]
    assert captured["serving_value_means"] == direct["serving_value_means"]


def test_history_primed_invalid_inputs_refuse_before_factory():
    from shengji.eval.fixed_tape_panel import collect_history_primed_panel
    root, tape = inputs()

    def fail():
        pytest.fail("factory called before validation")

    bad_cases = [
        (root, root.turn, ACTIONS, [["BJ"]], ACTIONS[1:], tape),
        (root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], []),
        (root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], [None]),
        (root, (root.turn + 1) % 4, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape),
    ]
    for args in bad_cases:
        with pytest.raises(ValueError):
            collect_history_primed_panel(fail, *args)


def test_history_primed_leaf_override_is_rejected_before_scoring():
    from shengji.eval.fixed_tape_panel import collect_history_primed_panel
    bot = served()
    calls = []
    original_leaf = bot._leaf

    def override(*args):
        calls.append(1)
        return original_leaf(*args)

    bot._leaf = override
    root, tape = inputs()
    with pytest.raises(ValueError, match="canonical production leaf"):
        collect_history_primed_panel(
            lambda: bot, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)
    assert calls == []


def test_history_primed_tape_mutation_is_rejected(monkeypatch):
    from shengji.eval import fixed_tape_panel as module
    from shengji.eval.fixed_tape_panel import collect_history_primed_panel
    original_capture = module.capture_fixed_tape

    def mutating_capture(bot, root, seat, actions, worlds, **kwargs):
        result = original_capture(bot, root, seat, actions, worlds, **kwargs)
        worlds[0] = ([], [])
        return result

    monkeypatch.setattr(module, "capture_fixed_tape", mutating_capture)
    root, tape = inputs()
    with pytest.raises(ValueError, match="mutated"):
        collect_history_primed_panel(
            served, root, root.turn, ACTIONS, ACTIONS[:1], ACTIONS[1:], tape)
