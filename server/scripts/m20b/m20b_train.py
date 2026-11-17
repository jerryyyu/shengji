#!/usr/bin/env python3
"""M20b add-on value head on the frozen f4f4127e trunk (PREDECLARE.md).  DEV, tier i.

  m20b_train.py train ARM ROOT          ARM in P, PS, C; writes ROOT/train/ARM/e{N}.pt + norm.npz + curve.jsonl
  m20b_train.py eval ARM EPOCH SET ROOT  writes ROOT/eval/SET/ARM-e{N}.npz (per decision: served/cand true and mixture NLL)
  m20b_train.py served SET ROOT          writes ROOT/eval/SET/served.npz

Rows come from m20b_gen.py (ROOT/rows/SET/*.npz).  logits' = h W + b (frozen served head) + g([h, features]).
"""
import glob, json, math, os, sys, time
from pathlib import Path

import numpy as np

PKG = '/Users/jerryyu/shengji-archive/2026-09-13/readouts/RD1-AV1/av1/models/g3a-e04-f4f4127e.npz'
TAGS = ('end', 'k0')
HID = 256
EPOCHS = int(os.environ.get("M20B_SMOKE_EPOCHS", "8"))
BATCH = 512
LR, LR_MIN, WD = 1e-3, 1e-4, 1e-4
LAMBDA_TRUE = 0.5


def load_set(root, name):
    """Per tag: dict of arrays grouped per decision (D, K+1, ...) with world 0 = the true world."""
    files = sorted(glob.glob(str(Path(root) / 'rows' / name / 'w*-c*.npz')))
    out = {}
    for tag in TAGS:
        H, RF, S, DF, Qd, T, CL, LEAD, CARDS, KK, PS_ = [], [], [], [], [], [], [], [], [], [], []
        for f in files:
            z = np.load(f)
            if z[f'{tag}_H'].shape[0] == 0:
                continue
            dec = z[f'{tag}_dec']; widx = z[f'{tag}_widx']
            nd = len(np.unique(dec))
            k1 = len(dec) // nd
            assert k1 * nd == len(dec) and (widx.reshape(nd, k1)[:, 0] == 0).all(), f
            ds = dec.reshape(nd, k1)[:, 0]
            assert (dec.reshape(nd, k1) == ds[:, None]).all()
            c = np.maximum(z['dec_copies'][ds], 1.0)
            llq = z[f'{tag}_llq'].reshape(nd, k1); llp = z[f'{tag}_llp'].reshape(nd, k1)
            mq, sq = z['dec_mean_q'][ds], z['dec_std_q'][ds]; mp, sp = z['dec_mean_p'][ds], z['dec_std_p'][ds]
            has = (z['dec_copies'][ds] > 0)[:, None]
            rf = np.stack([llq / c[:, None], llp / c[:, None], llq - z['dec_lme_q'][ds][:, None],
                           (llq - mq[:, None]) / (sq[:, None] + 1e-3), (llp - mp[:, None]) / (sp[:, None] + 1e-3)], -1) * has[..., None]
            df = np.stack([z['dec_ent'][ds], z['dec_top'][ds], z['dec_copies'][ds] / 100.0, sq / c, sp / c,
                           z['dec_cards_left'][ds] / 25.0, z['dec_lead'][ds].astype(float), np.full(nd, 1.0 if tag == 'end' else 0.0)], -1)
            H.append(z[f'{tag}_H'].reshape(nd, k1, -1)); PS_.append(z[f'{tag}_p_served'].reshape(nd, k1)); RF.append(rf.astype(np.float32))
            S.append(z[f'{tag}_surp'].reshape(nd, k1, 54).astype(np.float16)); DF.append(df.astype(np.float32))
            Qd.append(z['dec_Q'][ds].astype(np.float16)); T.append(z['dec_target'][ds]); CL.append(z['dec_cluster'][ds])
            LEAD.append(z['dec_lead'][ds]); CARDS.append(z['dec_cards_left'][ds]); KK.append(k1)
        assert len(set(KK)) == 1, set(KK)
        out[tag] = dict(H=np.concatenate(H), RF=np.concatenate(RF), S=np.concatenate(S), DF=np.concatenate(DF),
                        Q=np.concatenate(Qd), T=np.concatenate(T), CL=np.concatenate(CL), LEAD=np.concatenate(LEAD),
                        CARDS=np.concatenate(CARDS), PSV=np.concatenate(PS_))
    return out


def served_head():
    z = np.load(PKG)
    return z['head_weight'].astype(np.float32), z['head_bias'].astype(np.float32)


def arm_parts(arm):
    return {'P': ('RF', 'S', 'DF', 'Q'), 'PS': ('RF', 'DF'), 'C': ('DF_FLAG',)}[arm]


def features(d, arm, sl=slice(None)):
    """(D, K+1, F) float32 non-h features of the arm, unnormalised."""
    H = d['H'][sl]
    D, K1 = H.shape[:2]
    parts = []
    for p in arm_parts(arm):
        if p == 'RF':
            parts.append(d['RF'][sl])
        elif p == 'S':
            parts.append(d['S'][sl].astype(np.float32))
        elif p == 'DF':
            parts.append(np.broadcast_to(d['DF'][sl][:, None, :], (D, K1, d['DF'].shape[1])))
        elif p == 'Q':
            parts.append(np.broadcast_to(d['Q'][sl].astype(np.float32)[:, None, :], (D, K1, 216)))
        elif p == 'DF_FLAG':
            parts.append(np.broadcast_to(d['DF'][sl][:, None, -1:], (D, K1, 1)))
    return np.concatenate(parts, -1).astype(np.float32)


def build_net(nin):
    import torch
    net = torch.nn.Sequential(torch.nn.Linear(nin, HID), torch.nn.GELU(), torch.nn.Linear(HID, HID), torch.nn.GELU(),
                              torch.nn.Linear(HID, 204))
    torch.nn.init.zeros_(net[-1].weight); torch.nn.init.zeros_(net[-1].bias)
    return net


def forward(net, W, b, H, F, mu, sd):
    """log-probs (D, K+1, 204)."""
    import torch
    Ht = torch.from_numpy(np.ascontiguousarray(H, dtype=np.float32))
    Ft = (torch.from_numpy(np.ascontiguousarray(F)) - mu) / sd
    base = Ht @ W.T + b
    x = torch.cat([Ht, Ft], -1)
    return torch.log_softmax(base + net(x), -1)


def nll_parts(logp, T):
    import torch
    lt = logp.gather(-1, T.view(-1, 1, 1).expand(-1, logp.shape[1], 1)).squeeze(-1)    # (D, K+1)
    true = -lt[:, 0]
    k = lt.shape[1] - 1
    mix = -(torch.logsumexp(lt[:, 1:], 1) - math.log(k))
    return true, mix, lt


def cmd_train(arm, root):
    import torch
    torch.manual_seed(1); torch.set_num_threads(4)
    root = Path(root); od = root / 'train' / arm; od.mkdir(parents=True, exist_ok=True)
    data = load_set(root, 'train')
    W, b = (torch.from_numpy(x) for x in served_head())
    # normalisation on TRAIN sampled rows
    fs = []
    for t in TAGS:
        f = features(data[t], arm, slice(0, 20000))[:, 1:]
        fs.append(f.reshape(-1, f.shape[-1]))
    allf = np.concatenate(fs)
    mu = allf.mean(0); sd = allf.std(0) + 1e-3
    np.savez(od / 'norm.npz', mu=mu, sd=sd)
    mu_t, sd_t = torch.from_numpy(mu), torch.from_numpy(sd)
    nin = 165 + len(mu)
    net = build_net(nin)
    opt = torch.optim.AdamW(net.parameters(), lr=LR, weight_decay=WD)
    index = [(t, i) for t in TAGS for i in range(len(data[t]['T']))]
    steps_per = math.ceil(len(index) / BATCH); total = steps_per * EPOCHS
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: (LR_MIN + 0.5 * (LR - LR_MIN) * (1 + math.cos(math.pi * min(s, total) / total))) / LR)
    rng = np.random.default_rng(1)
    curve = open(od / 'curve.jsonl', 'a')
    step = 0
    for ep in range(1, EPOCHS + 1):
        t0 = time.time()
        perm = rng.permutation(len(index))
        agg = dict(loss=0.0, true=0.0, mix=0.0, n=0)
        for s0 in range(0, len(perm), BATCH):
            batch = [index[j] for j in perm[s0:s0 + BATCH]]
            loss_sum = 0.0; tot = 0
            opt.zero_grad()
            for t in TAGS:
                ii = np.array(sorted(i for tt, i in batch if tt == t))
                if len(ii) == 0:
                    continue
                d = data[t]
                logp = forward(net, W, b, d['H'][ii], features(d, arm, ii), mu_t, sd_t)
                true, mix, _ = nll_parts(logp, torch.from_numpy(d['T'][ii]))
                l = (mix + LAMBDA_TRUE * true).sum()
                (l / len(batch)).backward()
                agg['loss'] += float(l); agg['true'] += float(true.sum()); agg['mix'] += float(mix.sum()); agg['n'] += len(ii)
            opt.step(); sched.step(); step += 1
            if step % 100 == 0:
                curve.write(json.dumps(dict(step=step, ep=ep, lr=sched.get_last_lr()[0], **{k: agg[k] / max(agg['n'], 1) for k in ('loss', 'true', 'mix')})) + '\n'); curve.flush()
        torch.save(net.state_dict(), od / f'e{ep}.pt')
        print(json.dumps(dict(arm=arm, ep=ep, secs=round(time.time() - t0, 1), **{k: agg[k] / max(agg['n'], 1) for k in ('loss', 'true', 'mix')})), flush=True)
    print(json.dumps(dict(kind='train_done', arm=arm)), flush=True)


def evaluate(root, setname, arm=None, ep=None, data=None):
    import torch
    torch.set_num_threads(4)
    root = Path(root)
    data = data or load_set(root, setname)
    W, b = (torch.from_numpy(x) for x in served_head())
    out = {}
    if arm is not None:
        nz = np.load(root / 'train' / arm / 'norm.npz'); mu, sd = torch.from_numpy(nz['mu']), torch.from_numpy(nz['sd'])
        net = build_net(165 + len(nz['mu'])); net.load_state_dict(torch.load(root / 'train' / arm / f'e{ep}.pt')); net.eval()
    from shengji.rl.value_afterstate import category_signed_level  # noqa
    support = torch.tensor([category_signed_level(i) for i in range(204)], dtype=torch.float32)
    for t in TAGS:
        d = data[t]
        n = len(d['T']); tr, mx, pw, lvl = [], [], [], []
        with torch.no_grad():
            for s0 in range(0, n, 256):
                ii = np.arange(s0, min(n, s0 + 256))
                if arm is None:
                    Ht = torch.from_numpy(np.ascontiguousarray(d['H'][ii], dtype=np.float32))
                    logp = torch.log_softmax(Ht @ W.T + b, -1)
                else:
                    logp = forward(net, W, b, d['H'][ii], features(d, arm, ii), mu, sd)
                true, mix, lt = nll_parts(logp, torch.from_numpy(d['T'][ii]))
                tr.append(true.numpy()); mx.append(mix.numpy()); pw.append((-lt[:, 1:]).mean(1).numpy())
                lvl.append((logp[:, 1:].exp().mean(1) @ support).numpy())
        if arm is None:
            # the recomputed served NLL equals the generator's float64 served probabilities
            chk = np.abs(np.concatenate(tr) + np.log(d['PSV'][:, 0])).max()
            print('served-recompute max |d true NLL|', t, float(chk), flush=True)
        out[t] = dict(true=np.concatenate(tr), mix=np.concatenate(mx), perworld=np.concatenate(pw), lvl=np.concatenate(lvl),
                      cluster=d['CL'], lead=d['LEAD'], cards=d['CARDS'])
    return out


def save_eval(root, setname, tagname, out):
    od = Path(root) / 'eval' / setname; od.mkdir(parents=True, exist_ok=True)
    np.savez(od / f'{tagname}.npz', **{f'{t}_{k}': v for t, o in out.items() for k, v in o.items()})


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    cmd = sys.argv[1]
    if cmd == 'train':
        cmd_train(sys.argv[2], sys.argv[3])
    elif cmd == 'eval':
        arm, ep, setname, root = sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
        save_eval(root, setname, f'{arm}-e{ep}', evaluate(root, setname, arm, ep))
    elif cmd == 'evalall':
        # every epoch of the given arms on one set (SELECT only by the predeclared rule), loading the set once
        setname, root, arms = sys.argv[2], sys.argv[3], sys.argv[4].split(',')
        assert setname == 'select'
        data = load_set(root, setname)
        save_eval(root, setname, 'served', evaluate(root, setname, data=data))
        for arm in arms:
            for ep in range(1, EPOCHS + 1):
                save_eval(root, setname, f'{arm}-e{ep}', evaluate(root, setname, arm, ep, data=data))
                print('evaluated', arm, ep, flush=True)
    elif cmd == 'served':
        setname, root = sys.argv[2], sys.argv[3]
        save_eval(root, setname, 'served', evaluate(root, setname))
