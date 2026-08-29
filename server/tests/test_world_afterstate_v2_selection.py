import dataclasses

import pytest

from shengji.rl.world_afterstate_v2_model import new_world_afterstate_v2_model
from shengji.rl.world_afterstate_v2_selection import (
    WorldAfterstateV2SelectionError, score_epoch_select_v2)
from shengji.rl.world_afterstate_v2_training import model_state_sha256
from test_world_afterstate_v2_evaluation import _population


def _selection_population():
    _predictions, outcomes, _prior, root = _population(root="epoch-select")
    return (dataclasses.replace(
                root, split="select", select_subfold="epoch-select"),
            tuple(dataclasses.replace(row, split="select")
                  for row in outcomes))


def _score(model, root, outcomes):
    return score_epoch_select_v2(
        model, roots=(root,), outcomes=outcomes, epoch=1,
        seed_block=1, member_index=0, control_name="natural",
        sigma_pair_squared=1.0)


def test_epoch_select_score_is_deterministic_bound_and_model_immutable():
    root, outcomes = _selection_population()
    model = new_world_afterstate_v2_model(7)
    before = model_state_sha256(model)
    first = _score(model, root, outcomes)
    second = _score(model, root, outcomes)
    assert first == second
    assert first.loss_nano > 0
    assert first.model_state_sha256 == before == model_state_sha256(model)
    assert first.split == "select"
    assert first.select_subfold == "epoch-select"


def test_epoch_select_refuses_audit_roots_and_dropped_or_foreign_outcomes():
    root, outcomes = _selection_population()
    model = new_world_afterstate_v2_model(7)
    with pytest.raises(WorldAfterstateV2SelectionError,
                       match="root population"):
        _score(model, dataclasses.replace(
            root, split="audit", select_subfold=None), outcomes)
    with pytest.raises(WorldAfterstateV2SelectionError,
                       match="root population"):
        _score(model, dataclasses.replace(
            root, select_subfold="precision-select"), outcomes)
    with pytest.raises(WorldAfterstateV2SelectionError, match="drop"):
        _score(model, root, outcomes[:-1])
    with pytest.raises(WorldAfterstateV2SelectionError, match="foreign"):
        _score(model, root, (dataclasses.replace(
            outcomes[0], state_sha256="0" * 64), *outcomes[1:]))


def test_epoch_select_crn_link_is_witnessed():
    root, outcomes = _selection_population()
    forged = list(outcomes)
    forged[-1] = dataclasses.replace(
        forged[-1], continuation_sha256="1" * 64)
    with pytest.raises(WorldAfterstateV2SelectionError, match="CRN"):
        _score(new_world_afterstate_v2_model(7), root, tuple(forged))
