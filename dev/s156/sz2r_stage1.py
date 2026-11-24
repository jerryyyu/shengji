"""Validity and paired scoring for the SZ2-R supervisor after it verifies the seal."""
import importlib.util
from pathlib import Path

from sz2r_producer import run_inputs
from sz2r_recipe import S159, verify


def load_validator():
    kit = S159 / "kit"
    path = kit / "s159_read.py"
    verify(path, "1f3f8ed15fc9468eb5345ab9c49e63a54f4077998ae30ceddcf70cd8d63a8eca")
    verify(kit / "ut_read.py", "759eb118fac4c2c070bdda32ed07d8241643b367009cc3c6595a0533cdc3b4d0")
    spec = importlib.util.spec_from_file_location("s159_read", path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def paired_levels(rows, seed0, deals, bootstrap):
    values = [(rows[seed, 0]["ex_levels"] + rows[seed, 1]["ex_levels"]) / 2
              for seed in range(seed0, seed0 + deals)]
    return bootstrap(values)


def stage1(recipe, mode, lane, *, verified_rows_dir=None):
    if mode not in ("pilot", "screen"):
        raise ValueError("only pilot and screen rows enter stage one")
    seed0, deals, root = run_inputs(recipe, mode, Path(lane))
    if recipe["minimum_mean"] != 0.005 or recipe["minimum_lb80_exclusive"] != 0:
        raise ValueError("stage-one threshold drift")
    arm = dict(seed0=seed0, deals=deals, out_root=str(root if verified_rows_dir is None else verified_rows_dir))
    for role, prefix in (("defender", "def"), ("exploiter", "ex")):
        words = dict(word.split("=", 1) for word in recipe[role + "_words"])
        arm[role + "_name"] = recipe[role + "_name"]
        arm[prefix + "_package_sha256"] = words["SHENGJI_PV_UNIFIED_SHA256"]
    reader = load_validator()
    validity = reader.R.load_validity(recipe["tree"])
    valid, checks, counts, rows, unified = reader.validate(arm, validity)
    report = dict(mode=mode, seed0=seed0, deals=deals, checks=checks, counts=counts,
                  unified=unified, validity="VALID" if valid else "DEV_INVALID")
    if valid and mode == "screen":
        levels = paired_levels(rows, seed0, deals, reader.R.boot)
        report["levels"] = levels
        report["decision"] = ("PASS" if levels["mean"] >= recipe["minimum_mean"]
                              and levels["lb80"] > recipe["minimum_lb80_exclusive"] else "FAIL")
    return report
