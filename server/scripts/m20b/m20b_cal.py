#!/usr/bin/env python3
"""M20b amendment 1: low-capacity plausibility arms on the frozen served value (no per-round memorisation possible).

Per world w of a decision, with the served logits z_w (frozen), standardised world plausibility scalars f_w
(ll_q/copies, ll_p/copies, rel_q, z_q, z_p) and decision scalars d (entropy, top mass, copies/100, std_q/copies,
std_p/copies, cards left/25, lead, leaf-kind flag):
  RT  : p_w = softmax(z_w / T_w), log T_w = a . [f_w, d, 1]                          (14 parameters)
  RTW : RT, and the decision's mixture weights the worlds: m = sum_w softmax_w(b . [f_w, f_w * cards/25]) p_w
        (+10 parameters; the true-world row is a single world, so only T applies to it)
  RT0 : control, log T = a . [d, 1] (no world plausibility; 9 parameters)
Loss as the MLP arms: mixture NLL over the 24 sampled worlds + 0.5 x true-world CE.  Adam lr 0.01, batch 512 decision-kinds,
3 epochs, seed 1; candidates = the weights after each epoch.

  m20b_cal.py train ARM ROOT ; m20b_cal.py evalall select ROOT RT,RTW,RT0
"""
import json, math, sys, time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import m20b_train as MT

EPOCHS, BATCH, LR = 3, 512, 0.01
ARMS = ('RT', 'RTW', 'RT0')


def scalars(d, sl):
    """(D, K+1, 5) world scalars, (D, 8) decision scalars."""
    return d['RF'][sl].astype(np.float32), d['DF'][sl].astype(np.float32)


class Cal:
    def __init__(self, arm, mu_f, sd_f, mu_d, sd_d):
        import torch
        self.arm = arm
        self.mu_f, self.sd_f, self.mu_d, self.sd_d = (torch.from_numpy(x) for x in (mu_f, sd_f, mu_d, sd_d))
        nf = 5 if arm != 'RT0' else 0
        self.a = torch.zeros(nf + 8 + 1, requires_grad=True)
        self.b = torch.zeros(10, requires_grad=True) if arm == 'RTW' else None

    def params(self):
        return [p for p in (self.a, self.b) if p is not None]

    def logp(self, H, RF, DF, W, b):
        """(log-probs (D, K+1, 204), log world weights (D, K) over the sampled worlds)."""
        import torch
        Ht = torch.from_numpy(np.ascontiguousarray(H, dtype=np.float32))
        z = Ht @ W.T + b
        f = (torch.from_numpy(RF) - self.mu_f) / self.sd_f
        dd = (torch.from_numpy(DF) - self.mu_d) / self.sd_d
        D, K1 = z.shape[:2]
        dexp = dd[:, None, :].expand(D, K1, dd.shape[1])
        x = torch.cat(([f] if self.arm != 'RT0' else []) + [dexp, torch.ones(D, K1, 1)], -1)
        logT = (x * self.a).sum(-1).clamp(-3, 3)
        lp = torch.log_softmax(z / logT.exp()[..., None], -1)
        if self.b is not None:
            cards = torch.from_numpy(DF[:, 5:6])[:, None, :].expand(D, K1, 1)
            g = torch.cat([f, f * cards], -1)[:, 1:]
            lw = torch.log_softmax((g * self.b).sum(-1), 1)
        else:
            lw = torch.full((D, K1 - 1), -math.log(K1 - 1))
        return lp, lw

    def state(self):
        return dict(arm=self.arm, a=self.a.detach().numpy().tolist(), b=None if self.b is None else self.b.detach().numpy().tolist())


def nll(lp, lw, T):
    import torch
    lt = lp.gather(-1, T.view(-1, 1, 1).expand(-1, lp.shape[1], 1)).squeeze(-1)
    return -lt[:, 0], -torch.logsumexp(lt[:, 1:] + lw, 1), lt


def norms(data):
    rf = np.concatenate([data[t]['RF'][:, 1:].reshape(-1, 5) for t in MT.TAGS])
    df = np.concatenate([data[t]['DF'] for t in MT.TAGS])
    mu_d, sd_d = df.mean(0), df.std(0) + 1e-3
    mu_d[-1], sd_d[-1] = 0.0, 1.0                                     # the leaf-kind flag stays 0/1
    return rf.mean(0), rf.std(0) + 1e-3, mu_d, sd_d


def load_cal(root, arm, ep):
    import torch
    root = Path(root); nz = np.load(root / 'train' / arm / 'norm.npz')
    c = Cal(arm, nz['mu_f'], nz['sd_f'], nz['mu_d'], nz['sd_d'])
    st = json.loads((root / 'train' / arm / f'e{ep}.json').read_text())
    with torch.no_grad():
        c.a.copy_(torch.tensor(st['a']))
        if c.b is not None:
            c.b.copy_(torch.tensor(st['b']))
    return c


def cmd_train(arm, root):
    import torch
    torch.manual_seed(1); torch.set_num_threads(2)
    root = Path(root); od = root / 'train' / arm; od.mkdir(parents=True, exist_ok=True)
    data = MT.load_set(root, 'train')
    mu_f, sd_f, mu_d, sd_d = norms(data)
    np.savez(od / 'norm.npz', mu_f=mu_f, sd_f=sd_f, mu_d=mu_d, sd_d=sd_d)
    c = Cal(arm, mu_f, sd_f, mu_d, sd_d)
    W, b = (torch.from_numpy(x) for x in MT.served_head())
    opt = torch.optim.Adam(c.params(), lr=LR)
    index = [(t, i) for t in MT.TAGS for i in range(len(data[t]['T']))]
    rng = np.random.default_rng(1)
    for ep in range(1, EPOCHS + 1):
        t0 = time.time(); perm = rng.permutation(len(index)); agg = dict(true=0.0, mix=0.0, n=0)
        for s0 in range(0, len(perm), BATCH):
            batch = [index[j] for j in perm[s0:s0 + BATCH]]
            opt.zero_grad()
            for t in MT.TAGS:
                ii = np.array(sorted(i for tt, i in batch if tt == t))
                if len(ii) == 0:
                    continue
                d = data[t]; RF, DF = scalars(d, ii)
                lp, lw = c.logp(d['H'][ii], RF, DF, W, b)
                tr, mx, _ = nll(lp, lw, torch.from_numpy(d['T'][ii]))
                ((mx + MT.LAMBDA_TRUE * tr).sum() / len(batch)).backward()
                agg['true'] += float(tr.sum()); agg['mix'] += float(mx.sum()); agg['n'] += len(ii)
            opt.step()
        (od / f'e{ep}.json').write_text(json.dumps(c.state()))
        print(json.dumps(dict(ep=ep, secs=round(time.time() - t0, 1), true=agg['true'] / agg['n'], mix=agg['mix'] / agg['n'], **c.state())), flush=True)
    print(json.dumps(dict(kind='train_done', arm=arm)), flush=True)


def evaluate(root, setname, arm, ep, data):
    import torch
    torch.set_num_threads(2)
    c = load_cal(root, arm, ep)
    W, b = (torch.from_numpy(x) for x in MT.served_head())
    from shengji.rl.value_afterstate import category_signed_level
    support = torch.tensor([category_signed_level(i) for i in range(204)], dtype=torch.float32)
    out = {}
    for t in MT.TAGS:
        d = data[t]; n = len(d['T']); tr, mx, pw, lvl = [], [], [], []
        with torch.no_grad():
            for s0 in range(0, n, 256):
                ii = np.arange(s0, min(n, s0 + 256)); RF, DF = scalars(d, ii)
                lp, lw = c.logp(d['H'][ii], RF, DF, W, b)
                a, m, lt = nll(lp, lw, torch.from_numpy(d['T'][ii]))
                tr.append(a.numpy()); mx.append(m.numpy()); pw.append((-lt[:, 1:]).mean(1).numpy())
                lvl.append(((lp[:, 1:].exp() * lw.exp()[..., None]).sum(1) @ support).numpy())
        out[t] = dict(true=np.concatenate(tr), mix=np.concatenate(mx), perworld=np.concatenate(pw), lvl=np.concatenate(lvl),
                      cluster=d['CL'], lead=d['LEAD'], cards=d['CARDS'])
    return out


if __name__ == '__main__':
    if sys.argv[1] == 'train':
        cmd_train(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == 'evalall':
        setname, root, arms = sys.argv[2], sys.argv[3], sys.argv[4].split(',')
        assert setname == 'select'
        data = MT.load_set(root, setname)
        for arm in arms:
            for ep in range(1, EPOCHS + 1):
                MT.save_eval(root, setname, f'{arm}-e{ep}', evaluate(root, setname, arm, ep, data))
                print('evaluated', arm, ep, flush=True)
