"""FLYWHEEL TEST: does a value head trained on hybrid-teacher data make a
STRONGER hybrid than the head that generated that data?

v7w's head produced gen-v4; v9warm learned from gen-v4. If vleaf(v9warm)
beats vleaf(v7w)'s record vs mc, the loop turns: better hybrid -> better
data -> better head -> better hybrid.
"""
import sys
sys.path.insert(0, ".")
from shengji.ai.env import evaluate
from shengji.ai.mcbot import MCBot
from shengji.rl.torch_policy import MCValueLeaf

ck = sys.argv[1]
r = evaluate(MCValueLeaf(seed=61, ckpt=ck), MCBot(seed=62), n_games=120, seed=0)
print(f"RESULT vleaf({ck}) vs mc: {r['wins_a']}-{r['wins_b']} "
      f"({100*r['wins_a']/r['games']:.0f}%)  [v7w head on these seeds: 60%]",
      flush=True)
