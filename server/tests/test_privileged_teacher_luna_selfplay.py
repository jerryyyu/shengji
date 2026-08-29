"""Focused boundary checks for the fresh Luna self-play collector."""

from __future__ import annotations

import hashlib
import threading

import pytest

from shengji.rl import privileged_teacher_luna_selfplay as luna


SECRET = b"luna-self-play-secret-material!!"
assert len(SECRET) == 32


def test_population_and_mirrors_are_closed_and_clustered():
    design = luna.LunaDesign(
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    assert len(design.root_coordinates) == 52
    assert len(design.deal_clusters) == 52
    assert len(design.mirror_assignments) == 104
    assert all(sum(c == key for c, _ in design.mirror_assignments) == 2
               for key in design.deal_clusters)
    assert luna.agent_team_assignment(0) == (0, 1)
    assert luna.agent_team_assignment(1) == (1, 0)
    assert set(design.payload()) == {
        "schema", "namespace", "seed_commitment_sha256", "execution_git",
        "native_sha256", "hostname", "trump_ranks", "banker_seats",
        "replicates", "deal_cluster_count", "game_count",
        "mirror_count_per_cluster", "candidate_game_workers", "authority"}
    assert all(value is False for value in luna.AUTHORITY.values())


def test_fresh_root_and_full_information_observation():
    root = luna.build_root(SECRET, ("2", 0, 0))
    game = luna.LunaSelfPlayGame(root, coordinate=("2", 0, 0))
    observed = game.session(0).observe()
    assert observed["status"] == "decision"
    assert observed["hands_by_seat"] == [sorted(hand) for hand in root.hands]
    assert observed["hidden_burial"] == sorted(root.buried)
    assert observed["candidate_zero_is_production_prior"] is True
    assert game.session(0).memory is not game.session(1).memory
    assert game.session(0).session_id != game.session(1).session_id
    mirror = luna.LunaSelfPlayGame(
        luna.build_root(SECRET, ("2", 0, 0), mirror=1),
        coordinate=("2", 0, 0), mirror=1)
    assert game.root_sha256 == mirror.root_sha256
    assert game.session(0).agent_identity == mirror.session(1).agent_identity
    assert game.session(1).agent_identity == mirror.session(0).agent_identity


def test_state_digest_binds_current_points_and_mechanics():
    root = luna.build_root(SECRET, ("2", 0, 0))
    game = luna.LunaSelfPlayGame(root, coordinate=("2", 0, 0))
    team = game.acting_team
    before = luna._state_digest(root, team)
    root.attacker_points = 5
    assert luna._state_digest(root, team) != before
    root.attacker_points = 0
    root.kitty_bonus = 2
    assert luna._state_digest(root, team) != before
    root.kitty_bonus = 0
    observed = game.session(team).observe()
    game.session(team).play({"op": "play",
                             "decision_sha256": observed["decision_sha256"],
                             "candidate_index": 0, "confidence": "low"})
    event = game.trajectory.events[0]
    assert event["state_before"]["attacker_points"] == 0
    assert event["state_before"]["kitty_bonus"] == 0
    assert "signed_level_utility" not in event


def test_nonacting_planner_refused_and_failure_wakes_waiter():
    root = luna.build_root(SECRET, ("2", 0, 0))
    game = luna.LunaSelfPlayGame(root, coordinate=("2", 0, 0))
    wrong = 1 if game.acting_team == 0 else 0
    with pytest.raises(luna.LunaPlannerRequestError, match="non-acting"):
        game.session(wrong).play({"op": "play", "decision_sha256": "x",
                                  "candidate_index": 0, "confidence": "low"})
    got = []
    thread = threading.Thread(target=lambda: got.append(
        game.session(wrong).wait(timeout=None)))
    thread.start()
    game.fail("control failure")
    thread.join(1)
    assert not thread.is_alive() and got == [False]
    assert game.session(0).observe()["status"] == "failed"
    assert game.session(1).observe()["status"] == "failed"


def test_trajectory_is_private_sealed_state_action_only():
    root = luna.build_root(SECRET, ("2", 0, 0))
    game = luna.LunaSelfPlayGame(root, coordinate=("2", 0, 0))
    team = game.acting_team
    observed = game.session(team).observe()
    game.session(team).play({"op": "play",
                             "decision_sha256": observed["decision_sha256"],
                             "candidate_index": 0, "confidence": "low"})
    sealed = game.trajectory.seal()
    assert sealed.payload() == {
        "schema": luna.TRAJECTORY_SCHEMA, "private": True,
        "trajectory_sha256": sealed.sha256}
    assert b"value" not in sealed.private_bytes()
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError, match="sealed"):
        game.trajectory.append(team=0, seat=0, state_sha256="b" * 64,
                          action=["S3"], candidate_index=0)
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError, match="prose"):
        game.trajectory.record_model_text("do not retain")


def test_workers_progress_and_no_retry_incomplete_retention():
    assert luna.candidate_worker_arms() == (1, 2, 4, 6, 8)
    for workers in luna.CANDIDATE_GAME_WORKERS:
        assert luna.validate_capacity(workers)["launches"] == 0
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError):
        luna.validate_game_workers(3)
    updates = []
    calls = []

    def runner(coord, mirror):
        calls.append((coord, mirror))
        if len(calls) == 1:
            return luna.PrivateTrajectory(("3", 0, 0), mirror).seal()
        root_sha = luna.root_identity(luna.build_root(SECRET, coord))
        trajectory = luna.PrivateTrajectory(coord, mirror,
                                            root_sha256=root_sha).seal()
        terminal = luna.TerminalReceipt(
            coordinate=coord, mirror=mirror, root_sha256=root_sha,
            trajectory_sha256=trajectory.sha256, final_attacker_points=0,
            signed_level_utility=luna.sol0.signed_level_utility(
                0, banker_seat=coord[1], perspective_seat=0), completion=True)
        return luna.CompletedGameArtifacts(trajectory, terminal)

    report = luna.run_population(
        luna.LunaDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest()),
        seed_secret=SECRET,
        census=luna.root_census(
            SECRET, luna.LunaDesign(
                seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())),
        game_runner=runner, progress_sink=updates.append)
    assert len(calls) == 104
    assert report["total_games"] == 104
    assert report["completed_games"] == 104
    assert report["successful_games"] == 0
    assert report["terminal_route"] == luna.INCOMPLETE_ROUTE
    assert report["completed_deal_clusters"] == 0
    assert report["rows"][0]["status"] == "incomplete"
    luna.validate_population_report(
        report, luna.LunaDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest()))
    assert updates[-1]["percent_basis_points"] == 10000
    assert updates[-1]["successful_games"] == 0
    assert set(updates[-1]) == {
        "schema", "completed_games", "processed_games", "total_games",
        "successful_games",
        "completed_deal_clusters", "total_deal_clusters",
        "percent_basis_points", "elapsed_seconds", "eta_seconds",
        "failure_count", "active_game_workers", "active_model_processes",
        "recent_games_per_second"}


def test_progress_arithmetic():
    row = luna.progress(completed_games=52, total_games=104,
                        completed_deal_clusters=26, total_deal_clusters=52,
                        elapsed_seconds=10)
    assert row["percent_basis_points"] == 5000
    assert row["eta_seconds"] == 10


def test_root_census_covers_all_modes_and_mirrors_share_identity():
    design = luna.LunaDesign(
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    roots = {coordinate: luna.build_root(SECRET, coordinate)
             for coordinate in design.root_coordinates}
    luna.validate_root_population(roots, design=design)
    assert {luna.root_trump_mode(root) for root in roots.values()} == \
        set(luna.TRUMP_MODES)
    for coordinate, root in roots.items():
        assert luna.root_seed(SECRET, coordinate, 0) == \
            luna.root_seed(SECRET, coordinate, 1)
        assert luna.root_identity(root) == luna.root_identity(
            luna.build_root(SECRET, coordinate))
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError,
                       match="coordinate drift"):
        luna.validate_root_population(
            {coordinate: root for coordinate, root in roots.items()
             if luna.root_trump_mode(root) != "NT"}, design=design)


def test_score_free_census_and_terminal_receipt_are_separate():
    design = luna.LunaDesign(
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = luna.root_census(SECRET, design)
    luna.validate_root_census(census, design=design)
    reopened = luna.RootCensus.reopen(census.serialized(), design=design)
    assert reopened.census_sha256 == census.census_sha256
    forged_serialized = census.serialized()
    forged_serialized["census_sha256"] = "f" * 64
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError):
        luna.RootCensus.reopen(forged_serialized, design=design)
    assert "attacker_points" not in census.body
    forged = dict(census.body)
    forged["coordinates"] = list(census.body["coordinates"])
    forged["coordinates"][0] = dict(forged["coordinates"][0])
    forged["coordinates"][0]["mirror_root_sha256"] = "f" * 64
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError):
        luna.validate_root_census(forged, design=design)

    game = luna.LunaSelfPlayGame(
        luna.build_root(SECRET, ("2", 0, 0)), coordinate=("2", 0, 0))
    while not game.complete:
        team = game.acting_team
        observation = game.session(team).observe()
        game.session(team).play({"op": "play",
                                 "decision_sha256": observation["decision_sha256"],
                                 "candidate_index": 0, "confidence": "low"})
    trajectory = game.sealed_trajectory()
    assert trajectory.body["events"][-1]["state_after"] == {
        "phase": "round_end", "terminal_redacted": True}
    receipt = game.terminal_receipt()
    luna.validate_terminal_receipt(receipt.payload())
    assert receipt.receipt_sha256 == receipt.payload()["receipt_sha256"]
    forged_receipt = receipt.payload()
    forged_receipt["trajectory_sha256"] = "f" * 64
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError):
        luna.validate_terminal_receipt(
            forged_receipt, root_sha256=game.root_sha256,
            trajectory_sha256=trajectory.sha256,
            coordinate=game.coordinate, mirror=game.mirror)


def test_worker_threads_overlap_and_none_is_incomplete():
    import threading
    import time
    design = luna.LunaDesign(
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    active = 0
    peak = 0
    updates = []
    lock = threading.Lock()

    def runner(_coordinate, _mirror):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.002)
        with lock:
            active -= 1
        return None

    report = luna.run_population(design, seed_secret=SECRET,
                                 census=luna.root_census(SECRET, design),
                                 game_runner=runner, worker_count=4,
                                 progress_sink=updates.append)
    assert peak > 1
    assert report["completed_games"] == 104
    assert report["successful_games"] == 0
    assert max(row["active_game_workers"] for row in updates) > 1
    assert updates[-1]["active_game_workers"] == 0
    assert updates[-1]["active_model_processes"] == 0


def test_population_census_gate_and_incomplete_sealed_hash():
    design = luna.LunaDesign(
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = luna.root_census(SECRET, design)
    calls = []
    bad = census.serialized()
    bad["census_sha256"] = "f" * 64
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError):
        luna.run_population(design, seed_secret=SECRET, census=bad,
                            game_runner=lambda *_: calls.append(1))
    assert calls == []
    report = luna.run_population(
        design, seed_secret=SECRET, census=census,
        game_runner=lambda *_: None)
    assert report["processed_games"] == report["completed_games"] == 104
    assert all(row["status"] == "incomplete"
               and isinstance(row["incomplete_artifact_sha256"], str)
               for row in report["rows"])
    luna.validate_population_report(report, design)


def test_complete_artifact_replay_and_sealed_reopen_binding():
    coordinate = ("2", 0, 0)
    game = luna.LunaSelfPlayGame(
        luna.build_root(SECRET, coordinate), coordinate=coordinate)
    artifact = luna.run_game(game)
    assert artifact is not None
    reopened = luna.SealedTrajectory.reopen(
        artifact.trajectory.private_bytes())
    assert reopened.sha256 == artifact.trajectory.sha256
    with pytest.raises(luna.PrivilegedTeacherLunaSelfPlayError):
        artifact.trajectory.body["mirror"] = 1
        artifact.trajectory.private_bytes()
    assert artifact.terminal_receipt.final_attacker_points >= 0


def test_run_game_uses_two_independent_concurrent_callbacks():
    coordinate = ("2", 0, 0)
    game = luna.LunaSelfPlayGame(
        luna.build_root(SECRET, coordinate), coordinate=coordinate)
    seen = []
    lock = threading.Lock()

    def callback(session, observation):
        with lock:
            seen.append((session.team, observation["acting_seat"]))
        return {"op": "play", "decision_sha256": observation["decision_sha256"],
                "candidate_index": 0, "confidence": "low"}

    artifact = luna.run_game(game, {0: callback, 1: callback})
    assert artifact is not None
    assert {team for team, _ in seen} == {0, 1}
    assert all(seat % 2 == team for team, seat in seen)
    # Forced single-candidate actions are engine-owned and intentionally do
    # not invoke a planner.  The callback stream must match every contested
    # event in the engine trajectory, in order.
    contested = [event for event in artifact.trajectory.body["events"]
                 if len(event["legal_ballot"]) > 1]
    assert [(event["team"], event["seat"]) for event in contested] == seen
