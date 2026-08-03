import sys
sys.path.insert(0, ".")
from shengji.ai.env import evaluate
from shengji.ai.smart import SmartBot
from shengji.ai.mcbot import MCBot

job = sys.argv[1]
if job == "pairvoid_sampler":
    # queued sampler upgrade: never deal a pair into a PROVEN pair-void seat
    class PVSample(MCBot):
        PAIR_VOID_SAMPLING = True
    r = evaluate(PVSample(seed=1), MCBot(seed=2), n_games=120, seed=0)
elif job == "tempo_seek_v2":
    class T(SmartBot):
        TEMPO_SEEK = True
    r = evaluate(T(), SmartBot(), n_games=200, seed=0)
elif job == "size_first_mc":     # biggest-combo-first at MC level (tied at heuristic level)
    class S(MCBot):
        SIZE_FIRST = True
    r = evaluate(S(seed=1), MCBot(seed=2), n_games=120, seed=0)
print(f"RESULT {job}: {r['wins_a']}-{r['wins_b']} ({100*r['wins_a']/r['games']:.0f}%)", flush=True)
