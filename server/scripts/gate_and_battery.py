"""Air job: wide-follow gate (seed-blocked) + v7w battery. Durable prints."""
import sys
sys.path.insert(0, ".")
from shengji.ai.env import evaluate
from shengji.ai.tournament import play_pairing
from shengji.ai.registry import REGISTRY
from shengji.ai.mcbot import MCBot
from shengji.rl.torch_policy import RLBot

class WF(MCBot):
    WIDE_FOLLOW_BALLOT = True

mode = sys.argv[1]
if mode == "wf":  # one seed block: wf <block 0-2>
    b = int(sys.argv[2])
    r = evaluate(WF(seed=31), MCBot(seed=32), n_games=40, seed=1000 + 40 * b)
    print(f"WFBLOCK {b} {r['wins_a']} {r['wins_b']}", flush=True)
elif mode == "battery":
    for ep in ["ep00", "ep01", "ep02", "ep03"]:
        ck = f"snapshots_v7w/{ep}.pt"
        wa, wb = play_pairing(lambda: RLBot(ck), REGISTRY["smart"], 60, 1000)
        r = evaluate(RLBot(ck), RLBot("ckpt_distill_v6.pt"), n_games=200, seed=0)
        print(f"V7W {ep} probe {100*wa/(wa+wb):.0f}% duel {r['wins_a']}-{r['wins_b']}",
              flush=True)
