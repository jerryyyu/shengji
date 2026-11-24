"""Construct the SZ2-R screen sides through the fleet adapter; no deals are played."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

FLEET = Path.home() / "fleet"
S159 = FLEET / "claude-s159-rt4"
TREE = Path.home() / "Projects/shengji-wt/codex-sz2r-deploy-3e00a55a"
HEAD = "3e00a55a7a38e5a135809f601c9b47fb315fa725"
M2 = FLEET / "codex-sz2-export-v1/M" / (
    "74015553d61ccfd7d66c75474866c8d49124bf8f02cd3d805011336e71157962-"
    "69f181a3a9e838e32c9cbc9b695e7629479ca056e06274d9246abdfbbb139369-encode4")
KIT = {
    "rt3fs_adapter.py": "51ef8b5607260a49a4a7e87f04496d0bb07e059a136f159e0408dc130e7355bd",
    "rt3fs_probe.py": "87e954a28554a488673d3475c6a0d5281c1233deb6d92e1918021ef7f3f71404",
    "exploit_duel_s61.py": "813e6ed64fbb80d81d7ec064096ec6846ed9ca47e90ad2c6632d9451e2c8bd1d",
    "hypotheses.py": "4365a15d6c868263eaa64fca0038168342f2ebd96689da36f46be4e2082e49ce",
}
M2_HASHES = {
    "UNIFIED": "9cdf926415651a2cd298264ea5126f8aa6de989bbc2b3ae157463e2c57afaed1",
    "BELIEF": "9e63cd623aefe26b86eadf9f3dc00baee09fd69d8e0ed18dc971e7b66dff860f",
}


def verify(path, expected):
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"digest mismatch: {path}")


def build():
    def git(*args):
        return subprocess.check_output(["git", "-C", TREE, *args], text=True).strip()

    if git("rev-parse", "HEAD") != HEAD or git("status", "--porcelain"):
        raise ValueError("expected clean deployed R55 source")
    fly = TREE / "fly.toml"
    verify(fly, "aa3048fba371132c02704d629f0f2dbf3590458112f89058329b51b7bf4e5f29")
    settings = tomllib.loads(fly.read_text())["env"]
    kit = S159 / "kit"
    for name, digest in KIT.items():
        verify(kit / name, digest)
    mapping = {}
    for key in ("", "_PRIOR", "_UNIFIED", "_BELIEF"):
        prefix = f"SHENGJI_PV{key}"
        remote = settings[prefix + "_CKPT"]
        directory = "cand" if key in ("_UNIFIED", "_BELIEF") else "models"
        path = S159 / "inputs" / directory / Path(remote).name
        verify(path, settings[prefix + "_SHA256"])
        mapping[remote] = str(path)
    defender, challenger = {}, {}
    for kind, file in (("UNIFIED", "cand.npz"), ("BELIEF", "cand-belief.npz")):
        prefix = f"SHENGJI_PV_{kind}"
        path = M2 / file
        verify(path, M2_HASHES[kind])
        defender[prefix + "_CKPT"] = mapping[settings[prefix + "_CKPT"]]
        defender[prefix + "_SHA256"] = settings[prefix + "_SHA256"]
        challenger[prefix + "_CKPT"] = str(path)
        challenger[prefix + "_SHA256"] = M2_HASHES[kind]
    env = dict(HOME=str(Path.home()), PATH=os.defpath, PYTHONPATH=str(TREE / "server"),
               FIND_GAPS_SERVER=str(TREE / "server"), SHENGJI_FAST="1",
               FIND_GAPS_PKG=mapping[settings["SHENGJI_PV_CKPT"]],
               FIND_GAPS_PATH_MAP=";".join(f"{k}={v}" for k, v in mapping.items()))
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    words = [sorted(f"{k}={v}" for k, v in side.items()) for side in (defender, challenger)]
    probe = subprocess.check_output(
        [sys.executable, "-B", kit / "rt3fs_probe.py", kit / "rt3fs_adapter.py", settings["SHENGJI_BOT"],
         *[",".join(side) for side in words]], cwd=TREE / "server", env=env, text=True)
    defense, attack = json.loads(probe.strip().splitlines()[-1])
    expected_attack = (
        "pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-"
        "la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r9992f094-bury-"
        "hybrid-bwv-bbw-197b1a928c58-sc8-ushare9cdf9264-uvalue9cdf9264-ureply9cdf9264-ufast"
    )
    if defense != settings["SHENGJI_BOT"] or attack != expected_attack:
        raise ValueError("constructed side differs from the Fly comparison")
    return dict(arm="SZ2-R", tree=str(TREE), head=HEAD, adapter=str(kit / "rt3fs_adapter.py"),
                environment=env, defender_name=defense, exploiter_name=attack,
                defender_words=words[0], exploiter_words=words[1], round_plan="r2",
                seed0=2668000000, deals=3920, minimum_mean=0.005, minimum_lb80_exclusive=0)


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True, indent=2))
