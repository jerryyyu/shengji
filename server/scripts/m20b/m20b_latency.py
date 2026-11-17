#!/usr/bin/env python3
"""M20b latency (PREDECLARE.md): one 128-row batch, NumPy, one thread, this Mac.
served = the served value's `probabilities` (trunk + head); added = the add-on head's NumPy forward on [h, features] for the
same rows; per decision: the plausibility features of 64 worlds from the proposal.  Also a torch-vs-NumPy parity check.

  OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 m20b_latency.py ROOT ARM EPOCH
"""
import json, sys, time
from pathlib import Path

import numpy as np

root, arm, ep = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.argv = [sys.argv[0], str(root / 'lat_tmp'), '--store', '/Users/jerryyu/.cache/codex-y-100k-rounds-expand/corpus',
            '--clusters', str(root / 'select_clusters.txt'), '--salt', 'm20b-lat', '--k', '0', '--limit', '1']
import torch
torch.set_num_threads(1)
import m20b_train as MT
from shengji.ai.cwv_numpy import _gelu_exact

# one real decision through the generator's path: bot, proposal, worlds, leaves
g = {}
exec(compile(open(Path(__file__).resolve().parent / 'm20b_gen.py').read().split('n_dec = 0')[0], 'gen', 'exec'), g)
bot, ev, plaus, counts = g['bot'], g['ev'], g['plaus'], g['counts']
from shengji.harvest.rebuild import state_for_record
from shengji.ai.cwv_policy import afterstate
from shengji.ai.refusal import RefusalLedger
cl = int((root / 'select_clusters.txt').read_text().split()[0])
recs = [json.loads(l) for l in open(Path('/Users/jerryyu/.cache/codex-y-100k-rounds-expand/corpus/shards') / f'cluster-{cl:06d}.jsonl')]
rec = next(r for r in recs if r['decision_kind'] == 'play' and r['ply'] >= 4)
root_s = state_for_record(rec); seat = int(rec['seat'])
bot._refusals = RefusalLedger(); bot.sampler.rng.seed(1)
g['_CAP'].clear(); worlds, _ = bot._worlds(root_s, seat); prop = g['_CAP']['p']
leaves = [afterstate(root_s, seat, h, b, list(rec['action']), finish_trick=True) for h, b in worlds]
rows = [ev.encoder(l, seat) for l in leaves] * 2
rows = rows[:128]
pub = np.stack([r.public for r in rows]); wor = np.stack([r.world for r in rows]); per = np.stack([r.perspective for r in rows])


def tmed(f, n=300):
    f()
    ts = []
    for _ in range(n):
        t = time.perf_counter(); f(); ts.append(time.perf_counter() - t)
    return float(np.median(ts))


served = tmed(lambda: ev.probabilities_stacked(pub, wor, per))
plaus_dec = tmed(lambda: [plaus(prop, counts(seat, h, b, prop.kitty_hidden)) for h, b in worlds], 100)

# the add-on head in NumPy
nz = np.load(root / 'train' / arm / 'norm.npz'); mu, sd = nz['mu'], nz['sd']
net = MT.build_net(165 + len(mu)); net.load_state_dict(torch.load(root / 'train' / arm / f'e{ep}.pt'))
Wt = [(l.weight.detach().numpy().astype(np.float64), l.bias.detach().numpy().astype(np.float64)) for l in net if isinstance(l, torch.nn.Linear)]
x = np.concatenate((pub, wor.reshape(128, -1), per), axis=1).astype(np.float64)
H = ev.model._trunk(x)
F = np.random.default_rng(1).normal(size=(128, len(mu))) * sd + mu


def head(H, F):
    z = np.concatenate([H, (F - mu) / sd], 1)
    z = _gelu_exact(z @ Wt[0][0].T + Wt[0][1]); z = _gelu_exact(z @ Wt[1][0].T + Wt[1][1])
    return z @ Wt[2][0].T + Wt[2][1]


added = tmed(lambda: head(H, F))
with torch.no_grad():
    tz = net(torch.from_numpy(np.concatenate([H, (F - mu) / sd], 1)).float()).numpy()
parity = float(np.abs(tz - head(H, F)).max())
out = dict(arm=arm, ep=ep, served_128_ms=served * 1e3, head_128_ms=added * 1e3, head_ratio=added / served,
           plaus_64_worlds_ms=plaus_dec * 1e3, parity_max_abs_logit=parity, threads=1)
print(json.dumps(out))
