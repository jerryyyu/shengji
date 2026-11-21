#!/usr/bin/env python3
"""Offline unified value/reply gates against the frozen release-52 comparator.

Replays complete trajectory clusters with attempted throws. The adapter, words,
checkpoint and holdout are explicit inputs; this tool does not select or launch
an experiment. Use a fresh output for a different replay or checkpoint producer.
"""
import argparse, copy, hashlib, importlib.util, json, os, sys, time
from pathlib import Path
import numpy as np


REPLAY = "attempted-actions-v2"


def iter_gate_roots(records, bot):
    """Give both model inputs and the sampler the event-complete public history.

    The extractor replays attempted actions and verifies the accepted prefix.
    Snapshot roots because readout frames survive the iterator advancing.
    """
    from shengji.ai.refusal import RefusalLedger
    from shengji.train.belief_labels import iter_decisions

    ledger = None
    round_index = None
    for decision in iter_decisions(records):
        if decision.round_index != round_index:
            ledger = RefusalLedger()
            round_index = decision.round_index
        root = copy.deepcopy(decision.rnd)
        seen = tuple(ledger.observe(root))
        if seen != decision.refusals:
            raise ValueError("gate refusal history differs from the extract")
        bot._refusals = ledger
        yield decision.record, root


def mult(legal):
    from shengji.rl.encode import CARD_INDEX
    m = np.zeros((len(legal), 54))
    for i, act in enumerate(legal):
        for c in act:
            m[i, CARD_INDEX[c]] += 1
    return m



def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('--view', required=True); ap.add_argument('--adapter', required=True)
    ap.add_argument('--words', required=True); ap.add_argument('--pkg', required=True); ap.add_argument('--sha', required=True)
    ap.add_argument('--worker', type=int, default=0); ap.add_argument('--workers', type=int, default=1); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args(argv)
    sys.path.insert(0, a.adapter.rsplit('/', 1)[0])
    spec = importlib.util.spec_from_file_location('ut_adapter', a.adapter); A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
    from shengji.ai import belief_numpy
    from shengji.ai.belief_numpy import decision_inputs
    from shengji.ai.cwv_policy import afterstate
    from shengji.ai.unified_readout_numpy import load_unified_readout_numpy
    from shengji.harvest.legal import enumerate_legal
    from shengji.rl.value_afterstate import signed_level_category
    from shengji.train import unified_slots as US

    R52 = 'pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r12e81e0c-bury-hybrid-bwv-bbw-7a9a430fe690-sc8'
    name, make = A.D.variant_factory(A.D._parse_env(a.words.split(',')))
    assert name == R52, name
    bot = make(1)
    belief_numpy.PREP_SECONDS = 60.0
    model = load_unified_readout_numpy(a.pkg, a.sha)
    ev = bot.evaluator
    assert ev.checkpoint_sha256 == 'f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd'
    assert bot.worlds == 64 and bot.belief_worlds and bot.world_history_legal and bot.refusal_constraints
    view = Path(a.view)
    manifest_bytes = (view / 'manifest.json').read_bytes()
    clusters = sorted(int(sh['cluster']) for sh in json.loads(manifest_bytes)['shards'])
    mine = clusters[a.worker::a.workers]
    key = lambda cards: tuple(sorted(cards))
    seed_of = lambda ref: int(hashlib.sha256(('utv|' + ref).encode()).hexdigest()[:15], 16)
    identity = dict(replay=REPLAY, readout=model.package_sha256,
                    value=ev.checkpoint_sha256, bot=name,
                    view=str(view.resolve()), manifest=hashlib.sha256(manifest_bytes).hexdigest(),
                    adapter=hashlib.sha256(Path(a.adapter).read_bytes()).hexdigest(), words=a.words,
                    worker=a.worker, workers=a.workers)
    done = set()
    completed = False
    if os.path.exists(a.out):
        for l in open(a.out):
            row = json.loads(l)
            if completed:
                raise ValueError('output contains rows after its terminal marker')
            if any(row.get(k) != v for k, v in identity.items()):
                raise ValueError('output has incompatible replay or model/input identity; use a new output path')
            if row.get('kind') == 'worker_done':
                if row.get('worker') != a.worker or row.get('clusters') != len(mine):
                    raise ValueError('output belongs to a different worker partition')
                if type(row.get('rows')) is not int or row['rows'] != len(done):
                    raise ValueError('terminal row count differs from completed decisions')
                completed = True
                continue
            if not row.get('ref'):
                raise ValueError('output has incompatible replay or model/input identity; use a new output path')
            if row['ref'] in done:
                raise ValueError('duplicate decision in resumed output')
            done.add(row['ref'])
    if completed:
        return
    fh = open(a.out, 'a')
    print(json.dumps(dict(kind='header', pid=os.getpid(), bot=name, value=ev.checkpoint_sha256, readout=model.package_sha256, worker=a.worker, workers=a.workers)), flush=True)


    n = 0
    for cl in mine:
        recs = [json.loads(l) for l in open(view / 'shards' / f'cluster-{cl:06d}.jsonl')]
        plays = [r for r in recs if r['decision_kind'] == 'play']
        if all(r['source_ref'] in done for r in plays):
            continue
        trick_frames = []
        for rec, root in iter_gate_roots(plays, bot):
            ref = rec['source_ref']; rk = ref.rsplit(':', 2)[0]; seat = int(rec['seat'])
            t0 = time.perf_counter()
            bot.sampler.rng.seed(seed_of(ref))
            refusals = bot._refusals.observe(root)
            inp = decision_inputs(root, seat, refusals)
            q, g = model.card_states(inp, model.trunk.encode_history(inp))
            frame = US.LeafFrame(None, root, seat)
            frame._cache = model.decision_cache(q, g)
            trick_frames = [t for t in trick_frames if t[0] == rk and t[1] == len(root.history)]
            if ref in done:
                trick_frames.append((rk, len(root.history), frame))
                continue
            worlds, attempts = bot._worlds(root, seat)
            samp = dict(bot._last_sampling or {})
            o = rec['outcome']
            role_att = (seat % 2) != (int(rec['setup']['banker']) % 2)
            target = signed_level_category(int(o['attacker_points']), role_att)
            action = list(rec['action'])
            true_world = ([list(h) for h in root.hands], list(root.buried))
            row = dict(**identity, outcome=dict(o), banker=int(rec['setup']['banker']), ref=ref, cluster=cl, seat=seat, ply=int(rec['ply']), pos=len(root.trick.plays), cards_left=len(root.hands[seat]),
                       lead=not root.trick.plays, target=int(target), belief_fallback=samp.get('belief_fallback'), worlds=len(worlds))
            for tag, finish in (('end', True), ('k0', False)):
                leaves = [afterstate(root, seat, h, b, action, finish_trick=finish) for h, b in [true_world] + list(worlds)]
                if any(l.phase == 'round_end' for l in leaves):
                    row[tag] = None
                    continue
                feats = [US.leaf_features(frame, l) for l in leaves]
                assert all(f is not None for f in feats), (ref, tag)
                P = ev.probabilities([ev.encoder(l, seat) for l in leaves])
                Q = model.leaf_value_probs(frame._cache, np.stack([f[0] for f in feats]), np.stack([f[1] for f in feats]))
                row[tag] = dict(mlp_true=float(P[0, target]), mlp_mix=float(P[1:, target].mean()), ro_true=float(Q[0, target]), ro_mix=float(Q[1:, target].mean()),
                                mlp_lvl=float(P[1:].mean(0) @ ev.support), ro_lvl=float(Q[1:].mean(0) @ ev.support),
                                complete=bool(feats[0][1][2] > 0))
            # Each reply is scored against the earlier frames of its trick.
            trick_frames = [t for t in trick_frames if t[0] == rk and t[1] == len(root.history)]
            rep = []
            if root.trick.plays:
                ls = enumerate_legal(root, seat, cap=4000, must_include=[action])
                legal = [list(x) for x in ls.actions]
                if len(legal) >= 2:
                    j = next(i for i, x in enumerate(legal) if key(x) == key(action))
                    M = mult(legal)
                    ft1 = bot.scores(root, seat, legal, [true_world]).mean(axis=0)
                    top_f = set(np.argsort(-ft1, kind='stable')[:4].tolist())
                    for _, _, fr in trick_frames:
                        f = US.leaf_features(fr, root)
                        assert f is not None and f[1][8 + (seat - fr.seat) % 4] == 1.0, ref
                        ro = M @ model.leaf_reply_logits(fr._cache, f[0][None], f[1][None])[0].astype(np.float64)
                        top_r = set(np.argsort(-ro, kind='stable')[:4].tolist())
                        rep.append(dict(frame_pos=fr.pos, n_legal=len(legal), rank_ft1=int((ft1 > ft1[j]).sum()), rank_ro=int((ro > ro[j]).sum()),
                                        top4_overlap=len(top_f & top_r), top1_same=bool(int(np.argmax(ft1)) == int(np.argmax(ro)))))
            row['reply'] = rep
            trick_frames.append((rk, len(root.history), frame))
            row['secs'] = round(time.perf_counter() - t0, 4)
            fh.write(json.dumps(row) + '\n'); fh.flush()
            n += 1
            if a.limit and n >= a.limit:
                fh.close()
                return
    fh.write(json.dumps(dict(**identity, kind='worker_done', clusters=len(mine), rows=len(done) + n)) + '\n')
    fh.close()


if __name__ == "__main__":
    main()
