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
5. Codex HOLD (PR #243): the state key is bound to the rebuilt state and the
   work key to the played action -- two legal burials at one deck / prefix
   / seat are both labelled, two played actions at one state are both
   scored, identical twins still dedup (RED: a key over deck + prefix +
   seat only); rows under an older ``key_version`` are removed and
   relabelled while current rows resume; a rank-only holdout on a fit deal
   is refused before any metric (RED: the check inside the calibration
   branch only); an outcome mutation that keeps the stale ``record_sha256``
   is refused at ingestion (``invalid_record``) and at consumption
   (``EvalError``) (RED: no ``validate_record`` at either point).
6. Codex HOLD round 2: an invalid first copy (stale hash) never owns a work
   key, so its valid twin is labelled, at ingestion and when ownership is
   rebuilt from a resumed shard (RED: claim before validate -> the twin is
   ``duplicate_state``); a missing input or an incompatible resume refuses
   BEFORE any shard byte changes, and a legacy-version shard is moved to
   ``shards/legacy-v1/`` byte-identical with a manifest while its rows are
   carried forward (search labels retained) except a mis-deduped duplicate,
   which is relabelled (RED: truncating legacy rows before admission).
7. Codex HOLD round 3: an ``invalid_record`` row never marks its stale hash
   done -- the valid original with that hash is labelled on resume and the
   stale row is superseded in the manifest and the merged file; two input
   rows sharing one hash keep the valid one whatever its position (RED: a
   done set that includes invalid_record rows).
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
        thrown_rec = finalize_record({**later, "plays_prefix": prefix})
        _rnd, _legal, diffs = harvest_labels.rebuild_for_label(thrown_rec)
        assert diffs == [[src["ply"], list(src["action"]), src["engine_play"]]]
        row = harvest_labels.label_record(thrown_rec, work=TEST_WORK)
        assert row["search_labels"]["failed_throw_prefix"] is True
    del thrown

    # bury decisions have no play search
    bury = finalize_record({**rec, "decision_kind": "bury", "ply": None, "trick": None,
                            "plays_prefix": [], "action": list(rec["setup"]["buried"]),
                            "legal_actions": None, "legal_actions_complete": False,
                            "legal_actions_count": None, "ballot": None, "allocation": None,
                            "action_values": None, "preference": None, "exploration": None})
    with pytest.raises(harvest_labels.LabelRefused, match="bury_decision"):
        harvest_labels.rebuild_for_label(bury)

    # hidden hands: a dropped card in the acting hand is a mismatch
    snapshot = rebuild.hands_snapshot(rnd)
    with_hands = finalize_record({**rec, "hidden_hands": snapshot})
    harvest_labels.rebuild_for_label(with_hands)          # consistent hands pass
    mutated = json.loads(json.dumps(snapshot))
    mutated["hands_by_seat"][rec["seat"]].pop(0)
    with pytest.raises(harvest_labels.LabelRefused, match="hidden_hands_mismatch"):
        harvest_labels.rebuild_for_label(finalize_record({**rec, "hidden_hands": mutated}))

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
    swapped = finalize_record({**rec, "deck": deck})
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
    assert {k: v for k, v in row.items() if k not in cwv_eval.HOLDOUT_STRIP_KEYS} == rec
    assert cwv_eval.holdout_record(row) == rec
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
         "state_key": harvest_labels.state_key(rows[2]),
         "work_key": harvest_labels.work_key(rows[2])}]
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


# 5 ------------------------------------------------- Codex HOLD (PR #243)

def test_state_key_binds_setup_and_work_key_binds_action(records, tmp_path, monkeypatch):
    rec = next(r for r in _searched(records) if r["ply"] == 0)
    rnd, _legal, _diffs = harvest_labels.rebuild_for_label(rec)
    banker = rec["setup"]["banker"]
    # a second legal burial at the SAME deck / empty prefix / seat: swap one
    # buried card with a banker hand card (both plain, neither declared)
    declared = set()
    for d in rec["setup"]["declarations"]:
        declared |= set(d["cards"])
    keep = next(c for c in rec["setup"]["buried"] if c not in declared)
    swap = next(c for c in rnd.hands[banker] if c not in declared
                and c not in rec["setup"]["buried"] and c not in rec["action"])
    buried2 = sorted([c for c in rec["setup"]["buried"] if c != keep] + [swap])
    other = finalize_record({**rec, "setup": {**rec["setup"], "buried": buried2},
                             "legal_actions": None, "legal_actions_complete": False,
                             "legal_actions_count": None, "ballot": None, "allocation": None,
                             "action_values": None, "preference": None, "exploration": None})
    harvest_labels.rebuild_for_label(other)                 # a legal, different state
    assert harvest_labels.state_key(rec) != harvest_labels.state_key(other)
    # the same state with another played action: another work key
    keys = {action_key(c) for c in rec["ballot"]}
    off = next(a for a in rec["legal_actions"] if action_key(a) not in keys)
    other_action = finalize_record({**rec, "action": list(off)})
    assert harvest_labels.state_key(rec) == harvest_labels.state_key(other_action)
    assert harvest_labels.work_key(rec) != harvest_labels.work_key(other_action)
    # an identical twin (another policy label): the same work key
    twin = finalize_record({**rec, "policy": "human:twin"})
    assert harvest_labels.work_key(rec) == harvest_labels.work_key(twin)

    # run(): both burials labelled, both actions scored, the twin dedups
    in_dir, rows = _harvest_input(tmp_path, [rec, other, other_action, twin])
    monkeypatch.setattr(harvest_labels, "make_label_bot", lambda **kw: _make_test_bot(**kw))
    out = tmp_path / "labels"
    manifest = harvest_labels.run(inputs={"human": in_dir / "human.jsonl"}, out_dir=out,
                                  workers=1, log=None)
    c = manifest["sources"]["human"]["counts"]
    assert c["rows"] == 4 and c["labelled"] == 3 and c["refused"] == {"duplicate_state": 1}
    got = {g["record_sha256"]: g for g in (json.loads(line) for line in
           (out / "human.labels.jsonl").read_text().splitlines())}
    assert got[rows[1]["record_sha256"]]["search_labels"]["searched"] is True
    scored = got[rows[2]["record_sha256"]]["search_labels"]
    assert scored["searched"] and scored["played_in_ballot"] is False
    assert scored["ballot"][scored["played_index"]] == list(off)
    assert got[rows[3]["record_sha256"]]["label_refusal"]["duplicate_of"] == rows[0]["record_sha256"]
    assert manifest["key_version"] == harvest_labels.KEY_VERSION
    assert all(g["key_version"] == harvest_labels.KEY_VERSION for g in got.values())

    # rows under an older key version are migrated, never truncated (witness 6)
    shard = out / "shards" / "human.w0.jsonl"
    lines = [json.loads(line) for line in shard.read_text().splitlines()]
    lines[0]["key_version"] = 1                                 # the owner of the twin
    del lines[3]["key_version"]                                 # the pre-version duplicate
    shard.write_text("".join(json.dumps(line) + "\n" for line in lines))
    before = shard.read_bytes()
    again = harvest_labels.run(inputs={"human": in_dir / "human.jsonl"}, out_dir=out,
                               workers=1, log=None)
    mig = again["timings"]["migration"]
    assert (mig["rows"], mig["carried"], mig["carried_duplicates"]) == (4, 4, 1)
    assert mig["relabel_misdedup"] == 0 and again["timings"]["records_this_run"] == 0
    legacy = out / "shards" / "legacy-v1" / "human.w0.jsonl"
    assert legacy.read_bytes() == before and not shard.exists()
    lm = json.loads((out / "shards" / "legacy-v1" / "manifest.json").read_text())
    assert lm["files"][0]["rows"] == 4 and lm["files"][0]["migrated_to_key_version"] == 2
    carried = [json.loads(line)
               for line in (out / "shards" / "human.migrated.jsonl").read_text().splitlines()]
    assert [c["record_sha256"] for c in carried] == [line["record_sha256"] for line in lines]
    assert all(c["key_version"] == 2 for c in carried)
    assert [c.get("migrated_from") for c in carried] == [1, None, None, 1]
    assert carried[0]["search_labels"] == lines[0]["search_labels"]        # retained
    assert carried[3]["label_refusal"]["duplicate_of"] == rows[0]["record_sha256"]
    assert again["sources"]["human"]["counts"]["rows"] == 4
    third = harvest_labels.run(inputs={"human": in_dir / "human.jsonl"}, out_dir=out,
                               workers=1, log=None)
    assert third["timings"]["records_this_run"] == 0 and not third["timings"]["migration"]["rows"]


def test_identity_validated_at_ingestion_and_consumption(records, holdout_files, tmp_path):
    rec = _searched(records)[0]
    # an internally consistent outcome mutation that keeps the OLD record_sha256
    flipped = {**rec, "outcome": {**rec["outcome"],
                                  "attacker_points": (rec["outcome"]["attacker_points"] + 40) % 200}}
    assert flipped["record_sha256"] == rec["record_sha256"]
    with pytest.raises(harvest_labels.LabelRefused, match="invalid_record.*record_sha256 drift"):
        harvest_labels.rebuild_for_label(flipped)
    row = harvest_labels.label_record(flipped, work=TEST_WORK)
    assert row["search_labels"] is None and row["label_refusal"]["reason"] == "invalid_record"
    # at consumption: the same mutation inside a labelled row
    with_outcome, _no_outcome, _picks = holdout_files
    rows = [json.loads(line) for line in with_outcome.read_text().splitlines()]
    victim = next(r for r in rows if r["search_labels"] is not None)
    victim["outcome"] = {**victim["outcome"],
                         "attacker_points": (victim["outcome"]["attacker_points"] + 40) % 200}
    bad = tmp_path / "bad.jsonl"
    bad.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(cwv_eval.EvalError, match="record_sha256 drift"):
        cwv_eval.load_labeled_holdout(bad)
    hold = cwv_eval.load_labeled_holdout(with_outcome)
    hold.rows[0] = victim                                    # past the loader's check
    with pytest.raises(cwv_eval.EvalError, match="invalid record"):
        cwv_eval.materialize_holdout_records(hold, tmp_path / "m.jsonl")


def test_rank_only_holdout_on_a_fit_deal_is_refused(trained, store_dir, holdout_files, tmp_path):
    out, _kw, _receipt = trained
    _with, no_outcome, _picks = holdout_files
    by_deal: dict = {}
    for r in _searched(_records(store_dir)):
        by_deal.setdefault(tuple(r["deck"]), []).append(r)
    fit_rank_only = tmp_path / "fit-rank-only.jsonl"
    write_jsonl(fit_rank_only, _labelled_rows([r for rs in by_deal.values() for r in rs[:2]],
                                              drop_outcome=True))
    hold = cwv_eval.load_labeled_holdout(fit_rank_only)
    assert hold.supports == {"rank_regret": True, "calibration": False, "points": False}
    common = dict(checkpoint=str(out / "best.pt"), device="cpu", n_boot=10,
                  cache_dir=str(out / "cache"), cache_workers=1, eval_workers=1, bench_batch=8,
                  log=None)
    with pytest.raises(train_v0.TrainError, match="not held out"):
        train_cwv.evaluate(out=tmp_path / "f", eval_holdout=[f"fit={fit_rank_only}"], **common)
    ok = train_cwv.evaluate(out=tmp_path / "g", eval_holdout=[f"disjoint={no_outcome}"], **common)
    block = ok["holdouts"]["disjoint"]
    assert block["rank_regret"] is not None and block["population"]["shared_with_fit"] == 0
    assert block["population"]["deals"] == hold.counts["deals"] or block["population"]["deals"] >= 1


# 6 ----------------------------------------------- Codex HOLD round 2

def _stale_hash_copy(rec):
    """An internally consistent mutation that keeps the OLD record_sha256."""
    return {**rec, "outcome": {**rec["outcome"],
                               "attacker_points": (rec["outcome"]["attacker_points"] + 40) % 200}}


def test_invalid_first_copy_never_shadows_its_valid_twin(records, tmp_path, monkeypatch):
    rec = _searched(records)[1]
    invalid = _stale_hash_copy(rec)
    twin = finalize_record({**rec, "policy": "human:twin"})     # valid, distinct hash
    assert invalid["record_sha256"] != twin["record_sha256"]
    assert harvest_labels.work_key(invalid) == harvest_labels.work_key(twin)
    in_dir = tmp_path / "harvest"
    in_dir.mkdir()
    # the invalid row keeps its stale hash: written raw (write_jsonl re-encodes only)
    write_jsonl(in_dir / "human.jsonl", [{**invalid, "source": "human"}
                                         if False else invalid, twin])
    monkeypatch.setattr(harvest_labels, "make_label_bot", lambda **kw: _make_test_bot(**kw))
    monkeypatch.setitem(harvest_labels.SOURCE_FILES, "human", "human.jsonl")
    out = tmp_path / "labels"
    # the inputs are trajectory-sourced rows; the labeller only needs the file
    manifest = harvest_labels.run(inputs={"human": in_dir / "human.jsonl"}, out_dir=out,
                                  workers=1, log=None)
    c = manifest["sources"]["human"]["counts"]
    assert c["refused"] == {"invalid_record": 1} and c["labelled"] == 1 and c["searched"] == 1
    got = {g["record_sha256"]: g for g in (json.loads(line) for line in
           (out / "shards" / "human.w0.jsonl").read_text().splitlines())}
    assert got[twin["record_sha256"]]["search_labels"]["searched"] is True
    assert got[invalid["record_sha256"]]["label_refusal"]["reason"] == "invalid_record"
    assert got[invalid["record_sha256"]]["work_key"] == got[twin["record_sha256"]]["work_key"]

    # ownership rebuilt from a resumed shard: an invalid_record row that
    # carries the twin's work key (as an older labeller wrote it) owns nothing
    out2 = tmp_path / "labels2"
    (out2 / "shards").mkdir(parents=True)
    stale_row = harvest_labels.label_record(invalid, work=TEST_WORK)
    assert stale_row["label_refusal"]["reason"] == "invalid_record"
    (out2 / "shards" / "human.w0.jsonl").write_text(json.dumps(stale_row) + "\n")
    write_jsonl(in_dir / "human.jsonl", [twin])
    manifest = harvest_labels.run(inputs={"human": in_dir / "human.jsonl"}, out_dir=out2,
                                  workers=1, log=None)
    c = manifest["sources"]["human"]["counts"]
    assert c["labelled"] == 1 and c["searched"] == 1 and "duplicate_state" not in c["refused"]


def test_admission_before_mutation_and_legacy_migration(records, tmp_path, monkeypatch):
    picks = _searched(records)[:3]
    twin = finalize_record({**picks[1], "policy": "human:twin"})
    in_dir, rows = _harvest_input(tmp_path, [*picks, twin])
    inputs = {"human": in_dir / "human.jsonl"}
    monkeypatch.setattr(harvest_labels, "make_label_bot", lambda **kw: _make_test_bot(**kw))
    out = tmp_path / "labels"
    harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    shard = out / "shards" / "human.w0.jsonl"
    lines = [json.loads(line) for line in shard.read_text().splitlines()]
    assert lines[3]["label_refusal"]["duplicate_of"] == rows[1]["record_sha256"]
    # a legacy shard: version-1 rows, one duplicate MIS-deduped against a
    # different state (the coarse old key), plus a torn last line
    for line in lines:
        line["key_version"] = 1
    lines[3]["label_refusal"]["duplicate_of"] = rows[0]["record_sha256"]
    lines[3]["label_refusal"]["detail"] = rows[0]["record_sha256"]
    body = "".join(json.dumps(line) + "\n" for line in lines) + '{"torn": tru'
    shard.write_text(body)
    before = shard.read_bytes()
    snapshot = {p.name: p.read_bytes() for p in (out / "shards").glob("*.jsonl")}
    run_json = (out / "run.json").read_bytes()
    # (a) a missing input refuses before any byte changes
    with pytest.raises(harvest_labels.LabelError, match="missing"):
        harvest_labels.run(inputs={"human": in_dir / "nope.jsonl"}, out_dir=out, workers=1,
                           log=None)
    assert {p.name: p.read_bytes() for p in (out / "shards").glob("*.jsonl")} == snapshot
    assert (out / "run.json").read_bytes() == run_json
    assert not (out / "shards" / "legacy-v1").exists()
    # (b) an incompatible resume (scale) refuses before any byte changes
    with pytest.raises(harvest_labels.LabelError, match="cannot resume"):
        harvest_labels.run(inputs=inputs, out_dir=out, workers=1, scale=3, log=None)
    assert {p.name: p.read_bytes() for p in (out / "shards").glob("*.jsonl")} == snapshot
    # (c) the admitted run migrates: the legacy shard is preserved byte for
    # byte, unaffected rows are retained, the mis-deduped row is relabelled
    manifest = harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    legacy = out / "shards" / "legacy-v1" / "human.w0.jsonl"
    assert legacy.read_bytes() == before                     # torn tail included
    assert len(shard.read_text().splitlines()) == 1          # the fresh shard: 1 relabel
    mig = manifest["timings"]["migration"]
    assert (mig["rows"], mig["carried"], mig["relabel_misdedup"]) == (4, 3, 1)
    assert manifest["timings"]["records_this_run"] == 1
    assert manifest["scan"]["torn"] == ["human.w0.jsonl"]
    carried = [json.loads(line)
               for line in (out / "shards" / "human.migrated.jsonl").read_text().splitlines()]
    assert [c["search_labels"] for c in carried] == [line["search_labels"] for line in lines[:3]]
    relabelled = next(json.loads(line) for line in (out / "shards" / "human.w0.jsonl")
                      .read_text().splitlines())
    assert relabelled["record_sha256"] == rows[3]["record_sha256"]
    assert relabelled["label_refusal"]["duplicate_of"] == rows[1]["record_sha256"]
    c = manifest["sources"]["human"]["counts"]
    assert c["rows"] == 4 and c["labelled"] == 3 and c["refused"] == {"duplicate_state": 1}
    run_info = json.loads((out / "run.json").read_text())
    assert run_info["migrations"][0]["shards"] == ["human.w0.jsonl"]
    # resume after the migration is a no-op
    again = harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    assert again["timings"]["records_this_run"] == 0 and again["timings"]["migration"]["rows"] == 0


# 7 ----------------------------------------------- Codex HOLD round 3

def test_invalid_row_never_marks_its_hash_done(records, tmp_path, monkeypatch):
    rec = finalize_record({**_searched(records)[2], "source": "human"})
    stale = _stale_hash_copy(rec)                            # same hash H, invalid
    monkeypatch.setattr(harvest_labels, "make_label_bot", lambda **kw: _make_test_bot(**kw))
    in_dir = tmp_path / "harvest"
    in_dir.mkdir()
    # (a) resume: a shard holding an invalid_record row for H; the input is
    # the valid original with H
    out = tmp_path / "labels"
    (out / "shards").mkdir(parents=True)
    stale_row = harvest_labels.label_record(stale, work=TEST_WORK)
    assert stale_row["label_refusal"]["reason"] == "invalid_record"
    (out / "shards" / "human.w0.jsonl").write_text(json.dumps(stale_row) + "\n")
    write_jsonl(in_dir / "human.jsonl", [rec])
    inputs = {"human": in_dir / "human.jsonl"}
    manifest = harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    c = manifest["sources"]["human"]["counts"]
    assert manifest["timings"]["records_this_run"] == 1 and c["labelled"] == 1
    assert c["rows"] == 1 and c["superseded_invalid"] == 1 and c["refused"] == {}
    assert manifest["sources"]["human"]["superseded"] == [
        {"record_sha256": rec["record_sha256"], "superseded_by": "labelled"}]
    merged = [json.loads(line) for line in (out / "human.labels.jsonl").read_text().splitlines()]
    assert len(merged) == 1 and merged[0]["search_labels"] is not None
    again = harvest_labels.run(inputs=inputs, out_dir=out, workers=1, log=None)
    assert again["timings"]["records_this_run"] == 0
    # (b) two input rows with one hash: the valid one is kept whatever its position
    for order in ((stale, rec), (rec, stale)):
        out2 = tmp_path / f"labels-{order[0] is rec}"
        write_jsonl(in_dir / "human.jsonl", list(order))
        manifest = harvest_labels.run(inputs=inputs, out_dir=out2, workers=1, log=None)
        c = manifest["sources"]["human"]["counts"]
        assert c["labelled"] == 1 and c["rows"] == 1 and c["input_rows"] == 2
        assert c["superseded_invalid"] == (1 if order[0] is stale else 0)
        # valid first: the later invalid copy of a queued hash is not even written
        assert c["duplicate_rows_dropped"] == 0 and c["refused"] == {}
        merged = [json.loads(line)
                  for line in (out2 / "human.labels.jsonl").read_text().splitlines()]
        assert merged[0]["search_labels"] is not None
        # a rerun refuses nothing new and relabels nothing
        again = harvest_labels.run(inputs=inputs, out_dir=out2, workers=1, log=None)
        assert again["timings"]["records_this_run"] == 0
