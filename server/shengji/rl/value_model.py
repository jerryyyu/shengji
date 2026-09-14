"""Compact state-only GRU/Transformer value network, plus an MLP fast path.

All architectures consume the same afterstate tensors and emit the same
ordered 204-category terminal distribution.  The GRU is the historical
throughput baseline; the Transformer is the preferred trajectory experiment.
The ``mlp`` architecture is the batched fast path for search consumers: it
reads the fixed-size public, world and perspective tensors only
(concatenated, ``feedforward_width -> width`` trunk, GELU, dropout); the
history tensors are validated for the shared batch contract and otherwise
ignored.  No architecture receives a candidate action or search-policy
feature.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Mapping

import numpy as np
import torch
from torch import nn

from .douzero_micro import HISTORY_EVENT_DIM, HISTORY_MAX_EVENTS
from .value_afterstate import (
    OUTCOME_CLASSES,
    PERSPECTIVE_DIM,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
)
from .encode import N_CARDS
from .encode_versions import ENC_VERSION, OBS_DIM_BY_VERSION, check_version


MLP_INPUT_DIM = PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM
#: the two ADDITIVE config fields: absent from every archived payload, in
#: which case they take the v1 defaults and the rebuilt net is byte-identical
_WIDTH_FIELDS = ("public_dim", "enc_version")
#: omitted from a payload whose trunk is the legacy depth-2 plain shape, so
#: every checkpoint archived before the depth arms existed still loads.
_TRUNK_FIELDS = ("trunk_layers", "trunk_block")
_LEGACY_TRUNK = {"trunk_layers": 2, "trunk_block": "plain"}
#: #373: an optional second 204-class head on the same mlp trunk, trained on
#: the search-mean soft target, and the name of the head every consumer reads
#: (``value_head``).  Omitted from the payload at the legacy values so every
#: checkpoint trained before the option existed keeps its stored config.
_HEAD_FIELDS = ("search_head", "value_head")
_LEGACY_HEAD = {"search_head": False, "value_head": "outcome"}
#: #411: the ``grid`` trunk block's convolution width; omitted from every
#: payload whose trunk is not a grid, so archived configs compare unchanged.
_GRID_FIELDS = ("grid_channels",)
_LEGACY_GRID = {"grid_channels": 0}
VALUE_HEADS = ("outcome", "search-mean")


def mlp_input_dim(public_dim: int = PUBLIC_DIM) -> int:
    return int(public_dim) + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM


class ValueModelError(ValueError):
    """A model configuration, batch, or parameter state drifted."""


@dataclass(frozen=True)
class ValueModelConfig:
    architecture: str = "transformer"
    width: int = 64
    history_layers: int = 2
    attention_heads: int = 4
    feedforward_width: int = 128
    trunk_layers: int = 2
    trunk_block: str = "plain"
    grid_channels: int = 0
    dropout: float = 0.0
    max_history: int = HISTORY_MAX_EVENTS
    outcome_classes: int = OUTCOME_CLASSES
    #: the public tensor width this net reads and the observation encoder
    #: version it implies.  Defaults are v1; ``payload()`` omits them at the
    #: defaults so a v1 checkpoint's stored config is what it always was.
    public_dim: int = PUBLIC_DIM
    enc_version: int = ENC_VERSION
    #: #373 two-head net: ``search_head`` adds ``ValueNetwork.search_head``
    #: (mlp only); ``value_head`` names the head ``forward`` returns by
    #: default ("outcome" = the realised-outcome head every model has).
    search_head: bool = False
    value_head: str = "outcome"

    def validate(self) -> None:
        try:
            enc_version = check_version(self.enc_version)
        except ValueError as exc:
            raise ValueModelError("model configuration drift") from exc
        if type(self.public_dim) is not int \
                or self.public_dim != OBS_DIM_BY_VERSION[enc_version] + 1:
            raise ValueModelError("model configuration drift: public_dim does not "
                                  "match the encoder version")
        integer_fields = (
            self.width, self.history_layers, self.attention_heads,
            self.feedforward_width, self.max_history, self.outcome_classes)
        if type(self.architecture) is not str \
                or self.architecture not in ("transformer", "gru", "mlp"):
            raise ValueModelError("architecture must be transformer, gru or mlp")
        if any(type(value) is not int for value in integer_fields) \
                or isinstance(self.dropout, bool) \
                or not isinstance(self.dropout, (int, float)) \
                or not math.isfinite(float(self.dropout)) \
                or self.width < 8 or self.history_layers < 1 \
                or self.attention_heads < 1 \
                or self.width % self.attention_heads != 0 \
                or self.feedforward_width < self.width \
                or not 0.0 <= self.dropout < 1.0 \
                or self.max_history < 1 \
                or self.outcome_classes != OUTCOME_CLASSES \
                or type(self.trunk_layers) is not int or self.trunk_layers < 2 \
                or self.trunk_layers > 64 \
                or type(self.trunk_block) is not str \
                or self.trunk_block not in ("plain", "residual", "grid") \
                or type(self.grid_channels) is not int \
                or (self.trunk_block == "grid") != (self.grid_channels > 0) \
                or self.grid_channels > 1024:
            raise ValueModelError("model configuration drift")
        if type(self.search_head) is not bool or type(self.value_head) is not str \
                or self.value_head not in VALUE_HEADS:
            raise ValueModelError("model configuration drift")
        if self.search_head and self.architecture != "mlp":
            raise ValueModelError("model configuration drift: the search-mean head "
                                  "reads the mlp trunk")
        if self.value_head == "search-mean" and not self.search_head:
            raise ValueModelError("model configuration drift: value_head names a "
                                  "search-mean head this net does not have")

    def payload(self) -> dict[str, object]:
        self.validate()
        out = asdict(self)
        if self.enc_version == ENC_VERSION and self.public_dim == PUBLIC_DIM:
            # v1 payloads are unchanged: archived checkpoints compare their
            # stored config against this, field for field
            for name in _WIDTH_FIELDS:
                del out[name]
        if all(getattr(self, k) == v for k, v in _LEGACY_TRUNK.items()):
            for name in _TRUNK_FIELDS:
                del out[name]
        if all(getattr(self, k) == v for k, v in _LEGACY_HEAD.items()):
            for name in _HEAD_FIELDS:
                del out[name]
        if all(getattr(self, k) == v for k, v in _LEGACY_GRID.items()):
            for name in _GRID_FIELDS:
                del out[name]
        return out

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> "ValueModelConfig":
        base = set(asdict(cls())) - set(_WIDTH_FIELDS) - set(_TRUNK_FIELDS) \
            - set(_HEAD_FIELDS) - set(_GRID_FIELDS)
        allowed = {frozenset(base | w | t | h | g)
                   for w in (set(), set(_WIDTH_FIELDS))
                   for t in (set(), set(_TRUNK_FIELDS))
                   for h in (set(), set(_HEAD_FIELDS))
                   for g in (set(), set(_GRID_FIELDS))}
        if type(value) is not dict or frozenset(value) not in allowed:
            raise ValueModelError("model configuration schema drift")
        try:
            config = cls(**value)
        except TypeError as exc:
            raise ValueModelError("model configuration schema drift") from exc
        try:
            config.validate()
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueModelError):
                raise
            raise ValueModelError("model configuration drift") from exc
        return config


class ResidualTrunkBlock(nn.Module):
    """The tabular ResNet block of Gorishniy et al. 2021 (arXiv:2106.11959),
    which that paper finds no competitor consistently outperforms:
    ``x + Dropout(Linear(Dropout(ReLU(Linear(Norm(x))))))``.  Depth alone
    does not train in a plain MLP trunk; the normalisation and the skip are
    what make the depth arm a test of depth rather than of optimisation.

    ``Norm`` is LayerNorm, not the paper's default BatchNorm: the block store
    yields whatever trailing batch a window leaves, including a single row,
    and BatchNorm refuses a one-row batch in training mode.  LayerNorm is
    batch-size independent (the paper reports it as an equivalent choice),
    has the same parameter count, and makes every batch the loop can yield
    trainable."""

    def __init__(self, width: int, feedforward_width: int, dropout: float):
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.up = nn.Linear(width, feedforward_width)
        self.down = nn.Linear(feedforward_width, width)
        self.drop_inner = nn.Dropout(dropout)
        self.drop_outer = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.norm(x)
        h = torch.relu(self.up(h))
        h = self.drop_inner(h)
        h = self.down(h)
        return x + self.drop_outer(h)


class GridTrunk(nn.Module):
    """#411: the ``grid`` trunk block.  Lays the fourteen card planes out as
    ``GRID_ROWS x GRID_COLS`` cells (``card_grid``), convolves ALONG each row
    (kernel 3, weights shared across rows and ranks: "this level and its
    neighbours"), summarises every row by mean and max and pastes the summary
    back onto each of its cells, convolves once more, and hands the heads
    three views: a cheap per-cell projection (where exactly), the five row
    summaries (what each suit holds) and a global mean/max over rows, plus the
    non-card public columns untouched.  The stem projects to ``width`` and the
    same residual blocks as ``trunk_block=residual`` follow, so the two arms
    differ only in how the planes are read."""

    CELL_PROJ = 8
    COL_EMBED = 8

    def __init__(self, config: "ValueModelConfig"):
        super().__init__()
        from .card_grid import (GRID_COLS, GRID_ROWS, RANK_ONEHOT_OFFSET, SUIT_ONEHOT_OFFSET,
                                grid_table)
        self.public_dim = config.public_dim
        self.n_planes = 9 + WORLD_RECEIVERS
        self.scalar_dim = config.public_dim - 9 * N_CARDS
        self.rows, self.cols = GRID_ROWS, GRID_COLS
        self.suit_off, self.rank_off = SUIT_ONEHOT_OFFSET, RANK_ONEHOT_OFFSET
        self.register_buffer("table", torch.from_numpy(grid_table()), persistent=False)
        c = config.grid_channels
        cin = self.n_planes + GRID_ROWS + self.COL_EMBED
        self.col_embed = nn.Parameter(torch.zeros(self.COL_EMBED, 1, GRID_COLS))
        nn.init.normal_(self.col_embed, std=0.1)
        self.conv1 = nn.Conv2d(cin, c, kernel_size=(1, 3), padding=(0, 1))
        self.conv2 = nn.Conv2d(c, c, kernel_size=(1, 3), padding=(0, 1))
        self.conv3 = nn.Conv2d(3 * c, c, kernel_size=(1, 3), padding=(0, 1))
        self.cell_proj = nn.Conv2d(c, self.CELL_PROJ, kernel_size=1)
        feat = (self.CELL_PROJ * GRID_ROWS * GRID_COLS + 2 * c * GRID_ROWS + 4 * c
                + self.scalar_dim + PERSPECTIVE_DIM)
        width = config.width
        blocks = [ResidualTrunkBlock(width, config.feedforward_width, config.dropout)
                  for _ in range(config.trunk_layers)]
        self.stem = nn.Linear(feat, width)
        self.blocks = nn.Sequential(*blocks, nn.LayerNorm(width), nn.ReLU())
        self.drop = nn.Dropout(config.dropout)

    def grid(self, x: torch.Tensor) -> torch.Tensor:
        """``(batch, planes, rows, cols)`` cells of the concatenated input."""
        b = x.shape[0]
        public = x[:, :self.public_dim]
        world = x[:, self.public_dim:self.public_dim + WORLD_RECEIVERS * N_CARDS]
        planes = torch.cat((public[:, :9 * N_CARDS].reshape(b, 9, N_CARDS),
                            world.reshape(b, WORLD_RECEIVERS, N_CARDS)), dim=1)
        planes = torch.cat((planes, planes.new_zeros(b, self.n_planes, 1)), dim=2)
        suit = public[:, self.suit_off:self.suit_off + 5].argmax(dim=1)
        rank = public[:, self.rank_off:self.rank_off + 13].argmax(dim=1)
        slots = self.table[suit * 13 + rank]                       # (b, rows*cols)
        idx = slots.unsqueeze(1).expand(b, self.n_planes, slots.shape[1])
        return torch.gather(planes, 2, idx).reshape(b, self.n_planes, self.rows, self.cols)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b = x.shape[0]
        g = self.grid(x)
        row_id = torch.eye(self.rows, device=x.device, dtype=x.dtype)
        row_id = row_id.t().reshape(1, self.rows, self.rows, 1).expand(b, -1, -1, self.cols)
        col = self.col_embed.unsqueeze(0).expand(b, -1, self.rows, -1)
        h = torch.cat((g, row_id, col), dim=1)
        h = torch.nn.functional.gelu(self.conv1(h))
        h = torch.nn.functional.gelu(self.conv2(h))
        row_mean = h.mean(dim=3, keepdim=True).expand(-1, -1, -1, self.cols)
        row_max = h.amax(dim=3, keepdim=True).expand(-1, -1, -1, self.cols)
        h = torch.nn.functional.gelu(self.conv3(torch.cat((h, row_mean, row_max), dim=1)))
        cells = self.cell_proj(h).reshape(b, -1)
        rows = torch.cat((h.mean(dim=3), h.amax(dim=3)), dim=1)      # (b, 2c, rows)
        glob = torch.cat((rows.mean(dim=2), rows.amax(dim=2)), dim=1)
        scalars = x[:, 9 * N_CARDS:self.public_dim]
        perspective = x[:, -PERSPECTIVE_DIM:]
        feat = torch.cat((cells, rows.reshape(b, -1), glob, scalars, perspective), dim=1)
        return self.blocks(self.drop(self.stem(feat)))


class ValueNetwork(nn.Module):
    """One state-only value model with a selectable history encoder."""

    def __init__(self, config: ValueModelConfig = ValueModelConfig()):
        super().__init__()
        config.validate()
        self.config = config
        width = config.width
        if config.architecture == "mlp":
            # The fast path: one trunk over the concatenated fixed-size
            # tensors; no history encoder is built.  The sequence
            # architectures below are constructed exactly as before.
            self.history_position = None
            self.history_encoder = None
            din = mlp_input_dim(config.public_dim)
            if config.trunk_layers == 2 and config.trunk_block == "plain":
                # UNCHANGED PATH: byte-identical to every model trained so far.
                self.trunk = nn.Sequential(
                    nn.Linear(din, config.feedforward_width),
                    nn.GELU(),
                    nn.Dropout(config.dropout),
                    nn.Linear(config.feedforward_width, width), nn.GELU(),
                    nn.Dropout(config.dropout))
            elif config.trunk_block == "plain":
                # naive depth: the same block repeated, no normalisation, no skip.
                # Expected to degrade past ~4 layers; that is the point of the arm.
                mods = [nn.Linear(din, config.feedforward_width), nn.GELU(),
                        nn.Dropout(config.dropout)]
                for _ in range(config.trunk_layers - 2):
                    mods += [nn.Linear(config.feedforward_width, config.feedforward_width),
                             nn.GELU(), nn.Dropout(config.dropout)]
                mods += [nn.Linear(config.feedforward_width, width), nn.GELU(),
                         nn.Dropout(config.dropout)]
                self.trunk = nn.Sequential(*mods)
            elif config.trunk_block == "residual":
                # Gorishniy et al. 2021 tabular ResNet block, arXiv:2106.11959:
                #   block(x) = x + Dropout(Linear(Dropout(ReLU(Linear(LayerNorm(x))))))
                # stem projects to `width`; every block is width -> ffw -> width.
                blocks = [ResidualTrunkBlock(width, config.feedforward_width,
                                             config.dropout)
                          for _ in range(config.trunk_layers)]
                self.trunk = nn.Sequential(nn.Linear(din, width), *blocks,
                                           nn.LayerNorm(width), nn.ReLU())
            elif config.trunk_block == "grid":
                # #411: the card planes read as a suit x level table.
                self.trunk = GridTrunk(config)
            else:
                raise ValueModelError("trunk_block must be plain, residual or grid")
            self.head = nn.Linear(width, OUTCOME_CLASSES)
            if config.search_head:
                # #373: the second head, same trunk, search-mean soft target.
                self.search_head = nn.Linear(width, OUTCOME_CLASSES)
            return
        self.public_encoder = nn.Sequential(
            nn.Linear(config.public_dim, width), nn.ReLU(), nn.LayerNorm(width))
        self.world_encoder = nn.Sequential(
            nn.Linear(WORLD_RECEIVERS * N_CARDS, width), nn.ReLU(),
            nn.LayerNorm(width))
        self.perspective_encoder = nn.Sequential(
            nn.Linear(PERSPECTIVE_DIM, width), nn.ReLU(), nn.LayerNorm(width))
        self.history_input = nn.Linear(HISTORY_EVENT_DIM, width)
        if config.architecture == "transformer":
            self.history_position = nn.Embedding(config.max_history, width)
            layer = nn.TransformerEncoderLayer(
                d_model=width, nhead=config.attention_heads,
                dim_feedforward=config.feedforward_width,
                dropout=config.dropout, activation="gelu", batch_first=True)
            self.history_encoder: nn.Module = nn.TransformerEncoder(
                layer, num_layers=config.history_layers,
                enable_nested_tensor=False)
        else:
            self.history_position = None
            self.history_encoder = nn.GRU(
                width, width, num_layers=config.history_layers,
                dropout=(config.dropout if config.history_layers > 1 else 0.0),
                batch_first=True)
        self.fused = nn.Sequential(
            nn.Linear(4 * width, 2 * width), nn.GELU(),
            nn.LayerNorm(2 * width), nn.Linear(2 * width, OUTCOME_CLASSES))

    def features(self, public: torch.Tensor, world: torch.Tensor,
                 perspective: torch.Tensor) -> torch.Tensor:
        """The mlp trunk's ``width``-dim embedding of the fixed-size tensors
        (an auxiliary head may read it); the sequence architectures expose
        no intermediate."""
        if self.config.architecture != "mlp":
            raise ValueModelError("features are exposed by the mlp architecture only")
        return self.trunk(torch.cat(
            (public, world.flatten(start_dim=1), perspective), dim=1))

    def head_logits(self, features: torch.Tensor, head: str | None = None) -> torch.Tensor:
        """The named head's 204-class logits over mlp trunk features;
        ``None`` = the configured ``value_head``.  A head this net does not
        have is a named refusal, never a silent fallback to the other."""
        if self.config.architecture != "mlp":
            raise ValueModelError("head selection is exposed by the mlp architecture only")
        head = self.config.value_head if head is None else head
        if head == "outcome":
            return self.head(features)
        if head == "search-mean":
            if not self.config.search_head:
                raise ValueModelError("this net has no search-mean head")
            return self.search_head(features)
        raise ValueModelError(f"unknown value head {head!r}")

    def _history_context(self, history: torch.Tensor,
                         history_mask: torch.Tensor) -> torch.Tensor:
        encoded = self.history_input(history)
        if self.config.architecture == "transformer":
            positions = torch.arange(
                history.shape[1], device=history.device).unsqueeze(0)
            encoded = encoded + self.history_position(positions)
            encoded = self.history_encoder(
                encoded, src_key_padding_mask=~history_mask)
            weights = history_mask.unsqueeze(-1).to(encoded.dtype)
            return (encoded * weights).sum(dim=1) / weights.sum(dim=1)
        output, _hidden = self.history_encoder(encoded)
        last = history_mask.sum(dim=1) - 1
        return output[torch.arange(output.shape[0], device=output.device), last]

    def forward(self, public: torch.Tensor, history: torch.Tensor,
                history_mask: torch.Tensor, world: torch.Tensor,
                perspective: torch.Tensor, head: str | None = None) -> torch.Tensor:
        batch = public.shape[0]
        if public.shape != (batch, self.config.public_dim) \
                or history.ndim != 3 or history.shape[0] != batch \
                or history.shape[2] != HISTORY_EVENT_DIM \
                or history.shape[1] > self.config.max_history \
                or history_mask.shape != history.shape[:2] \
                or history_mask.dtype != torch.bool \
                or not bool(torch.all(history_mask.any(dim=1))) \
                or world.shape != (batch, WORLD_RECEIVERS, N_CARDS) \
                or perspective.shape != (batch, PERSPECTIVE_DIM):
            raise ValueModelError("model batch shape drift")
        if self.config.architecture == "mlp":
            return self.head_logits(self.features(public, world, perspective), head)
        if head not in (None, "outcome"):
            raise ValueModelError("the sequence architectures have one head")
        context = torch.cat((
            self.public_encoder(public),
            self._history_context(history, history_mask),
            self.world_encoder(world.flatten(start_dim=1)),
            self.perspective_encoder(perspective),
        ), dim=1)
        return self.fused(context)


def model_state_sha256(model: ValueNetwork) -> str:
    """Stable logical-state hash independent of checkpoint container bytes."""
    if type(model) is not ValueNetwork:
        raise ValueModelError("state hash requires an exact ValueNetwork")
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        array = value.detach().cpu().contiguous().numpy()
        if array.dtype.byteorder not in ("<", "|", "="):
            array = array.byteswap().view(array.dtype.newbyteorder("<"))
        elif array.dtype.byteorder == "=" and not np.little_endian:
            array = array.byteswap().view(array.dtype.newbyteorder("<"))
        label = name.encode("utf-8")
        shape = ",".join(str(size) for size in array.shape).encode("ascii")
        dtype = str(array.dtype.newbyteorder("<")).encode("ascii")
        payload = array.tobytes(order="C")
        for part in (label, shape, dtype, payload):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()
