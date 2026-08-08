"""Outcome-free O0-v2 integration guard for shared public-view CRN keys.

The mechanics module supplies arm-independent keyed draws, but a future runner
could still defeat that property by deriving each arm's key from its own model
input.  The oracle input contains privileged planes, so that mistake silently
turns common random numbers back into independent random numbers.

This module closes that integration boundary in two ways:

* the only runner-facing decision endpoint derives its key directly from one
  legal public projection of :class:`~shengji.engine.round.Round`; it accepts no
  arm, model, logits, mask or privileged observation; and
* every crossed seed/iteration pair must publish outcome-free key receipts.
  The gate requires the first ordinary-play public context to couple in 100%
  of pairs.  Later aligned-position coupling is diagnostic only because the
  policies may legitimately choose different first actions and then reach
  different public histories.

There is deliberately no collector, learner, population, CLI, artifact writer,
launch authority, strength claim or production policy here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.round import Round
from .actions import enumerate_actions
from .douzero_micro import encode_public_history
from .encode import encode_obs
from .exact_resume import state_digest
from .suphx_micro import PERFECT_DIM, encode_legal_private
from .suphx_o0_v2_mechanics import (
    ARMS,
    MECHANICS_SPEC_SHA256,
    CrossedCRNSpec,
    CrossedCRNStreams,
    SuphxO0V2MechanicsError,
    public_decision_key,
)
from .suphx_policy import role_for, surface_for


INTEGRATION_SCHEMA = "suphx-o0-v2-public-crn-integration-v1"
PUBLIC_PROJECTION_SCHEMA = "suphx-o0-v2-round-public-projection-v1"
ARM_RECEIPT_SCHEMA = "suphx-o0-v2-arm-key-receipt-v1"
COUPLING_GATE_SCHEMA = "suphx-o0-v2-cross-arm-key-coupling-gate-v1"
MINIMUM_INITIAL_PUBLIC_KEY_COUPLING_RATE = 1.0

_MECHANICS_RECEIPT_FIELDS = {
    "schema", "spec_sha256", "training_seed_index", "iteration",
    "deal_seed", "public_decision_keys", "public_decision_keys_sha256",
    "arm_identity_in_draw_key", "outcomes",
}
_ARM_RECEIPT_FIELDS = {
    "schema", "integration_schema", "mechanics_spec_sha256", "arm",
    "complete", "public_projection_schema", "decision_count",
    "first_public_decision_key", "mechanics_receipt", "outcomes",
    "strength_scores", "strength_claim", "production_promotion",
}


class SuphxO0V2IntegrationError(SuphxO0V2MechanicsError):
    """The shared-public-view integration contract was violated."""


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


@dataclass(frozen=True)
class PublicDecisionProjection:
    """The exact legal/public material used both by the actor and CRN key."""

    deal_seed: int
    seat: int
    role: int
    surface: int
    observation: np.ndarray
    legal_private: np.ndarray
    history: np.ndarray
    candidate_cards: tuple[tuple[str, ...], ...]
    public_key: str


def project_public_decision(
        rnd: Round, seat: int, *, deal_seed: int) -> PublicDecisionProjection:
    """Project one ordinary-play turn without accepting privileged inputs.

    ``encode_feature_partition`` returns a separate ``perfect`` tensor, but it
    is intentionally discarded here.  The returned public tensors are the same
    objects a v2 actor must feed to both endpoint models; only the separately
    masked perfect tensor may differ between oracle and public arms.
    """
    if not isinstance(rnd, Round) or rnd.phase != "play" \
            or rnd.turn != seat or rnd.trick is None or rnd.ordering is None:
        raise SuphxO0V2IntegrationError(
            "public projection requires the exact acting ordinary-play turn")
    if isinstance(deal_seed, bool) or not isinstance(deal_seed, int) \
            or deal_seed < 0:
        raise SuphxO0V2IntegrationError(
            "public projection deal seed must be a nonnegative integer")
    actions = enumerate_actions(
        rnd, seat, exhaustive_follows=False, include_throws=False)
    if not actions:
        raise SuphxO0V2IntegrationError(
            "public projection ordinary-play ballot is empty")
    # Call the three public/legal encoders directly.  In particular, do not
    # call ``encode_feature_partition`` and then discard ``perfect``: never
    # constructing the privileged tensor makes accidental inclusion a much
    # harder class of failure.  Freeze the arrays after hashing so a caller
    # cannot mutate the model input away from the key it was paired with.
    observation = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
    legal_private = encode_legal_private(rnd, seat).copy()
    history = encode_public_history(rnd, seat).copy()
    candidate_cards = tuple(tuple(action) for action in actions)
    role = role_for(rnd, seat)
    surface = surface_for(rnd)
    key = public_decision_key(
        deal_seed=deal_seed,
        seat=seat,
        role=role,
        surface=surface,
        observation=observation,
        legal_private=legal_private,
        history=history,
        candidate_cards=candidate_cards,
    )
    for value in (observation, legal_private, history):
        value.setflags(write=False)
    return PublicDecisionProjection(
        deal_seed=deal_seed,
        seat=seat,
        role=role,
        surface=surface,
        observation=observation,
        legal_private=legal_private,
        history=history,
        candidate_cards=candidate_cards,
        public_key=key,
    )


@dataclass(frozen=True)
class KeyedDecisionDraws:
    """One public projection and its arm-independent named draws."""

    projection: PublicDecisionProjection
    occurrence: int
    mask_uniforms: tuple[float, ...]
    action_uniform: float


@dataclass
class SharedPublicDecisionCRN:
    """Runner-facing CRN endpoint that cannot see endpoint identity."""

    streams: CrossedCRNStreams
    _keys: list[str] = field(default_factory=list, init=False, repr=False)
    _occurrences: Counter[str] = field(
        default_factory=Counter, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.streams, CrossedCRNStreams):
            raise SuphxO0V2IntegrationError(
                "shared public CRN requires exact crossed streams")

    def decision_draws(self, rnd: Round, seat: int) -> KeyedDecisionDraws:
        projection = project_public_decision(
            rnd, seat, deal_seed=self.streams.deal_seed())
        key = projection.public_key
        occurrence = self._occurrences[key]
        self._occurrences[key] += 1
        self._keys.append(key)
        return KeyedDecisionDraws(
            projection=projection,
            occurrence=occurrence,
            mask_uniforms=self.streams.mask_uniforms(key, PERFECT_DIM),
            action_uniform=self.streams.action_uniform(key, occurrence),
        )

    def receipt(self, *, arm: str) -> dict[str, Any]:
        """Publish hashes/work only; ``arm`` is added after draw derivation."""
        if arm not in ARMS:
            raise SuphxO0V2IntegrationError(
                f"unsupported O0-v2 endpoint receipt {arm!r}")
        if not self._keys:
            raise SuphxO0V2IntegrationError(
                "cannot publish an empty public-key receipt")
        mechanics = self.streams.receipt(self._keys)
        return {
            "schema": ARM_RECEIPT_SCHEMA,
            "integration_schema": INTEGRATION_SCHEMA,
            "mechanics_spec_sha256": MECHANICS_SPEC_SHA256,
            "arm": arm,
            "complete": True,
            "public_projection_schema": PUBLIC_PROJECTION_SCHEMA,
            "decision_count": len(self._keys),
            "first_public_decision_key": self._keys[0],
            "mechanics_receipt": mechanics,
            "outcomes": None,
            "strength_scores": None,
            "strength_claim": False,
            "production_promotion": False,
        }


def _receipt_problems(
        receipt: object, spec: CrossedCRNSpec) -> list[str]:
    problems: list[str] = []
    if not isinstance(receipt, Mapping) \
            or set(receipt) != _ARM_RECEIPT_FIELDS:
        return ["arm key receipt fields mismatch"]
    if receipt.get("schema") != ARM_RECEIPT_SCHEMA \
            or receipt.get("integration_schema") != INTEGRATION_SCHEMA \
            or receipt.get("mechanics_spec_sha256") != MECHANICS_SPEC_SHA256 \
            or receipt.get("arm") not in ARMS \
            or receipt.get("complete") is not True \
            or receipt.get("public_projection_schema") \
            != PUBLIC_PROJECTION_SCHEMA \
            or receipt.get("outcomes") is not None \
            or receipt.get("strength_scores") is not None \
            or receipt.get("strength_claim") is not False \
            or receipt.get("production_promotion") is not False:
        problems.append("arm key receipt identity/authority drift")
    mechanics = receipt.get("mechanics_receipt")
    if not isinstance(mechanics, Mapping) \
            or set(mechanics) != _MECHANICS_RECEIPT_FIELDS:
        problems.append("mechanics key receipt fields mismatch")
        return problems
    expected_spec = state_digest(spec.as_dict())
    index = mechanics.get("training_seed_index")
    iteration = mechanics.get("iteration")
    if mechanics.get("schema") != "suphx-o0-v2-crn-iteration-receipt-v1" \
            or mechanics.get("spec_sha256") != expected_spec \
            or isinstance(index, bool) or not isinstance(index, int) \
            or index not in spec.training_seed_indices \
            or isinstance(iteration, bool) \
            or not isinstance(iteration, int) \
            or not 0 <= iteration < spec.iterations_per_arm \
            or mechanics.get("arm_identity_in_draw_key") is not False \
            or mechanics.get("outcomes") is not None:
        problems.append("mechanics key receipt identity/authority drift")
    if isinstance(index, int) and not isinstance(index, bool) \
            and isinstance(iteration, int) and not isinstance(iteration, bool) \
            and index in spec.training_seed_indices \
            and 0 <= iteration < spec.iterations_per_arm:
        expected_deal = CrossedCRNStreams(
            spec, index, iteration).deal_seed()
        if mechanics.get("deal_seed") != expected_deal:
            problems.append("mechanics key receipt deal drift")
    keys = mechanics.get("public_decision_keys")
    if not isinstance(keys, list) or not keys \
            or any(not _is_sha256(value) for value in keys):
        problems.append("mechanics public-key population malformed")
    else:
        if mechanics.get("public_decision_keys_sha256") != state_digest(keys):
            problems.append("mechanics public-key digest drift")
        if receipt.get("decision_count") != len(keys) \
                or receipt.get("first_public_decision_key") != keys[0]:
            problems.append("arm/mechanics public-key reconciliation drift")
    count = receipt.get("decision_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0 \
            or not _is_sha256(receipt.get("first_public_decision_key")):
        problems.append("arm key receipt decision summary malformed")
    return sorted(set(problems))


def cross_arm_coupling_gate(
        spec: CrossedCRNSpec,
        receipts: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    """Measure and gate the complete crossed-grid public-key coupling.

    The first decision must couple for every pair because declaration and bury
    remain shared SmartBot controls.  Later aligned positions are reported but
    not gated: different sampled first actions legitimately fork public state.
    """
    if not isinstance(spec, CrossedCRNSpec):
        raise SuphxO0V2IntegrationError(
            "coupling gate requires an exact crossed CRN spec")
    if not isinstance(receipts, Sequence) \
            or isinstance(receipts, (str, bytes)):
        raise SuphxO0V2IntegrationError(
            "coupling gate receipts must be a sequence")
    expected_cells = {
        (index, iteration)
        for index in spec.training_seed_indices
        for iteration in range(spec.iterations_per_arm)
    }
    by_cell: dict[tuple[int, int], dict[str, Mapping[str, object]]] = {}
    problems: list[str] = []
    for position, receipt in enumerate(receipts):
        receipt_problems = _receipt_problems(receipt, spec)
        problems.extend(
            f"receipt {position}: {problem}" for problem in receipt_problems)
        if receipt_problems or not isinstance(receipt, Mapping):
            continue
        mechanics = receipt["mechanics_receipt"]
        assert isinstance(mechanics, Mapping)
        cell = (mechanics["training_seed_index"], mechanics["iteration"])
        arm = receipt["arm"]
        assert isinstance(cell[0], int) and isinstance(cell[1], int) \
            and isinstance(arm, str)
        arms = by_cell.setdefault(cell, {})
        if arm in arms:
            problems.append(
                f"duplicate {arm} key receipt for seed/iteration {cell}")
        else:
            arms[arm] = receipt
    observed_cells = set(by_cell)
    missing = sorted(expected_cells - observed_cells)
    extra = sorted(observed_cells - expected_cells)
    if missing:
        problems.append(f"missing crossed key receipt cells: {missing}")
    if extra:
        problems.append(f"unexpected crossed key receipt cells: {extra}")

    paired = 0
    deal_matches = 0
    initial_matches = 0
    aligned_positions = 0
    aligned_matches = 0
    shared_prefix_total = 0
    minimum_shared_prefix: int | None = None
    for cell in sorted(expected_cells & observed_cells):
        arms = by_cell[cell]
        if set(arms) != set(ARMS):
            problems.append(
                f"seed/iteration {cell} lacks exact oracle/public receipts")
            continue
        oracle = arms["oracle"]["mechanics_receipt"]
        public = arms["public"]["mechanics_receipt"]
        assert isinstance(oracle, Mapping) and isinstance(public, Mapping)
        oracle_keys = oracle["public_decision_keys"]
        public_keys = public["public_decision_keys"]
        assert isinstance(oracle_keys, list) and isinstance(public_keys, list)
        paired += 1
        deal_matches += int(oracle["deal_seed"] == public["deal_seed"])
        initial_matches += int(oracle_keys[0] == public_keys[0])
        overlap = min(len(oracle_keys), len(public_keys))
        aligned_positions += overlap
        aligned_matches += sum(
            left == right for left, right in zip(oracle_keys, public_keys))
        prefix = 0
        for left, right in zip(oracle_keys, public_keys):
            if left != right:
                break
            prefix += 1
        shared_prefix_total += prefix
        minimum_shared_prefix = prefix if minimum_shared_prefix is None \
            else min(minimum_shared_prefix, prefix)
    expected_pairs = len(expected_cells)
    initial_rate = initial_matches / paired if paired else 0.0
    aligned_rate = aligned_matches / aligned_positions \
        if aligned_positions else 0.0
    if paired != expected_pairs:
        problems.append("crossed key receipt pair count is incomplete")
    if deal_matches != paired:
        problems.append("oracle/public paired deal coupling drift")
    if initial_rate < MINIMUM_INITIAL_PUBLIC_KEY_COUPLING_RATE:
        problems.append("initial public-key coupling rate below floor")
    if minimum_shared_prefix is None:
        problems.append("crossed key receipt population has no pairs")
    elif minimum_shared_prefix < 1:
        # A larger minimum is fine and expected when policies happen to agree.
        problems.append("a crossed pair has no shared public-key prefix")
    unique_problems = sorted(set(problems))
    return {
        "schema": COUPLING_GATE_SCHEMA,
        "integration_schema": INTEGRATION_SCHEMA,
        "mechanics_spec_sha256": MECHANICS_SPEC_SHA256,
        "crn_spec_sha256": state_digest(spec.as_dict()),
        "complete_crossed_grid_required": True,
        "training_seed_count": len(spec.training_seed_indices),
        "iterations_per_arm": spec.iterations_per_arm,
        "expected_pairs": expected_pairs,
        "paired_receipts": paired,
        "paired_deal_matches": deal_matches,
        "initial_public_key_matches": initial_matches,
        "initial_public_key_coupling_rate": initial_rate,
        "minimum_initial_public_key_coupling_rate":
            MINIMUM_INITIAL_PUBLIC_KEY_COUPLING_RATE,
        "minimum_shared_prefix_decisions": minimum_shared_prefix,
        "shared_prefix_decisions_total": shared_prefix_total,
        "aligned_position_key_matches": aligned_matches,
        "aligned_position_key_count": aligned_positions,
        "aligned_position_key_coupling_rate_diagnostic": aligned_rate,
        "later_alignment_is_gate": False,
        "problems": unique_problems,
        "passed": not unique_problems,
        "experiment_launch_authorized": False,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }


def integration_spec() -> dict[str, Any]:
    return {
        "schema": INTEGRATION_SCHEMA,
        "claim": "outcome-free CRN integration only; no recipe conclusion",
        "public_projection_schema": PUBLIC_PROJECTION_SCHEMA,
        "key_source": "one round-derived public projection for both arms",
        "key_excludes": [
            "arm", "model", "checkpoint", "logits", "mask",
            "perfect_or_hidden_features", "outcome",
        ],
        "crossed_grid_required": True,
        "minimum_training_seeds": 8,
        "iterations_per_arm": 64,
        "first_public_context_coupling_rate_floor":
            MINIMUM_INITIAL_PUBLIC_KEY_COUPLING_RATE,
        "later_aligned_position_rate": "diagnostic_only_after_policy_fork",
        "experiment_launch_authorized": False,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }


INTEGRATION_SPEC = integration_spec()
INTEGRATION_SPEC_SHA256 = state_digest(INTEGRATION_SPEC)
