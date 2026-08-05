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


@pytest.mark.parametrize("name", ["pilot_dev512.v6.json",
                                  "pilot_calib512.v6.json"])
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


@pytest.mark.parametrize("name", ["pilot_dev512.v6.json", "pilot_calib512.v6.json"])
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
    for name in ("pilot_dev512.v6.json", "pilot_calib512.v6.json"):
        d = _load(name)
        for band, counts in d["roles_by_band"].items():
            assert "?" not in counts, f"{name}/{band}: role never carried"
            assert set(counts) == {"attacker", "defender"}, counts
            lo, hi = min(counts.values()), max(counts.values())
            assert hi - lo <= 1, f"{name}/{band} role imbalance {counts}"


def test_dev_and_calib_are_deal_disjoint():
    d, c = _load("pilot_dev512.v6.json"), _load("pilot_calib512.v6.json")
    kd = {(s["source"], s["seed"]) for s in d["states"]}
    kc = {(s["source"], s["seed"]) for s in c["states"]}
    assert not (kd & kc), f"{len(kd & kc)} deals appear in BOTH gate sets"
    assert d["salt"] != c["salt"], "the two sets must use distinct salts"


def test_source_and_split_digests_are_recorded_and_current():
    """A frozen set whose inputs cannot be identified is not reproducible."""
    for name in ("pilot_dev512.v6.json", "pilot_calib512.v6.json"):
        d = _load(name)
        for src, meta in d["sources"].items():
            assert meta.get("corpus_sha256_16"), f"{name}/{src}: no corpus digest"
            assert meta.get("split_sha256_16"), f"{name}/{src}: no split digest"
            # Compare BOTH against live bytes. The previous version asserted
            # the split digest was merely PRESENT and only ever compared the
            # corpus, so a split file edited after the freeze passed (Codex).
            for kind, key in (("corpus", "corpus_sha256_16"),
                              ("split", "split_sha256_16")):
                path = os.path.join(ART, os.path.basename(meta[kind]))
                assert os.path.exists(path), f"{name}/{src}: {kind} missing"
                assert PS.digest(path)[:16] == meta[key], \
                    f"{name}/{src}: {kind} changed since the freeze"


def test_freezer_refuses_a_dirty_tree_and_an_existing_path():
    src = open(PS.__file__).read()
    assert "REFUSING: the tree is dirty" in src
    assert "REFUSING: {args.out} exists" in src or "exists. A frozen pilot set" in src
    # The real property is that no override ARGUMENT exists — a docstring
    # explaining why the flag was removed is desirable, and grepping for the
    # bare string flagged that prose instead of the behaviour.
    assert 'add_argument("--force"' not in src, \
        "an existing frozen path must be unconditionally non-overwritable"


@pytest.mark.parametrize("art", ["pilot_dev512.v6.json",
                                 "pilot_calib512.v6.json"])
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


def test_superseded_sets_are_REJECTED_by_the_current_contract():
    """v3/v4/v5 are retained ONLY as named negative controls."""
    for art in ("pilot_dev512.v3.json", "pilot_dev512.v4.json"):
        d = _load(art)
        assert PS.check_contract(d["states"], d.get("requested", 512),
                                 d.get("replay_errors", 0)), \
            f"{art} must be rejected by the current contract"


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
    d = _load("pilot_dev512.v3.json")
    bad = PS.check_contract(d["states"], d.get("requested", 512),
                            d.get("replay_errors", 0))
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
    """Eligible rows across three sources, several per deal.

    CRITICAL: each deal carries TWO decisions in the SAME
    source/band/size/role cell, differing only in ply/seat. The earlier fixture
    had one row per cell, so a selector that collapsed a cell to its LAST row
    and tied on priority still looked order-independent. That blind spot let a
    real 52/512 DEV order dependence ship (Codex).
    """
    out = {}
    srcs = ["original", "late", "deep"]
    for i in range(n):
        rows = []
        for j, band in enumerate(("early", "mid", "late")):
            for k, size in enumerate(("small", "med", "wide")):
                for dup, ply in enumerate((4 + k, 12 + k)):
                    rows.append({
                        "seed": 1000 + i, "band": band,
                        "source": srcs[(i + j) % 3],
                        "role": ("attacker", "defender")[(i + k) % 2],
                        "stratum": f"{band}/x/{size}", "tricks": j,
                        "ply": ply, "seat": (i + dup) % 4})
        out[1000 + i] = rows
    return out


def _ids(picked):
    """FULL identity. Comparing only deal/stratum hid which decision won."""
    return [(p["source"], p["seed"], p["ply"], p["seat"], p["band"],
             PS.size_of(p), p.get("role")) for p in picked]


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


@pytest.mark.parametrize("name", ["pilot_dev512.v6.json",
                                  "pilot_calib512.v6.json"])
def test_v6_source_marginals_are_exact(name):
    """The marginal v4 lacked; asserted separately so it cannot regress."""
    d = _load(name)
    for band, wants in PS.SOURCE_QUOTA.items():
        have = {}
        for s in d["states"]:
            if s["band"] == band:
                have[s["source"]] = have.get(s["source"], 0) + 1
        for src, want in wants.items():
            assert have.get(src, 0) == want, \
                f"{name} {band}/{src}: {have.get(src, 0)} != {want}"


def test_v6_dev_and_calib_share_the_population_but_not_the_deals():
    """The property v4 broke: same structure, disjoint deals."""
    dev, cal = _load("pilot_dev512.v6.json"), _load("pilot_calib512.v6.json")
    for q in (PS.SIZE_QUOTA, PS.ROLE_QUOTA, PS.SOURCE_QUOTA):
        for band in q:
            f = lambda d, k: sum(1 for s in d["states"]
                                 if s["band"] == band and s.get(k[0]) == k[1])
            for key in q[band]:
                field = ("source" if q is PS.SOURCE_QUOTA
                         else "role" if q is PS.ROLE_QUOTA else None)
                if field:
                    assert f(dev, (field, key)) == f(cal, (field, key))
    assert not ({s["seed"] for s in dev["states"]}
                & {s["seed"] for s in cal["states"]})


def test_cell_keyed_dedup_FAILS_exact_state_invariance():
    """Negative control reproducing the v5 defect precisely.

    v5 deduplicated with `seen[(band, size, role, source)] = row`, so when one
    deal held two decisions in a cell the LAST one encountered won, and
    priority omitted ply/seat so they tied. Reversing rows changed 52/512 DEV
    and 41/512 CALIB exact states, systematically favouring deeper forward
    states. Without this control the invariance tests could pass against a
    selector that still had the bug.
    """
    def v5_dedup(by_deal):
        out = {}
        for seed, rows in by_deal.items():
            seen = {}
            for r in rows:
                seen[(r["band"], PS.size_of(r), r.get("role"), r["source"])] = r
            out[seed] = list(seen.values())
        return out
    base = _synth()
    rev = {k: list(reversed(v)) for k, v in base.items()}
    a = _ids(sum(v5_dedup(base).values(), []))
    b = _ids(sum(v5_dedup(rev).values(), []))
    assert a != b, "the v5 cell-keyed dedup must be order-dependent"


def test_conflicting_metadata_for_one_exact_state_fails_closed():
    """One (source, seed, ply, seat) cannot be two different states."""
    base = _synth(4)
    first = next(iter(base))
    clash = dict(base[first][0])
    clash["band"] = "late" if clash["band"] != "late" else "early"
    base[first] = base[first] + [clash]
    picked, unsatisfied = PS.select_states(base, "s1", "dev", **_Q)
    assert picked == [] and any("non-identical duplicate" in u
                                for u in unsatisfied), unsatisfied


@pytest.mark.parametrize("art", ["pilot_dev512.v6.json",
                                 "pilot_calib512.v6.json"])
def test_v6_exact_state_identities_are_unique(art):
    """One decision per deal, identified by (source, seed, ply, seat).

    v5 could select two different decisions depending on traversal order; this
    asserts the published identity set is exactly 512 distinct states.
    """
    d = _load(art)
    idents = {(s["source"], s["seed"], s["ply"], s["seat"])
              for s in d["states"]}
    assert len(idents) == 512, f"{art}: {len(idents)} distinct identities"
    assert len({s["seed"] for s in d["states"]}) == 512


def test_duplicate_identity_differing_in_ANY_field_fails_closed():
    """The contract is byte/field-identical copies only.

    Checking a named subset (band/role/tricks/size) let a duplicate identity
    differing in `n_candidates` or `is_banker_seat` reach the last-row
    assignment, so row reversal selected the opposite payload with no
    violation raised (Codex). These fields are outside the marginals, which is
    exactly why a subset check missed them.
    """
    for field, a, b in (("n_candidates", 5, 9),
                        ("is_banker_seat", True, False)):
        base = _synth(4)
        first = next(iter(base))
        row = dict(base[first][0])
        row[field] = a
        twin = dict(row)
        twin[field] = b
        base[first] = [row, twin] + base[first][1:]
        picked, unsatisfied = PS.select_states(base, "s1", "dev", **_Q)
        assert picked == [], f"{field}: selection proceeded despite a conflict"
        assert any("non-identical duplicate" in u and field in u
                   for u in unsatisfied), (field, unsatisfied)


def test_identical_duplicate_rows_are_still_accepted():
    """Guards against the new check refusing legitimate exact copies."""
    base = _synth()
    first = next(iter(base))
    base[first] = [dict(base[first][0])] + base[first]
    picked, unsatisfied = PS.select_states(base, "s1", "dev", **_Q)
    assert not unsatisfied and picked, unsatisfied


def test_an_unsatisfiable_cell_REPORTS_instead_of_crashing():
    """Fail closed means a message, not a traceback.

    With fewer deals than the band quota the tightest cell has demand and no
    candidates; that path used to reach `cand[0]` and raise IndexError.
    """
    picked, unsatisfied = PS.select_states(_synth(6), "s1", "dev", **_Q)
    # Selection may partially fill before hitting the wall; what matters is
    # that it REPORTS the cell rather than raising, and that `main` refuses on
    # any non-empty `unsatisfied` so no short artifact is published.
    assert any("no eligible deal remains" in u for u in unsatisfied), \
        unsatisfied
    assert len(picked) < 512


def test_selection_is_invariant_under_source_grouping_order():
    """Codex listed source permutation explicitly; assert it directly.

    Verified faithfully through the real freezer too: with
    SHENGJI_SOURCES_ORDER set to two different permutations, the dry run
    reproduced the frozen v6 DEV set 512/512.
    """
    base = _synth()
    order = {"deep": 0, "late": 1, "original": 2}
    perm = {k: sorted(v, key=lambda r: order[r["source"]])
            for k, v in base.items()}
    a, _ = PS.select_states(base, "s1", "dev", **_Q)
    b, _ = PS.select_states(perm, "s1", "dev", **_Q)
    assert _ids(a) == _ids(b)
