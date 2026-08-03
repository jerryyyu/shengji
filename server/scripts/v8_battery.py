"""v8 battery: snapshot probes first, then anchors on the best."""
import sys
sys.path.insert(0, ".")
from shengji.ai.tournament import play_pairing
from shengji.ai.registry import REGISTRY
from shengji.rl.torch_policy import RLBot

snap_dir = sys.argv[1]          # e.g. snapshots_v8a
eps = sys.argv[2].split(",")    # e.g. ep00,ep01,ep02,ep03
best, best_rate = None, -1
for ep in eps:                  # probe: round-level vs smart, fixed seeds
    ck = f"{snap_dir}/{ep}.pt"
    wa, wb = play_pairing(lambda: RLBot(ck), REGISTRY["smart"], 60, 1000)
    rate = wa / (wa + wb)
    print(f"PROBE {snap_dir}/{ep} vs smart: {wa}-{wb} ({100*rate:.0f}%)", flush=True)
    if rate > best_rate:
        best, best_rate = ck, rate
print(f"BEST {best} at {100*best_rate:.0f}%", flush=True)
for opp in ["smart", "mc"]:     # anchors = the strength claim
    wa, wb = play_pairing(lambda: RLBot(best), REGISTRY[opp], 60, 0)
    print(f"ANCHOR {best} vs {opp}: {wa}-{wb} ({100*wa/(wa+wb):.0f}%)", flush=True)
