"""Pins for the S158A replay: the abandon denominator, load validation, null-safe means, the read gate."""
import json, os, sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as R

TUNE = R.SPLITS["tune"]; READ = R.SPLITS["read"]


def row(seed, L, served=0, vm=None, T=None, attacker=True, pi=None, censored=False, nodecap=None):
    n = len(L[0]) if L else 3
    T = T or [[1000] * n for _ in L]
    return dict(seed=seed, trick=10, pos=1, seat=1, attacker=attacker, n_adm=n,
                admitted=[[f"c{i}"] for i in range(n)], served_idx=served,
                value_means=vm if vm is not None else [0.0] * n, n_worlds=64, worlds_done=len(L),
                L=L, N=[[1] * n for _ in L], T=T, D=[[-1] * n for _ in L], censored=censored,
                nodecap=nodecap if nodecap is not None else [], pi=pi if pi is not None else list(range(n)),
                pi_censored=False, stage_cpu=sum(map(sum, T)) / 1e6)


def deal(seed, rows, plain=False):
    return dict(seed=seed, plain=plain, plays=[[0, ["x"]]], attacker_points=0, decisions=rows)


def write_split(d, lo, hi, make=lambda s: [row(s, [[0.0, 1.0, 0.5]] * 64)]):
    for s in range(lo, hi):
        json.dump(deal(s, make(s)), open(os.path.join(d, f"{s}.json"), "w"))


NO_RACE = dict(D=1.95, Wmin=0, z=None, prune=0.3, cap=None)


# fix 3: a pruned candidate's node-capped null is never read
def test_pruned_null_does_not_crash_final_selection():
    r = row(1, [[0.0, 1.0, None]] * 64, served=0, vm=[0.0, 1.0, -1.0])
    assert R.pruned_set(r, 0.3) == {2}
    pk, abd, t = R.sim(r, 1.95, 0, None, 0.3, None)
    assert (pk, abd) == (1, False)


def test_pruned_null_does_not_crash_racing():
    r = row(1, [[0.0, 1.0, None]] * 64, served=0, vm=[0.0, 1.0, -1.0])
    for z in (1.5, 2.0, 2.5):
        pk, abd, _ = R.sim(r, 1.95, 16, z, 0.3, None)
        assert (pk, abd) == (1, False)


def test_surviving_null_is_unresolved():
    r = row(1, [[0.0, 1.0, None]] * 64, served=0, vm=[0.0, -1.0, 1.0])   # prune drops 1, keeps the null 2
    assert R.sim(r, 1.95, 0, None, 0.3, None) == (None, None, None)
    assert R.sim(r, 1.95, 16, 2.0, 0.3, None) == (None, None, None)
    x = R.evaluate([r], NO_RACE)
    assert (x["abandons"], x["unresolved"], x["eligible"]) == (0, 1, 1)


# fix 1: the denominator keeps unresolved follows
def test_unresolved_follows_stay_in_the_denominator():
    rows = [row(s, [], censored=True) for s in range(99)]           # capture stopped before world 1
    rows += [row(99, [[0.0, 1.0, 0.5]] * 64)]
    x = R.evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None))
    assert (x["eligible"], x["abandons"], x["unresolved"]) == (100, 0, 99)
    assert x["abandon_interval"] == [0.0, 0.99]
    assert x["abandon_bar"] == "INCONCLUSIVE"
    assert R.stage_a_verdict(x) == "INCONCLUSIVE"


def test_capture_error_counts_as_unresolved():
    bad = dict(row(1, [[0.0, 1.0, 0.5]] * 64), capture_error="no stash")
    x = R.evaluate([bad], dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None))
    assert (x["eligible"], x["unresolved"]) == (1, 1)


def test_abandon_verdicts():
    slow = [[50_000, 50_000, 50_000]] * 64                          # 9.6 s stage: all-or-nothing abandons
    fast = [[1000] * 3] * 64
    rows = [row(s, [[0.0, 1.0, 0.5]] * 64, T=slow if s < 3 else fast) for s in range(100)]
    x = R.evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None))
    assert x["abandon_interval"] == [0.03, 0.03] and x["abandon_bar"] == "FAIL"
    rows = [row(s, [[0.0, 1.0, 0.5]] * 64, T=slow if s < 2 else fast) for s in range(100)]
    x = R.evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None))
    assert x["abandon_bar"] == "PASS"
    rows[50] = row(50, [], censored=True)
    x = R.evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None))
    assert x["abandon_interval"] == [0.02, 0.03] and x["abandon_bar"] == "INCONCLUSIVE"


def test_incomplete_reference_is_excluded_from_pi_but_counted():
    r = row(1, [[0.0, 1.0, 0.5]] * 40, censored=True)
    assert R.full_ref(r) is None
    x = R.evaluate([r, row(2, [[0.0, 1.0, 0.5]] * 64)], dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None))
    assert x["eligible"] == 2 and x["ref_decisions"] == 1 and x["pi_coverage"] == 0.5


# fix 2: load validation
def test_load_accepts_a_complete_synthetic_tune_split(tmp_path):
    write_split(tmp_path, *TUNE)
    rows, deals = R.load(str(tmp_path), *TUNE)
    assert deals == 1500 and len(rows) == 1500
    x = R.evaluate(rows, dict(D=1.95, Wmin=16, z=2.0, prune=0.3, cap=None), with_ci=True)
    assert x["eligible"] == 1500 and x["unresolved"] == 0 and x["abandon_bar"] == "PASS"


def test_tune_cli_end_to_end_on_the_synthetic_split(tmp_path, monkeypatch):
    write_split(tmp_path, *TUNE)
    monkeypatch.setattr(R, "GRID", dict(Wmin=[0, 16], z=[None, 2.0], prune=[0.0, 0.3], cap=[None]))
    out = R.main(["tune", str(tmp_path), str(TUNE[0]), str(TUNE[1]), str(tmp_path / "tune.json")])
    assert out["summary"]["deals"] == 1500 and out["chosen"]["abandon_bar"] == "PASS"


def test_load_refuses_an_undeclared_interval(tmp_path):
    with pytest.raises(R.ReplayInputError):
        R.load(str(tmp_path), 1, 2)


def test_load_refuses_a_missing_deal(tmp_path):
    write_split(tmp_path, *TUNE)
    os.remove(tmp_path / f"{TUNE[0] + 7}.json")
    with pytest.raises(R.ReplayInputError, match="missing deal"):
        R.load(str(tmp_path), *TUNE)


def test_load_refuses_a_mismatched_deal_seed(tmp_path):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 1
    json.dump(deal(999, [row(999, [[0.0, 1.0, 0.5]] * 64)]), open(tmp_path / f"{s}.json", "w"))
    with pytest.raises(R.ReplayInputError, match="holds seed 999"):
        R.load(str(tmp_path), *TUNE)


def test_load_refuses_a_row_from_another_deal(tmp_path):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 3
    json.dump(deal(s, [row(s + 1, [[0.0, 1.0, 0.5]] * 64)]), open(tmp_path / f"{s}.json", "w"))
    with pytest.raises(R.ReplayInputError, match="row seed"):
        R.load(str(tmp_path), *TUNE)


def test_load_refuses_a_plain_deal(tmp_path):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 5
    json.dump(deal(s, [], plain=True), open(tmp_path / f"{s}.json", "w"))
    with pytest.raises(R.ReplayInputError, match="not an instrumented"):
        R.load(str(tmp_path), *TUNE)


def test_load_refuses_a_temp_file(tmp_path):
    write_split(tmp_path, *TUNE)
    open(tmp_path / f"{TUNE[0] + 9}.json.tmp123", "w").write("{")
    with pytest.raises(R.ReplayInputError, match="temp file"):
        R.load(str(tmp_path), *TUNE)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(worlds_done=40, L=r["L"][:40], N=r["N"][:40], T=r["T"][:40]),   # short, not censored
    lambda r: r.update(L=r["L"][:63]),                                                  # shape mismatch
    lambda r: r.update(n_worlds=32),
    lambda r: r.update(served_idx=5),
    lambda r: r.update(value_means=[0.0]),
    lambda r: r.update(pi=[1]),                                                         # PI short, not censored
    lambda r: r["T"].__setitem__(0, [1, -1, 1]),
])
def test_load_refuses_malformed_rows(tmp_path, mutate):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 11
    r = row(s, [[0.0, 1.0, 0.5]] * 64); r["L"] = [list(x) for x in r["L"]]; mutate(r)
    json.dump(deal(s, [r]), open(tmp_path / f"{s}.json", "w"))
    with pytest.raises(R.ReplayInputError):
        R.load(str(tmp_path), *TUNE)


# the held-out gate: terminal capture and freeze identity before any deal file is opened
def _rule(tmp_path):
    p = tmp_path / "frozen_rule.json"
    json.dump(dict(rule=dict(D=1.95, Wmin=16, z=2.0, prune=0.3, cap=None)), open(p, "w"))
    return p


def test_read_refuses_without_terminal_line(tmp_path, monkeypatch):
    p = _rule(tmp_path); open(str(p) + ".sha256", "w").write(R.file_sha256(p) + "\n")
    open(tmp_path / "status.log", "w").write("x RUN START\n")
    opened = []
    monkeypatch.setattr(R, "load", lambda *a: opened.append(a))
    with pytest.raises(R.ReplayInputError, match="not terminal"):
        R.main(["read", str(tmp_path), str(READ[0]), str(READ[1]), str(p), str(tmp_path / "o.json")])
    assert not opened


def test_read_refuses_a_changed_rule(tmp_path, monkeypatch):
    p = _rule(tmp_path); open(str(p) + ".sha256", "w").write("0" * 64 + "\n")
    open(tmp_path / "status.log", "w").write("x " + R.TERMINAL_LINE + "\n")
    opened = []
    monkeypatch.setattr(R, "load", lambda *a: opened.append(a))
    with pytest.raises(R.ReplayInputError, match="frozen rule sha"):
        R.main(["read", str(tmp_path), str(READ[0]), str(READ[1]), str(p), str(tmp_path / "o.json")])
    assert not opened


def test_read_refuses_the_tune_interval(tmp_path):
    p = _rule(tmp_path)
    with pytest.raises(R.ReplayInputError, match="read split"):
        R.main(["read", str(tmp_path), str(TUNE[0]), str(TUNE[1]), str(p), str(tmp_path / "o.json")])


def test_read_end_to_end_on_a_synthetic_read_split(tmp_path):
    write_split(tmp_path, *READ)
    p = _rule(tmp_path); open(str(p) + ".sha256", "w").write(R.file_sha256(p) + "\n")
    open(tmp_path / "status.log", "w").write("x " + R.TERMINAL_LINE + "\n")
    out = R.main(["read", str(tmp_path), str(READ[0]), str(READ[1]), str(p), str(tmp_path / "o.json")])
    assert out["frozen"]["eligible"] == 1500 and out["verdict"] == "PASS"
