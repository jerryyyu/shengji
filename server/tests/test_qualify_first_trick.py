"""Synthetic contract tests for the exact-lead qualifier's first-trick mode."""

import asyncio
import copy
import io
import json
import pytest
from types import SimpleNamespace

from scripts import qualify_exact_lead as q
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

    async def fake_qualify(checkpoint, dest, *, first_trick=False):
        called.append((checkpoint, dest, first_trick))
        return 0

    monkeypatch.setattr(q, "qualify", fake_qualify)
    assert q.main(["--checkpoint", "model.npz", "--out", str(tmp_path / "out"),
                   "--first-trick"]) == 0
    assert called[0][2] is True


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
