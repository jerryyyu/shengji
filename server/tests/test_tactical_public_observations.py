"""Exposed DEV mechanism fixtures; no model calls or best-action labels."""
from collections import Counter
from itertools import combinations
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.eval import tactical as T


PATH = Path(__file__).parent / "tactical" / "public_observations.jsonl"


@pytest.fixture(scope="module")
def cases():
    return T.load_fixtures(PATH)


class RecordedAction:
    """A test double, not a policy screen or a model inference."""
    def __init__(self, fx, action=None):
        self.action = list(action or fx.observed["action"])
        self.last_decision_record = {
            "work_complete": True, "admitted": fx.observed["admitted"],
            "value_means": fx.observed["value_means"],
        }

    def decide_play(self, rnd, seat):
        return self.action


def test_source_scope_and_public_information(cases):
    assert len(cases) == 4
    assert len({fx.source["source_ref"] for fx in cases}) == 4
    for fx in cases:
        assert fx.category == "observation" and fx.current_bot is None
        assert fx.observed["exploration"] is None
        assert fx.source["git_dirty"] is True
        assert fx.source["transcript_sha256"] == "e15afce77105f259acc0c808ddbfba10c5beadd791206f14d465ad7e56de5253"
        assert set(fx.setup) == {"banker", "trump_rank", "trump_suit", "trump_is_nt", "declarations", "buried"}
        assert fx.setup["buried"] is None or fx.seat == fx.setup["banker"]
        assert fx.observed["engine_play"] == fx.observed["action"]
        assert Counter(fx.observed["action"]) <= Counter(fx.hand)


@pytest.mark.parametrize("index", range(4))
def test_public_rebuild_and_consequences_are_hidden_fill_invariant(cases, index):
    fx = cases[index]
    a, b = T.public_round(fx, 0), T.public_round(fx, 1)
    assert [a.hands[s] for s in range(4) if s != fx.seat] != [b.hands[s] for s in range(4) if s != fx.seat]
    for rnd in (a, b):
        assert rnd.attacker_points == fx.observed["public_points"]
        assert [{"seat": p.seat, "cards": p.cards} for p in rnd.trick.plays] == fx.observed["public_table"]
        assert sorted(rnd.hands[fx.seat]) == sorted(fx.hand)
    results = [T.run_fixture(RecordedAction(fx), fx, fill_seed=seed) for seed in (0, 1)]
    assert all(r.status == "observed" and r.passed is None and r.error is None for r in results)
    assert results[0].extra == results[1].extra


@pytest.mark.parametrize("index,winner,points,complete,alt_winner,alt_points", [
    (0, 0, 25, True, 0, 25),
    (1, 0, 5, False, 0, 5),
    (2, 1, 0, True, 1, 0),
    (3, 0, 20, True, 2, 15),
])
def test_recorded_and_alternative_public_effects(cases, index, winner, points, complete, alt_winner, alt_points):
    fx = cases[index]
    for action, expected_winner, expected_points in (
        (fx.observed["action"], winner, points),
        (fx.observed["alternative"], alt_winner, alt_points),
    ):
        result = T.run_fixture(RecordedAction(fx, action), fx)
        assert result.error is None, result.detail
        obs = result.extra["observation"]
        assert (obs["current_winner"], obs["current_points"], obs["trick_complete"]) == (expected_winner, expected_points, complete)
        assert Counter(obs["residual_hand"]) == Counter(fx.hand) - Counter(action)
        assert len(obs["admitted"]) == len(fx.observed["admitted"])


def test_follow_obligation_rejects_nontrump_discard(cases):
    # C2 is a level trump, not an ordinary club. The actor must follow trump.
    fx = cases[1]
    result = T.run_fixture(RecordedAction(fx, ["H5", "HA"]), fx)
    assert result.status == "ERROR"


def test_observations_not_counted_as_strategic_passes(cases):
    results = [T.run_fixture(RecordedAction(fx), fx) for fx in cases]
    report = T.format_table(results)
    assert "0 pass, 0 fail, 0 error" in report
    assert "observations: 4" in report
    assert "moved vs" not in report


@pytest.mark.parametrize("mutation", ["known_verdict", "scored_category", "wrong_predicate"])
def test_observation_cannot_acquire_a_strategic_label(cases, mutation):
    row = cases[0].to_json()
    if mutation == "known_verdict":
        row["current_bot"] = "fail"
    elif mutation == "scored_category":
        row["category"] = "shortlist-miss"
    else:
        row["predicate"] = {"name": "admitted_ballot_not_crowded", "args": {}}
    with pytest.raises(T.TacticalError):
        T.fixture_from_json(row)


def test_cli_writes_observed_without_stamping_failure(cases, tmp_path, monkeypatch):
    from scripts import tactical_report
    fixture_path, output = tmp_path / "cases.jsonl", tmp_path / "report.json"
    fixture_path.write_text(json.dumps(cases[0].to_json()) + "\n")
    monkeypatch.setattr(T, "bot_from_environ", lambda *a, **k: ("recorded-test-double", RecordedAction(cases[0])))
    monkeypatch.setattr("sys.argv", ["tactical_report", "--from-env", "--fixtures", str(fixture_path),
                                    "--json", str(output), "--stamp"])
    tactical_report.main()
    report = json.loads(output.read_text())
    assert report["results"][0]["status"] == "observed"
    assert report["results"][0]["observation"]["trick_complete"] is True
    assert json.loads(fixture_path.read_text())["current_bot"] is None


def test_cli_comparison_records_pair_telemetry_and_refuses_reuse(cases, tmp_path, monkeypatch):
    from scripts import tactical_report
    fixture_path, output = tmp_path / "cases.jsonl", tmp_path / "comparison.json"
    fixture_path.write_text("\n".join(json.dumps(fx.to_json()) for fx in cases) + "\n")

    class RecordedSet:
        def decide_play(self, rnd, seat):
            fx = next(fx for fx in cases if fx.trick == len(rnd.history)
                      and fx.position == len(rnd.trick.plays) and fx.seat == seat)
            indices = [100 + 3 * i for i in range(len(fx.observed["admitted"]))]
            selected = next(i for i, a in enumerate(fx.observed["admitted"])
                            if Counter(a) == Counter(fx.observed["action"]))
            self.last_decision_record = {"work_complete": True,
                                         "admitted": fx.observed["admitted"],
                                         "admitted_indices": indices,
                                         "value_means": fx.observed["value_means"],
                                         "policy_log_odds_admitted": fx.observed["policy_log_odds"],
                                         "selected_index": indices[selected],
                                         "worlds": [["private-world"]]}
            return fx.observed["action"]

    calls = []
    def fake_bot(env, *, seed):
        calls.append((env, seed))
        return ("fake-treatment" if env.get("SHENGJI_PV_LEAD_ANCHOR") == "1"
                else "fake-r36", RecordedSet())

    monkeypatch.setattr(T, "bot_from_environ", fake_bot)
    monkeypatch.setattr("sys.argv", ["tactical_report", "--compare-observations",
                                      "--ckpt", "/models/smv3out.npz",
                                      "--sha256", T.OBSERVATION_COMPARISON_SHA256,
                                      "--fixtures", str(fixture_path), "--json", str(output)])
    tactical_report.main()
    report = json.loads(output.read_text())
    assert report["seeds"] == [0, 1, 2] and report["fill_seed"] == 0
    assert len(report["results"]) == 12
    assert report["results"][0]["control"]["status"] == "observed"
    assert report["results"][0]["control"]["decision"]["value_means"]
    for pair in report['results']:
        fixture = next(fx for fx in cases if fx.id == pair["id"])
        for arm in ('control', 'treatment'):
            coverage = pair[arm]['ballot_opportunity']
            assert coverage['schema'] == 'hand-conditioned-ballot-opportunity-v1'
            assert coverage['strategic_quality_assessed'] is False
            decision = pair[arm]['decision']
            assert decision['policy_log_odds_admitted'] == fixture.observed['policy_log_odds']
            assert decision['selected_index'] >= 100
            assert decision['admitted_indices'] == [100 + 3 * i for i in range(len(decision['admitted']))]
            slot = decision['admitted_indices'].index(decision['selected_index'])
            assert Counter(decision['admitted'][slot]) == Counter(pair[arm]['action'])
            assert 'worlds' not in decision
    assert report['results'][0]['control']['ballot_opportunity']['cards']['S6']['ballot_spent'] == [2]
    assert "worlds" not in report["results"][0]["control"]["decision"]
    before = len(calls)
    monkeypatch.setattr("sys.argv", ["tactical_report", "--compare-observations",
                                      "--ckpt", "/models/smv3out.npz",
                                      "--sha256", T.OBSERVATION_COMPARISON_SHA256,
                                      "--fixtures", str(fixture_path), "--json", str(output)])
    with pytest.raises(SystemExit, match="already exists"):
        tactical_report.main()
    assert len(calls) == before
    for extra, expected in ((["--env-override", "SHENGJI_PV_CAP=1"], "overrides"),
                            (["--compare-seeds", "0,0"], "duplicates")):
        target = tmp_path / ("refuse-" + expected + ".json")
        monkeypatch.setattr("sys.argv", ["tactical_report", "--compare-observations",
                                          "--ckpt", "/models/smv3out.npz",
                                          "--sha256", T.OBSERVATION_COMPARISON_SHA256,
                                          "--fixtures", str(fixture_path), "--json", str(target),
                                          *extra])
        with pytest.raises(SystemExit, match=expected):
            tactical_report.main()
        assert len(calls) == before


def test_observation_does_not_wrap_or_delete_world_sampler(cases):
    class WithSampler(RecordedAction):
        def _worlds(self, *args, **kwargs):
            raise AssertionError("sampler not needed for recorded action")
    bot = WithSampler(cases[0])
    sentinel = lambda: None
    bot._worlds = sentinel
    result = T.run_fixture(bot, cases[0])
    assert result.status == "observed" and bot._worlds is sentinel


def test_frozen_comparison_recipes_change_only_the_four_named_flags():
    envs = T.observation_comparison_environs("/models/smv3out.npz", "a" * 64)
    control, treatment = envs["r36-smv3"], envs["div+rc+tb+la"]
    assert control["SHENGJI_PV_WORLDS"] == "64"
    assert control["SHENGJI_PV_CANDIDATES"] == "8"
    assert control["SHENGJI_PV_CKPT"] == treatment["SHENGJI_PV_CKPT"]
    assert control["SHENGJI_PV_SHA256"] == treatment["SHENGJI_PV_SHA256"]
    assert {key for key in set(control) | set(treatment)
            if control.get(key) != treatment.get(key)} == set(T.OBSERVATION_COMPARISON_FLAGS)


def test_frozen_comparison_pairs_all_roots_and_seeds_without_strategic_verdict(cases):
    class RecordedSet:
        def decide_play(self, rnd, seat):
            fx = next(fx for fx in cases if fx.trick == len(rnd.history)
                      and fx.position == len(rnd.trick.plays) and fx.seat == seat)
            self.last_decision_record = {
                "work_complete": True, "admitted": fx.observed["admitted"],
                "value_means": fx.observed["value_means"],
            }
            return fx.observed["action"]

    def factory(seed):
        return RecordedSet()

    rows = T.run_observation_comparison(factory, factory, cases)
    assert len(rows) == 12
    assert {(row["fixture"], row["seed"], row["fill_seed"]) for row in rows} == {
        (fx.id, seed, 0) for seed in (0, 1, 2) for fx in cases
    }
    for row in rows:
        assert row["control"].status == row["treatment"].status == "observed"
        assert row["control"].passed is row["treatment"].passed is None


def test_comparison_refuses_mixed_or_stamped_fixtures(cases):
    bad = [replace(cases[0], current_bot="fail"), *cases[1:]]
    with pytest.raises(T.TacticalError, match="exactly four"):
        T.run_observation_comparison(lambda seed: RecordedAction(cases[0]),
                                     lambda seed: RecordedAction(cases[0]), bad)


def test_historical_prior_value_disagreement_is_not_a_new_model_result(cases):
    joker, ace = cases[1:3]
    def indices(fx):
        ballot = [tuple(sorted(a)) for a in fx.observed["admitted"]]
        return (ballot.index(tuple(sorted(fx.observed["action"]))),
                ballot.index(tuple(sorted(fx.observed["alternative"]))))
    j, ja = indices(joker)
    assert joker.observed["policy_log_odds"][ja] > joker.observed["policy_log_odds"][j]
    assert joker.observed["value_means"][j] - joker.observed["value_means"][ja] == pytest.approx(0.025632123929171)
    a, aa = indices(ace)
    assert ace.observed["value_means"][a] - ace.observed["value_means"][aa] == pytest.approx(0.0092825103171985)


def test_diversity_can_admit_available_alternative_but_cannot_create_it(cases):
    from shengji.train.policy_value_search import PolicyValueBot
    fx = cases[0]
    rnd = T.public_round(fx)
    historical = fx.observed["admitted"]
    assert all(Counter(a)["S6"] == 2 for a in historical)
    rule = SimpleNamespace(candidates=8, max_per_structure=2)
    unchanged = PolicyValueBot._admit_diverse(rule, rnd, historical, list(range(8)), 0)
    assert set(unchanged) == set(range(8))  # backfill: no new candidate exists
    augmented = historical + [fx.observed["alternative"]]
    chosen = PolicyValueBot._admit_diverse(rule, rnd, augmented, list(range(9)), 0)
    assert 8 in chosen and len(chosen) == 8
    # A fixed-candidate mechanism witness, NOT a fresh sampled combo screen.


@pytest.mark.parametrize("fill_seed", [0, 1])
def test_real_pv_candidate_stage_keeps_pair_preserving_follow(cases, fill_seed):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.legal import validate_follow
    from shengji.harvest.legal import enumerate_legal
    from shengji.train.pv_search_policy import PVSearchBot
    fx = cases[0]
    rnd = T.public_round(fx, fill_seed)
    anchor = HeuristicBot().decide_play(rnd, fx.seat)
    assert anchor == ["S6", "S6", "S8"]
    # Actual PV candidate hook; no bot/model construction or sampled worlds.
    legal = PVSearchBot._legal(SimpleNamespace(cap=4000), rnd, fx.seat, [anchor])
    assert legal.complete and legal.count == len(legal.actions) == 712
    # Independent small combinatorial oracle: actor is void in ordinary hearts.
    oracle = {tuple(sorted(cards)) for cards in combinations(fx.hand, 3)}
    for action in oracle:
        validate_follow(list(action), fx.hand, rnd.trick.plays[0].cards, rnd.ordering)
    assert {tuple(a) for a in legal.actions} == oracle
    assert legal.actions.index(fx.observed["alternative"]) == 267
    assert sum(Counter(a)["S6"] == 0 for a in legal.actions) == 575
    assert sum(Counter(a)["S6"] == 1 for a in legal.actions) == 121
    assert sum(Counter(a)["S6"] == 2 for a in legal.actions) == 16
    listing = enumerate_legal(rnd, fx.seat, cap=256)
    assert not listing.complete and listing.count == 712
    assert fx.observed["alternative"] not in listing.actions
    # The harvest's displayed prefix is NOT the PV scorer's 4000-action cap.


def test_same_pair_in_every_slot_has_no_listwise_gradient(cases):
    """Actual loss function, tiny CPU tensors only; no network or training run."""
    import torch
    from shengji.train.policy_prior import CARD_INDEX, ballot_tensors, listwise_loss_soft
    from shengji.train.cwv_data import VALUE_UNITS_SCALE
    fx = cases[0]
    cards = lambda action: [CARD_INDEX[c] for c in action]
    ballot = [cards(a) for a in fx.observed["admitted"]]
    meta = [{"ballot": ballot, "taken": cards(fx.observed["action"])}]
    ball, mask, target = ballot_tensors(meta)
    scale = VALUE_UNITS_SCALE[fx.observed["value_units"]]
    values = torch.tensor([[v * scale for v in fx.observed["value_means"]]])
    logits = torch.zeros((1, 54), requires_grad=True)
    loss = listwise_loss_soft(logits, ball, mask, target, values)
    loss.backward()
    s6 = CARD_INDEX["S6"]
    assert abs(logits.grad[0, s6].item()) < 1e-6
    assert logits.grad.abs().max().item() > 1e-3  # not an all-zero/unused loss
    shifted = logits.detach().clone()
    shifted[0, s6] += 2
    assert listwise_loss_soft(shifted, ball, mask, target, values).item() == pytest.approx(loss.item(), abs=1e-6)

    # The co-trained card-presence BCE DOES encourage the recorded S6 play.
    bce_logits = torch.zeros((1, 54), requires_grad=True)
    labels = torch.zeros_like(bce_logits)
    for card in fx.observed["action"]:
        labels[0, CARD_INDEX[card]] = 1
    torch.nn.functional.binary_cross_entropy_with_logits(bce_logits, labels).backward()
    assert bce_logits.grad[0, s6].item() == pytest.approx(-0.5 / 54)

    # Positive control: one additional scored preserving move permits that
    # gradient. Its high value is SYNTHETIC, not a claimed counterfactual score.
    extended = [{"ballot": ballot + [cards(fx.observed["alternative"])] ,
                 "taken": cards(fx.observed["action"])}]
    ball2, mask2, target2 = ballot_tensors(extended)
    values2 = torch.cat([values, values.max().reshape(1, 1) + 10], dim=1)
    logits2 = torch.zeros((1, 54), requires_grad=True)
    listwise_loss_soft(logits2, ball2, mask2, target2, values2).backward()
    assert logits2.grad[0, s6].item() > 1.0
