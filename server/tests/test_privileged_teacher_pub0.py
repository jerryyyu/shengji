"""Adversarial witnesses for the public-information Pub0 boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl import privileged_teacher_full_ab as full
from shengji.rl import privileged_teacher_pub0 as pub0
from shengji.rl import privileged_teacher_sol0 as sol0


_SECRET = b"pt-full-private-seed-material!!!"
assert len(_SECRET) == 32

HIDDEN_KEYS = ("hands_by_seat", "hidden_burial", "remaining_points_by_seat")


def _root():
    design = full.FullABDesign(
        seed_commitment_sha256=hashlib.sha256(_SECRET).hexdigest(),
        execution_git="a" * 40,
        native_sha256="b" * 64,
        hostname=full.MINI_HOSTNAME,
    )
    coordinate = design.root_coordinates[0]
    return coordinate, full._build_root(design, _SECRET, *coordinate)


def _sessions():
    coordinate, root = _root()
    public = pub0.Pub0GameSession(
        root, treatment_team=root.banker % 2, seed_secret=_SECRET,
        coordinate=coordinate, role="banker-team")
    _, root2 = _root()
    exact = sol0.Sol0GameSession(
        root2, treatment_team=root2.banker % 2, seed_secret=_SECRET,
        coordinate=coordinate, role="banker-team")
    return public, exact


def test_observe_serves_no_hidden_information():
    public, exact = _sessions()
    view = public.observe()
    reference = exact.observe()
    for key in HIDDEN_KEYS:
        assert key not in view, key
    assert view["information_model"] == pub0.INFO_MODEL
    seat = view["acting_seat"]
    assert view["acting_hand"] == sorted(public.rnd.hands[seat])
    if seat == public.rnd.banker:
        assert view["burial_if_banker"] == sorted(public.rnd.buried)
    else:
        assert view["burial_if_banker"] is None
    assert view["cards_remaining_by_seat"] == [
        len(hand) for hand in public.rnd.hands]
    # Public fields must agree with the exact-information session on the
    # identical root; redaction removes, never distorts.
    for key in ("acting_seat", "banker", "trump_rank", "trump_suit",
                "attacker_points", "current_trick", "completed_tricks"):
        assert view[key] == reference[key], key
    assert view["decision_sha256"] != reference["decision_sha256"]
    assert view["public_state_sha256"] == pub0.pt0_public_state_sha256(
        public.rnd, perspective_seat=seat)
    assert [c["cards"] for c in view["candidates"]] == \
        [c["cards"] for c in reference["candidates"]]


def test_observe_redaction_event_logs_only_the_redacted_view():
    public, _ = _sessions()
    view = public.observe()
    logged = public._events[-1]
    served = logged["response"] if "response" in logged else logged
    raw = str(served)
    for key in HIDDEN_KEYS:
        assert key not in raw
    assert str(view["decision_sha256"]) in raw


def test_rollout_samples_worlds_deterministically_and_reports_spread():
    public, _ = _sessions()
    other, _ = _sessions()  # fresh session, identical root and state
    view = public.observe()
    result_a = public._evaluate(0, "smart-all")
    result_b = other._evaluate(0, "smart-all")
    assert result_a["worlds"] == pub0.WORLDS_PER_EVALUATION
    assert len(result_a["attacker_points_per_world"]) == \
        pub0.WORLDS_PER_EVALUATION
    assert result_a["attacker_points_per_world"] == \
        result_b["attacker_points_per_world"]
    assert result_a["world_fingerprints"] == result_b["world_fingerprints"]
    assert len(set(result_a["world_fingerprints"])) > 1
    assert result_a["information_model"] == pub0.INFO_MODEL
    assert result_a["attacker_points_min"] <= \
        result_a["attacker_points_mean"] <= result_a["attacker_points_max"]
    del view


def test_public_decision_and_view_are_identical_across_hidden_twins():
    public, _ = _sessions()
    twin, _ = _sessions()
    seat = public.rnd.turn
    assert seat is not None and twin.rnd.turn == seat
    hidden = [value for value in range(4) if value != seat]
    left, right = hidden[:2]
    twin.rnd.hands[left][0], twin.rnd.hands[right][0] = (
        twin.rnd.hands[right][0], twin.rnd.hands[left][0])
    twin._public_state_sha256, twin._decision_sha256 = (
        pub0._public_decision_sha256(twin))
    assert public.observe() == twin.observe()

    # A non-banker cannot distinguish a hand/kitty exchange either.
    coordinate, root = _root()
    attacker = pub0.Pub0GameSession(
        root, treatment_team=1 - root.banker % 2, seed_secret=_SECRET,
        coordinate=coordinate, role="attacker-team")
    attacker_twin = copy.deepcopy(attacker)
    acting = attacker.rnd.turn
    assert acting is not None and acting != attacker.rnd.banker
    donor = next(value for value in range(4) if value != acting)
    attacker_twin.rnd.hands[donor][0], attacker_twin.rnd.buried[0] = (
        attacker_twin.rnd.buried[0], attacker_twin.rnd.hands[donor][0])
    attacker_twin._public_state_sha256, attacker_twin._decision_sha256 = (
        pub0._public_decision_sha256(attacker_twin))
    assert attacker.observe() == attacker_twin.observe()

    # Actor-private facts remain positively bound.
    acting_twin = copy.deepcopy(public)
    acting_twin.rnd.hands[seat][0], acting_twin.rnd.hands[left][0] = (
        acting_twin.rnd.hands[left][0], acting_twin.rnd.hands[seat][0])
    assert pub0._public_decision_sha256(acting_twin) != \
        pub0._public_decision_sha256(public)


def test_every_candidate_and_continuation_reuses_one_world_bank():
    public, _ = _sessions()
    assert public._candidates is not None and len(public._candidates) > 1
    first = public._evaluate(0, "smart-all")
    second = public._evaluate(1, "smart-all")
    third = public._evaluate(0, "team-smart")
    assert first["world_fingerprints"] == second["world_fingerprints"] \
        == third["world_fingerprints"]
    assert first["sampler_attempts"] == second["sampler_attempts"] \
        == third["sampler_attempts"]


def test_rollout_utility_is_averaged_after_each_world_threshold():
    attacker, attacker_mean = pub0._mean_signed_level_utility(
        [79, 81], banker_seat=0, perspective_seat=1)
    banker, banker_mean = pub0._mean_signed_level_utility(
        [79, 81], banker_seat=0, perspective_seat=0)
    assert attacker == [-1, 1] and attacker_mean == 0
    assert banker == [1, -1] and banker_mean == 0
    # Rounding the mean points first would incorrectly choose a winner at 80.
    assert sol0.signed_level_utility(
        80, banker_seat=0, perspective_seat=1) == 1


def test_prompt_builder_is_public_and_bound_to_the_session():
    assert pub0.Pub0GameSession.planner_prompt_builder is \
        pub0.pub0_planner_prompt
    prompt = pub0.pub0_planner_prompt(
        mailbox_path="/mb", tool_script="/tool.py", python="/py", seat=2)
    assert "fixed seat 2" in prompt
    assert "separate isolated" in prompt
    assert "all hands" not in prompt
    assert str(pub0.WORLDS_PER_EVALUATION) in prompt
    assert not hasattr(sol0.Sol0GameSession, "planner_prompt_builder") or \
        getattr(sol0.Sol0GameSession, "planner_prompt_builder", None) is None


def test_pub0_design_identifies_arm_and_pins_estimand():
    design = pub0.Pub0Design(
        seed_commitment_sha256="a" * 64, execution_git="b" * 40,
        native_sha256="c" * 64, hostname=full.MINI_HOSTNAME,
        c0_external_sha256="d" * 64, c0_report_sha256="e" * 64,
        c0_execution_git="f" * 40, full_external_sha256="0" * 64,
        full_report_sha256="1" * 64, full_execution_git="2" * 40,
        codex_binary_sha256="3" * 64, codex_version="9.9.9",
        python_binary_sha256="4" * 64, python_version="3.14 test",
        tool_script_sha256="5" * 64,
        planner="claude", planner_model="claude-fable-5")
    payload = design.payload()
    assert payload["schema"] == pub0.PUB0_DESIGN_SCHEMA
    assert payload["model"] == "claude-fable-5"
    assert payload["prompt_template_sha256"] == \
        pub0.PUB0_PROMPT_TEMPLATE_SHA256
    config = payload["planner_config"]
    assert config["information_model"] == pub0.INFO_MODEL
    assert config["planner_context_scope"] == \
        "fixed-seat-isolated-persistent-v1"
    assert config["planner_contexts_per_role"] == 2
    assert config["world_source"] == pub0.WORLD_SOURCE
    assert config["world_comparison"] == "common-random-world-bank-v1"
    assert config["worlds_per_evaluation"] == pub0.WORLDS_PER_EVALUATION
    assert config["utility_aggregation"] == \
        "mean-per-world-signed-level-v1"
    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="Pub0 planner identity drift"):
        pub0.Pub0Design(
            seed_commitment_sha256="a" * 64, execution_git="b" * 40,
            native_sha256="c" * 64, hostname=full.MINI_HOSTNAME,
            c0_external_sha256="d" * 64, c0_report_sha256="e" * 64,
            c0_execution_git="f" * 40, full_external_sha256="0" * 64,
            full_report_sha256="1" * 64, full_execution_git="2" * 40,
            codex_binary_sha256="3" * 64, codex_version="9.9.9",
            python_binary_sha256="4" * 64, python_version="3.14 test",
            tool_script_sha256="5" * 64, planner="gemini")


def test_session_factory_seam_defaults_to_sol0():
    import inspect
    from shengji.rl import privileged_teacher_sol0_report as report
    for fn in (report.run_dev, report._run_root, report._run_role):
        parameter = inspect.signature(fn).parameters["session_factory"]
        assert parameter.default is report.Sol0GameSession
        runner = inspect.signature(fn).parameters["session_runner"]
        assert runner.default is report.run_sol_session


def test_pub0_runner_uses_two_isolated_fixed_seat_contexts(tmp_path: Path):
    public, _ = _sessions()
    public._opponents = [HeuristicBot() for _ in range(4)]
    private = tmp_path / "private.json"
    seen: dict[int, list[int]] = {}
    prompts: dict[int, str] = {}

    def planner(control, *, prompt, final_output_path, **_kwargs):
        seat = control.seat
        prompts[seat] = prompt
        seen[seat] = []
        completion_token = None
        while True:
            observed = control.observe()
            if observed["status"] == "round_end":
                completion_token = observed["completion_token"]
                break
            assert observed["acting_seat"] == seat
            assert "hands_by_seat" not in observed
            seen[seat].append(observed["acting_seat"])
            played = control.play({
                "op": "play",
                "decision_sha256": observed["decision_sha256"],
                "candidate_index": 0,
                "confidence": "low",
            })
            completion_token = played.get("completion_token") or \
                completion_token
            if played["status"] == "round_end":
                break
        final_output_path.write_text(json.dumps({
            "schema": sol0.FINAL_RESPONSE_SCHEMA,
            "status": "complete",
            "completion_token": completion_token,
        }))
        return subprocess.CompletedProcess(
            args=("fake-pub0",), returncode=0,
            stdout=f"seat-{seat}-private".encode("ascii"))

    outcome = pub0.run_pub0_session(
        public, private_output=private, tool_script=Path(__file__),
        planner_process=planner, codex_binary=Path(sys.executable))
    assert public.complete and outcome.model_exit_code == 0
    assert set(seen) == {public.treatment_team, public.treatment_team + 2}
    assert all(values and set(values) == {seat}
               for seat, values in seen.items())
    assert all(f"fixed seat {seat}" in prompts[seat] for seat in seen)
    evidence = json.loads(private.read_text())
    assert evidence["process_error"] is None
    stdout_frame = json.loads(__import__("base64").b64decode(
        evidence["model_stdout_base64"]))
    assert [row["seat"] for row in stdout_frame["seats"]] == sorted(seen)
