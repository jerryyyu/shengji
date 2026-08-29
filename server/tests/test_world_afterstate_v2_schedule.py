import dataclasses
import hashlib

import numpy as np
import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_schedule import (
    BLOCK_1, BLOCK_2, DATA_ORDER_SEEDS_BLOCK_1, MAX_EPOCHS,
    WorldAfterstateV2ScheduleError, build_training_batches,
    derive_nested_prefixes,
    reuse_schedule_for_control,
    select_common_epoch, training_epoch_batches,
    validate_common_epoch_checkpoints, validate_control_schedule_match,
    validate_schedule_receipt, validate_seed_blocks,
)
from shengji.rl.world_afterstate_v2_training import WorldAfterstateV2TrainingExample


def _hex(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _rows(name, deals=4, candidates=2, cohort="primary"):
    rows = []
    for deal_no in range(deals):
        root = f"{name}:{deal_no}"
        deal, slot, state = (_hex(root + x) for x in (":deal", ":slot", ":state"))
        successors = [_hex(root + f":successor:{index}") for index in range(candidates)]
        cset = hashlib.sha256(canonical_json_bytes({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": state, "successor_sha256s": successors})).hexdigest()
        for candidate, successor in enumerate(successors):
            for replica in range(8):
                public = np.zeros(PUBLIC_DIM, dtype=np.float32)
                public[deal_no % PUBLIC_DIM] = 1
                world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
                world[0, candidate] = 1
                rows.append(WorldAfterstateV2TrainingExample(
                    deal, slot, state, cset, candidate, candidate == 0,
                    successor, _hex(root + f":continuation:{replica}"), replica,
                        "natural", "fit", "attacker", "early", "lead",
                        "2", "S",
                        WorldAfterstateTensorsV0(
                        public, np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
                        world, np.array([1.0, 0.0], dtype=np.float32)),
                    (candidate + replica) % 204, cohort))
    return tuple(rows)


def test_root_grouped_schedule_and_frozen_seed_blocks():
    rows = _rows("schedule")
    schedule, batches = training_epoch_batches(rows, epoch=1, batch_example_cap=16)
    assert sum(batch.size for batch in batches) == len(rows)
    assert all(batch.root_count == 1 for batch in batches)
    assert schedule.batch_example_cap == 16
    assert schedule.sha256() == schedule.sha256()
    validate_seed_blocks()
    assert BLOCK_1.name == "block-1-primary"
    assert BLOCK_2.name == "block-2-confirmatory"
    assert not set(BLOCK_1.initialization_seeds + BLOCK_1.data_order_seeds) & set(
        BLOCK_2.initialization_seeds + BLOCK_2.data_order_seeds)


def test_schedule_rejects_root_drop_and_duplicate_but_accepts_source_mix():
    rows = _rows("reject")
    with pytest.raises(WorldAfterstateV2ScheduleError, match="incomplete"):
        training_epoch_batches(rows[:-1], epoch=1)
    with pytest.raises(WorldAfterstateV2ScheduleError, match="duplicate"):
        training_epoch_batches(rows + (rows[0],), epoch=1)
    mixed = tuple(dataclasses.replace(
        row, source="pt-sol" if row.deal_sha256 == rows[0].deal_sha256
        else row.source) for row in rows)
    schedule, batches = training_epoch_batches(mixed, epoch=1)
    assert schedule.source == "mixed"
    assert sum(batch.size for batch in batches) == len(mixed)
    receipt_batches, receipt = build_training_batches(mixed, epoch=1)
    validate_schedule_receipt(receipt)
    assert receipt["source"] == "mixed"
    assert sum(batch.size for batch in receipt_batches) == len(mixed)


def test_control_order_match_ignores_sealed_tensor_and_label_transform():
    natural = _rows("control")
    control = tuple(dataclasses.replace(row, cohort="control",
                                        signed_level_category=(row.signed_level_category + 1) % 204)
                    for row in natural)
    first, _ = training_epoch_batches(natural, epoch=1,
                                      data_order_seed=DATA_ORDER_SEEDS_BLOCK_1[0])
    second, _ = reuse_schedule_for_control(
        first, control, control_name="label-permutation")
    assert second.control_name == "label-permutation"
    validate_control_schedule_match(first, second)


def test_common_epoch_is_four_member_common_and_rejects_audit_or_truncation():
    losses = tuple((1_000_000, 900_000, 900_000, 900_000, 899_000)
                   for _ in range(4))
    decision = select_common_epoch(losses)
    assert decision.selected_epoch == 5
    assert decision.stop_epoch == 5
    with pytest.raises(WorldAfterstateV2ScheduleError, match="four-member"):
        select_common_epoch(losses[:3])
    with pytest.raises(WorldAfterstateV2ScheduleError, match="audit"):
        select_common_epoch(tuple(tuple(row) for row in losses) + ({"audit": 1},))
    with pytest.raises(WorldAfterstateV2ScheduleError, match="truncated"):
        validate_common_epoch_checkpoints((1, 2, 3), selected_epoch=1)
    with pytest.raises(WorldAfterstateV2ScheduleError, match="epoch count"):
        select_common_epoch(tuple((1,) * (MAX_EPOCHS + 1) for _ in range(4)))


def test_nested_prefixes_select_complete_deal_groups():
    rows = _rows("prefix", deals=8)
    prefixes = derive_nested_prefixes(rows)
    assert len(prefixes[0.25]) == len(rows) // 4
    assert len(prefixes[0.50]) == len(rows) // 2
    assert len(prefixes[1.0]) == len(rows)
    assert {row.example_key for row in prefixes[0.25]}.issubset(
        {row.example_key for row in prefixes[0.50]})
    for prefix in prefixes.values():
        assert {row.deal_sha256 for row in prefix}
        assert len(prefix) % 16 == 0
