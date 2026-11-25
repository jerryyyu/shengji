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


def _copy_attention(a, b):
    d, width = a.embed_dim, b.embed_dim
    for i in range(3):
        old_rows = slice(i * d, (i + 1) * d)
        new_rows = slice(i * width, i * width + d)
        b.in_proj_weight[new_rows].zero_()
        b.in_proj_weight[new_rows, :d].copy_(a.in_proj_weight[old_rows])
        b.in_proj_bias[new_rows].copy_(a.in_proj_bias[old_rows])
    _copy_residual_projection(a.out_proj, b.out_proj)


def _copy_leading_linear(source, target):
    rows, columns = source.weight.shape
    target.weight[:rows].zero_()
    target.weight[:rows, :columns].copy_(source.weight)
    target.bias[:rows].copy_(source.bias)


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
        _copy_attention(a.self_attn, b.self_attn)
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


@torch.no_grad()
def widen_card_outputs(original, medium):
    """Transfer the history, card trunk, belief, policy and both leaf outputs."""
    a, b = original.trunk, medium.trunk
    if (original.config["readout"] != medium.config["readout"]
            or a.config["x_hidden"] != b.config["x_hidden"]
            or not (a.config["card_self_attn"] and b.config["card_self_attn"])):
        raise ValueError("expected matching readout, context and card self-attention")
    widen_history(a, b)
    b.x_mlp.load_state_dict(a.x_mlp.state_dict())
    b.x_logits.load_state_dict(a.x_logits.state_dict())
    for name in ("x_to_q", "row_card"):
        _copy_residual_projection(getattr(a, name), getattr(b, name))

    for i, src in enumerate(a.xattn):
        dst = b.xattn[i]
        _copy_norm(a.ln_q[i], b.ln_q[i])
        _copy_leading_linear(src.q, dst.q)
        _copy_residual_projection(src.o, dst.o)
    for i in range(len(a.xattn), len(b.xattn)):
        for projection in (b.xattn[i].o, b.ff[i][-1]):
            projection.weight.zero_()
            projection.bias.zero_()
    for src, dst in [*zip(a.ff, b.ff), (a.self_ff, b.self_ff)]:
        _copy_norm(src[0], dst[0])
        _copy_leading_linear(src[1], dst[1])
        _copy_residual_projection(src[-1], dst[-1])
    _copy_norm(a.self_ln, b.self_ln)
    _copy_attention(a.self_attn, b.self_attn)
    for src, dst in ((a.out, b.out), (original.p_head, medium.p_head)):
        _copy_norm(src[0], dst[0])
        _copy_leading_linear(src[1], dst[1])
        dst[2:].load_state_dict(src[2:].state_dict())

    src, dst = original.readout, medium.readout
    _copy_norm(src.card_ln, dst.card_ln)
    _copy_leading_linear(src.card_proj, dst.card_proj)
    # The unchanged context precedes the original normalized card coordinates.
    _copy_leading_linear(src.ctx, dst.ctx)
    for name in ("stem", "ln", "up", "down", "out_ln", "value", "reply"):
        getattr(dst, name).load_state_dict(getattr(src, name).state_dict())
