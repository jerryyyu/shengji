"""Bounded Stage-C proposal focusing for a future report-LCB composition.

The learned model never directly overrides the incumbent here.  It selects at
most one challenger from an already frozen public-information candidate union.
The treatment pair is incumbent versus that challenger.  A matched null uses
the exact same model trigger (and therefore the same number of searched arms)
but substitutes one deterministic random non-incumbent candidate.  A later
reviewed policy wrapper may feed those pairs to fresh paired report-LCB search.

This module does not generate ballots, sample worlds, play cards, register a
bot, open evidence, or authorize strength/promotion/deployment.
"""
from __future__ import annotations

import hashlib
from typing import Sequence

from .encode import encode_action, encode_obs
from .stage_c_npnet import StageCEnsemble


SCHEMA = "teacher-stage-c-focused-proposal-v1"
PLAY_CANDIDATE_CAP = 20
BURY_CANDIDATE_CAP = 33


class StageCCompositionError(RuntimeError):
    """A candidate union, surface, model result, or null identity drifted."""


def action_key(cards: Sequence[object]) -> tuple[str, ...]:
    if (not isinstance(cards, (list, tuple)) or not cards
            or any(not isinstance(card, str) or not card for card in cards)):
        raise StageCCompositionError("Stage-C composition action geometry drift")
    return tuple(sorted(cards))


def _candidate_union(candidates: Sequence[Sequence[str]], surface: str
                     ) -> list[list[str]]:
    if surface not in {"play", "bury"} or not isinstance(candidates, (list, tuple)):
        raise StageCCompositionError("Stage-C composition surface/union drift")
    cap = PLAY_CANDIDATE_CAP if surface == "play" else BURY_CANDIDATE_CAP
    values = [list(candidate) for candidate in candidates]
    keys = [action_key(value) for value in values]
    if not values or len(values) > cap or len(set(keys)) != len(keys):
        raise StageCCompositionError("Stage-C composition candidate union drift")
    return values


def _matched_random_index(candidates: Sequence[Sequence[str]], *,
                          state_key: str) -> int:
    if not isinstance(state_key, str) or not state_key:
        raise StageCCompositionError("Stage-C composition state key drift")
    if len(candidates) <= 1:
        return 0
    identity = [list(action_key(candidate)) for candidate in candidates]
    digest = hashlib.sha256(
        ("teacher-stage-c-composition-null-v1|" + state_key + "|"
         + repr(identity)).encode()).digest()
    return 1 + int.from_bytes(digest[:16], "big") % (len(candidates) - 1)


def focused_pairs(
    ensemble: StageCEnsemble, rnd, seat: int,
    candidates: Sequence[Sequence[str]], *, state_key: str,
) -> dict:
    """Freeze treatment/null arms with identical model-triggered work geometry."""
    surface = ensemble.surface
    values = _candidate_union(candidates, surface)
    if (not isinstance(seat, int) or not 0 <= seat < 4
            or (surface == "play"
                and (getattr(rnd, "phase", None) != "play"
                     or getattr(rnd, "turn", None) != seat))
            or (surface == "bury"
                and (getattr(rnd, "phase", None) != "bury"
                     or getattr(rnd, "banker", None) != seat))):
        raise StageCCompositionError("Stage-C composition decision surface drift")
    obs = encode_obs(rnd, seat)
    actions = [encode_action(candidate, rnd) for candidate in values]
    selection = ensemble.select(obs, actions)
    model_index = selection.get("selected_index")
    if (isinstance(model_index, bool) or not isinstance(model_index, int)
            or not 0 <= model_index < len(values)
            or selection.get("surface") != surface
            or selection.get("candidate_count") != len(values)):
        raise StageCCompositionError("Stage-C composition model selection drift")
    triggered = model_index != 0
    null_index = (_matched_random_index(values, state_key=state_key)
                  if triggered else 0)
    treatment_indices = [0] if not triggered else [0, model_index]
    null_indices = [0] if not triggered else [0, null_index]
    result = {
        "schema": SCHEMA,
        "surface": surface,
        "head": ensemble.head,
        "epoch": ensemble.epoch,
        "state_key": state_key,
        "candidate_count": len(values),
        "candidate_keys": [list(action_key(value)) for value in values],
        "incumbent_index": 0,
        "model_selected_index": model_index,
        "model_triggered": triggered,
        "matched_random_index": null_index,
        "treatment_indices": treatment_indices,
        "null_indices": null_indices,
        "treatment_candidates": [values[index] for index in treatment_indices],
        "null_candidates": [values[index] for index in null_indices],
        "searched_arms_treatment": len(treatment_indices),
        "searched_arms_null": len(null_indices),
        "selection": selection,
        "model_direct_override_authorized": False,
        "fresh_paired_report_lcb_required": triggered,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if (result["treatment_candidates"][0] != values[0]
            or result["null_candidates"][0] != values[0]
            or result["searched_arms_treatment"]
            != result["searched_arms_null"]):
        raise StageCCompositionError("Stage-C composition matched-arm drift")
    return result
