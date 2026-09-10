from __future__ import annotations

import json
import pytest

from shengji.train.simple_belief_calibration import SCHEMA, analyze


def _position(*, model, reference=None, target=0, ply=0, is_nt=False):
    reference = model if reference is None else reference
    probabilities = [[[1.0, 0.0, 0.0] for _ in range(54)] for _ in range(4)]
    references = [[[1.0, 0.0, 0.0] for _ in range(54)] for _ in range(4)]
    targets = [[0 for _ in range(54)] for _ in range(4)]
    uncertain = [[False for _ in range(54)] for _ in range(4)]
    probabilities[0][0], references[0][0] = model, reference
    targets[0][0], uncertain[0][0] = target, True
    return {"probabilities": probabilities,
            "reference_probabilities": references, "targets": targets,
            "uncertain": uncertain, "ply": ply, "trump_rank": "2",
            "is_nt": is_nt, "is_banker": False, "state_key": "state-1"}


def _write_input(root, rows):
    (root / "recipe.json").write_text(json.dumps({
        "schema": SCHEMA, "checkpoint_sha256": "checkpoint"}))
    (root / "summary.json").write_text(json.dumps({
        "schema": SCHEMA, "deals": 1, "positions": len(rows)}))
    (root / "deal.json").write_text(json.dumps({
        "deal_key": "deck:test", "identity": "identity", "rows": rows}))


def test_miscalibration_has_per_class_ece_and_expected_count_errors(tmp_path):
    row = _position(model=[0.7, 0.2, 0.1], reference=[.5,.5,0.], target=0)
    row2 = _position(model=[0.7, 0.2, 0.1], reference=[.5,.5,0.], target=1)
    _write_input(tmp_path, [row, row2])
    result = analyze(tmp_path)
    # Three different answers: pooled numerators or constant curves cannot pass.
    assert result["reliability"]["class_0"]["ece"] == pytest.approx(.2)
    assert result["reliability"]["class_1"]["ece"] == pytest.approx(.3)
    assert result["reliability"]["class_2"]["ece"] == pytest.approx(.1)
    assert result["reliability"]["class_0"]["bins"][7]["count"] == 2
    assert result["reliability"]["class_1"]["bins"][2]["count"] == 2
    assert result["reliability"]["class_2"]["bins"][1]["count"] == 2
    assert result["expected_card_count"]["receiver_0"]["signed_error"] == pytest.approx(-.1)
    assert result["expected_card_count"]["receiver_0"]["absolute_error"] == pytest.approx(.5)
    assert all(r["ece"] == 0 for r in result["reference_reliability_raw_mc"].values())


def test_reference_identical_gives_zero_paired_brier(tmp_path):
    rows = [_position(model=[0.9, 0.1, 0.0], target=0),
            _position(model=[0.9, 0.1, 0.0], target=1, ply=2, is_nt=True)]
    _write_input(tmp_path, rows)
    result = analyze(tmp_path)
    assert result["positions"] == 2
    assert result["reliability"]["class_0"]["ece"] == 0.4
    assert result["reliability"]["class_1"]["ece"] == 0.4
    assert result["expected_card_count"]["receiver_0"]["signed_error"] == -0.4
    assert result["paired_raw_brier"]["overall_and_phase"]["all"]["difference"] == 0.0
    assert all(group["difference"] == 0.0
               for group in result["paired_raw_brier"]["overall_and_phase"].values()
               if group["positions"])
    assert result['top_positions'] == {'helpful': [], 'harmful': []}


def test_harmful_position_explains_harmful_cells_not_larger_helpful_ones(tmp_path):
    row = _position(model=[1.,0.,0.], reference=[0.,1.,0.], target=0)
    # One large improvement (-2), outweighed by six smaller regressions (+.5).
    for card in range(1,7):
        row['probabilities'][0][card] = [.5,.5,0.]
        row['reference_probabilities'][0][card] = [1.,0.,0.]
        row['uncertain'][0][card] = True
    _write_input(tmp_path, [row])
    result = analyze(tmp_path)['top_positions']
    assert result['helpful'] == []
    worst = result['harmful'][0]
    assert worst['difference'] == pytest.approx(1/7)
    assert worst['explanation_direction'] == 'higher_error'
    assert len(worst['explanations']) == 3
    assert all(cell['squared_error_difference'] == .5 and cell['card_index'] != 0
               and cell['card'] for cell in worst['explanations'])
