"""Freezer contract. A gate artifact is only as good as what its builder enforces.

Every case here is a property Codex named as unenforced when the first 512 sets
were frozen: the source list, the side selector, the exact registered quotas,
one-state-per-deal, DEV/CALIB disjointness, and fail-closed behaviour. The
freezer recorded role and candidate-size strata without enforcing either, and
reported `?` for role because the field was never carried — a mechanism that
looked implemented and was not.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import pilot_states as PS  # noqa: E402

ART = os.path.join(os.path.dirname(__file__), "..", "rl_data")


def _load(name):
    p = os.path.join(ART, name)
    if not os.path.exists(p):
        pytest.skip(f"{name} not frozen in this checkout")
    return json.load(open(p))


def test_sources_include_the_deep_reservoir():
    """Without it the registered late band is unreachable: the mined corpora
    hold only 3 DEV deals with a lead at trick >= 12."""
    names = {n for n, _, _ in PS.SOURCES}
    assert "deep" in names, f"deep reservoir missing from SOURCES: {names}"
    for _, corpus, split in PS.SOURCES:
        assert corpus and split, "every source needs a corpus AND a split"


def test_registered_quota_is_170_171_171():
    assert PS.BAND_QUOTA == {"early": 170, "mid": 171, "late": 171}
    assert sum(PS.BAND_QUOTA.values()) == 512


@pytest.mark.parametrize("name", ["pilot_dev512.v4.json",
                                  "pilot_calib512.v4.json"])
def test_no_selected_state_belongs_to_the_REPORT_split(name):
    """REPORT membership checked against the DECLARED SPLIT FILES.

    The previous version grepped `pilot_states.py` for the literal
    `choices=("dev","calib")`. That passes whether or not a single REPORT deal
    leaked into an artifact, because it never reads the artifact — it asserts
    the source contains a string (Codex). This resolves every selected seed
    through the split file its own source registers.
    """
    d = _load(name)
    want = d["side"]
    checked = 0
    for st in d["states"]:
        split_path = os.path.join(ART, os.path.basename(
            d["sources"][st["source"]]["split"]))
        if not os.path.exists(split_path):
            pytest.skip(f"split file for {st['source']} absent")
        with open(split_path) as fh:
            assign = json.load(fh)["assign"]
        got = assign.get(str(st["seed"]))
        assert got != "report", \
            f"seed {st['seed']} is a REPORT deal and must never be selected"
        assert got == want, f"seed {st['seed']} is {got}, artifact is {want}"
        checked += 1
    assert checked == 512, f"only {checked} states resolved against a split"


@pytest.mark.parametrize("name", ["pilot_dev512.v4.json", "pilot_calib512.v4.json"])
def test_frozen_artifact_meets_the_contract(name):
    d = _load(name)
    assert d["selected"] == 512
    assert d["bands_selected"] == PS.BAND_QUOTA, \
        f"{name} band composition {d['bands_selected']} != registered quota"
    seeds = [s["seed"] for s in d["states"]]
    assert len(set(seeds)) == 512, "one state per deal violated"
    assert d["leads_only"] and d["one_state_per_deal"]
    assert d["tree_dirty"] is False, "frozen from a dirty tree"
    assert d["ballot_at_selection"], "no ballot identity recorded"
    for key in ("script_sha256_16", "sources"):
        assert d.get(key), f"{name} missing provenance: {key}"
    assert not any(s.get("split") == "report" for s in d["states"]), \
        "a REPORT row was selected"


def test_role_balance_is_enforced_not_merely_recorded():
    """The first freeze reported `?` for every band: rows carried no role, so
    the balancing loop matched nothing and silently fell through."""
    for name in ("pilot_dev512.v3.json", "pilot_calib512.v3.json"):
        d = _load(name)
        for band, counts in d["roles_by_band"].items():
            assert "?" not in counts, f"{name}/{band}: role never carried"
            assert set(counts) == {"attacker", "defender"}, counts
            lo, hi = min(counts.values()), max(counts.values())
            assert hi - lo <= 1, f"{name}/{band} role imbalance {counts}"


def test_dev_and_calib_are_deal_disjoint():
    d, c = _load("pilot_dev512.v3.json"), _load("pilot_calib512.v3.json")
    kd = {(s["source"], s["seed"]) for s in d["states"]}
    kc = {(s["source"], s["seed"]) for s in c["states"]}
    assert not (kd & kc), f"{len(kd & kc)} deals appear in BOTH gate sets"
    assert d["salt"] != c["salt"], "the two sets must use distinct salts"


def test_source_and_split_digests_are_recorded_and_current():
    """A frozen set whose inputs cannot be identified is not reproducible."""
    for name in ("pilot_dev512.v3.json", "pilot_calib512.v3.json"):
        d = _load(name)
        for src, meta in d["sources"].items():
            assert meta.get("corpus_sha256_16"), f"{name}/{src}: no corpus digest"
            assert meta.get("split_sha256_16"), f"{name}/{src}: no split digest"
            live = PS.digest(os.path.join(ART, os.path.basename(meta["corpus"])))
            if live:
                assert live == meta["corpus_sha256_16"], \
                    f"{name}/{src}: corpus changed since the freeze"


def test_freezer_refuses_a_dirty_tree_and_an_existing_path():
    src = open(PS.__file__).read()
    assert "REFUSING: the tree is dirty" in src
    assert "REFUSING: {args.out} exists" in src or "exists. A frozen pilot set" in src
    # The real property is that no override ARGUMENT exists — a docstring
    # explaining why the flag was removed is desirable, and grepping for the
    # bare string flagged that prose instead of the behaviour.
    assert 'add_argument("--force"' not in src, \
        "an existing frozen path must be unconditionally non-overwritable"


@pytest.mark.parametrize("art", ["pilot_dev512.v4.json",
                                 "pilot_calib512.v4.json"])
def test_every_selected_state_replays(art):
    """A state that cannot be rebuilt cannot be scored. All 1,024 rows."""
    d = _load(art)
    # ALL of them. Sampling six of 512 leaves a 1-in-85 chance of touching any
    # given bad state, so the previous version could pass with dozens of
    # unreplayable rows (Codex).
    srcs = {n: c for n, c, _ in PS.SOURCES}
    for st in d["states"]:
        path = os.path.join(ART, os.path.basename(srcs[st["source"]]))
        if not os.path.exists(path):
            pytest.skip(f"{st['source']} corpus absent")
        row = next(json.loads(l) for l in open(path)
                   if json.loads(l)["seed"] == st["seed"]
                   and json.loads(l)["ply"] == st["ply"])
        rnd = PS.replay(row)
        assert rnd.turn == st["seat"], f"{st['seed']} replayed to another seat"


# --- refusal contract -------------------------------------------------------
# Codex: "a shortage or replay-error-bearing build can still write a short
# artifact and exit successfully; the tests exercise neither refusal." These
# call `check_contract` directly so a refusal can be PROVEN to fire rather than
# assumed from a passing freeze — a guard only ever seen on good input is an
# untested guard.

def _rows(n, band="early", size="wide", seed0=0):
    return [{"seed": seed0 + i, "band": band,
             "stratum": f"{band}/attacker/{size}"} for i in range(n)]


def test_check_contract_refuses_a_short_selection():
    import pilot_states as P
    bad = P.check_contract(_rows(500), requested=512, errors=0)
    assert any("selected 500, requested 512" in v for v in bad), bad


def test_check_contract_refuses_replay_errors():
    import pilot_states as P
    bad = P.check_contract(_rows(512), requested=512, errors=3)
    assert any("replay error" in v for v in bad), bad


def test_check_contract_refuses_a_missed_band_quota():
    import pilot_states as P
    rows = _rows(170, "early") + _rows(171, "mid", seed0=1000) \
        + _rows(170, "late", seed0=2000)
    bad = P.check_contract(rows, requested=511, errors=0)
    assert any("band late" in v and "quota 171" in v for v in bad), bad


def test_check_contract_refuses_a_missed_SIZE_quota():
    """The stratum that was recorded but never enforced."""
    import pilot_states as P
    rows = (_rows(170, "early", "wide") + _rows(171, "mid", "wide", 1000)
            + _rows(171, "late", "wide", 2000))
    bad = P.check_contract(rows, requested=512, errors=0)
    assert any("size small" in v for v in bad), bad
    assert any("size wide" in v for v in bad), bad


def test_check_contract_refuses_duplicate_deals():
    import pilot_states as P
    rows = _rows(512)
    rows[7]["seed"] = rows[6]["seed"]
    bad = P.check_contract(rows, requested=512, errors=0)
    assert any("duplicate deal seeds" in v for v in bad), bad


def test_v4_is_SUPERSEDED_and_fails_the_source_marginals():
    """Known-bad regression: v4's population depended on corpus order.

    v4 satisfies band, size and role but NOT source, because selection walked a
    supply index built in file order. DEV came out mid 163 original / 8 late
    against CALIB 55 / 116 — a population shift, so CALIB was not a held-out
    replicate of DEV. Asserting v4 is REJECTED keeps the source guard from
    silently becoming vacuous later.
    """
    for art in ("pilot_dev512.v4.json", "pilot_calib512.v4.json"):
        d = _load(art)
        bad = PS.check_contract(d["states"], d["requested"], d["replay_errors"])
        assert any("source" in b for b in bad), \
            f"{art} should fail the source marginals, got {bad}"


def test_the_frozen_v3_sets_FAIL_the_size_quota_as_registered():
    """Guards against the check being vacuous.

    The v3 artifacts predate size enforcement, so a check that passes them is
    not checking anything. This asserts the known-bad input is REJECTED.
    """
    import json
    import pilot_states as P
    d = _load("pilot_dev512.v3.json")
    bad = P.check_contract(d["states"], d["requested"], d["replay_errors"])
    assert any("size" in v for v in bad), "size quota is not being enforced"


def test_publish_refuses_and_leaves_no_artifact_on_shortage(tmp_path):
    """A shortage must publish NOTHING — not a short file, not a .tmp."""
    out = tmp_path / "v4.json"
    tmp = tmp_path / "v4.json.tmp"
    tmp.write_text('{"partial": true}')
    with pytest.raises(SystemExit) as e:
        PS.publish_or_refuse({"states": []}, str(out), str(tmp),
                             ["band late: 150 selected, quota 171"])
    assert e.value.code == 4
    assert not out.exists(), "a short artifact was published"
    assert not tmp.exists(), "a .tmp was left behind for a later run to promote"


def test_publish_refuses_on_replay_errors(tmp_path):
    out = tmp_path / "v4.json"
    tmp = tmp_path / "v4.json.tmp"
    with pytest.raises(SystemExit) as e:
        PS.publish_or_refuse({"states": []}, str(out), str(tmp),
                             ["3 replay error(s): a state that does not "
                              "replay cannot be scored"])
    assert e.value.code == 4
    assert not out.exists()


def test_publish_writes_when_the_contract_is_clean(tmp_path):
    """Guards against the refusal being unconditional."""
    out = tmp_path / "v4.json"
    tmp = tmp_path / "v4.json.tmp"
    PS.publish_or_refuse({"states": [1, 2]}, str(out), str(tmp), [])
    assert out.exists() and json.loads(out.read_text())["states"] == [1, 2]
    assert not tmp.exists()


def test_registered_quotas_are_internally_consistent():
    for b, want in PS.BAND_QUOTA.items():
        assert sum(PS.SIZE_QUOTA[b].values()) == want
        assert sum(PS.ROLE_QUOTA[b].values()) == want
    assert sum(PS.BAND_QUOTA.values()) == 512


# --- C1: selection must not depend on corpus traversal order ----------------
# v4's selector walked a supply index built in SOURCES/file order and took the
# first live seed, while the `deals_for` shuffle above it was dead code. The
# artifact was therefore a function of insertion order, and DEV/CALIB drew
# different source mixes (DEV mid 163 original/8 late vs CALIB 55/116). These
# assert the property directly rather than inspecting a produced artifact.

def _synth(n=60):
    """Eligible rows across three sources, several per deal."""
    out = {}
    srcs = ["original", "late", "deep"]
    for i in range(n):
        rows = []
        for j, band in enumerate(("early", "mid", "late")):
            for k, size in enumerate(("small", "med", "wide")):
                rows.append({
                    "seed": 1000 + i, "band": band, "source": srcs[(i + j) % 3],
                    "role": ("attacker", "defender")[(i + k) % 2],
                    "stratum": f"{band}/x/{size}", "tricks": j, "ply": k,
                    "seat": i % 4})
        out[1000 + i] = rows
    return out


def _ids(picked):
    return [(p["seed"], p["band"], PS.size_of(p), p.get("role"), p["source"])
            for p in picked]


_Q = dict(band_quota={"early": 3, "mid": 3, "late": 3},
          size_quota={b: {"small": 1, "med": 1, "wide": 1}
                      for b in ("early", "mid", "late")},
          role_quota={b: {"attacker": 2, "defender": 1}
                      for b in ("early", "mid", "late")},
          source_quota={b: {"original": 1, "late": 1, "deep": 1}
                        for b in ("early", "mid", "late")})


def test_selection_is_invariant_under_deal_order():
    a, _ = PS.select_states(_synth(), "s1", "dev", **_Q)
    shuffled = dict(reversed(list(_synth().items())))
    b, _ = PS.select_states(shuffled, "s1", "dev", **_Q)
    assert _ids(a) == _ids(b)


def test_selection_is_invariant_under_row_order_within_a_deal():
    base = _synth()
    rev = {k: list(reversed(v)) for k, v in base.items()}
    a, _ = PS.select_states(base, "s1", "dev", **_Q)
    b, _ = PS.select_states(rev, "s1", "dev", **_Q)
    assert _ids(a) == _ids(b)


def test_duplicate_eligible_rows_do_not_change_selection():
    base = _synth()
    dup = {k: v + list(v) for k, v in base.items()}
    a, _ = PS.select_states(base, "s1", "dev", **_Q)
    b, _ = PS.select_states(dup, "s1", "dev", **_Q)
    assert _ids(a) == _ids(b)


def test_the_salt_actually_changes_what_is_selected():
    """Guards against the priority being constant, which would make every
    invariance test above pass vacuously."""
    a, _ = PS.select_states(_synth(), "salt-A", "dev", **_Q)
    b, _ = PS.select_states(_synth(), "salt-B", "dev", **_Q)
    assert _ids(a) != _ids(b)


def test_side_changes_selection_so_DEV_and_CALIB_are_not_twins():
    a, _ = PS.select_states(_synth(), "s1", "dev", **_Q)
    b, _ = PS.select_states(_synth(), "s1", "calib", **_Q)
    assert _ids(a) != _ids(b)


def test_an_order_dependent_selector_FAILS_this_property():
    """Negative control reproducing the v4 defect.

    Without it, the invariance tests could pass against any selector and would
    not demonstrate that the property is the thing being enforced.
    """
    def v4_like(by_deal):
        picked, used = [], set()
        for band in ("early", "mid", "late"):
            need = 3
            for seed, rows in by_deal.items():       # insertion order
                if seed in used or need == 0:
                    continue
                for r in rows:
                    if r["band"] == band:
                        picked.append(r)
                        used.add(seed)
                        need -= 1
                        break
        return picked
    base = _synth()
    rev = dict(reversed(list(base.items())))
    assert _ids(v4_like(base)) != _ids(v4_like(rev))


def test_unsatisfiable_marginals_are_reported_not_silently_relaxed():
    q = dict(_Q)
    q["source_quota"] = {b: {"original": 3, "late": 0, "deep": 0}
                         for b in ("early", "mid", "late")}
    picked, unsatisfied = PS.select_states(_synth(6), "s1", "dev", **q)
    assert unsatisfied, "an impossible source quota must be reported"
