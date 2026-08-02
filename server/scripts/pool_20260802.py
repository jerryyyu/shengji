"""Elo pool, 2026-08-02: core round-robin + dated-generation anchor pairings.

Core (full round-robin): heuristic, smart, mc (wide ballot), rl-v5,
rl-v6, rl-v6.1-ep1 [+ mc-vleaf if it gated — pass --vleaf].
Generational entrants (anchor pairings vs mc/smart/heuristic only —
Bradley-Terry needs a connected graph, not a full round-robin):
smart-20260801, mc-20260802am, mc-20260801.

Nets need: SHENGJI_RL_CKPT ignored — checkpoints are hardcoded below.
Run:  uv run python scripts/pool_20260802.py [n_seeds] [--vleaf]
"""

import sys

sys.path.insert(0, ".")
from shengji.ai.registry import REGISTRY  # noqa: E402
from shengji.ai.tournament import fit_elo, play_pairing  # noqa: E402


def make_rl(ckpt):
    def f():
        from shengji.rl.torch_policy import RLBot
        return RLBot(ckpt)
    return f


def make_vleaf():
    from shengji.rl.torch_policy import MCValueLeaf
    return MCValueLeaf(ckpt="ckpt_distill_v6.pt")


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60
    factories = {
        "heuristic": REGISTRY["heuristic"],
        "smart": REGISTRY["smart"],
        "mc": REGISTRY["mc"],
        "rl-v5": make_rl("ckpt_distill_full.pt"),
        "rl-v6": make_rl("ckpt_distill_v6.pt"),
        "rl-v6.1": make_rl("snapshots_v61/ep01.pt"),
    }
    if "--vleaf" in sys.argv:
        factories["mc-vleaf"] = make_vleaf
    core = list(factories)
    for g in ["smart-20260801", "mc-20260802am", "mc-20260801"]:
        factories[g] = REGISTRY[g]
    names = list(factories)
    anchors = ["heuristic", "smart", "mc"]  # LIST: set order is
    # hash-randomized PER PROCESS -> chunked workers disagreed on pairing
    # indices (2026-08-02: one pairing ran 3x, two never ran)

    pairs = [(i, j) for i in range(len(core)) for j in range(i + 1, len(core))]
    for gi in range(len(core), len(names)):
        pairs += [(names.index(a), gi) for a in anchors]

    # --chunk k/n: run only every n-th pairing starting at k, emitting
    # merge-ready lines — lets N worker processes (or machines) split the
    # pool; merge with --merge <files...>.
    chunk = next((a for a in sys.argv if a.startswith("--chunk")), None)
    if chunk:
        k, n = map(int, chunk.split("=")[1].split("/"))
        pairs = pairs[k::n]

    if "--merge" in sys.argv:
        wins: dict[tuple[int, int], int] = {}
        idx = {nm: i for i, nm in enumerate(names)}
        for path in sys.argv[sys.argv.index("--merge") + 1:]:
            for line in open(path):
                if line.startswith("PAIR "):
                    _, a, b, wa, wb = line.split()
                    wins[(idx[a], idx[b])] = wins.get((idx[a], idx[b]), 0) + int(wa)
                    wins[(idx[b], idx[a])] = wins.get((idx[b], idx[a]), 0) + int(wb)
        elo = fit_elo(names, wins)
        print("\nElo ratings (round-level, heuristic = 1000):")
        for name, r in sorted(elo.items(), key=lambda kv: -kv[1]):
            print(f"  {name:16s} {r:7.0f}")
        return

    wins = {}
    for i, j in pairs:
        wa, wb = play_pairing(factories[names[i]], factories[names[j]],
                              n_seeds, seed0=0)
        wins[(i, j)], wins[(j, i)] = wa, wb
        print(f"PAIR {names[i]} {names[j]} {wa} {wb}", flush=True)

    if not chunk:
        elo = fit_elo(names, wins)
        print("\nElo ratings (round-level, heuristic = 1000):")
        for name, r in sorted(elo.items(), key=lambda kv: -kv[1]):
            print(f"  {name:16s} {r:7.0f}")


if __name__ == "__main__":
    main()
