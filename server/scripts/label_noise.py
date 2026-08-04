"""Label-noise ceiling diagnostic (Codex's #1 recommendation).

Question: is the teacher's own signal stable enough for a student to beat
it? Freeze real decision states; evaluate each with K independent N=30
teacher seeds plus one high-N reference. If a SINGLE teacher sample
agrees with the high-N reference no more often than our student does,
then no amount of student capacity can recover the missing signal — the
ceiling is the labels, not the model.

Usage: uv run python scripts/label_noise.py [n_states] [K] [N_ref]
"""
import random
import sys
from collections import Counter

sys.path.insert(0, ".")
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.rl.torch_policy import RLBot  # noqa: E402

n_states = int(sys.argv[1]) if len(sys.argv) > 1 else 120
K = int(sys.argv[2]) if len(sys.argv) > 2 else 8
N_ref = int(sys.argv[3]) if len(sys.argv) > 3 else 200

student = RLBot("snapshots_v9warm16/ep08.pt")
states = []
rng = random.Random(4242)
probe = MCBot(seed=1)
g = Game(random.Random(999))
rnd = g.start_round()
while len(states) < n_states:
    if rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, probe.decide_bury(rnd, rnd.banker))
        elif rnd.phase == "round_end":
            g.finish_round(); rnd = g.start_round()
        continue
    seat = rnd.turn
    cands = probe._candidates(rnd, seat)
    if len(cands) > 1 and rng.random() < 0.35:
        import copy
        states.append((copy.deepcopy(rnd), seat, cands))
        print(f"  collected {len(states)}/{n_states}", flush=True)
    rnd.play(seat, probe.decide_play(rnd, seat))

self_agree = ref_agree = stu_agree = 0
margin_flips = 0
for i, (st, seat, cands) in enumerate(states):
    picks = []
    for k in range(K):
        b = MCBot(seed=1000 + k)
        picks.append(tuple(sorted(b.decide_play(st, seat))))
    ref_bot = MCBot(seed=7)
    ref_bot.N_DETERMINIZATIONS = N_ref
    ref = tuple(sorted(ref_bot.decide_play(st, seat)))
    stu = tuple(sorted(student.decide_play(st, seat)))
    mode, cnt = Counter(picks).most_common(1)[0]
    self_agree += cnt / K                      # teacher self-consistency
    ref_agree += sum(p == ref for p in picks) / K   # 1 teacher sample vs ref
    stu_agree += (stu == ref)                  # student vs ref
    if len(set(picks)) > 1:
        margin_flips += 1
    if (i + 1) % 20 == 0:
        print(f"PROGRESS {i+1}/{len(states)}: teacher-self {100*self_agree/(i+1):.0f}% "
              f"teacher-vs-ref {100*ref_agree/(i+1):.0f}% "
              f"student-vs-ref {100*stu_agree/(i+1):.0f}%", flush=True)

n = len(states)
print(f"\nRESULT label-noise ceiling over {n} states (K={K} teacher seeds, "
      f"ref N={N_ref}):", flush=True)
print(f"  teacher self-agreement (modal share): {100*self_agree/n:.1f}%")
print(f"  ONE teacher sample vs high-N reference: {100*ref_agree/n:.1f}%")
print(f"  student (v9warm16-ep08) vs reference:   {100*stu_agree/n:.1f}%")
print(f"  states where teacher seeds disagreed:   {100*margin_flips/n:.1f}%")
print("  => if student >= one-teacher-sample, the LABELS are the ceiling.")
