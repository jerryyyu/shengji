"""The search's per-candidate means, carried into the policy rows (#496 H3).

AlphaGo Zero trains its policy on the MCTS visit distribution; we train on the single
played action and throw the search's relative preference away. The values needed to fix
that are already in every sealed trajectory (`action_values.means`), so this is a
re-extract, not a re-harvest.

THE RISK THIS FILE EXISTS FOR IS ALIGNMENT. `eligible_indices` index the RAW ballot, while
`ballot_tensors` DROPS falsy ballot entries -- so every slot after an empty one shifts. A
misalignment here would not crash: it would train the policy on another candidate's value.
"""
import json
import numpy as np
import pytest

from shengji.train.policy_prior import ballot_tensors, ballot_value_tensor


def _meta(ballot, means, taken):
    return {"ballot": ballot, "means": means, "taken": taken}


def test_slots_line_up_after_empty_ballot_entries_are_dropped():
    """The whole point: an empty entry at position 1 shifts every later slot by one, and
    the means must shift WITH it."""
    ballot = [[1, 2], [], [3], [4, 5]]          # position 1 is dropped by `if a`
    means = [10.0, 99.0, 20.0, 30.0]            # 99.0 belongs to the dropped entry
    meta = [_meta(ballot, means, [3])]
    ball, mask, tgt = ballot_tensors(meta)
    vals, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert mask[0].tolist()[:3] == [True, True, True] and int(mask[0].sum()) == 3
    # slot 0 = [1,2] -> 10.0, slot 1 = [3] -> 20.0, slot 2 = [4,5] -> 30.0; 99.0 is GONE
    assert vals[0, :3].tolist() == [10.0, 20.0, 30.0]
    assert 99.0 not in vals[0].tolist()
    # and the played action [3] is slot 1, whose value is 20.0 -- not 99.0
    assert int(tgt[0]) == 1 and vals[0, int(tgt[0])] == 20.0


def test_a_row_the_search_never_scored_is_marked_unusable_not_zero():
    meta = [_meta([[1], [2]], [float("nan"), float("nan")], [1])]
    ball, _m, _t = ballot_tensors(meta)
    vals, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert not bool(has[0]), "a row with no finite mean must not look like a flat target"
    assert np.isnan(vals[0]).all()


def test_one_finite_mean_is_not_a_distribution():
    meta = [_meta([[1], [2]], [5.0, float("nan")], [1])]
    ball, _m, _t = ballot_tensors(meta)
    _v, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert not bool(has[0]), "one value cannot form a preference over candidates"


def test_two_finite_means_are_usable():
    meta = [_meta([[1], [2]], [5.0, 7.0], [1])]
    ball, _m, _t = ballot_tensors(meta)
    _v, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert bool(has[0])


def test_a_short_or_long_means_list_pads_rather_than_zip_truncating():
    """zip() would silently drop the tail; that would misalign every later row's slots."""
    meta = [_meta([[1], [2], [3]], [1.0], [2])]          # far too short
    ball, _m, _t = ballot_tensors(meta)
    vals, _h = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert vals[0, 0] == 1.0 and np.isnan(vals[0, 1]) and np.isnan(vals[0, 2])


def test_widths_match_ballot_tensors_so_a_slot_index_is_valid_in_both():
    metas = [_meta([[1, 2], [], [3]], [1.0, 9.0, 2.0], [3]),
             _meta([[4]], [5.0], [4])]
    ball, mask, _t = ballot_tensors(metas)
    vals, _h = ballot_value_tensor(metas, b_max=int(ball.shape[1]))
    assert vals.shape == (len(metas), int(ball.shape[1]))
    assert vals.shape[:2] == mask.shape


# ---------------------------------------------------------------- the soft target itself

import torch

from shengji.train.policy_prior import listwise_loss, listwise_loss_soft, soft_ballot_targets


def test_the_target_is_a_distribution_over_masked_finite_slots_only():
    vals = torch.tensor([[10.0, 12.0, float("nan"), 5.0]])
    mask = torch.tensor([[True, True, True, False]])     # slot 3 masked OUT, slot 2 has no value
    probs, usable = soft_ballot_targets(vals, mask, temperature=1.0)
    assert bool(usable[0])
    assert probs[0, 2] == 0.0 and probs[0, 3] == 0.0, "no mass on unscored or unmasked slots"
    assert abs(float(probs[0].sum()) - 1.0) < 1e-6
    assert probs[0, 1] > probs[0, 0], "the higher-valued candidate must carry more mass"


def test_a_row_the_search_did_not_score_is_not_usable_and_gets_no_mass():
    vals = torch.tensor([[float("nan"), float("nan")]])
    mask = torch.tensor([[True, True]])
    probs, usable = soft_ballot_targets(vals, mask, temperature=1.0)
    assert not bool(usable[0]) and float(probs[0].sum()) == 0.0


def test_temperature_moves_the_target_between_one_hot_and_uniform():
    vals = torch.tensor([[0.0, 30.0, 60.0]])
    mask = torch.ones(1, 3, dtype=torch.bool)
    sharp, _ = soft_ballot_targets(vals, mask, temperature=1.0)
    flat, _ = soft_ballot_targets(vals, mask, temperature=100_000.0)
    assert float(sharp[0].max()) > 0.99, "T=1 on a 60-point gap is nearly one-hot"
    # T=1000 still leaves 60/1000 = 0.06 of logit spread, so it approaches uniform without
    # reaching it (max 0.3434). The limit is the claim, so test it at a T where it holds.
    assert abs(float(flat[0].max()) - 1 / 3) < 0.01, "a large T washes out to uniform"


def test_soft_falls_back_to_the_hard_target_where_the_search_scored_nothing():
    """Rows the search never scored keep the played-action target, so the ROW COUNT does not
    change between the hard and soft arms -- otherwise the two would differ in sample size
    as well as in target, and the comparison would be confounded."""
    logits = torch.zeros(1, 54, requires_grad=True)
    ball = torch.tensor([[[0, -1], [1, -1]]], dtype=torch.int64)
    mask = torch.ones(1, 2, dtype=torch.bool)
    tgt = torch.tensor([1])
    vals = torch.full((1, 2), float("nan"))
    soft = listwise_loss_soft(logits, ball, mask, tgt, vals, temperature=1.0)
    hard = listwise_loss(logits, ball, mask, tgt)
    assert torch.allclose(soft, hard, atol=1e-6), "no search values => identical to the hard loss"


def test_soft_differs_from_hard_where_the_search_DID_score():
    # NON-uniform logits are essential: with all-zero logits log_softmax is uniform and ANY
    # normalised target gives the identical loss, so the test could not tell them apart.
    logits = torch.zeros(1, 54)
    logits[0, 0] = 2.0
    logits = logits.clone().requires_grad_(True)
    ball = torch.tensor([[[0, -1], [1, -1]]], dtype=torch.int64)
    mask = torch.ones(1, 2, dtype=torch.bool)
    tgt = torch.tensor([1])
    vals = torch.tensor([[8.0, 10.0]])                 # the search liked BOTH, slot 1 more
    soft = listwise_loss_soft(logits, ball, mask, tgt, vals, temperature=1.0)
    hard = listwise_loss(logits, ball, mask, tgt)
    assert not torch.allclose(soft, hard, atol=1e-6), "a real preference must change the loss"


def test_the_soft_loss_backpropagates():
    logits = torch.zeros(2, 54, requires_grad=True)
    ball = torch.tensor([[[0, -1], [1, -1]], [[2, -1], [3, -1]]], dtype=torch.int64)
    mask = torch.ones(2, 2, dtype=torch.bool)
    tgt = torch.tensor([0, 1])
    vals = torch.tensor([[9.0, 4.0], [1.0, 7.0]])
    listwise_loss_soft(logits, ball, mask, tgt, vals, 1.0).backward()
    assert logits.grad is not None and torch.isfinite(logits.grad).all()


# ------------------------------------------------- the trainer flag and its refusal

def test_policy_losses_dispatches_to_the_soft_loss_only_when_asked():
    from shengji.train.policy_rows import policy_losses

    class _M:
        def features_flat(self, x):
            return x
        def policy_logits(self, f):
            out = torch.zeros(f.shape[0], 54)
            out[:, 0] = 2.0
            return out.requires_grad_(True)

    t = {"x": torch.zeros(1, 4), "y": torch.zeros(1, 54),
         "ball": torch.tensor([[[0, -1], [1, -1]]], dtype=torch.int64),
         "mask": torch.ones(1, 2, dtype=torch.bool), "tgt": torch.tensor([1]),
         "vals": torch.tensor([[8.0, 10.0]])}
    hard = policy_losses(_M(), t, listwise_weight=1.0)[1]
    soft = policy_losses(_M(), t, listwise_weight=1.0, soft_targets=True)[1]
    assert not torch.allclose(hard, soft), "the flag must change the listwise term"


def test_the_soft_flag_refuses_an_extract_with_no_values_rather_than_training_hard():
    """A run asked for the soft arm; silently training the hard one would produce a result
    labelled as something it is not. The refusal lives in the trainer loop, so this pins the
    message that makes it diagnosable."""
    import inspect

    from shengji.train import train_cwv
    src = inspect.getsource(train_cwv)
    assert "--policy-soft-targets: this extract carries no per-candidate search" in src
    assert "re-extract with the current" in src
    # and it is guarded on the tensor actually being absent, not on a config flag
    assert 'if policy_soft_targets and "vals" not in p_tensors:' in src   # the batch tensors, after the stage timer


def test_the_flag_needs_a_policy_head_and_a_positive_temperature(tmp_path):
    """Exercise the validation for real rather than grepping the source for its message."""
    import pytest as _pytest

    from shengji.train.train_cwv import TrainError, build_config

    base = dict(data=["/nonexistent"], policy_head=True, policy_rows="x", policy_eval="y")

    # a flag is a flag
    with _pytest.raises(TrainError, match="--policy-soft-targets is a flag"):
        build_config(**base, policy_soft_targets="yes")
    # temperature must be finite and positive: 0 would divide by zero, negative inverts the
    # preference, and NaN would poison every target silently
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with _pytest.raises(TrainError, match="--policy-soft-temperature"):
            build_config(**base, policy_soft_targets=True, policy_soft_temperature=bad)
    # and it is refused without a policy head at all
    with _pytest.raises(TrainError, match="need --policy-head"):
        build_config(data=["/nonexistent"], policy_head=False, policy_soft_targets=True)


def test_cli_forwards_every_argument_train_is_called_with():
    """Every ``x=args.y`` at the CLI call site must be a parameter ``train()`` accepts.

    The soft-target flags shipped parsed, validated and forwarded -- and `train()` itself,
    a thin wrapper over `build_config`, never grew the two parameters.  `--policy-soft-targets`
    therefore died with `TypeError: train() got an unexpected keyword argument` one second into
    a 15-hour run, after the preflight had passed.  Every unit test I wrote for this feature
    called the loss functions directly and never crossed the CLI -> train() -> build_config
    boundary, so all of them passed against a build that could not run.

    This checks the boundary generally rather than pinning the two flags: it reads the actual
    `train(...)` call in `main()` and asserts the signature accepts each keyword.
    """
    import ast
    import inspect
    import textwrap

    from shengji.train import train_cwv

    source = inspect.getsource(train_cwv.main)
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "train"]
    assert calls, "no train(...) call found in main(); this guard has gone blind"

    accepted = set(inspect.signature(train_cwv.train).parameters)
    missing = sorted({kw.arg for call in calls for kw in call.keywords
                      if kw.arg is not None and kw.arg not in accepted})
    assert not missing, f"main() passes keywords train() does not accept: {missing}"


def test_train_forwards_soft_target_settings_into_the_receipt_config():
    """The forwarded values must reach the config, not merely be accepted and dropped."""
    from shengji.train import train_cwv

    config = train_cwv.build_config(policy_head=True, policy_rows="rows",
                                    policy_soft_targets=True, policy_soft_temperature=0.5,
                                    data=["d"], eval_luna=None)
    assert config["policy_soft_targets"] is True
    assert config["policy_soft_temperature"] == 0.5


def _monolithic(tmp_path, rows, with_means=True):
    """A current-format single-file extract: X/Y npz + meta.jsonl, optionally carrying means."""
    from shengji.train.policy_prior import input_dim
    tmp_path.mkdir(parents=True, exist_ok=True)
    X = np.zeros((len(rows), input_dim(2)), np.float32); Y = np.zeros((len(rows), 54), np.float32)
    np.savez_compressed(tmp_path / "m.npz", X=X, Y=Y)
    with open(tmp_path / "m.meta.jsonl", "w") as fh:
        for ballot, means, taken, key in rows:
            m = {"n_legal": len(ballot), "legal": ballot, "ballot": ballot, "taken": taken, "complete": True,
                 "deal": "d" * 16, "deal_key": key}
            if with_means:
                m["means"] = means
            fh.write(json.dumps(m) + "\n")
    return tmp_path / "m"


def test_the_monolithic_loader_carries_the_search_values_end_to_end(tmp_path):
    """Codex on the rebase PR: ``policy_prior extract`` writes ``means`` into the meta file by
    default (chunk_rows=None) but ``PolicyRows`` never yielded ``vals``, so the soft flag refused a
    freshly re-extracted dataset.  Now the monolithic loader carries them through filtering,
    shuffling and ``tensors``, aligned to the ballot slots; an extract without the key yields none."""
    from shengji.train.policy_rows import PolicyRows
    rows = [([[1], [2], [3]], [3.0, 4.0, float("nan")], [1], "deck:aaaa"),
            ([[4], [5]], [0.5, 0.25], [5], "deck:bbbb"),
            ([[6]], [1.0], [6], "deck:cccc")]
    prefix = _monolithic(tmp_path / "with", rows)
    pr = PolicyRows(prefix)
    assert pr.vals is not None and pr.vals.shape == (3, pr.ball.shape[1])
    batch = next(pr.batches(8, np.random.default_rng(0)))
    t = PolicyRows.tensors(batch, "cpu")
    assert "vals" in t and t["vals"].shape == (3, pr.ball.shape[1])
    # row order is shuffled: match rows by their taken slot target and check values by slot
    for i in range(3):
        b = batch["ball"][i]; v = batch["vals"][i]
        first = int(b[0][0])
        expect = {1: [3.0, 4.0], 4: [0.5, 0.25], 6: [1.0]}[first]
        got = [float(x) for x in v[:len(expect)]]
        assert got == expect and np.isnan(v[len(expect):]).all()
    # exclusion still filters vals with the rows
    pr2 = PolicyRows(prefix, exclude={"deck:bbbb"})
    assert pr2.n == 2 and pr2.vals.shape[0] == 2
    # a pre-#496 extract (no ``means`` key) yields no vals at all -- not NaNs
    prefix_old = _monolithic(tmp_path / "old", rows, with_means=False)
    pr3 = PolicyRows(prefix_old)
    assert pr3.vals is None and "vals" not in next(pr3.batches(8, np.random.default_rng(0)))
