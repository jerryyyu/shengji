"""The S68 DEV lane constants, one source for make_s68dev.py, make_s68dev_read.py and the packet tests: the candidate tree, the output
root, the pins the generators assert, the stops and the two arms."""
HEAD = "8b6ead101108fac9aaf9a7c81026fd04f89e6bc7"
R = f"/root/claude-s68-src-{HEAD[:8]}"
OUT = "/root/vol-dev-claude-s68dev-r48-20261026"
FLY_SHA = "ff64b52fb7ac81ae13158f6d3e03db2308338c1c961cd9e771b7679d62bf0a6e"   # git show <HEAD>:fly.toml | sha256sum
CAND_SHA = "90e53155504175200d008d239bd668549e66e9ce6f7881943c139ff1d8484b8f"  # git show <HEAD>:server/shengji/eval/singleton_challenger.py (= 39d514cc's)
ADAPTER_SHA = "80e0e7f8b8e59612251858b7af22a61907141f5992cef0b6cdf0732024082477"
KILL, BACK = 30000, 30010
R48 = "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a"
ARMS = {   # arm: seed0, exploiter name (name_probe.out), --exploiter-env words
    "b": (243660910, "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-bwc-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-red111e2f-bury-hybrid-bwv-9125072c7686-sc8",
          "S66_EXPLOITER=sc8 SHENGJI_PV_BELIEF_CAPACITY=1"),
    "a": (244060910, "pv-search-491ee4bf-w96-k12-div-rc-whl-whd-bw-bwc-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd1000-ed7-xf7-xfcompactlevel-r99a6f365-bury-hybrid-bwv-533c84747dc9-sc8",
          "S66_EXPLOITER=sc8 SHENGJI_PV_BELIEF_CAPACITY=1 SHENGJI_PV_WORLDS=96 SHENGJI_PV_CANDIDATES=12 SHENGJI_PV_SERVING_BUDGET_SECONDS=1.5 SHENGJI_PV_LEAF_GREEDY_DEADLINE=1 SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS=1"),
}
