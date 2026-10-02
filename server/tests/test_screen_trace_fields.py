"""#679 B6: the served-screen trace keeps list-valued decision fields as bounded
summaries (``<field>__len``, short numeric lists whole) and counts what it could
not keep; the scalar receipt it wrote before is unchanged key for key."""
import copy
import json

import pytest

from shengji.train import search_screen as S
from shengji.train.screen_deadline import latency_summary
from test_pv_search_serving import package  # noqa: F401

SCALARS = (str, int, float, bool, type(None))


def _old_play_trace(seat, trick, rec):
    """The pre-B6 reduction, verbatim: what every existing reader was written against."""
    return {"seat": seat, "trick": trick, "played": rec.get("played"),
            **{k: v for k, v in rec.items() if k != "played" and isinstance(v, SCALARS)}}


def _record():
    return {
        "schema": "pv-search-decision-v1", "policy": "pv", "worlds": 64, "actions": 40,
        "legal_complete": True, "selected_index": 3, "seconds": 0.41, "error_class": None,
        "admitted_indices": [0, 3, 7, 9, 12, 15, 21, 30],
        "value_means": [0.12, 0.31, -0.05, 0.30, 0.0, 0.11, 0.2, -0.4],
        "diversity_skipped": [2, 4],
        "tiebreak_near_set": [1, 3],
        "tiebreak_points": [12.5, 10.0],
        "tiebreak_applied": False,
        "forced_single_added": [30],
        "forced_single_detail": [{"index": 30, "component": "pair"}],
        "refusal_codes": ["S", "H"],
        "admitted": [["S2"], ["H3", "H3"]] * 4,
        "policy_log_odds_listing": [0.5] * 40,
        "played": ["H3", "H3"],
        "sampling_detail": {"attempts": 3},
    }


class _Bot:
    def __init__(self, rec):
        self.last_decision_record = rec

    def decide_play(self, rnd, seat):
        return list(self.last_decision_record["played"])


class _Rnd:
    history = [object(), object()]


def _trace(rec):
    policy = S.TimedPolicy(_Bot(rec))
    policy.decide_play(_Rnd(), 1)
    (out,) = policy.decisions
    return out


def test_each_list_type_is_summarized_with_correct_lengths_and_values():
    rec = _record()
    out = _trace(rec)
    for field in ("admitted_indices", "value_means", "diversity_skipped", "tiebreak_near_set",
                  "tiebreak_points", "forced_single_added"):
        assert out[f"{field}__len"] == len(rec[field])
        assert out[field] == rec[field]                       # short numeric: kept whole
    for field in ("forced_single_detail", "refusal_codes", "admitted", "policy_log_odds_listing"):
        assert out[f"{field}__len"] == len(rec[field])
        assert field not in out                               # non-numeric or long: length only
    assert "sampling_detail" not in out and "sampling_detail__len" not in out
    # 4 list fields kept as length only + 1 dict; ``played`` is the explicit contract key
    assert out["trace_dropped_fields"] == 5
    assert out["played"] == rec["played"] and "played__len" not in out


def test_scalar_keys_are_byte_identical_and_first_in_order():
    rec = _record()
    old, new = _old_play_trace(1, 2, rec), _trace(rec)
    assert list(new)[:len(old)] == list(old)                   # same keys, same order, first
    assert json.dumps({k: new[k] for k in old}) == json.dumps(old)
    added = set(new) - set(old)
    assert added and all(k.endswith("__len") or k == "trace_dropped_fields" or
                         (k in rec and not isinstance(rec[k], SCALARS)) for k in added)


def test_a_hundred_entry_list_keeps_only_its_length():
    out = _trace({"schema": "pv-search-decision-v1", "played": ["S2"],
                  "value_means": [0.1] * 100, "diversity_skipped": list(range(100))})
    assert out["value_means__len"] == 100 and out["diversity_skipped__len"] == 100
    assert "value_means" not in out and "diversity_skipped" not in out
    assert out["trace_dropped_fields"] == 2


def test_boundary_and_no_lists():
    out = _trace({"played": ["S2"], "a": list(range(16)), "b": list(range(17)), "c": []})
    assert out["a"] == list(range(16)) and "b" not in out and out["b__len"] == 17
    assert out["c"] == [] and out["c__len"] == 0 and out["trace_dropped_fields"] == 1
    plain = _trace({"played": ["S2"], "schema": "pv-search-fallback-v1", "reason": "budget"})
    assert plain["trace_dropped_fields"] == 0        # present and zero: nothing lost, not missing


def test_summary_never_overwrites_a_recorded_key():
    out = S.trace_fields({"x": [1, 2], "x__len": 99, "trace_dropped_fields": "kept"})
    assert out["x__len"] == 99 and out["x"] == [1, 2] and out["trace_dropped_fields"] == "kept"


def test_bury_receipts_gain_the_same_summaries_without_changing_scalars():
    class Bury:
        last_bury_record = {"schema": "cwv-bury-policy-v1", "fallback": False,
                            "buried": ["S2", "S3"], "scores": [0.1, 0.2]}

        def decide_bury(self, rnd, seat):
            return ["S2", "S3"]

    policy = S.TimedPolicy(Bury())
    policy.decide_bury(None, 0)
    (out,) = policy.bury_decisions
    assert list(out)[:4] == ["seat", "phase", "schema", "fallback"]
    assert out["scores"] == [0.1, 0.2] and out["buried__len"] == 2 and "buried" not in out
    assert out["trace_dropped_fields"] == 1


def test_an_old_format_reader_still_parses_a_new_shard():
    """A shard written with the new traces goes through JSON and the readers that
    exist (the deadline latency summary; a scalar-key paired reader) unchanged."""
    rec = _record()
    traces = []
    for side in ("arm", "baseline"):
        d = _trace(copy.deepcopy(rec))
        d["deadline"] = {"elapsed_seconds": 0.5, "timed_out": False}
        traces.append({"mirror": 0, "side": side, "decisions": [d]})
    shard = json.loads(json.dumps({"cluster": 0, "decision_traces": traces}))

    def old_reader(shard):        # the scalar-only access pattern of the paired readers
        rows = []
        for trace in shard["decision_traces"]:
            for d in trace["decisions"]:
                rows.append({k: d[k] for k in ("schema", "selected_index", "seconds",
                                               "tiebreak_applied", "played")})
        return rows

    old_shard = {"cluster": 0, "decision_traces": [
        {**t, "decisions": [{**_old_play_trace(1, 2, rec), "deadline": t["decisions"][0]["deadline"]}]}
        for t in shard["decision_traces"]]}
    assert old_reader(shard) == old_reader(old_shard)
    assert latency_summary([shard]) == latency_summary([old_shard])
    # and the field the combo reader reported as "missing, not zero" is now observable
    d = shard["decision_traces"][0]["decisions"][0]
    assert d["diversity_skipped"] == [2, 4] and d["tiebreak_near_set__len"] == 2


def test_a_real_pv_search_record_round_trips(package):
    """End to end on the served bot with diversity + tie-break + forced-single on."""
    from test_pv_search_hooks import _state
    from shengji.train import pv_search_policy as pv
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=3, worlds=3, candidates=4, cap=400,
                                batch_size=16, admission_diversity=True,
                                admit_forced_single=True, tiebreak_points=True)
    rnd = _state()
    policy = S.TimedPolicy(bot)
    policy.decide_play(copy.deepcopy(rnd), rnd.turn)
    rec, (out,) = bot.last_decision_record, policy.decisions
    assert rec["schema"] == "pv-search-decision-v1"
    assert {k: out[k] for k in _old_play_trace(0, 0, rec) if k not in ("seat", "trick")} == \
        {k: v for k, v in _old_play_trace(0, 0, rec).items() if k not in ("seat", "trick")}
    for field in ("diversity_skipped", "tiebreak_near_set", "admitted_indices", "value_means"):
        assert out[f"{field}__len"] == len(rec[field])
        assert out[field] == rec[field]
    assert json.loads(json.dumps(out)) == out
