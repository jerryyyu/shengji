from __future__ import annotations

import copy
import importlib.util
import random
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
MODULE = SCRIPTS / "h0_partial_coverage_exploration.py"
RUNTIME = SCRIPTS / "h0_human_counterfactual_runtime.py"

spec = importlib.util.spec_from_file_location("h0_geometry", MODULE)
assert spec and spec.loader
h0x = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h0x)

runtime_spec = importlib.util.spec_from_file_location("h0_runtime", RUNTIME)
assert runtime_spec and runtime_spec.loader
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)

SYNTHETIC_SHA = h0x.sha256({"fixture": "h0-geometry-v1"})
OPEN_DEV_SHA = h0x.sha256({"new_open_dev_capture": "fixture-v1"})


class _FakeNet:
    def value_candidates(self, _obs, actions):
        return list(range(len(actions)))


def _scope(kind: str = "SYNTHETIC") -> dict:
    return {
        "population_kind": kind,
        "source_scope": h0x.SOURCE_SCOPES[kind],
        "source_manifest_sha256": (
            SYNTHETIC_SHA if kind == "SYNTHETIC" else OPEN_DEV_SHA),
    }


def _row(index: int, *, split: str = "SYNTHETIC",
         human_action: list[str] | None = None,
         deal: str | None = None) -> dict:
    decision = f"decision-{index}"
    return {
        "row_key": f"{split}|play|{decision}",
        "decision_key": decision,
        "split": split,
        "surface_type": "play",
        "deal_key": deal or f"deal-{index}",
        "surface": "follow",
        "phase": "early",
        "role": "attacker",
        "human_action": human_action or ["H3"],
    }


def _simple(row: dict) -> h0x.CandidateSet:
    return h0x.CandidateSet([{
        "cards": list(row["human_action"]),
        "sources": ["human_action", "live_production_ballot"],
    }], {
        "live_candidates": 1,
        "analysis_actions": 1,
        "novel_pool": 0,
        "human_in_live_ballot": True,
        "v11_proposed": False,
        "random_proposed": False,
        "v11_random_same": False,
        "v11_score_count": 0,
    })


def _complex_follow(n_in_suit: int):
    """Reproduce the two H0-v3 12-live versus 3-analysis refusals."""
    from shengji.ai.registry import make_bot
    from shengji.engine.cards import Ordering, RANKS
    from shengji.engine.round import Round, Trick, TrickPlay

    rnd = Round("2", 0, random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("S", "2")
    rnd.trump_suit = "S"
    lead = ["H5", "H6", "H7", "H8", "H9", "H10", "HJ"]
    rnd.trick = Trick(leader=0, plays=[TrickPlay(0, lead)])
    rnd.turn = 1
    hearts = ["H3", "H4"][:n_in_suit]
    off_suit = [suit + rank for suit in "CD" for rank in RANKS
                if rank != "2"]
    rnd.hands = [[], hearts + off_suit[:25 - n_in_suit], [], []]
    bot = make_bot("mc-s0-report-lcb", seed=0)
    live = bot._candidates(rnd, 1)
    assert len(live) == 12
    return rnd, bot, live[-1]


@pytest.mark.parametrize("n_in_suit", [1, 2])
def test_complex_follow_uses_engine_legality_not_menu_cardinality(
        n_in_suit: int) -> None:
    rnd, bot, human = _complex_follow(n_in_suit)
    row = _row(n_in_suit, split="DEV", human_action=human)
    context = h0x.EngineContext(rnd, 1, _FakeNet(), bot)
    candidates = h0x._engine_candidates(row, h0x._identity(row, "OPEN_DEV"),
                                        context)
    assert candidates.diagnostics["live_candidates"] == 12
    assert candidates.diagnostics["analysis_actions"] == 3
    with pytest.raises(runtime.RuntimeRefused,
                       match="candidate diagnostics do not reconcile"):
        runtime._validate_candidate_diagnostics({
            "surface_type": "play", "surface": "follow",
            "candidate_diagnostics": candidates.diagnostics,
        }, candidates.candidates)

    result = h0x.prevalidate_population(
        [row], lambda _row: context,
        population_id="open-dev-complex-follow-fixture-v1", **_scope("OPEN_DEV"))
    assert result["counts"] == {"selected": 1, "valid": 1, "refused": 0}
    assert result["records"][0]["candidate_manifest_sha256"]


def test_illegal_follow_is_named_score_free_refusal() -> None:
    rnd, bot, human = _complex_follow(1)
    row = _row(1, split="DEV", human_action=human)
    original = h0x._engine_candidates(
        row, h0x._identity(row, "OPEN_DEV"),
        h0x.EngineContext(rnd, 1, _FakeNet(), bot))
    broken = copy.deepcopy(list(original.candidates))
    broken[0]["cards"] = ["BJ"]

    def forged_build(*_args, **_kwargs):
        return broken, original.diagnostics

    old = h0x.H0.build_play_union
    h0x.H0.build_play_union = forged_build
    try:
        result = h0x.prevalidate_population(
            [row], lambda _row: h0x.EngineContext(
                rnd, 1, _FakeNet(), bot),
            population_id="open-dev-illegal-follow-v1", **_scope("OPEN_DEV"))
    finally:
        h0x.H0.build_play_union = old
    assert result["counts"] == {"selected": 1, "valid": 0, "refused": 1}
    assert result["records"][0]["reason_code"] == "ILLEGAL_CANDIDATE"


def test_failed_lead_throw_is_an_accepted_attempt_not_hidden_info_filter() -> None:
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round, Trick

    rnd = Round("2", 0, random.Random(0))
    rnd.phase = "play"
    rnd.turn = 0
    rnd.ordering = Ordering("S", "2")
    rnd.trump_suit = "S"
    rnd.trick = Trick(leader=0)
    rnd.hands = [["H3", "H3", "HA"], ["H4", "H4"], [], []]
    row = _row(5, split="DEV", human_action=["H3", "H3", "HA"])
    row.update({"surface": "lead", "role": "defender"})
    candidate = [{
        "cards": ["H3", "H3", "HA"],
        "sources": ["human_action", "live_production_ballot"],
    }]
    diagnostics = {
        "live_candidates": 1, "analysis_actions": 1, "novel_pool": 0,
        "human_in_live_ballot": True, "v11_proposed": False,
        "random_proposed": False, "v11_random_same": False,
        "v11_score_count": 0,
    }

    def build(*_args, **_kwargs):
        return candidate, diagnostics

    old = h0x.H0.build_play_union
    h0x.H0.build_play_union = build
    try:
        result = h0x.prevalidate_population(
            [row], lambda _row: h0x.EngineContext(rnd, 0, _FakeNet()),
            population_id="open-dev-failed-throw-v1", **_scope("OPEN_DEV"))
    finally:
        h0x.H0.build_play_union = old
    assert result["counts"]["valid"] == 1


def _bury_state():
    from shengji.ai.smart import SmartBot
    from shengji.engine.cards import Ordering, make_deck
    from shengji.engine.round import Round

    rnd = Round("2", 0, random.Random(0))
    rnd.phase, rnd.turn, rnd.banker = "bury", 0, 0
    rnd.ordering = Ordering("S", "2")
    rnd.trump_suit = "S"
    rnd.hands = [make_deck()[:33], [], [], []]
    human = SmartBot().decide_bury(rnd, 0)
    row = {
        "row_key": "DEV|bury|bury-decision-1",
        "decision_key": "bury-decision-1",
        "split": "DEV", "surface_type": "bury", "deal_key": "bury-deal-1",
        "surface": "bury", "phase": "bury", "role": "banker",
        "human_action": human,
    }
    return rnd, row


def test_bury_actions_are_validated_directly_by_engine() -> None:
    rnd, row = _bury_state()
    result = h0x.prevalidate_population(
        [row], lambda _row: h0x.EngineContext(rnd, 0),
        population_id="open-dev-bury-v1", **_scope("OPEN_DEV"))
    assert result["counts"]["valid"] == 1

    original = h0x.H0.build_bury_union(rnd, 0, row["human_action"])
    broken = copy.deepcopy(original[0])
    index = next(i for i, item in enumerate(broken)
                 if "human_action" not in item["sources"])
    broken[index]["cards"] = ["ZZ"] * 8
    old = h0x.H0.build_bury_union
    h0x.H0.build_bury_union = lambda *_args, **_kwargs: (broken, original[1])
    try:
        refused = h0x.prevalidate_population(
            [row], lambda _row: h0x.EngineContext(rnd, 0),
            population_id="open-dev-illegal-bury-v1", **_scope("OPEN_DEV"))
    finally:
        h0x.H0.build_bury_union = old
    assert refused["records"][0]["reason_code"] == "ILLEGAL_CANDIDATE"


def test_every_row_is_prepared_before_geometry_is_terminal() -> None:
    rows = [_row(1), _row(2), _row(3)]
    events = []

    def prepare(row):
        events.append(row["decision_key"])
        if row["decision_key"] == "decision-2":
            raise h0x.GeometryRefused(
                "CANDIDATE_BUILD", "private /path utility=99")
        return _simple(row)

    result = h0x.prevalidate_population(
        rows, prepare, population_id="synthetic-all-rows-v1", **_scope())
    assert events == [row["decision_key"] for row in rows]
    assert result["counts"] == {"selected": 3, "valid": 2, "refused": 1}
    assert result["deal_clusters"] == {"selected": 3, "valid": 2, "refused": 1}
    encoded = h0x.canonical_json(result).decode()
    assert "/path" not in encoded and "utility=99" not in encoded
    assert "score_records" not in result and "metrics" not in result


@pytest.mark.parametrize("extra", [
    {"winner": 1}, {"attacker_points": 100}, {"label": 3},
    {"metadata": {"utility": 99}},
    {"metadata": [{"outcome": "human-win"}]},
])
def test_outcome_aliases_refuse_before_prepare(extra: dict) -> None:
    called = False

    def prepare(row):
        nonlocal called
        called = True
        return _simple(row)

    with pytest.raises(h0x.GeometryRefused):
        h0x.prevalidate_population(
            [{**_row(1), **extra}], prepare,
            population_id="synthetic-outcome-alias-v1", **_scope())
    assert called is False


@pytest.mark.parametrize("source", [
    "evil:boundary+999", "structured_bury_ballot",
    "void:H+point_preserving",
])
def test_play_source_allowlist_is_exact(source: str) -> None:
    row = _row(1)
    value = _simple(row)
    candidates = copy.deepcopy(list(value.candidates))
    candidates[0]["sources"] = sorted([*candidates[0]["sources"], source])
    with pytest.raises(h0x.GeometryRefused) as exc:
        h0x._candidate_set(
            h0x._identity(row, "SYNTHETIC"),
            h0x.CandidateSet(candidates, value.diagnostics))
    assert exc.value.code == "CANDIDATE_SOURCE"


def test_bury_source_grammar_matches_both_producer_suit_orders() -> None:
    assert h0x._bury_source("void:S+C+point_preserving")
    assert h0x._bury_source("void:C+S+trump_preserving")
    assert h0x._bury_source("void:H+pair_preserving:boundary+3")
    assert not h0x._bury_source("void:H+pair_preserving:boundary+4")
    assert not h0x._bury_source("void:H+H+point_preserving")
    assert not h0x._bury_source("evil:boundary+1")


def test_synthetic_candidate_set_cannot_bypass_open_dev_engine() -> None:
    row = _row(1, split="DEV")
    result = h0x.prevalidate_population(
        [row], _simple, population_id="open-dev-no-callback-v1",
        **_scope("OPEN_DEV"))
    assert result["records"][0]["reason_code"] == "ENGINE_CONTEXT"


def test_closed_h0_source_digest_cannot_be_reopened() -> None:
    with pytest.raises(h0x.GeometryRefused, match="population scope drift"):
        h0x.prevalidate_population(
            [_row(1, split="DEV")], lambda _row: None,
            population_id="new-label-does-not-grant-authority",
            population_kind="OPEN_DEV", source_scope="NEW_OPEN_DEV_CAPTURE",
            source_manifest_sha256=h0x.H0.SOURCE_MANIFEST_SHA256)


def test_duplicate_semantic_decisions_refuse_before_prepare() -> None:
    called = False

    def prepare(row):
        nonlocal called
        called = True
        return _simple(row)

    row = _row(1)
    with pytest.raises(h0x.GeometryRefused, match="duplicated"):
        h0x.prevalidate_population(
            [row, copy.deepcopy(row)], prepare,
            population_id="synthetic-duplicate-v1", **_scope())
    assert called is False


def test_unexpected_prepare_exception_aborts_no_partial_artifact() -> None:
    def crash(_row):
        raise ValueError("unexpected preparation defect")

    with pytest.raises(ValueError, match="unexpected preparation defect"):
        h0x.prevalidate_population(
            [_row(1)], crash, population_id="synthetic-crash-v1", **_scope())


def test_external_digest_and_semantic_validation_resist_rehashing() -> None:
    artifact = h0x.prevalidate_population(
        [_row(1)], _simple, population_id="synthetic-artifact-v1", **_scope())
    trusted = artifact["artifact_sha256"]
    forged = copy.deepcopy(artifact)
    record = forged["records"][0]
    record["candidates"][0]["sources"].append("evil:boundary+1")
    record["candidates"][0]["sources"].sort()
    record["candidate_manifest_sha256"] = h0x.sha256(record["candidates"])
    forged["geometry_manifest_sha256"] = h0x.sha256(forged["records"])
    forged["artifact_sha256"] = h0x.sha256({
        key: value for key, value in forged.items() if key != "artifact_sha256"})
    with pytest.raises(h0x.GeometryRefused, match="artifact digest drift"):
        h0x.validate_artifact(forged, expected_sha256=trusted)
    with pytest.raises(h0x.GeometryRefused) as exc:
        h0x.validate_artifact(
            forged, expected_sha256=forged["artifact_sha256"])
    assert exc.value.code == "CANDIDATE_SOURCE"


def test_rehashed_diagnostic_forgery_fails_reconciliation() -> None:
    artifact = h0x.prevalidate_population(
        [_row(1)], _simple, population_id="synthetic-diagnostic-v1", **_scope())
    forged = copy.deepcopy(artifact)
    forged["records"][0]["candidate_diagnostics"]["live_candidates"] = 2
    forged["geometry_manifest_sha256"] = h0x.sha256(forged["records"])
    forged["artifact_sha256"] = h0x.sha256({
        key: value for key, value in forged.items() if key != "artifact_sha256"})
    with pytest.raises(h0x.GeometryRefused) as exc:
        h0x.validate_artifact(
            forged, expected_sha256=forged["artifact_sha256"])
    assert exc.value.code == "DIAGNOSTIC_RECONCILIATION"


def test_authority_and_foreign_fields_remain_closed() -> None:
    artifact = h0x.prevalidate_population(
        [_row(1)], _simple, population_id="synthetic-authority-v1", **_scope())
    for mutation in (
        lambda value: value["authority"].update({"training_authorized": True}),
        lambda value: value.update({"verdict": "PASS"}),
        lambda value: value["records"][0].update({"nested": {"winner": 1}}),
        lambda value: value["counts"].update({"selected": True}),
    ):
        forged = copy.deepcopy(artifact)
        mutation(forged)
        forged["artifact_sha256"] = h0x.sha256({
            key: value for key, value in forged.items()
            if key != "artifact_sha256"})
        with pytest.raises(h0x.GeometryRefused):
            h0x.validate_artifact(
                forged, expected_sha256=forged["artifact_sha256"])
