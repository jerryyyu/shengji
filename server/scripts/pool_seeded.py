"""Elo pool under the SEEDED protocol (reproducible pairings).

The unseeded protocol produced non-reproducible pairings: mc-vleaf vs mc
read 70-50 on one run and 57-63 on a re-run. Every number here should now
reproduce exactly.
"""
import sys
sys.path.insert(0, ".")
from shengji.ai.tournament import fit_elo, play_pairing
from shengji.ai.registry import REGISTRY
from shengji.rl.torch_policy import MCValueLeaf, RLBot

def vleaf(ck):
    return lambda seed=None: MCValueLeaf(seed=seed, ckpt=ck)

def rl(ck):
    return lambda seed=None: RLBot(ck)

F = {"heuristic": REGISTRY["heuristic"], "smart": REGISTRY["smart"],
     "mc": REGISTRY["mc"],
     "mc-vleaf-v7w-ep02": vleaf("snapshots_v7w/ep02.pt"),
     "rl-v7w": rl("snapshots_v7w/ep02.pt"),
     "rl-v9warm": rl("snapshots_v9warm/ep05.pt")}
names = list(F)
pairs = [(i, j) for i in range(len(names)) for j in range(i + 1, len(names))]
chunk = next((a for a in sys.argv if a.startswith("--chunk")), None)
if chunk:
    k, n = map(int, chunk.split("=")[1].split("/"))
    pairs = pairs[k::n]
for i, j in pairs:
    wa, wb = play_pairing(F[names[i]], F[names[j]], 60, 0)
    print(f"PAIR {names[i]} {names[j]} {wa} {wb}", flush=True)
