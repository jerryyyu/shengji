"""Batched outcome-value continuations for DEV search (#436).

Inputs are already determinized afterstates, not live opponent hands. A horizon
is measured in completed tricks relative to the PRE-action root: k=0 reads the
immediate afterstate; k=1 completes that root trick, including when the action
itself completed it. None means a full heuristic continuation (levels control).
Values are absolute final signed levels from each supplied seat's TEAM view.
Do not add accrued points, or negate according to the next player to move.
This is a determinized continuation, not an information-set-correct policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..ai.cwv_puct import leaf_copy
from ..ai.heuristic import HeuristicBot
from ..engine.round import Round
from ..rl.value_afterstate import (
    OUTCOME_CLASSES, category_signed_level, terminal_distribution,
)

_SUPPORT = np.asarray([category_signed_level(i) for i in range(OUTCOME_CLASSES)])


@dataclass(frozen=True)
class ContinuationValues:
    values: np.ndarray
    heuristic_plies: int
    terminal_rows: int
    model_rows: int
    model_batches: int


def continuation_values(
    afterstates: Sequence[Round], seats: Sequence[int],
    root_tricks: Sequence[int], *, evaluator, tricks: int | None,
    batch_size: int = 256, policy=None,
) -> ContinuationValues:
    """Advance private copies and score bounded batches, retaining input order.

    The caller owns world sampling and action enumeration. No selection by
    world value occurs here. Terminal outcomes always bypass the learned head.
    An exact-endgame solver is deliberately absent in both arms of this kernel:
    the None control is the same heuristic continued to actual round end.
    """
    if tricks is not None and (type(tricks) is not int or tricks < 0):
        raise ValueError('tricks must be None or a non-negative integer')
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('batch_size must be a positive integer')
    if len(afterstates) != len(seats) or len(seats) != len(root_tricks):
        raise ValueError('misaligned continuation inputs')
    # Validate the whole request before consuming any evaluator work.
    for rnd, seat, start in zip(afterstates, seats, root_tricks, strict=True):
        if rnd.phase not in ('play', 'round_end'):
            raise ValueError('continuation requires a play or terminal state')
        if type(seat) is not int or not 0 <= seat < 4:
            raise ValueError('invalid perspective seat')
        if type(start) is not int or start < 0 or len(rnd.history) not in (start, start + 1):
            raise ValueError('root trick count must precede one action')
    policy = HeuristicBot() if policy is None else policy
    values = np.empty(len(afterstates), dtype=np.float64)
    pending, indices, perspectives = [], [], []
    plies = terminals = rows = batches = 0

    def flush():
        nonlocal rows, batches
        if not pending:
            return
        scores = np.asarray(evaluator.score_many(pending, perspectives), dtype=np.float64)
        if scores.shape != (len(pending),) or not np.isfinite(scores).all():
            raise ValueError('expected one finite signed-level value per leaf')
        values[indices] = scores
        rows += len(pending)
        batches += 1
        pending.clear()
        indices.clear()
        perspectives.clear()

    for i, (state, seat, start) in enumerate(zip(afterstates, seats, root_tricks, strict=True)):
        clone = leaf_copy(state)
        while clone.phase == 'play' and (tricks is None or len(clone.history) < start + tricks):
            mover = clone.turn
            clone.play(mover, policy.decide_play(clone, mover))
            plies += 1
        if clone.phase == 'round_end':
            values[i] = float(terminal_distribution(clone, seat) @ _SUPPORT)
            terminals += 1
        else:
            pending.append(clone)
            perspectives.append(seat)
            indices.append(i)
            if len(pending) == batch_size:
                flush()
    flush()
    return ContinuationValues(values, plies, terminals, rows, batches)
