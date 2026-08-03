"""Expert-research heuristics #2 (kitty policy) and #4 (tree-planting)."""
import sys
sys.path.insert(0, ".")
from shengji.ai.env import evaluate
from shengji.ai.smart import SmartBot

job = sys.argv[1]
cls = {"kitty": type("K", (SmartBot,), {"KITTY_POINT_POLICY": True}),
       "tree": type("T", (SmartBot,), {"TREE_PLANTING": True}),
       "both": type("B", (SmartBot,), {"KITTY_POINT_POLICY": True,
                                       "TREE_PLANTING": True})}[job]
r = evaluate(cls(), SmartBot(), n_games=200, seed=0)
print(f"RESULT {job}: {r['wins_a']}-{r['wins_b']} "
      f"({100*r['wins_a']/r['games']:.0f}%)", flush=True)
