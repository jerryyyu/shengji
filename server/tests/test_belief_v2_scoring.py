"""Common-surface inference and exact V2 round-score witnesses."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import multiprocessing
import random
from types import SimpleNamespace

import pytest

import shengji.rl.belief_v2_scoring as SCORING
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_information_partition,
)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_refc_capture import capture_ref_c_worlds
from shengji.rl.belief_v2_accelerator import portable_model_state_sha256
from shengji.rl.belief_v2_common_surface import (
    build_common_surface_tensors,
    common_surface_actor,
)
from shengji.rl.belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
from shengji.rl.belief_v2_scoring import (
    V2CohortModelsV1,
    V2ScoringDecisionV1,
    score_v2_round,
    v2_scoring_actor,
)


def _state(seed: int = 15001, plays: int = 5):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declaration = rnd.declaration
            transcript = transcript.with_declaration(
                declaration["seat"], declaration["cards"],
                declaration["strength"])
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declaration = rnd.declaration
            transcript = transcript.with_declaration(
                declaration["seat"], declaration["cards"],
                declaration["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous))
    partition = build_information_partition(rnd, rnd.turn, transcript)
    return rnd, transcript, partition


def _informative_and_empty_decisions(seed: int = 9927):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declaration = rnd.declaration
            transcript = transcript.with_declaration(
                declaration["seat"], declaration["cards"],
                declaration["strength"])
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declaration = rnd.declaration
            transcript = transcript.with_declaration(
                declaration["seat"], declaration["cards"],
                declaration["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    informative = None
    empty = None
    decision_index = 0
    while rnd.phase == "play":
        partition = build_information_partition(rnd, rnd.turn, transcript)
        needs_fixture = (partition.actor.deductions.unseen
                         and informative is None) \
            or not partition.actor.deductions.unseen
        if needs_fixture:
            reference = capture_ref_c_worlds(
                rnd, rnd.turn, transcript,
                sampler_seed=17011 + decision_index)
            common = build_common_surface_tensors(
                partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
            decision = V2ScoringDecisionV1(
                decision_key=hashlib.sha256(
                    f"decision-{decision_index}".encode("ascii")
                ).hexdigest(),
                source_actor=partition.actor, target=partition.targets,
                common=common, reference=reference)
            if partition.actor.deductions.unseen:
                informative = decision
            else:
                empty = decision
        if empty is not None:
            break
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous))
        decision_index += 1
    assert informative is not None and empty is not None
    return rnd.trump_rank, informative, empty


def _cohort() -> V2CohortModelsV1:
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    return V2CohortModelsV1(
        cohort_id="synthetic-primary-v2",
        models=models,
        model_sha256s=tuple(portable_model_state_sha256(model)
                            for model in models))


def test_v2_round_scoring_uses_common_surface_and_corrected_ref_c(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript, partition = _state()
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17001)
    common = build_common_surface_tensors(
        partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    decision = V2ScoringDecisionV1(
        decision_key="a" * 64, source_actor=partition.actor,
        target=partition.targets, common=common, reference=reference)
    row = score_v2_round(
        round_key=hashlib.sha256(b"synthetic-round").hexdigest(),
        source_kind="synthetic", split="calibration",
        trump_rank=rnd.trump_rank, decisions=(decision,),
        cohorts=(_cohort(),))
    scoring_actor = v2_scoring_actor(partition.actor)
    assert scoring_actor.sha256() != partition.actor.sha256()
    assert all(not play.attempted_cards
               for trick in (*scoring_actor.completed_tricks,
                              scoring_actor.current_trick)
               for play in trick.plays)
    assert row.decision_count == 1
    assert row.reference_brier_ppb >= 0
    assert row.cohort_brier_ppb[0][0] == "synthetic-primary-v2"
    assert len(row.cohort_member_brier_ppb[0][1]) == len(COHORT_SEEDS)


def test_process_parallel_projection_is_byte_identical(monkeypatch):
    """The fixed worker path must reproduce serial score bytes exactly."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript, partition = _state(15004)
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17004)
    common = build_common_surface_tensors(
        partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    decision = V2ScoringDecisionV1(
        decision_key="d" * 64, source_actor=partition.actor,
        target=partition.targets, common=common, reference=reference)
    cohort = _cohort()
    kwargs = {
        "round_key": hashlib.sha256(b"parallel-round").hexdigest(),
        "source_kind": "synthetic", "split": "calibration",
        "trump_rank": rnd.trump_rank, "decisions": (decision,),
        "cohorts": (cohort,),
    }
    serial = score_v2_round(**kwargs)
    with ProcessPoolExecutor(
            max_workers=2,
            mp_context=multiprocessing.get_context("forkserver")) as executor:
        parallel = score_v2_round(
            **kwargs, projection_executor=executor)
    assert parallel == serial


def test_process_parallel_decisions_are_byte_identical(monkeypatch):
    """Each worker runs unchanged serial scoring on a distinct decision."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(SCORING, "V2_DECISION_WORKERS", 2)
    rnd, transcript, partition = _state(15005)
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17005)
    common = build_common_surface_tensors(
        partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    decisions = tuple(V2ScoringDecisionV1(
        decision_key=hashlib.sha256(
            f"decision-parallel-{index}".encode("ascii")).hexdigest(),
        source_actor=partition.actor, target=partition.targets,
        common=common, reference=reference) for index in range(4))
    cohort = _cohort()
    kwargs = {
        "round_key": hashlib.sha256(b"decision-parallel-round").hexdigest(),
        "source_kind": "synthetic", "split": "calibration",
        "trump_rank": rnd.trump_rank, "decisions": decisions,
        "cohorts": (cohort,),
    }
    serial = score_v2_round(**kwargs)
    with SCORING.V2DecisionScoringPool((cohort,)) as pool:
        pool.warm()
        parallel = score_v2_round(**kwargs, decision_pool=pool)
    assert parallel == serial


def test_decision_pool_uses_filename_backed_tensor_transport(monkeypatch):
    """The complete model population must not consume one FD per storage."""
    cohort = _cohort()
    observed = []
    sharing_strategy = ["file_descriptor"]

    class Barrier:
        pass

    barrier = Barrier()

    class Context:
        def get_start_method(self):
            return "forkserver"

        def Barrier(self, parties):
            assert parties == SCORING.V2_DECISION_WORKERS
            return barrier

    class Executor:
        def __init__(self, **kwargs):
            observed.append((
                "executor", SCORING.torch_multiprocessing
                .get_sharing_strategy(), kwargs))

        def shutdown(self, **kwargs):
            observed.append(("shutdown", kwargs))

    monkeypatch.setattr(
        SCORING.torch_multiprocessing, "get_all_sharing_strategies",
        lambda: {"file_descriptor", "file_system"})
    monkeypatch.setattr(
        SCORING.torch_multiprocessing, "get_sharing_strategy",
        lambda: sharing_strategy[0])
    monkeypatch.setattr(
        SCORING.torch_multiprocessing, "set_sharing_strategy",
        lambda value: sharing_strategy.__setitem__(0, value))
    monkeypatch.setattr(
        SCORING.multiprocessing, "get_context", lambda _method: Context())
    monkeypatch.setattr(SCORING, "ProcessPoolExecutor", Executor)
    pool = SCORING.V2DecisionScoringPool((cohort,))
    assert observed[0][0:2] == ("executor", "file_system")
    assert observed[0][2]["mp_context"].get_start_method() == "forkserver"
    assert observed[0][2]["initargs"][1] is pool._startup_barrier is barrier
    assert SCORING.torch_multiprocessing.get_sharing_strategy() \
        == "file_system"
    pool.close()
    assert SCORING.torch_multiprocessing.get_sharing_strategy() \
        == "file_descriptor"
    assert observed[-1] == (
        "shutdown", {"wait": True, "cancel_futures": True})


def test_decision_pool_refuses_missing_filename_transport(monkeypatch):
    cohort = _cohort()
    monkeypatch.setattr(
        SCORING.torch_multiprocessing, "get_all_sharing_strategies",
        lambda: {"file_descriptor"})
    with pytest.raises(SCORING.BeliefV2ScoringError,
                       match="tensor transport is unavailable"):
        SCORING.V2DecisionScoringPool((cohort,))


def test_decision_pool_types_forkserver_fd_refusal():
    pool = object.__new__(SCORING.V2DecisionScoringPool)
    pool.cohort_identity = (("cohort", ("a" * 64,) * 8),)

    def refuse(*_args, **_kwargs):
        raise ValueError("too many fds")

    pool._executor = SimpleNamespace(map=refuse)
    with pytest.raises(SCORING.BeliefV2ScoringError,
                       match="decision worker startup refused"):
        pool.warm()


def test_decision_worker_probe_waits_for_complete_population(monkeypatch):
    identity = (("cohort", ("a" * 64,) * 8),)
    waits = []

    class Barrier:
        def wait(self, *, timeout):
            waits.append(timeout)

    monkeypatch.setattr(SCORING, "_DECISION_WORKER_COHORTS", (object(),))
    monkeypatch.setattr(SCORING, "_DECISION_WORKER_IDENTITY", identity)
    monkeypatch.setattr(
        SCORING, "_DECISION_WORKER_STARTUP_BARRIER", Barrier())
    pid, observed = SCORING._decision_worker_probe(identity)
    assert pid > 0
    assert observed == identity
    assert waits == [SCORING.DECISION_WORKER_STARTUP_TIMEOUT_SECONDS]


def test_decision_worker_probe_refuses_incomplete_population(monkeypatch):
    """A missing worker must break warm-up instead of weakening the proof."""
    identity = (("cohort", ("a" * 64,) * 8),)

    class Barrier:
        def wait(self, *, timeout):
            assert timeout == SCORING.DECISION_WORKER_STARTUP_TIMEOUT_SECONDS
            raise SCORING.BrokenBarrierError

    monkeypatch.setattr(SCORING, "_DECISION_WORKER_COHORTS", (object(),))
    monkeypatch.setattr(SCORING, "_DECISION_WORKER_IDENTITY", identity)
    monkeypatch.setattr(
        SCORING, "_DECISION_WORKER_STARTUP_BARRIER", Barrier())
    with pytest.raises(SCORING.BeliefV2ScoringError,
                       match="^V2 decision worker startup barrier refused$"):
        SCORING._decision_worker_probe(identity)


def test_decision_pool_identity_and_result_order_can_refuse(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    cohort = _cohort()
    wrong = SCORING.V2CohortModelsV1(
        cohort_id="wrong-cohort", models=cohort.models,
        model_sha256s=cohort.model_sha256s)
    pool = object.__new__(SCORING.V2DecisionScoringPool)
    pool.cohort_identity = SCORING._cohort_identity((cohort,))
    rnd, transcript, partition = _state(15007)
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17007)
    decision = V2ScoringDecisionV1(
        decision_key=hashlib.sha256(b"wrong-pool-decision").hexdigest(),
        source_actor=partition.actor, target=partition.targets,
        common=build_common_surface_tensors(
            partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS),
        reference=reference)
    with pytest.raises(SCORING.BeliefV2ScoringError,
                       match="decision pool identity"):
        score_v2_round(
            round_key=hashlib.sha256(b"wrong-pool").hexdigest(),
            source_kind="synthetic", split="calibration", trump_rank="2",
            decisions=(decision,), cohorts=(wrong,), decision_pool=pool)

    first = SimpleNamespace(decision_key="a" * 64)
    second = SimpleNamespace(decision_key="b" * 64)
    pool._executor = SimpleNamespace(map=lambda *args, **kwargs: (
        SCORING._ScoredDecisionV1(second.decision_key, ()),
        SCORING._ScoredDecisionV1(first.decision_key, ())))
    with pytest.raises(SCORING.BeliefV2ScoringError,
                       match="result order drift"):
        pool.score((first, second))


def test_decision_pool_submission_batches_are_bounded_and_ordered(
        monkeypatch):
    monkeypatch.setattr(SCORING, "V2_DECISION_WORKERS", 2)
    pool = object.__new__(SCORING.V2DecisionScoringPool)
    pool.cohort_identity = (("cohort", ("a" * 64,) * 8),)
    decisions = tuple(SimpleNamespace(
        decision_key=hashlib.sha256(
            f"bounded-decision-{index}".encode("ascii")).hexdigest())
        for index in range(5))
    batch_sizes = []

    def mapped(_function, tasks, *, chunksize):
        tasks = tuple(tasks)
        assert chunksize == 1
        batch_sizes.append(len(tasks))
        return tuple(SCORING._ScoredDecisionV1(
            task.decision.decision_key, ()) for task in tasks)

    pool._executor = SimpleNamespace(map=mapped)
    rows = pool.score(decisions)
    assert batch_sizes == [4, 1]
    assert tuple(row.decision_key for row in rows) \
        == tuple(row.decision_key for row in decisions)


def test_member_projection_failure_reports_exact_scoring_context(monkeypatch):
    """Witness the public identifiers needed to diagnose a failed member."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript, partition = _state(15002)
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17002)
    common = build_common_surface_tensors(
        partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    decision = V2ScoringDecisionV1(
        decision_key="c" * 64, source_actor=partition.actor,
        target=partition.targets, common=common, reference=reference)
    cohort = _cohort()

    def refuse(*args, **kwargs):
        raise ValueError("projection refused")

    monkeypatch.setattr(SCORING, "project_count_weights", refuse)
    expected = (
        "V2 scoring member prediction refused: "
        f"decision_key={'c' * 64}, "
        f"cohort_id={cohort.cohort_id}, member_index=0, "
        f"model_sha256={cohort.model_sha256s[0]}")
    with pytest.raises(SCORING.BeliefV2ScoringError, match=expected):
        score_v2_round(
            round_key=hashlib.sha256(b"failed-round").hexdigest(),
            source_kind="synthetic", split="calibration",
            trump_rank=rnd.trump_rank, decisions=(decision,),
            cohorts=(cohort,))


def test_incomplete_human_style_actor_reuses_identical_common_scoring_surface(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript, partition = _state(15003)
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17003)
    incomplete = common_surface_actor(partition.actor)
    assert incomplete.declaration_history_complete is False
    assert incomplete.attempted_play_history_complete is False
    common = build_common_surface_tensors(
        incomplete, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    row = score_v2_round(
        round_key=hashlib.sha256(b"human-round").hexdigest(),
        source_kind="human", split="calibration",
        trump_rank=rnd.trump_rank,
        decisions=(V2ScoringDecisionV1(
            decision_key="b" * 64, source_actor=incomplete,
            target=partition.targets, common=common,
            reference=reference),),
        cohorts=(_cohort(),))
    assert row.source_kind == "human"
    assert v2_scoring_actor(incomplete).canonical_bytes() \
        == v2_scoring_actor(partition.actor).canonical_bytes()


def test_zero_unknown_endgame_is_counted_but_neutral_in_round_score(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    trump_rank, informative, empty = _informative_and_empty_decisions()
    cohort = _cohort()
    informative_only = score_v2_round(
        round_key=hashlib.sha256(b"informative-only").hexdigest(),
        source_kind="synthetic", split="calibration",
        trump_rank=trump_rank, decisions=(informative,), cohorts=(cohort,))
    with_empty = score_v2_round(
        round_key=hashlib.sha256(b"with-empty-endgame").hexdigest(),
        source_kind="synthetic", split="calibration", trump_rank=trump_rank,
        decisions=(informative, empty), cohorts=(cohort,))
    assert with_empty.decision_count == 2
    assert with_empty.reference_brier_ppb == informative_only.reference_brier_ppb
    assert with_empty.reference_log_loss_nanonats \
        == informative_only.reference_log_loss_nanonats
    assert with_empty.cohort_brier_ppb == informative_only.cohort_brier_ppb
    assert with_empty.cohort_log_loss_nanonats \
        == informative_only.cohort_log_loss_nanonats
    assert with_empty.cohort_member_brier_ppb \
        == informative_only.cohort_member_brier_ppb
