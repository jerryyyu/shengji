from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_champion_natural_dose_design as DESIGN  # noqa: E402


EXPECTED_ARTIFACT_SHA256 = (
    "4629ccde834f0dc04f2032e335653ec5428f9458fb287aedf42af8fda95ba93c")
EXPECTED_INTERNAL_SHA256 = (
    "0e1a6006724a4e04470cc2732548a33ffb325647a3121ff0d70cec0fe0e37dc7")
EXPECTED_LANES = (
    (0, 512, 248, 264, "e065b5fdc265f364d948467db9df630ed8c6d1b3333cdfc5a30f32dee0adf1ee"),
    (1, 512, 261, 251, "960d7d030f8180e9e0eb4df467aa0c68efb31c61f464189ae136564a4bbfd81f"),
    (2, 512, 260, 252, "09b724f9f234b265866c2dab65a7bbd164bdb0f87f1fd633709a407603081345"),
    (3, 512, 242, 270, "1698e718b6d81022cd14d0f84fa3ac6cdeb41e645f090a61f055f372f57d5380"),
    (4, 512, 253, 259, "8e8b6e81a3e25ea75a1d07cb8e1e6b02520beffdfea30aeda7ed20d0acf6dca8"),
    (5, 512, 265, 247, "abae7d2b771cc63aef157cae5383e8967241c9961763a83efae8ce799d1f8877"),
    (6, 512, 277, 235, "c392ba431c1193948e5d82ed4ca5db4f7eebd40acf1de885e9e71a399e1e9e48"),
    (7, 512, 260, 252, "08cb8d99e15e16f7107653e89f8f5ad1bc0c6e492cfbf22d54799ee7fd917adf"),
    (8, 512, 248, 264, "5fb4b31e42b5bcf2c8c708096c55a71b63e9764e953c7f689e0171e9deddc3c6"),
    (9, 512, 261, 251, "577a73f94b5bb5600c20f702726bf25efaed83a6b3d2092ef1bafa8341d5f891"),
    (10, 512, 266, 246, "b3877e98ad8904a773a1e0992ec338ca2e0d069684a3ea890dd68cd0c7dcd221"),
    (11, 512, 248, 264, "13ce430dcb4f8003ea2180f3a89183309b1b62c1a2ef8a5c78258350d3378a32"),
    (12, 512, 260, 252, "3bec279b8b16c29f1839bfd8673eedcc5e8e55268959ddb526f05c7111310379"),
    (13, 512, 251, 261, "6995f9758f47b786132b9f611ac76937d1b6391079bc9b74292b198d0e6afebf"),
    (14, 512, 260, 252, "591434cb17072a8ee6e30d840def10dfe53b15bafb6caedef5f35874539a6be9"),
    (15, 512, 236, 276, "f86470a9031670fdcdc691e74b257ae83f29de808a06625737b12742d7f57450"),
)


@pytest.fixture(scope="module")
def design() -> dict:
    return DESIGN.build_design()


def _rehash(payload: dict) -> None:
    body = dict(payload)
    body.pop("design_sha256", None)
    payload["design_sha256"] = DESIGN._digest(DESIGN._canonical(body))


def test_exact_reviewed_requirement_and_provenance_are_reconstructed(design):
    assert design["provenance"] == {
        "source_design_git": DESIGN.SOURCE_GIT,
        "source_merge_git": DESIGN.SOURCE_MERGE_GIT,
        "source_review_git": DESIGN.SOURCE_REVIEW_GIT,
        "source_path": DESIGN.SOURCE_PATH,
        "source_sha256": DESIGN.SOURCE_SHA256,
        "source_artifact_sha256": DESIGN.SOURCE_ARTIFACT_SHA256,
        "source_internal_sha256": DESIGN.SOURCE_INTERNAL_SHA256,
        "review_is_design_only": True,
        "execution_authority_inherited": False,
    }
    assert design["source_requirement"] == {
        "required_before_whole_game_or_value_for_compute_claim": True,
        "exact_policy_identity_required": "mc-s0-report-lcb",
        "all_natural_search_reachable_omission_events_counted": True,
        "counts_required_by_role": ["attacker", "defender"],
        "counts_required_by_band": ["early", "mid", "late"],
        "fresh_design_and_independent_review_required": True,
        "included_in_this_scored_packet": False,
        "implementation_authorized": False,
        "execution_authorized": False,
    }


def test_artifact_and_internal_digest_are_exact(design):
    assert design["design_sha256"] == EXPECTED_INTERNAL_SHA256
    assert hashlib.sha256(DESIGN._canonical(design)).hexdigest() \
        == EXPECTED_ARTIFACT_SHA256


def test_population_is_independently_reconstructed_and_balanced(design):
    rows = DESIGN.selected_population()
    assert len(rows) == 8_192
    assert rows[0] == {"index": 0, "seed": 600_000_000_000,
                       "split": "dev"}
    assert rows[-1]["seed"] == 600_000_008_341
    assert {split: sum(row["split"] == split for row in rows)
            for split in DESIGN.SPLITS} == {"dev": 4_096, "calib": 4_096}
    assert hashlib.sha256(DESIGN._canonical(rows)).hexdigest() \
        == "e66d251a040bbd473e016cd06a1a6a28381f459e34372d2bc43840e3783d025a"
    assert design["population"]["selected_seed_manifest_sha256"] \
        == DESIGN.POPULATION_SHA256


def test_all_lane_membership_is_literal_and_independently_pinned(design):
    lanes = design["population"]["lane_manifest"]
    observed = tuple((
        lane["lane_index"], lane["deals"],
        lane["deals_by_split"]["dev"],
        lane["deals_by_split"]["calib"],
        lane["seed_manifest_sha256"],
    ) for lane in lanes)
    assert observed == EXPECTED_LANES
    assert sum(row[2] for row in observed) == 4_096
    assert sum(row[3] for row in observed) == 4_096
    assert all(row[1] == 512 and row[2] + row[3] == 512
               for row in observed)
    assert DESIGN._digest(DESIGN._canonical(list(observed))) \
        == "f5684a8b4953670153af5d20cee2f2dbe6e1d7c77b42bca5b477c0e538f9c3fe"


def test_complete_seed_domain_is_disjoint_from_every_known_pair_domain(design):
    population = design["population"]
    proposed = population["complete_game_and_actor_seed_domain"]
    assert proposed == {"low": 600_000_000_000, "high": 600_001_508_341}
    assert population["known_pair_seed_domains"] == [
        {"name": name, "low": low, "high": high}
        for name, low, high in DESIGN.KNOWN_PAIR_SEED_DOMAINS
    ]
    assert all(not DESIGN._overlap(
        proposed["low"], proposed["high"], row["low"], row["high"])
        for row in population["known_pair_seed_domains"])
    assert population["fresh_and_disjoint_from_known_pair_populations_verified"] \
        is True
    assert population["partial_split_publication_permitted"] is False


def test_estimand_counts_every_natural_event_by_exact_role_and_band(design):
    estimand = design["estimand"]
    assert estimand["policy"] == estimand["opponent_policy"] \
        == "mc-s0-report-lcb"
    assert estimand["roles"] == ["attacker", "defender"]
    assert estimand["bands"] == {
        "early": "trick < 4",
        "mid": "4 <= trick < 12",
        "late": "trick >= 12",
    }
    assert estimand["counts_all_eligible_omission_states"] is True
    assert estimand["not_only_first_event_per_deal_or_band"] is True
    assert estimand["no_outcome_or_utility_estimand"] is True


def test_instrumentation_is_actor_visible_observational_and_exact(design):
    contract = design["instrumentation_contract"]
    assert contract["instrumentation_occurs_before_the_natural_lead_decision"] \
        is True
    assert contract["candidate_view"] \
        == "acting hand plus public round state only"
    assert contract["opponent_hands_or_future_information_visible"] is False
    assert contract["pair_actions"] == "every legal in-hand pair action"
    assert contract["role_definition"] \
        == "seat parity relative to current banker"
    assert contract["band_definition"] \
        == "completed tricks before the natural lead"
    assert contract["candidate_ballots_and_pair_enumeration_must_be_pure"] \
        is True
    assert contract["instrumentation_consumes_no_rng_and_cannot_change_actions"] \
        is True
    assert contract["same_game_and_bot_rng_seeds_across_instrumented_and_reference"] \
        is True
    assert contract["complete_declaration_bury_play_histories_must_be_byte_equal"] \
        is True
    assert contract["root_worlds"] == 30
    assert contract["report_worlds"] == 300
    assert contract["short_zero_void_fallback_or_exact_endgame"] \
        == "refuse census"


def test_score_free_output_is_closed_and_uses_exact_denominators(design):
    output = design["score_free_output_contract"]
    assert output["all_split_role_band_cells_are_present"] is True
    assert output["cell_weights_are_eligible_omission_counts_divided_by_all_eligible_omissions"] \
        is True
    assert output["band_and_role_weights_are_exact_marginals_of_cell_counts"] \
        is True
    assert output["zero_event_cells_are_published_not_imputed"] is True
    assert output["raw_actions_states_hands_decks_buries_and_histories_published"] \
        is False
    assert output["winner_points_scores_utilities_labels_and_effects_published"] \
        is False
    assert output["report_or_sealed_strength_artifact_read"] is False
    assert output["score_free_supervisor_final_review_before_aggregate"] is True
    assert output["result_interpretation_requires_separate_review"] is True


def test_air_screen_is_complementary_not_a_substitute(design):
    boundary = design["interpretation_boundary"]
    assert boundary["current_air_pair_screen_is_complementary_but_lacks_all_band_counts"] \
        is True
    assert boundary["may_inform_a_fresh_scored_packet_design_after_terminal_review"] \
        is True
    assert boundary["does_not_rewrite_the_reviewed_scored_packet"] is True
    assert boundary["does_not_estimate_human_production_traffic"] is True
    assert boundary["does_not_measure_pair_retention_effect"] is True
    assert boundary["does_not_establish_utility_per_compute_or_strength"] is True


def test_all_post_design_authority_is_closed(design):
    assert design["status"] == "design only; census implementation does not exist"
    assert design["authority"] == {
        "design_review_only": True,
        "implementation_authorized": False,
        "capacity_preflight_authorized": False,
        "packet_freeze_authorized": False,
        "census_execution_authorized": False,
        "population_open_authorized": False,
        "scored_output_access_authorized": False,
        "aggregation_authorized": False,
        "report_access_authorized": False,
        "scored_pair_packet_authorized": False,
        "whole_game_execution_authorized": False,
        "retry_authorized": False,
        "extension_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


@pytest.mark.parametrize(
    "path,value",
    (
        (("authority", "census_execution_authorized"), True),
        (("authority", "report_access_authorized"), True),
        (("estimand", "counts_all_eligible_omission_states"), False),
        (("instrumentation_contract", "root_worlds"), 29),
        (("instrumentation_contract", "opponent_hands_or_future_information_visible"), True),
        (("score_free_output_contract", "raw_actions_states_hands_decks_buries_and_histories_published"), True),
        (("population", "candidate_seed_hi_inclusive"), 600_000_008_340),
        (("interpretation_boundary", "does_not_measure_pair_retention_effect"), False),
    ),
)
def test_coordinated_self_rehash_mutations_refuse(
        monkeypatch, design, path, value):
    changed = copy.deepcopy(design)
    changed[path[0]][path[1]] = value
    _rehash(changed)
    monkeypatch.setattr(DESIGN, "build_design", lambda: copy.deepcopy(design))
    with pytest.raises(DESIGN.DoseDesignRefused,
                       match="reconstruction drift"):
        DESIGN.validate_design(changed)


def test_overlapping_reserved_domain_refuses(monkeypatch):
    monkeypatch.setattr(DESIGN, "KNOWN_PAIR_SEED_DOMAINS", (
        ("collision", 600_000_000_100, 600_000_000_200),
    ))
    with pytest.raises(DESIGN.DoseDesignRefused,
                       match="fresh population reconstruction drift"):
        DESIGN.build_design()


def test_reviewer_actor_drift_refuses(monkeypatch):
    original = DESIGN._git_text

    def wrong_actor(*args):
        if args[:3] == ("show", "-s", "--format=%an <%ae>%n%cn <%ce>"):
            return "Codex <noreply@openai.com>\nCodex <noreply@openai.com>\n"
        return original(*args)

    monkeypatch.setattr(DESIGN, "_git_text", wrong_actor)
    with pytest.raises(DESIGN.DoseDesignRefused,
                       match="review provenance drift"):
        DESIGN._reviewed_source()


def test_review_ledger_rewrite_refuses(monkeypatch):
    original = DESIGN._git_bytes

    def rewritten(ref, path):
        raw = original(ref, path)
        if ref == DESIGN.SOURCE_REVIEW_GIT and path == DESIGN.REVIEW_LEDGER:
            return b"rewritten\n" + raw
        return raw

    monkeypatch.setattr(DESIGN, "_git_bytes", rewritten)
    with pytest.raises(DESIGN.DoseDesignRefused,
                       match="review statement drift"):
        DESIGN._reviewed_source()


def test_source_bytes_cannot_drift_or_be_preloaded(monkeypatch):
    original = DESIGN._stable_bytes

    def drift(path, *, label, frozen=False):
        raw = original(path, label=label, frozen=frozen)
        if label == "source design":
            return raw + b"\n"
        return raw

    monkeypatch.setitem(
        sys.modules, "pair_ballot_affected_scored_packet_design", object())
    monkeypatch.setattr(DESIGN, "_stable_bytes", drift)
    with pytest.raises(DESIGN.DoseDesignRefused,
                       match="source bytes drift"):
        DESIGN._reviewed_source()


def test_verify_accepts_only_frozen_canonical_file(tmp_path, design):
    path = tmp_path / "design.json"
    path.write_bytes(DESIGN._canonical(design))
    path.chmod(0o444)
    assert DESIGN.verify_design(path) == design

    path.chmod(0o644)
    with pytest.raises(DESIGN.DoseDesignRefused, match="non-writable"):
        DESIGN.verify_design(path)


@pytest.mark.parametrize(
    "raw,match",
    (
        (b'{"schema":"a","schema":"b"}\n', "duplicate key"),
        (b'{"elapsed":NaN}\n', "non-finite"),
        (b'{"schema":"x"} trailing\n', "strict JSON"),
    ),
)
def test_verify_rejects_noncanonical_json(tmp_path, raw, match):
    path = tmp_path / "design.json"
    path.write_bytes(raw)
    path.chmod(0o444)
    with pytest.raises(DESIGN.DoseDesignRefused, match=match):
        DESIGN.verify_design(path)


@pytest.mark.parametrize("kind", ("symlink", "hardlink"))
def test_verify_rejects_linked_inputs(tmp_path, design, kind):
    source = tmp_path / "source.json"
    source.write_bytes(DESIGN._canonical(design))
    source.chmod(0o444)
    target = tmp_path / "target.json"
    if kind == "symlink":
        target.symlink_to(source)
    else:
        os.link(source, target)
    with pytest.raises(DESIGN.DoseDesignRefused,
                       match="regular, unlinked"):
        DESIGN.verify_design(target)


def test_cli_build_and_verify_are_stdout_only(tmp_path, design):
    script = Path(DESIGN.__file__)
    before = set(tmp_path.iterdir())
    built = subprocess.run(
        [sys.executable, str(script), "build"], cwd=DESIGN.REPO,
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert set(tmp_path.iterdir()) == before
    assert json.loads(built.stdout) == design
    path = tmp_path / "design.json"
    path.write_text(built.stdout)
    path.chmod(0o444)
    verified = subprocess.run(
        [sys.executable, str(script), "verify", "--design", str(path)],
        cwd=DESIGN.REPO, check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert json.loads(verified.stdout) == {
        "schema": DESIGN.SCHEMA,
        "design_sha256": EXPECTED_INTERNAL_SHA256,
        "deals": 8_192,
        "implementation_authorized": False,
        "census_execution_authorized": False,
    }


def test_module_has_no_implementation_gameplay_or_writer_surface():
    source = Path(DESIGN.__file__).read_text()
    for forbidden in (
        "import shengji", "multiprocessing", "systemd-run", "Popen",
        "play_round", "make_bot(", "Game(", "write_bytes(", "write_text(",
        "open(\"w", "os.system", "execv", "spawn",
    ):
        assert forbidden not in source
    assert set(DESIGN.main.__code__.co_names).isdisjoint({
        "fork", "execv", "spawn", "system", "Popen",
    })
