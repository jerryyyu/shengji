"""Synthetic contract tests for the exact-lead qualifier's first-trick mode."""

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import pytest
from types import SimpleNamespace

from scripts import qualify_exact_lead as q
from scripts import exact_lead_cost_probe as cost_probe
from shengji.train import pv_exact_endgame, pv_search_policy
from test_encoder_round_compat import pinned_production_package  # noqa: F401


class _Round:
    def __init__(self):
        self.hands = [["BJ"], ["S5"], ["S8"], ["SQ"]]


class _Bot:
    def __init__(self, enabled, first_trick):
        self.enabled = enabled
        self.first_trick = first_trick
        self._refusals = None
        self.last_decision_record = None


class _Room:
    def __init__(self, *, game, bot, **_kwargs):
        self.game, self.bot = game, bot


def _install_synthetic(monkeypatch, seen):
    def recipes(**kwargs):
        seen.append(kwargs)
        enabled = kwargs.get("exact_lead_endgame", False)
        name = "synthetic" if enabled else q.BASELINE
        return {name: lambda **_kw: _Bot(
            enabled, kwargs.get("exact_lead_first_trick", False))}

    monkeypatch.setattr(q, "pv_registry_entries", recipes)
    monkeypatch.setattr(q, "pv_env_recipe", lambda env: {
        "exact_lead_endgame": env["SHENGJI_PV_EXACT_LEAD_ENDGAME"] == "1",
        "exact_lead_first_trick": env["SHENGJI_PV_EXACT_LEAD_FIRST_TRICK"] == "1",
    })
    monkeypatch.setattr(q, "restore_with_ledger", lambda _packet: (_Round(), object()))
    monkeypatch.setattr(q, "Game", lambda _rng: SimpleNamespace(round=None))
    monkeypatch.setattr(q.srv, "Room", _Room)
    monkeypatch.setattr(q.srv, "Seat", lambda name, is_bot: name)

    async def paced(room, _seat, minimum_turn_seconds=0):
        enabled = room.bot.enabled
        mode = "first_trick" if room.bot.first_trick else None
        record = {
            "work_complete": True,
            "exact_lead_status": "complete" if enabled else "ineligible",
            "exact_lead_worlds_completed": 64 if enabled else 0,
            "exact_lead_mode": mode,
            "selected_index": 0,
            "played": ["BJ"] if enabled else ["BJ", "S5", "S8", "SQ"],
            "value_means": [1.0, 0.5],
            "exact_lead_selected_level_mean": 1.0,
            "exact_lead_base_level_mean": 0.5,
            "exact_lead_selected_level_delta": 0.5,
            "exact_lead_seconds": 0.01,
            "exact_lead_nodes": 7,
            "exact_lead_cache_hits": 2,
        }
        copied = copy.copy(room.bot)
        copied.last_decision_record = record
        return SimpleNamespace(decision=SimpleNamespace(
            cards=record["played"], snapshot=SimpleNamespace(bot_copy=copied)))

    def commit(room, prepared):
        if getattr(prepared, "_committed", False):
            return False
        prepared._committed = True
        return True

    monkeypatch.setattr(q.srv, "_paced_bot_step", paced)
    monkeypatch.setattr(q.srv, "_commit_bot_turn", commit)


def test_first_trick_writes_two_mode_mechanism_records_without_action_claim(monkeypatch, tmp_path):
    seen = []
    _install_synthetic(monkeypatch, seen)
    out = tmp_path / "rows.jsonl"
    with out.open("w") as dest:
        result = asyncio.run(q.qualify("checked-in.npz", dest, first_trick=True))
    assert result == 0
    assert [item["exact_lead_first_trick"] for item in seen] == [False, True]
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 2
    assert all(row["passed"] and row["committed"] for row in rows)
    assert rows[1]["record"]["exact_lead_worlds_completed"] == 64
    assert rows[1]["record"]["exact_lead_mode"] == "first_trick"
    assert {"action_record", "value_record", "cost_record"} <= rows[1].keys()
    assert rows[1]["action_record"]["cards"] == ["BJ"]


def test_default_interface_keeps_bj_expectation(monkeypatch, tmp_path):
    seen = []
    _install_synthetic(monkeypatch, seen)
    out = tmp_path / "rows.jsonl"
    with out.open("w") as dest:
        assert asyncio.run(q.qualify("checked-in.npz", dest)) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows[0]["cards"] == ["BJ", "S5", "S8", "SQ"]
    assert rows[1]["cards"] == ["BJ"]
    assert all(not item["exact_lead_first_trick"] for item in seen)


def test_cli_accepts_first_trick_switch(monkeypatch, tmp_path):
    called = []

    async def fake_qualify(checkpoint, dest, release=44, *, first_trick=False):
        called.append((checkpoint, dest, release, first_trick))
        return 0

    monkeypatch.setattr(q, "qualify", fake_qualify)
    assert q.main(["--checkpoint", "model.npz", "--out", str(tmp_path / "out"),
                   "--first-trick"]) == 0
    assert called[0][2:] == (44, True)


def test_cli_cost_out_requires_first_trick_before_invocation(monkeypatch, tmp_path):
    called = []

    def forbidden(*args, **kwargs):
        called.append((args, kwargs))
        return 0

    monkeypatch.setattr(q, "qualify", forbidden)
    with pytest.raises(SystemExit):
        q.main(["--checkpoint", "model.npz", "--out", str(tmp_path / "out"),
                "--cost-out", str(tmp_path / "cost")])
    assert called == []
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "cost").exists()


def test_cli_cost_out_rejects_reused_path_before_invocation(monkeypatch, tmp_path):
    called = []

    async def forbidden(*args, **kwargs):
        called.append((args, kwargs))
        return 0

    monkeypatch.setattr(q, "qualify", forbidden)
    out = tmp_path / "out"
    cost = tmp_path / "cost"
    out.write_text("existing\n")
    cost.write_text("existing\n")
    with pytest.raises(SystemExit):
        q.main(["--checkpoint", "model.npz", "--out", str(out), "--first-trick",
                "--cost-out", str(cost)])
    assert called == []


def test_direct_qualify_cost_out_requires_first_trick(tmp_path):
    with pytest.raises(ValueError, match="cost_out requires first_trick"):
        asyncio.run(q.qualify("unused.npz", io.StringIO(), cost_out=io.StringIO()))


def test_cli_cost_out_same_path_refuses_before_creating_output(tmp_path):
    path = tmp_path / "same"
    with pytest.raises(SystemExit):
        q.main(["--checkpoint", "model.npz", "--out", str(path), "--first-trick",
                "--cost-out", str(path)])
    assert not path.exists()


def test_cli_cost_out_forwards_one_invocation_and_preserves_partial(monkeypatch, tmp_path):
    calls = []
    async def qualify(checkpoint, dest, release=44, *, first_trick=False, cost_out=None):
        calls.append((release, first_trick))
        dest.write('{"passed":false}\n')
        cost_out.write('{"status":"abandoned"}\n')
        return 1
    monkeypatch.setattr(q, "qualify", qualify)
    out, cost = tmp_path / "out", tmp_path / "cost"
    assert q.main(["--checkpoint", "model.npz", "--out", str(out),
                   "--release", "45", "--first-trick", "--cost-out", str(cost)]) == 1
    assert calls == [(45, True)]
    assert json.loads(out.read_text()) == {"passed": False}
    assert json.loads(cost.read_text()) == {"status": "abandoned"}


def test_cost_probe_projects_scalars_and_restores_both_seams(monkeypatch):
    original_stage = pv_search_policy.PVSearchBot._exact_lead_decision
    original_evaluator = pv_exact_endgame.exact_first_trick_means
    seen = []
    ticks = iter([10.0, 10.0, 10.25, 10.25, 10.75, 10.75,
                  11.0, 11.0])

    def clock():
        return next(ticks)

    def evaluator(*args, **kwargs):
        seen.append((args, kwargs))
        return object(), {"worlds_completed": 4, "nodes": 9,
                          "cache_hits": 2, "values": [1, 2]}

    def stage(bot, rnd, seat, admitted, worlds, started, check_budget, priors, base):
        result = pv_exact_endgame.exact_first_trick_means(
            rnd, seat, admitted, worlds, check_budget)
        bot._exact_lead = {"exact_lead_status": "complete",
                           "exact_lead_worlds_completed": result[1]["worlds_completed"]}
        return base

    monkeypatch.setattr(pv_search_policy.PVSearchBot, "_exact_lead_decision", stage)
    monkeypatch.setattr(pv_exact_endgame, "exact_first_trick_means", evaluator)
    sink = io.StringIO()
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]), hands=[["BJ"]] * 4)
    bot = SimpleNamespace(serving_budget_seconds=3.0, _exact_lead={})
    admitted = [["BJ"]]
    worlds = [(None, None)]
    base = object()
    with cost_probe.exact_lead_cost_probe(sink, perf_clock=clock, thread_clock=clock):
        assert pv_search_policy.PVSearchBot._exact_lead_decision(
            bot, rnd, 0, admitted, worlds, 9.0, None, [], base) is base
    assert len(seen) == 1 and seen[0][0][2] is admitted and seen[0][0][3] is worlds
    row = json.loads(sink.getvalue())
    assert row["world_count"] == row["admitted_count"] == 1
    assert row["remaining_soft_seconds"] == pytest.approx(1.4)
    assert row["total_stage_seconds"] == pytest.approx(1.0)
    assert row["evaluator_seconds"] == pytest.approx(0.5)
    assert row["non_evaluator_seconds"] == pytest.approx(0.5)
    assert row["evaluator_cpu_seconds"] == pytest.approx(0.5)
    assert row["evaluator_stats"] == {"worlds_completed": 4, "nodes": 9, "cache_hits": 2}
    assert row["status"] == "complete" and row["partial_worlds"] is None
    assert "values" not in row and pv_exact_endgame.exact_first_trick_means is evaluator
    assert pv_search_policy.PVSearchBot._exact_lead_decision is stage
    assert original_stage is not stage and original_evaluator is not evaluator


def test_cost_probe_skipped_budget_never_calls_evaluator(monkeypatch):
    monkeypatch.setattr(pv_search_policy.time, "perf_counter", lambda: 2.0)
    def forbidden(*args, **kwargs):
        pytest.fail("skipped stage called evaluator")
    monkeypatch.setattr(pv_exact_endgame, "exact_first_trick_means", forbidden)
    bot = SimpleNamespace(exact_lead_first_trick=True, serving_budget_seconds=3.0)
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]), hands=[["BJ"]] * 4)
    base = object()
    sink = io.StringIO()
    with cost_probe.exact_lead_cost_probe(sink):
        assert pv_search_policy.PVSearchBot._exact_lead_decision(
            bot, rnd, 0, [["BJ"]], [object()], 0.0, None, [], base) is base
    row = json.loads(sink.getvalue())
    assert row["status"] == "skipped_budget"
    assert row["eligible_start"] is False
    assert row["evaluator_calls"] == row["evaluator_seconds"] == 0


def test_cost_probe_rethrows_same_baseexception_and_marks_unknown(monkeypatch):
    class Cancelled(BaseException):
        pass

    failure = Cancelled()
    ticks = iter([1.0, 1.0, 1.1, 1.1, 1.2, 1.2, 1.3, 1.3])
    monkeypatch.setattr(pv_exact_endgame, "exact_first_trick_means",
                        lambda *args, **kwargs: (_ for _ in ()).throw(failure))

    def stage(bot, rnd, seat, admitted, worlds, started, check_budget, priors, base):
        return pv_exact_endgame.exact_first_trick_means(rnd, seat, admitted, worlds)

    monkeypatch.setattr(pv_search_policy.PVSearchBot, "_exact_lead_decision", stage)
    sink = io.StringIO()
    bot = SimpleNamespace(serving_budget_seconds=None)
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]), hands=[["BJ"]] * 4)
    with cost_probe.exact_lead_cost_probe(sink, perf_clock=lambda: next(ticks),
                                          thread_clock=lambda: 0.0):
        with pytest.raises(Cancelled) as raised:
            pv_search_policy.PVSearchBot._exact_lead_decision(
                bot, rnd, 0, [["BJ"]], [(None, None)], 1.0, None, [], None)
    assert raised.value is failure
    row = json.loads(sink.getvalue())
    assert row["partial_worlds"] == "UNKNOWN"
    assert row["stage_error"] == row["evaluator_error"] == "Cancelled"


def test_cost_probe_real_stage_worker_captures_absorbed_soft_expiry(monkeypatch):
    ticks = iter([0.0, 0.0, 0.0, 3.0, 3.0, 3.0, 3.0, 3.0])
    monkeypatch.setattr(pv_search_policy.time, "perf_counter", lambda: next(ticks))

    def expire(*args, **kwargs):
        # The real stage's guard converts its soft deadline into the
        # OptionalStage transaction exception, which the stage absorbs.
        args[4]()

    monkeypatch.setattr(pv_exact_endgame, "exact_first_trick_means", expire)
    sink = io.StringIO()
    bot = SimpleNamespace(exact_lead_first_trick=True,
                          serving_budget_seconds=None, _exact_lead={})
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]), hands=[["BJ"]] * 4)
    base = (object(), 0, 0, ["BJ"], 0)

    with cost_probe.exact_lead_cost_probe(sink):
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                pv_search_policy.PVSearchBot._exact_lead_decision,
                bot, rnd, 0, [["BJ"]], [(None, None)], 0.0, None, [], base,
            ).result()

    assert result is base
    row = json.loads(sink.getvalue())
    assert row["status"] == "abandoned"
    assert row["abandon_reason"] == "soft_budget"
    assert row["evaluator_error"] == "_AdaptiveWorldsExpired"
    assert row["partial_worlds"] == "UNKNOWN"


def test_first_trick_accepts_different_action_and_preserves_partial_on_failure(monkeypatch):
    _install_synthetic(monkeypatch, [])
    paced = q.srv._paced_bot_step

    async def different(room, *args, **kwargs):
        prepared = await paced(room, *args, **kwargs)
        if room.bot.enabled:
            prepared.decision.cards = ['S5']
            prepared.decision.snapshot.bot_copy.last_decision_record['played'] = ['S5']
        return prepared

    monkeypatch.setattr(q.srv, '_paced_bot_step', different)
    dest = io.StringIO()
    assert asyncio.run(q.qualify('model.npz', dest, first_trick=True)) == 0
    assert json.loads(dest.getvalue().splitlines()[1])['cards'] == ['S5']

    async def fail_second(room, *args, **kwargs):
        if room.bot.enabled:
            raise RuntimeError('second call failed')
        return await paced(room, *args, **kwargs)

    monkeypatch.setattr(q.srv, '_paced_bot_step', fail_second)
    partial = io.StringIO()
    with pytest.raises(RuntimeError, match='second call failed'):
        asyncio.run(q.qualify('model.npz', partial, first_trick=True))
    assert len(partial.getvalue().splitlines()) == 1
    assert json.loads(partial.getvalue())['enabled'] is False


def test_release45_real_recipe_reaches_qualifier_consumer(monkeypatch, pinned_production_package):
    """Real recipe/registry/constructor; synthetic API decision avoids a host run."""
    real_env, real_entries = q.pv_env_recipe, q.pv_registry_entries
    _install_synthetic(monkeypatch, [])
    observed = []

    def entries(**kwargs):
        actual = real_entries(**kwargs)
        name, = actual
        built = actual[name](seed=941210121)
        assert built.bury_wide_value and built.bury_wide_k == 64
        assert built.worlds == 64 and built.candidates == 8
        enabled = kwargs.get('exact_lead_endgame', False)
        assert built.exact_lead_first_trick is enabled
        observed.append(name)
        return {name: lambda **kw: _Bot(enabled, enabled)}

    monkeypatch.setattr(q, 'pv_env_recipe', real_env)
    monkeypatch.setattr(q, 'pv_registry_entries', entries)
    dest = io.StringIO()
    assert asyncio.run(q.qualify(pinned_production_package, dest,
                                first_trick=True, release45=True)) == 0
    assert observed[0] == q.BASELINE45
    rows = [json.loads(line) for line in dest.getvalue().splitlines()]
    assert all(row['passed'] and row['committed'] and row['recipe_release'] == 45 for row in rows)
    assert all('not a release45 trajectory' in row['root_provenance'] for row in rows)


def test_release45_cli_forwards_both_flags(monkeypatch, tmp_path):
    calls = []

    async def qualify(checkpoint, dest, **kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(q, 'qualify', qualify)
    assert q.main(['--checkpoint', 'model.npz', '--out', str(tmp_path / 'out'),
                   '--first-trick', '--release45']) == 0
    assert calls == [dict(first_trick=True, release45=True)]


@pytest.mark.parametrize('release', ['44', '45'])
def test_release_alias_conflict_refuses_before_output(tmp_path, release):
    out = tmp_path / 'not-created.jsonl'
    with pytest.raises(SystemExit):
        q.main(['--checkpoint', 'unused.npz', '--out', str(out),
                '--release', release, '--release45'])
    assert not out.exists()


def test_first_trick_release45_arm_drift_refuses_before_root_access(monkeypatch):
    monkeypatch.setattr(q, 'pv_registry_entries', lambda **kwargs: {'wrong-arm': None})
    def forbidden(_packet):
        raise AssertionError('root must not be restored for a wrong arm')
    monkeypatch.setattr(q, 'restore_with_ledger', forbidden)
    dest = io.StringIO()
    with pytest.raises(ValueError, match='arm drift'):
        asyncio.run(q.qualify('unused.npz', dest, 45, first_trick=True))
    assert dest.getvalue() == ''
