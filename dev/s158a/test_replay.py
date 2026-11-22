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


FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
# genuine identity captures (seeds outside both splits): 1011403002 has a refused throw (trick 8, lead 3
# wide, follows 2) and three contested rows; 1011403001 has a single-candidate row
GENUINE = {s: json.load(open(os.path.join(FIX, f"{s}.json"))) for s in (1011403001, 1011403002)}


def deal(seed, template=1011403002, plain=False):
    """A genuine capture re-keyed to ``seed`` (deal and row seeds), the producer's shape."""
    x = json.loads(json.dumps(GENUINE[template]))
    x["seed"] = seed; x["plain"] = plain
    for r in x["decisions"]:
        r["seed"] = seed
    return x


def write_split(d, lo, hi):
    for s in range(lo, hi):
        json.dump(deal(s), open(os.path.join(d, f"{s}.json"), "w"))


def put(d, s, x):
    json.dump(x, open(os.path.join(d, f"{s}.json"), "w"))


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
    assert deals == 1500 and len(rows) == 4500
    x = R.evaluate(rows, dict(D=1.95, Wmin=16, z=2.0, prune=0.3, cap=None), with_ci=True)
    assert x["eligible"] == 4500 and x["unresolved"] == 0


def test_tune_cli_end_to_end_on_the_synthetic_split(tmp_path, monkeypatch):
    write_split(tmp_path, *TUNE)
    monkeypatch.setattr(R, "GRID", dict(Wmin=[0, 16], z=[None, 2.0], prune=[0.0, 0.3], cap=[None]))
    out = R.main(["tune", str(tmp_path), str(TUNE[0]), str(TUNE[1]), str(tmp_path / "tune.json")])
    assert out["summary"]["deals"] == 1500 and out["summary"]["eligible"] == 4500


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
    put(tmp_path, s, deal(999))
    with pytest.raises(R.ReplayInputError, match="holds seed 999"):
        R.load(str(tmp_path), *TUNE)


def test_load_refuses_a_row_from_another_deal(tmp_path):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 3
    x = deal(s); x["decisions"][0]["seed"] = s + 1; put(tmp_path, s, x)
    with pytest.raises(R.ReplayInputError, match="row seed"):
        R.load(str(tmp_path), *TUNE)


def test_load_refuses_a_plain_deal(tmp_path):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 5
    put(tmp_path, s, deal(s, plain=True))
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
    lambda r: r.update(served_idx=r["n_adm"]),
    lambda r: r.update(value_means=[0.0]),
    lambda r: r.update(pi=[1]),                                                         # PI short, not censored
    lambda r: r["T"].__setitem__(0, [-1] * r["n_adm"]),
    lambda r: r.update(n_adm=-1),
])
def test_load_refuses_malformed_rows(tmp_path, mutate):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 11
    x = deal(s); mutate(x["decisions"][0]); put(tmp_path, s, x)
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
    assert out["frozen"]["eligible"] == 4500 and out["verdict"] in ("PASS", "PARK", "INCONCLUSIVE")


# producer-to-reader: genuine captures, zero-admission rows, complete history and row identity
SMOKE = {"identity": (1011403001, 1011403003)}


def test_genuine_identity_captures_load(tmp_path):
    for s, x in GENUINE.items():
        put(tmp_path, s, x)
    allr = []
    rows, n = R.load(str(tmp_path), *SMOKE["identity"], splits=SMOKE, census=allr)
    assert n == 2 and len(rows) == 5 and len(allr) == 6
    assert sum(R.ineligible_census(allr).values()) == 1


def test_refused_throw_uses_the_played_width():
    plays = GENUINE[1011403002]["plays"]
    t = plays[28:32]
    assert [len(c) for _, c in t] == [3, 2, 2, 2]                    # the refused throw
    want = R.expected_rows(plays)
    assert {(a, b, c) for a, b, c, _ in want} == {(r["trick"], r["pos"], r["seat"])
                                                  for r in GENUINE[1011403002]["decisions"]}


def test_zero_admission_fallback_row_is_ineligible_not_fatal(tmp_path):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 2
    x = deal(s); r = x["decisions"][1]
    x["decisions"][1] = dict(seed=s, trick=r["trick"], pos=r["pos"], seat=r["seat"], attacker=r["attacker"],
                             n_adm=0, dec_sec=3.1, schema="pv-search-fallback-v1", fallback=True,
                             fallback_reason="budget")
    put(tmp_path, s, x)
    allr = []
    rows, _ = R.load(str(tmp_path), *TUNE, census=allr)
    assert len(rows) == 4499
    c = R.ineligible_census(allr)
    assert c == {"n_adm=0 schema=pv-search-fallback-v1 fallback=True reason=budget": 1}


@pytest.mark.parametrize("mutate,match", [
    (lambda x: x.update(plays=[[0, ["x"]]]), "whole tricks"),                         # a one-play deal
    (lambda x: x.update(plays=x["plays"][:-4]), "incomplete"),                        # last trick missing
    (lambda x: x["plays"].__setitem__(1, [x["plays"][3][0], x["plays"][1][1]]), "out of turn"),
    (lambda x: x["plays"][30].__setitem__(1, x["plays"][30][1][:1]), "follow widths"),
    (lambda x: x["decisions"].append(dict(x["decisions"][0])), "duplicate"),
    (lambda x: x["decisions"].pop(1), "do not match"),                                # a captured follow missing
    (lambda x: x["decisions"][0].update(pos=x["decisions"][0]["pos"] % 3 + 1), "duplicate|do not match"),
    (lambda x: x["decisions"][0].update(seat=(x["decisions"][0]["seat"] + 1) % 4), "do not match"),
    (lambda x: x["decisions"][0].update(trick=1), "do not match"),
    (lambda x: x["decisions"][0].update(played=["XX"]), "played cards differ"),
])
def test_history_and_row_identity_are_enforced(tmp_path, mutate, match):
    write_split(tmp_path, *TUNE)
    s = TUNE[0] + 4
    x = deal(s); mutate(x); put(tmp_path, s, x)
    with pytest.raises(R.ReplayInputError, match=match):
        R.load(str(tmp_path), *TUNE)
