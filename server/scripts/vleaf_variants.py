"""vleaf with different value heads + pool anchors for vleaf."""
import sys
sys.path.insert(0, ".")
from shengji.ai.env import evaluate
from shengji.ai.tournament import play_pairing
from shengji.ai.registry import REGISTRY
from shengji.ai.mcbot import MCBot
from shengji.rl.torch_policy import MCValueLeaf

job = sys.argv[1]
if job == "v8a_head":     # does the new data's VALUE head beat v7w's?
    r = evaluate(MCValueLeaf(seed=51, ckpt="snapshots_v8a/ep03.pt"),
                 MCBot(seed=52), n_games=120, seed=0)
    print(f"RESULT vleaf(v8a) vs mc [same seeds as block1]: "
          f"{r['wins_a']}-{r['wins_b']} ({100*r['wins_a']/r['games']:.0f}%)",
          flush=True)
elif job == "pool_anchors":   # place vleaf(v7w) on the Elo scale
    def vl():
        return MCValueLeaf(ckpt="snapshots_v7w/ep02.pt")
    for opp in ["mc", "smart", "heuristic"]:
        wa, wb = play_pairing(vl, REGISTRY[opp], 60, 0)
        print(f"PAIR mc-vleaf {opp} {wa} {wb}", flush=True)
