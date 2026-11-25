"""Transfer RT4 history features and their key/value projections into the medium trunk."""
import math

import torch


def _lift(values, width):
    # Appended mean channels leave the mean unchanged. Scaling restores variance
    # over the wider vector, including the epsilon used by every LayerNorm.
    d = values.shape[-1]
    mean = values.mean(dim=-1, keepdim=True)
    return torch.cat((mean + math.sqrt(width / d) * (values - mean),
                      mean.expand(*values.shape[:-1], width - d)), dim=-1)


def _copy_norm(source, target):
    d, width = source.weight.numel(), target.weight.numel()
    target.weight[:d].copy_(source.weight / math.sqrt(width / d))
    target.bias[:d].copy_(source.bias)
    target.bias[d:].zero_()


def _copy_residual_projection(source, target):
    # The target's unused hidden units and heads can acquire an output weight.
    target.weight.zero_()
    target.weight[:, :source.in_features].copy_(_lift(source.weight.T, target.out_features).T)
    target.bias.copy_(_lift(source.bias, target.out_features))


@torch.no_grad()
def widen_history(source, target):
    """Populate the history encoder and the original heads of each KV consumer in-place.

    Both inputs are stock HistoryBelief trunks. The target's first d output
    channels carry the original normalized history. The card path and outcome
    head require their own conversions before publishing a unified checkpoint.
    """
    old, new = source.config, target.config
    d, width = old["d"], new["d"]
    if (width <= d or width * old["heads"] != d * new["heads"]
            or old["enc_layers"] > new["enc_layers"] or old["xattn_layers"] > new["xattn_layers"]):
        raise ValueError("expected wider history with unchanged head dimension and at least the source depth")

    target.card_id.copy_(_lift(source.card_id, width))
    for name in ("tok_meta", "card_feat"):
        _copy_residual_projection(getattr(source, name), getattr(target, name))
    for name in ("trick_emb", "rel_emb", "pos_emb"):
        getattr(target, name).weight.copy_(_lift(getattr(source, name).weight, width))

    # Undo the lifted first d channels before applying the learned history projection.
    weight = source.att_proj.weight
    inv_scale = math.sqrt(d / width)
    decoded = inv_scale * weight + (1 - inv_scale) * weight.mean(dim=1, keepdim=True)
    target.att_proj.weight.zero_()
    target.att_proj.weight[:, :d].copy_(_lift(decoded.T, width).T)

    for a, b in zip(source.encoder.layers, target.encoder.layers):
        _copy_norm(a.norm1, b.norm1)
        _copy_norm(a.norm2, b.norm2)
        for i in range(3):
            old_rows = slice(i * d, (i + 1) * d)
            new_rows = slice(i * width, i * width + d)
            b.self_attn.in_proj_weight[new_rows].zero_()
            b.self_attn.in_proj_weight[new_rows, :d].copy_(a.self_attn.in_proj_weight[old_rows])
            b.self_attn.in_proj_bias[new_rows].copy_(a.self_attn.in_proj_bias[old_rows])
        _copy_residual_projection(a.self_attn.out_proj, b.self_attn.out_proj)
        hidden = a.linear1.out_features
        b.linear1.weight[:hidden].zero_()
        b.linear1.weight[:hidden, :d].copy_(a.linear1.weight)
        b.linear1.bias[:hidden].copy_(a.linear1.bias)
        _copy_residual_projection(a.linear2, b.linear2)

    for layer in target.encoder.layers[old["enc_layers"]:]:
        for projection in (layer.self_attn.out_proj, layer.linear2):
            projection.weight.zero_()
            projection.bias.zero_()
    _copy_norm(source.enc_norm, target.enc_norm)
    target.null_kv[..., :d].copy_(source.null_kv)
    for a, b in zip(source.kv, target.kv):
        for i in range(2):
            old_rows = slice(i * d, (i + 1) * d)
            new_rows = slice(i * width, i * width + d)
            b.weight[new_rows].zero_()
            b.weight[new_rows, :d].copy_(a.weight[old_rows])
            b.bias[new_rows].copy_(a.bias[old_rows])
