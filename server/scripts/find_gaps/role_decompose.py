"""Decompose an arm's paired level margin by banker transition vs the identity
arm on the same (deal, mirror): (would-have-been role, actual role).  DEV."""
import json
import statistics as st
import sys
from collections import defaultdict


def load(path):
    return {(r["seed"], r["mirror"]): r for r in map(json.loads, open(path))}


def main(base_path, arm_path):
    base, arm = load(base_path), load(arm_path)
    cat = defaultdict(list)
    for k, r in arm.items():
        if k not in base:
            continue
        b = base[k]
        brole = "banker" if b["banker"] % 2 == r["ex_team"] else "attacker"
        cat[(brole, r["ex_role"])].append((r["ex_levels"], b["ex_levels"], r["trump"] == b["trump"]))
    n = sum(len(v) for v in cat.values())
    print(f"mirror-rounds {n}")
    for k, v in sorted(cat.items()):
        d = [a - b for a, b, _ in v]
        print(f"  base {k[0]:8s} -> arm {k[1]:8s} n={len(v):5d} share {len(v)/n:.3f}"
              f"  arm lv {st.mean(a for a, _, _ in v):+.3f}  base lv {st.mean(b for _, b, _ in v):+.3f}"
              f"  delta {st.mean(d):+.3f}  contrib/round {sum(d)/n:+.4f}  same-trump {sum(s for *_, s in v)/len(v):.2f}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
