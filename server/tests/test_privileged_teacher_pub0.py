"""Adversarial witnesses for the public-information Pub0 boundary."""

from __future__ import annotations

import hashlib

import pytest

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
                "attacker_points", "current_trick", "completed_tricks",
                "decision_sha256"):
        assert view[key] == reference[key], key
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


def test_prompt_builder_is_public_and_bound_to_the_session():
    assert pub0.Pub0GameSession.planner_prompt_builder is \
        pub0.pub0_planner_prompt
    prompt = pub0.pub0_planner_prompt(
        mailbox_path="/mb", tool_script="/tool.py", python="/py")
    assert "ONLY what the acting seat" in prompt
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
    assert config["world_source"] == pub0.WORLD_SOURCE
    assert config["worlds_per_evaluation"] == pub0.WORLDS_PER_EVALUATION
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
