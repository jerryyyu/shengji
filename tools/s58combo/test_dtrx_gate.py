import copy
import pytest

from dtrx_gate import DTR_FIELDS, DTRX_FIELDS, check_dtrx, validate_record


def dtr(schema="pv-search-decision-v1", **extra):
    value = dict(schema=schema,
                 doomed_throw_reselect_applied=False,
                 doomed_throw_reselect_from="SJ",
                 doomed_throw_reselect_to="SJ",
                 doomed_throw_reselect_doomed_candidates=0,
                 doomed_throw_reselect_forced_excluded=0,
                 doomed_throw_reselect_fallback_forced=False)
    value.update(extra)
    return value


def plan_shards(candidate=None, comparator=None):
    candidate = candidate or [dtr(**dict(doomed_throw_reselect_exact_guarded=True,
                                          doomed_throw_reselect_exact_floor_excluded=0))]
    comparator = comparator or [dtr()]
    plan = dict(
        arms={side: dict(identity=dict(config=dict(
            doomed_throw_reselect=True,
            doomed_throw_reselect_exact_guard=side == "candidate")))
              for side in ("candidate", "comparator")},
        windows=[dict(side=side, output=side) for side in ("candidate", "comparator")],
    )
    shards = {side: [dict(decision_traces=[dict(side="arm", decisions=records)])]
              for side, records in (("candidate", candidate), ("comparator", comparator))}
    return plan, shards


@pytest.mark.parametrize("field,value", [
    (DTR_FIELDS[0], 1), (DTR_FIELDS[3], -1), (DTR_FIELDS[4], True),
    (DTR_FIELDS[5], 0), (DTRX_FIELDS[0], 1), (DTRX_FIELDS[1], -1),
])
def test_malformed_receipts_fail_closed(field, value):
    rec = dtr(doomed_throw_reselect_exact_guarded=True,
              doomed_throw_reselect_exact_floor_excluded=0)
    rec[field] = value
    with pytest.raises(ValueError):
        validate_record(rec, exact_guard=True)


@pytest.mark.parametrize("field", DTR_FIELDS + DTRX_FIELDS)
def test_missing_receipt_field_fails_closed(field):
    rec = dtr(doomed_throw_reselect_exact_guarded=True,
              doomed_throw_reselect_exact_floor_excluded=0)
    del rec[field]
    with pytest.raises(ValueError):
        validate_record(rec, exact_guard=True)


def test_comparator_and_fallback_cannot_carry_dtrx():
    for schema in ("pv-search-decision-v1", "pv-search-fallback-v1"):
        rec = dtr(schema, doomed_throw_reselect_exact_guarded=True,
                  doomed_throw_reselect_exact_floor_excluded=0)
        with pytest.raises(ValueError):
            validate_record(rec, exact_guard=False)


def test_ordinary_and_abandoned_dtr_are_valid():
    assert validate_record(dtr(), exact_guard=False) == "search"
    assert validate_record({"schema": "pv-search-fallback-v1"}, exact_guard=False) == "fallback"
    with pytest.raises(ValueError):
        validate_record(dtr("pv-search-fallback-v1",
                            doomed_throw_reselect_abandoned="budget"), exact_guard=False)
    with pytest.raises(ValueError):
        validate_record(dtr("pv-search-fallback-v1",
                            doomed_throw_reselect_abandoned=None), exact_guard=False)


def test_population_and_activation_gate():
    plan, shards = plan_shards()
    result = check_dtrx(plan, shards)
    assert result["verdict"] == "VALID"
    assert result["counts"]["candidate"]["guarded"] == 1
    bad = copy.deepcopy(shards)
    bad["comparator"][0]["decision_traces"][0]["decisions"][0][DTRX_FIELDS[0]] = False
    assert check_dtrx(plan, bad)["verdict"] == "SCREEN_INVALID"


def test_fallback_receipts_are_allowed_without_common_dtr_fields():
    plan, shards = plan_shards(
        candidate=[dtr(doomed_throw_reselect_exact_guarded=True,
                        doomed_throw_reselect_exact_floor_excluded=0),
                   {"schema": "pv-search-fallback-v1"}],
        comparator=[dtr(), {"schema": "pv-search-fallback-v1"}],
    )
    assert check_dtrx(plan, shards)["verdict"] == "VALID"


def test_candidate_requires_floor_application():
    plan, shards = plan_shards(candidate=[dtr(doomed_throw_reselect_exact_guarded=False,
                                               doomed_throw_reselect_exact_floor_excluded=0)])
    result = check_dtrx(plan, shards)
    assert result["verdict"] == "SCREEN_INVALID"
    assert any("never applied" in reason for reason in result["reasons"])


def test_unguarded_floor_exclusions_fail_closed():
    rec = dtr(doomed_throw_reselect_exact_guarded=False,
              doomed_throw_reselect_exact_floor_excluded=2)
    with pytest.raises(ValueError):
        validate_record(rec, exact_guard=True)


def test_common_dtr_config_is_required():
    plan, shards = plan_shards()
    del plan["arms"]["comparator"]["identity"]["config"]["doomed_throw_reselect"]
    result = check_dtrx(plan, shards)
    assert result["verdict"] == "SCREEN_INVALID"


def test_invalid_guard_blocks_estimation(monkeypatch):
    import outcome_gate as consumer
    plan, shards = plan_shards()
    shards['candidate'][0]['decision_traces'][0]['decisions'][0][DTRX_FIELDS[1]] = -1
    monkeypatch.setattr(consumer, 'admit_records', lambda *a: {})
    for name in ('check_outcomes', 'check_decisions', 'check_exact', 'check_optional_stages', 'check_greedy'):
        monkeypatch.setattr(consumer, name, lambda *a: dict(verdict='VALID'))
    monkeypatch.setattr(consumer, 'paired_result', lambda *a: pytest.fail('invalid dtrx reached estimation'))
    assert consumer.outcome_checked_result(plan, {}, {}, shards)['status'] == 'DTRX_INVALID'
