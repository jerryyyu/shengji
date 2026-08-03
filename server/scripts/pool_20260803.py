"""Elo pool refresh: current mc (DECLARER_PIN + new throw rule) vs the net line."""
import sys
sys.path.insert(0, ".")
from shengji.ai.tournament import fit_elo, play_pairing
from shengji.ai.registry import REGISTRY
from shengji.rl.torch_policy import RLBot

def rl(ck):
    return lambda: RLBot(ck)

F = {"heuristic": REGISTRY["heuristic"], "smart": REGISTRY["smart"],
     "mc": REGISTRY["mc"], "rl-v7w": rl("snapshots_v7w/ep02.pt"),
     "rl-v8a": rl("snapshots_v8a/ep03.pt")}
names = list(F)
pairs = [(i, j) for i in range(len(names)) for j in range(i + 1, len(names))]
chunk = next((a for a in sys.argv if a.startswith("--chunk")), None)
if chunk:
    k, n = map(int, chunk.split("=")[1].split("/"))
    pairs = pairs[k::n]
for i, j in pairs:
    wa, wb = play_pairing(F[names[i]], F[names[j]], 60, 0)
    print(f"PAIR {names[i]} {names[j]} {wa} {wb}", flush=True)
