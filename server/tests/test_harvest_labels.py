"""Production search labels for harvested positions (``train.harvest_labels``
/ ``scripts/label_harvest.py``) and the ``--eval-holdout`` wiring
(``cwv_eval.load_labeled_holdout`` / ``train_cwv``): witnesses, each with
the mutation that turns it RED.

1. Rebuild refusals: a bury decision, a dropped card in ``hidden_hands``
   (hidden-hands mismatch) and a deck mutation that changes the acting
   hand (legal-set mismatch against the record's ``legal_actions``) are
   REFUSED with the reason; the untouched record rebuilds (RED: skipping
   the hidden-hands / legal-set checks).
2. Capture: at the generator's own production ballot the label ballot IS
   production's list (``played_in_ballot`` true, means aligned, the seed
   is the record-hash stream, the block carries the identity); a played
   action outside production's ballot is APPENDED and flagged
   (``played_in_ballot`` false, ``played_index`` last) and still scored
   (RED: a ballot without ``must_include``).
3. Durability: a worker killed after two rows (fault injection) leaves a
   resumable directory; the rerun labels the rest, no ``record_sha256``
   twice, the manifest's counts equal the input and the merged file is in
   input order; a torn last line is dropped and relabelled (RED: resume
   that does not read the shards).
4. Loader + wiring: a synthetic labelled file from a DISJOINT trajectory
   run (labels built from its own action_values; one refused row; a
   second file without outcomes) loads with the right support flags, a
   non-labelled file and mixed labellers are refused, and ``evaluate`` /
   ``train`` report ``search_facing.holdouts.<name>`` through the one
   function: rank regret on both, CE / points only where the outcome
   exists (skipped with the reason otherwise); a holdout on a fit deal is
   refused (RED: an approximated outcome).
"""
from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")

from shengji.harvest import rebuild  # noqa: E402
from shengji.harvest.common import action_key, write_jsonl  # noqa: E402
from shengji.harvest.schema import finalize_record  # noqa: E402
from shengji.train import cwv_eval, harvest_labels, train_cwv, train_v0  # noqa: E402

from test_cwv_train import (  # noqa: E402, F401  (module fixtures)
    EXPLORE,
    SEED0,
    THIRDS,
    WORK,
    _records,
    other_dir,
    other_records,
    records,
    store_dir,
)
from test_cwv_search_facing import trained  # noqa: E402, F401

TEST_WORK = (2, 30)          # selection worlds, report worlds: the tests' search dose


def _searched(recs):
    return [r for r in recs if r.get("action_values") and r.get("exploration") is None
            and r["decision_kind"] == "play"]


# 1 ------------------------------------------------------------ refusals

def test_rebuild_refusals_name_the_reason(records):
    rec = next(r for r in _searched(records) if r["ply"] == 0)
    rnd, legal, diffs = harvest_labels.rebuild_for_label(rec)
    assert rnd.turn == rec["seat"] and legal.keys() >= {action_key(rec["action"])}
    assert diffs == []
    # a record whose prefix carries the engine's cards of a failed throw
    # replays without a diff; the SUBMITTED throw in its place is repaired by
    # the engine and reported (highn's 13 rows, harvest audit)
    thrown = next((r for r in records if r["decision_kind"] == "play" and any(
        p["cards"] != r["plays_prefix"][i]["cards"] for i, p in enumerate(r["plays_prefix"]))),
        None)
    failed = [r for r in records if "engine_play" in r]
    if failed:
        src = failed[0]
        later = next(r for r in records if r["source_ref"].rsplit(":", 1)[0] ==
                     src["source_ref"].rsplit(":", 1)[0] and r["ply"] > src["ply"]
                     and r["decision_kind"] == "play")
        prefix = json.loads(json.dumps(later["plays_prefix"]))
        assert sorted(prefix[src["ply"]]["cards"]) == sorted(src["engine_play"])
        prefix[src["ply"]]["cards"] = list(src["action"])       # the submitted throw
        _rnd, _legal, diffs = harvest_labels.rebuild_for_label({**later, "plays_prefix": prefix})
        assert diffs == [[src["ply"], list(src["action"]), src["engine_play"]]]
        row = harvest_labels.label_record({**later, "plays_prefix": prefix}, work=TEST_WORK)
        assert row["search_labels"]["failed_throw_prefix"] is True
    del thrown

    # bury decisions have no play search
    bury = {**rec, "decision_kind": "bury", "ply": None, "trick": None, "plays_prefix": []}
    with pytest.raises(harvest_labels.LabelRefused, match="bury_decision"):
        harvest_labels.rebuild_for_label(bury)

    # hidden hands: a dropped card in the acting hand is a mismatch
    snapshot = rebuild.hands_snapshot(rnd)
    with_hands = {**rec, "hidden_hands": snapshot}
    harvest_labels.rebuild_for_label(with_hands)          # consistent hands pass
    mutated = json.loads(json.dumps(snapshot))
    mutated["hands_by_seat"][rec["seat"]].pop(0)
    with pytest.raises(harvest_labels.LabelRefused, match="hidden_hands_mismatch"):
        harvest_labels.rebuild_for_label({**rec, "hidden_hands": mutated})

    # the deck: swap one card of the acting (banker, opening lead) hand with a
    # card of the next seat -> a different hand -> the record's legal set no
    # longer matches the enumerator's
    banker = rec["setup"]["banker"]
    assert rec["seat"] == banker
    reserved = set(rec["setup"]["buried"])
    for d in rec["setup"]["declarations"]:
        reserved |= set(d["cards"])
    deck = list(rec["deck"])
    mine = next(i for i in range(100) if i % 4 == banker and deck[i] not in reserved)
    other_seat = (banker + 1) % 4
    theirs = next(i for i in range(100) if i % 4 == other_seat and deck[i] != deck[mine]
                  and deck[i] not in reserved)
    deck[mine], deck[theirs] = deck[theirs], deck[mine]
    swapped = {**rec, "deck": deck}
    with pytest.raises(harvest_labels.LabelRefused, match="legal_set_mismatch"):
        harvest_labels.rebuild_for_label(swapped)
    # label_record turns the refusal into a row with the reason, no labels
    refusal = harvest_labels.label_record(swapped, work=TEST_WORK)
    assert refusal["search_labels"] is None
    assert refusal["label_refusal"]["reason"] == "legal_set_mismatch"


# 2 -------------------------------------------------------------- capture

def test_capture_matches_production_ballot_and_flags_off_ballot_play(records):
    rec = next(r for r in _searched(records) if len(r["ballot"]) >= 3
               and len(r["legal_actions"]) > len(r["ballot"]))
    row = harvest_labels.label_record(rec, work=TEST_WORK, code_sha="test")
    labels = row["search_labels"]
    assert row["label_refusal"] is None
    assert labels["schema"] == harvest_labels.LABELS_SCHEMA
    assert labels["policy"] == "mc-s0-report-lcb" and labels["policy_class"] == "MCS0ReportLCB"
    assert (labels["n_worlds"], labels["report_worlds"]) == TEST_WORK
    assert labels["work_override"] == list(TEST_WORK) and labels["scale"] == 1
    assert labels["seed"] == harvest_labels.label_seed(rec["record_sha256"], 1)
    assert labels["seed"] != harvest_labels.label_seed(rec["record_sha256"], 3)
    # production's own ballot at this state (same registry class, same knobs)
    assert labels["ballot"] == rec["ballot"] == labels["production_ballot"]
    assert labels["played_in_ballot"] is True
    assert labels["played_index"] == rec["allocation"]["played_index"]
    assert labels["searched"] is True and len(labels["means"]) == len(rec["ballot"])
    assert len(labels["se"]) == len(rec["ballot"]) and labels["se"][0] == 0.0
    assert labels["chosen"] == labels["ballot"][labels["chosen_index"]]
    assert labels["action_values"]["perspective"] == "acting-team"
    assert labels["action_values"]["means"] == labels["means"]
    assert labels["allocation"]["kind"] == "search-work"
    assert labels["allocation"]["selection_worlds"] == [TEST_WORK[0]] * len(rec["ballot"])
    assert labels["report_fold"]["worlds"] == TEST_WORK[1]
    assert labels["reason"].startswith("report_")
    assert labels["wall_ms"] > 0 and labels["code_sha"] == "test"
    assert labels["forced"] is False and labels["legal_count"] == rec["legal_actions_count"]
    assert labels["ballot_source"] == harvest_labels.BALLOT_SOURCE
    assert labels["record_ballot_matches"] is True and labels["failed_throw_prefix"] is False
    assert row["deal_key"].startswith("deck:") and len(row["state_key"]) == 32
    # every row keeps the input record untouched
    assert {k: v for k, v in row.items()
            if k not in ("search_labels", "label_refusal", "deal_key", "state_key")} == rec
    # a forced decision (one legal action) is flagged and never searched
    forced = next((r for r in records if r["decision_kind"] == "play"
                   and r["legal_actions_complete"] and r["legal_actions_count"] == 1), None)
    if forced is not None:
        fl = harvest_labels.label_record(forced, work=TEST_WORK)["search_labels"]
        assert fl["forced"] is True and fl["searched"] is False and fl["means"] is None
    # a record with a foreign ballot: production's list is generated anyway
    foreign = finalize_record({**rec, "ballot": [rec["ballot"][0]], "action_values": None,
                               "allocation": None, "preference": None})
    fl = harvest_labels.label_record(foreign, work=TEST_WORK)["search_labels"]
    assert fl["ballot"] == rec["ballot"] and fl["record_ballot_matches"] is False
    # the same seed reproduces the same labels (deterministic capture)
    again = harvest_labels.label_record(rec, work=TEST_WORK, code_sha="test")["search_labels"]
    assert again["means"] == labels["means"] and again["chosen_index"] == labels["chosen_index"]

    # a legal action production does not list: appended and flagged
    keys = {action_key(c) for c in rec["ballot"]}
    off = next(a for a in rec["legal_actions"] if action_key(a) not in keys)
    played_off = finalize_record({**rec, "action": list(off)})
    row = harvest_labels.label_record(played_off, work=TEST_WORK)
    labels = row["search_labels"]
    assert labels["played_in_ballot"] is False
    assert labels["ballot"] == rec["ballot"] + [list(off)]
    assert labels["production_ballot"] == rec["ballot"]
    assert labels["played_index"] == len(rec["ballot"])
    assert len(labels["means"]) == len(rec["ballot"]) + 1
    assert labels["eligible_indices"] == list(range(len(rec["ballot"]) + 1))
    assert labels["allocation"]["selection_worlds"][-1] == TEST_WORK[0]


# 3 ----------------------------------------------------------- durability

def _harvest_input(tmp_path, recs, name="human"):
    """A harvest-shaped input file (``source`` re-labelled so the labeller's
    source map resolves it; the records stay schema-valid)."""
    rows = [finalize_record({**r, "source": name}) for r in recs]
    in_dir = tmp_path / "harvest"
    in_dir.mkdir()
    write_jsonl(in_dir / harvest_labels.SOURCE_FILES[name], rows)
    return in_dir, rows


def test_resume_after_a_killed_worker_has_no_duplicates(records, tmp_path, monkeypatch):
    picks = _searched(records)[:5]
    # an exact twin of the third record (same state, another policy label:
    # the human_v8 / room-log, mirror and PT1-seed situations of the audit)
    twin = {**picks[2], "policy": "human:twin", "source_ref": picks[2]["source_ref"] + "#twin"}
    picks = picks[:4] + [twin] + picks[4:]
    in_dir, rows = _harvest_input(tmp_path, picks)
    inputs = {"human": in_dir / "human.jsonl"}
    out = tmp_path / "labels"
    monkeypatch.setattr(harvest_labels, "make_label_bot",
                        lambda **kw: _make_test_bot(**kw))
    monkeypatch.setenv(harvest_labels.FAIL_AFTER_ENV, "2")
    with pytest.raises(harvest_labels.LabelError, match="injected failure after 2"):
        harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    partial = json.loads((out / "manifest.json").read_text())
    assert partial["sources"]["human"]["counts"]["rows"] == 2
    assert partial["sources"]["human"]["complete"] is False
    assert partial["timings"]["failures"]
    # a torn last line (the process died mid-write) is dropped and relabelled
    shard = out / "shards" / "human.w0.jsonl"
    with open(shard, "ab") as fh:
        fh.write(b'{"record_sha256":"deadbeef","search_labels":nul')
    monkeypatch.delenv(harvest_labels.FAIL_AFTER_ENV)
    manifest = harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    counts = manifest["sources"]["human"]["counts"]
    assert counts["rows"] == counts["input_rows"] == 6 and counts["labelled"] == 5
    assert counts["refused"] == {"duplicate_state": 1} and counts["duplicate_state"] == 1
    assert manifest["sources"]["human"]["duplicates"] == [
        {"record_sha256": rows[4]["record_sha256"], "duplicate_of": rows[2]["record_sha256"],
         "state_key": harvest_labels.state_key(rows[2])}]
    assert manifest["sources"]["human"]["complete"] is True
    assert manifest["scan"]["torn"] == ["human.w0.jsonl"]
    assert manifest["timings"]["records_this_run"] == 4
    shas = [json.loads(line)["record_sha256"] for line in shard.read_text().splitlines()]
    assert len(shas) == 6 and len(set(shas)) == 6
    merged = out / "human.labels.jsonl"
    got = [json.loads(line) for line in merged.read_text().splitlines()]
    assert [g["record_sha256"] for g in got] == [r["record_sha256"] for r in rows]
    assert manifest["outputs"]["human.labels.jsonl"]["records"] == 6
    dup_row = got[4]
    assert dup_row["search_labels"] is None
    assert dup_row["label_refusal"]["duplicate_of"] == rows[2]["record_sha256"]
    assert dup_row["state_key"] == got[2]["state_key"] and dup_row["deal_key"] == got[2]["deal_key"]
    assert manifest["outputs"]["human.labels.jsonl"]["sha256"] == \
        __import__("hashlib").sha256(merged.read_bytes()).hexdigest()
    assert all(g["search_labels"]["n_worlds"] == TEST_WORK[0] for g in got if g["search_labels"])
    # a third run has nothing to do and leaves the counts alone
    again = harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    assert again["sources"]["human"]["counts"]["rows"] == 6
    assert again["timings"]["records_this_run"] == 0
    # a different scale cannot resume this directory
    with pytest.raises(harvest_labels.LabelError, match="cannot resume"):
        harvest_labels.run(inputs=inputs, out_dir=out, workers=1, scale=3, log=None)


def _make_test_bot(*, seed, scale=1, policy=harvest_labels.POLICY, work=None):
    """The production bot at the tests' reduced dose (the run() path has no
    work override by design; the identity is stamped in every row)."""
    bot = harvest_labels.make_bot(policy, seed=seed)
    bot.__class__ = harvest_labels.label_class(type(bot))
    bot.N_DETERMINIZATIONS, bot.REPORT_FOLD_WORLDS = TEST_WORK
    return bot


# 4 ------------------------------------------------------ loader + wiring

def _labelled_rows(recs, *, drop_outcome=False, refuse_one=False):
    """Labelled rows synthesised from the trajectory records' own
    ``action_values`` (the SAME quantity the labeller captures from the
    decision record), so the loader is exercised without a search."""
    rows = []
    for i, r in enumerate(recs):
        base = dict(r)
        if drop_outcome:
            base = finalize_record({**base, "outcome": None})
        values = r["action_values"]
        played = r["allocation"]["played_index"]
        labels = {
            "schema": harvest_labels.LABELS_SCHEMA, "policy": "mc-s0-report-lcb",
            "policy_class": "MCS0ReportLCB", "scale": 1, "n_worlds": WORK["select_worlds"],
            "report_worlds": WORK["report_worlds"], "report_rule": "lcb",
            "work_override": None, "seed": harvest_labels.label_seed(r["record_sha256"]),
            "seed_recipe": harvest_labels.SEED_RECIPE, "chosen": r["action"],
            "code_sha": "synthetic", "wall_ms": 1.0, "ballot": r["ballot"],
            "production_ballot": r.get("production_ballot") or r["ballot"],
            "means": values["means"], "se": values["paired_se"],
            "eligible_indices": values["eligible_indices"], "chosen_index": played,
            "played_index": played, "played_in_ballot": True,
            "reason": r["allocation"]["reason"], "searched": True,
            "worlds_sampled": r["allocation"]["selection_worlds"][0],
            "report_fold": values["report"], "allocation": r["allocation"],
            "action_values": values, "work": r["allocation"]["work"],
            "forced": False, "legal_count": r["legal_actions_count"],
            "ballot_source": harvest_labels.BALLOT_SOURCE, "record_ballot_matches": True,
            "failed_throw_prefix": False, "prefix_engine_diffs": [],
        }
        base["deal_key"] = harvest_labels.record_deal_key(base)
        base["state_key"] = harvest_labels.state_key(base)
        if refuse_one and i == 0:
            rows.append({**base, "search_labels": None,
                         "label_refusal": {"reason": "legal_set_mismatch", "detail": "test"}})
        else:
            rows.append({**base, "search_labels": labels, "label_refusal": None})
    return rows


@pytest.fixture(scope="module")
def holdout_files(other_records, tmp_path_factory):
    picks = _searched(other_records)[:24]
    assert len(picks) >= 12
    root = tmp_path_factory.mktemp("cwv-holdouts")
    with_outcome = root / "outcome.labels.jsonl"
    write_jsonl(with_outcome, _labelled_rows(picks, refuse_one=True))
    no_outcome = root / "nooutcome.labels.jsonl"
    write_jsonl(no_outcome, _labelled_rows(picks, drop_outcome=True))
    return with_outcome, no_outcome, picks


def test_loader_support_flags_and_refusals(holdout_files, tmp_path, records):
    with_outcome, no_outcome, picks = holdout_files
    hold = cwv_eval.load_labeled_holdout(with_outcome)
    c = hold.counts
    assert c["rows"] == len(picks) and c["labelled"] == len(picks) - 1
    assert c["refused"] == {"legal_set_mismatch": 1} and c["searched"] == len(picks) - 1
    assert c["rank_eligible"] == len(picks) - 1 and c["with_outcome"] == len(picks)
    assert c["forced"] == 0 and c["duplicate_state"] == 0 and c["deals"] >= 1
    assert hold.supports == {"rank_regret": True, "calibration": True, "points": True}
    assert hold.identity["policy"] == "mc-s0-report-lcb" and hold.identity["scale"] == 1
    assert hold.sources == {"trajectory": len(picks)}
    means = cwv_eval.holdout_search_means(hold.rows[1])
    assert means is not None and len(means[0]) >= 2
    assert cwv_eval.holdout_search_means(hold.rows[0]) is None
    # the record inside a row is the untouched harvest record
    rec = cwv_eval.holdout_record(hold.rows[1])
    assert rec == picks[1]
    hold2 = cwv_eval.load_labeled_holdout(no_outcome)
    assert hold2.supports == {"rank_regret": True, "calibration": False, "points": False}
    assert hold2.counts["with_outcome"] == 0
    # the candidate set: one entry per rank-eligible row, means on the search scale
    cands = cwv_eval.holdout_candidate_set(hold2, history=False, label="t")
    assert cands.records == len(picks) and cands.meta["counts"]["encoded"] == len(picks)
    assert cands.meta["holdout_sha256"] == hold2.sha256
    # a plain harvest / trajectory file is not a labelled file
    plain = tmp_path / "plain.jsonl"
    write_jsonl(plain, records[:3])
    with pytest.raises(cwv_eval.EvalError, match="not a labelled harvest row"):
        cwv_eval.load_labeled_holdout(plain)
    # mixed labellers are refused
    rows = _labelled_rows(picks[:2])
    rows[1]["search_labels"]["scale"] = 3
    mixed = tmp_path / "mixed.jsonl"
    write_jsonl(mixed, rows)
    with pytest.raises(cwv_eval.EvalError, match="mixed labeller identities"):
        cwv_eval.load_labeled_holdout(mixed)
    # duplicates collapse to the first occurrence
    dup = tmp_path / "dup.jsonl"
    write_jsonl(dup, _labelled_rows(picks[:2]) * 2)
    d = cwv_eval.load_labeled_holdout(dup).counts
    assert (d["rows"], d["duplicates"]) == (2, 2)
    with pytest.raises(train_v0.TrainError, match="NAME=PATH"):
        train_cwv.parse_holdouts(["nopath"])
    with pytest.raises(train_v0.TrainError, match="duplicate holdout name"):
        train_cwv.parse_holdouts([f"a={with_outcome}", f"a={no_outcome}"])


def test_evaluate_and_train_report_holdouts_through_one_function(trained, holdout_files,
                                                                 store_dir, tmp_path):
    out, kw, receipt = trained
    with_outcome, no_outcome, picks = holdout_files
    ev = train_cwv.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "e",
                            data=kw["data"], device="cpu", n_boot=10,
                            cache_dir=str(out / "cache"), cache_workers=1, eval_workers=1,
                            bench_batch=8, log=None,
                            eval_holdout=[f"outcome={with_outcome}",
                                          f"no_outcome={no_outcome}"])
    holds = ev["final"]["test"]["search_facing"]["holdouts"]
    assert set(holds) == {"outcome", "no_outcome"} and ev["holdouts"] == holds
    a, b = holds["outcome"], holds["no_outcome"]
    # rank regret on both (the labels), the same definitions as the split blocks
    for block in (a, b):
        assert block["rank_records"] == len(picks) - (1 if block is a else 0)
        assert block["rank_regret"] is not None and block["rank_regret"] >= 0
        assert 0 <= block["rank_top1"] <= 1
        assert block["rank_scale"] == cwv_eval.RANK_SCALE
        assert block["rank_regret_definition"] == cwv_eval.RANK_REGRET_DEFINITION
        assert block["held_out"] is True and block["holdout"]["counts"]["rows"] == len(picks)
    # CE / value MAE / reliability / points only where the outcome exists
    assert a["n"] == len(picks) and a["cross_entropy"] is not None
    assert a["value_mae"] is not None and a["reliability"]["pt0"]
    assert a["points_n"] == len(picks) and a["points_mae"] is not None
    assert a["skipped"] == {}
    assert a["rows"]["population"]["shared_with_fit"] == 0
    assert b["n"] == 0 and b["cross_entropy"] is None and b["value_mae"] is None
    assert b["points_mae"] is None and b["points_n"] == 0
    assert set(b["skipped"]) == {"calibration", "cross_entropy", "value_mae", "points"}
    assert "outcome" in b["skipped"]["points"]
    # the rows' metrics come from the one function: recompute on the ev arrays
    ranked = cwv_eval.rank_metrics(
        train_cwv.rank_levels(train_cwv.load_cwv_checkpoint(out / "best.pt", "cpu")[0],
                              cwv_eval.holdout_candidate_set(
                                  cwv_eval.load_labeled_holdout(no_outcome), history=False),
                              torch.device("cpu"), batch_size=64),
        cwv_eval.holdout_candidate_set(cwv_eval.load_labeled_holdout(no_outcome),
                                       history=False))
    assert ranked["rank_regret"] == pytest.approx(b["rank_regret"], abs=1e-9)
    # evaluate on holdouts alone (no --data) still works and reports them
    only = train_cwv.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "h",
                              device="cpu", n_boot=10, cache_dir=str(out / "cache"),
                              cache_workers=1, eval_workers=1, bench_batch=8, log=None,
                              eval_holdout=[f"no_outcome={no_outcome}"])
    assert only["holdouts"]["no_outcome"]["rank_regret"] == pytest.approx(b["rank_regret"])
    # a holdout on a fit deal is refused: not held out
    fit = tmp_path / "fit.jsonl"
    by_deal: dict = {}
    for r in _searched(_records(store_dir)):
        by_deal.setdefault(tuple(r["deck"]), []).append(r)
    write_jsonl(fit, _labelled_rows([r for rs in by_deal.values() for r in rs[:2]]))
    with pytest.raises(train_v0.TrainError, match="not held out"):
        train_cwv.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "f",
                           device="cpu", n_boot=10, cache_dir=str(out / "cache"),
                           cache_workers=1, eval_workers=1, bench_batch=8, log=None,
                           eval_holdout=[f"fit={fit}"])
    # train carries the block in its final test pass and in the receipt
    rc = train_cwv.train(out=tmp_path / "t", **{**kw, "epochs": 1},
                         eval_holdout=[f"outcome={with_outcome}"])
    got = rc["final"]["test"]["search_facing"]["holdouts"]["outcome"]
    assert got["rank_regret"] is not None and got["cross_entropy"] is not None
    assert rc["holdouts"]["outcome"]["rank_records"] == got["rank_records"]
    assert rc["config"]["eval_holdouts"] == {"outcome": str(with_outcome.resolve())}
    metrics = json.loads((tmp_path / "t" / "metrics.json").read_text())
    assert metrics["holdouts"]["outcome"]["rank_regret"] == pytest.approx(got["rank_regret"])
