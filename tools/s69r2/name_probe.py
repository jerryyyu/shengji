#!/usr/bin/env python3
"""s69 name probe (this Mac): the harness's OWN served_env / variant_factory (exploit_duel_s61.py, verbatim) on the R48 tree, with fly.toml's
belief path mapped to a local S58 copy.  Prints the defender name (fly.toml SHENGJI_BOT = R48 as served) and the exploiter name (R48 at the
M27 expert budget: the nine --exploiter-env arguments of EX_ARGS), and checks on one built bot per side: the three fly.toml latency switches
on BOTH sides (single_candidate_fast off), the same S58 package and temperature on both, the defender's served knobs, the exploiter's
lifted knobs, and that the config diff is exactly the knobs the exploiter changes.  The launcher's check_names repeats these on the host.
Usage: FIND_GAPS_SERVER=<tree>/server FIND_GAPS_PKG=<smv3out> FIND_GAPS_PATH_MAP=/data/models/s58-e6-42444515.npz=<s58> \
       SHENGJI_FAST=1 python3 name_probe.py <harness>   (cwd <tree>/server)"""
import dataclasses
import importlib.util
import os
import sys

duel = sys.argv[1]
sys.path.insert(0, duel.rsplit("/", 1)[0])
spec = importlib.util.spec_from_file_location("exploit_duel_s61", duel)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
R48 = "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a"
S58_SHA = "424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e"
EX_ARGS = ["SHENGJI_PV_WORLDS=256", "SHENGJI_PV_CANDIDATES=32", "SHENGJI_PV_EXACT_DEEP_CARDS=8", "SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS=8",
           "SHENGJI_PV_EXACT_LEAD_MAX_SECONDS=9.0", "SHENGJI_PV_EXACT_DEEP_MAX_NODES=200000000", "SHENGJI_PV_EXACT_FOLLOW_MAX_NODES=200000000",
           "SHENGJI_PV_SERVING_BUDGET_SECONDS=60", "SHENGJI_PV_LEAF_GREEDY_DEADLINE="]
assert m.R45 == R48, m.R45
LAT = ("encode_prefix_cache", "leaf_greedy_stream", "encode_batch_fast", "single_candidate_fast")
assert all(os.environ.get(k) == "1" for k in ("SHENGJI_PV_ENCODE_PREFIX_CACHE", "SHENGJI_PV_LEAF_GREEDY_STREAM", "SHENGJI_PV_ENCODE_BATCH_FAST"))
assert not os.environ.get("SHENGJI_PV_SINGLE_CANDIDATE_FAST")
cfg = lambda b: dataclasses.asdict(b.config)
KNOBS = ("worlds", "candidates", "exact_deep_cards", "exact_follow_max_cards", "exact_lead_max_seconds", "exact_deep_max_nodes",
         "exact_follow_max_nodes", "serving_budget_seconds", "leaf_greedy_deadline_ms")
KEEP = ("bury_arm", "bury_serving_budget_seconds")
dn, dmake = m.variant_factory(())
db = dmake(7)
en, emake = m.variant_factory(m._parse_env(EX_ARGS))
eb = emake(7)
for side, b in (("defender", db), ("exploiter", eb)):
    print(side, "knobs", {k: cfg(b).get(k) for k in KNOBS}, "| attrs", {k: getattr(b, k, None) for k in KNOBS + KEEP},
          "| switches", [getattr(b, a, False) for a in LAT], "| belief", b.belief_model.package_sha256[:8], b.belief_model.temperature,
          "| class", type(b).__name__)
cdiff = sorted(x for x in set(cfg(db)) | set(cfg(eb)) if cfg(db).get(x) != cfg(eb).get(x))
print("defender", dn)
print("exploiter", en)
print("config diff", cdiff)
assert dn == R48 and en != dn
assert [getattr(b, a, False) for b in (db, eb) for a in LAT] == [True, True, True, False] * 2
assert db.belief_model.package_sha256 == eb.belief_model.package_sha256 == S58_SHA and db.belief_model.temperature == eb.belief_model.temperature
assert [getattr(eb, a, None) for a in KEEP] == [getattr(db, a, None) for a in KEEP] == ["hybrid", 2.0]
print("ok")
