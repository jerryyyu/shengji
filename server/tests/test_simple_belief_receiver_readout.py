import json

import pytest

from shengji.train.simple_belief_receiver_readout import analyze, corrected_brier


def _probability(p, cards=(0,)):
    result = [[[1.0, 0.0, 0.0] for _ in range(54)] for _ in range(4)]
    for card in cards:
        result[0][card] = list(p)
    return result


def _row(state, *, model=(1.0, 0.0, 0.0), ordinary=(.5, .5, 0.0),
         primary=(.8, .2, 0.0), control=(.6, .4, 0.0), kitty=False,
         uncertain_cards=1):
    uncertain = [[False for _ in range(54)] for _ in range(4)]
    cards = tuple(range(uncertain_cards))
    if kitty:
        for card in cards:
            uncertain[3][card] = True
    else:
        for card in cards:
            uncertain[0][card] = True
    return {
        "state_key": state,
        "probabilities": _probability(model, cards),
        "reference_probabilities": _probability(ordinary, cards),
        "targets": [[0 for _ in range(54)] for _ in range(4)],
        "uncertain": uncertain,
    }, {
        "state_key": state,
        "arms": {
            "synthetic-primary": {"probabilities": _probability(primary)},
            "hard-geometry-label-permutation": {"probabilities": _probability(control)},
        },
    }


def _write_pair(root, deal_rows):
    reference = root / "reference"
    r4 = root / "r4"
    reference.mkdir()
    r4.mkdir()
    (reference / "recipe.json").write_text(json.dumps({
        "schema": "simple-belief-reference-readout-v1", "worlds": 256,
    }))
    (r4 / "recipe.json").write_text(json.dumps({
        "schema": "simple-belief-r4-compare-v1",
    }))
    (reference / "summary.json").write_text(json.dumps({
        "schema": "simple-belief-reference-readout-v1", "deals": len(deal_rows),
    }))
    (r4 / "summary.json").write_text(json.dumps({
        "schema": "simple-belief-r4-compare-v1", "deals": len(deal_rows),
    }))
    for index, rows in enumerate(deal_rows):
        ref_rows, r4_rows = zip(*rows)
        payload = {"deal_key": f"deck:{index}", "identity": str(index), "rows": ref_rows}
        (reference / f"{index}.json").write_text(json.dumps(payload))
        payload = {"deal_key": f"deck:{index}", "identity": str(index), "rows": r4_rows}
        (r4 / f"{index}.json").write_text(json.dumps(payload))
    return reference, r4


def test_equal_deal_weight_and_mc_correction_sign_with_unequal_rows(tmp_path):
    # Within deal zero, one position has one uncertain cell and one has two.
    # Its position means are .0 and .5, so the deal mean is .25 rather than
    # the cell-weighted 1/3.  Deal one supplies a second equal-weight deal.
    first_deal = [_row("a0", model=(1, 0, 0)),
                  _row("a1", model=(.5, .5, 0), uncertain_cards=2)]
    second_deal = [_row("b0", model=(.5, .5, 0))]
    reference, r4 = _write_pair(tmp_path, [first_deal, second_deal])
    result = analyze(reference, r4)
    assert result["opponents"]["per_deal"]["deck:0"]["newmodel"] == pytest.approx(.25)
    assert result["equal_deal_mean_brier"]["opponents"]["newmodel"] == pytest.approx(.375)
    assert result["opponents"]["positions"] == 3
    assert result["opponents"]["uncertain_cells"] == 4
    assert result["opponents"]["deals"] == 2
    raw = result["equal_deal_mean_brier"]["opponents"]["ordinary_raw"]
    debiased = result["equal_deal_mean_brier"]["opponents"]["ordinary_debiased"]
    assert debiased < raw
    assert corrected_brier(raw, .25) == pytest.approx(raw - .25)
    assert result["kitty"]["absent_receiver_group_rows_skipped"] == 3


def test_missing_or_mismatched_state_join_fails(tmp_path):
    rows = [[_row("state-a")]]
    reference, r4 = _write_pair(tmp_path, rows)
    payload = json.loads((r4 / "0.json").read_text())
    payload["rows"][0]["state_key"] = "state-b"
    (r4 / "0.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="state join population differs"):
        analyze(reference, r4)


def test_cli_style_output_is_not_overwritten(tmp_path):
    rows = [[_row("state-a")]]
    reference, r4 = _write_pair(tmp_path, rows)
    output = tmp_path / "report.json"
    output.write_text("sentinel")
    assert output.read_text() == "sentinel"
