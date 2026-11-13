#!/usr/bin/env python3
"""Write docs/visuals/search-pipeline.svg and models.svg, the README's search and model figures.

Edit the data blocks below, then run this script; `--check` exits 1 when either
committed SVG differs from what the data blocks generate. Stdlib only.

Every number comes from the README's search and model text (release 52). The
heatmap shades, world tiles, bar heights and tree shape are illustrative,
drawn from a fixed seed. Palette, fonts and helpers follow
build_decision_diagram.py: one dark palette on a rounded dark panel, the same
on GitHub's light and dark pages, because <img> ignores the page's CSS.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
OUT_SEARCH = HERE / "search-pipeline.svg"
OUT_MODELS = HERE / "models.svg"
SEED = 52

# Search figure data.

SEARCH_TITLE = "How the search works"
SEARCH_SUBTITLE = ("One card-play decision in release 52, left to right. Shades, tiles, bars and the tree "
                   "are illustrative; every number is the served setting.")

# Each panel: (colour token, kicker, headline, body lines, rule chips).
PANELS = [
    ("belief", "1 · BELIEF SAMPLING", "Draw 64 worlds",
     ["64 worlds kept; history tests",
      "on the first 512 draws; plain",
      "fill after 2,560.",
      "Belief prep over 0.25 s or an",
      "error → Monte Carlo sampler",
      "under the same tests."],
     ["bw"]),
    ("prior", "2 · CANDIDATES", "Admit 8 plays",
     ["Legal plays ≤ 4,000.",
      "Prior = summed card log-odds,",
      "averaged over 64 root worlds.",
      "div: ≤ 2 per shape, no near-",
      "duplicate throws. la: weak",
      "single lead → strongest pair",
      "or tractor in slot 1. sc8: a",
      "hand has > 7 cards → singles",
      "probed on 8 worlds."],
     ["div", "la", "sc8"]),
    ("value", "3 · VALUE PASS", "Score 8 × 64",
     ["512 positions, batches of 128;",
      "value = expected signed levels",
      "for the bot's team.",
      "tb: within 0.02 of the best →",
      "trick points decide.",
      "dtr: a lead throw refused in",
      "every world is dropped; dtrx:",
      "never below the exact mean."],
     ["lgf", "lgfx", "lgfd2000", "tb", "dtr", "dtrx"]),
    ("exact", "4 · EXACT ENDGAME", "≤ 7 cards a hand",
     ["Each play solved per world,",
      "hands face up: partnership",
      "minimax, alpha-beta and a",
      "transposition table; results",
      "averaged over the 64 worlds.",
      "Lead: own first trick (elm),",
      "kept only if strictly higher",
      "(elt), stops by 1.6 s (els1600).",
      "Follows: strictly higher only."],
     ["ele", "ed7", "xf7", "elm", "elt", "els1600"]),
    ("accent", "5 · CHOOSE", "Best mean wins",
     ["The admitted play with the",
      "best mean over the 64 worlds",
      "is played; an exact stage",
      "replaces it only on a strictly",
      "higher exact mean.",
      "Past the budget or on any",
      "error → the heuristic's",
      "choice."],
     []),
]
WORLDS, BELIEF_REJECTS = 64, ["whl", "whd", "wht", "rc", "rcec"]
SLOTS = [("heur.", "1"), ("prior", "2"), ("prior", "3"), ("prior", "4"),
         ("prior", "5"), ("prior", "6"), ("prior", "7"), ("prior", "8")]

# Budget timeline: seconds into the 3 s card-play budget.
BUDGET_S = 3.0
LANES = [  # (label, start, end, colour token)
    ("belief prep ≤ 0.25 s", 0.0, 0.25, "belief"),
    ("exact lead may start (first half)", 0.0, 1.5, "exact"),
    ("lgf greedy finish, stops at 2 s", 0.0, 2.0, "value"),
    ("exact stages stop by 80% = 2.4 s", 0.0, 2.4, "exact"),
]
LEAD_SOLVE_STOP = 1.6
MARKS = [(0.0, "0"), (1.0, "1 s"), (1.6, "1.6"), (2.0, "2"), (2.4, "2.4"), (3.0, "3 s")]

DECLARE = ("DECLARE", ["vd", "vdef"],
           ["Where the heuristic would declare,",
            "at the last chance, or at any chance",
            "in round 1 (vdef): each option and",
            "passing scored on 64 deals, each",
            "with the heuristic's bury and first",
            "trick; replaces the heuristic's",
            "choice only if strictly higher (vd)."])
BURY = ("BURY", ["bwv", "bbw"],
        ["Up to 64 candidate kitties (the",
         "heuristic's, structured alternatives,",
         "single-card swaps) scored on 32",
         "belief-drawn worlds; the best mean",
         "is kept (bwv, bbw).",
         "Budget 2 s per bury."])

SEARCH_ARIA = (
    "How the search works, as a five-stage pipeline. 1, belief sampling: the belief model reads the public "
    "history and gives each hidden card's holder probabilities, masked to the holders the public facts allow; "
    "64 worlds are kept, drawn worlds are rejected by the history tests whl, whd, wht, rc and rcec, which apply "
    "to the first 512 draws, the plain sampler fills any shortfall after 2,560, and belief preparation over "
    "0.25 s falls back to the Monte Carlo sampler. 2, candidates: up to 4,000 legal plays; the prior's summed "
    "card log-odds averaged over 64 root worlds rank them; 8 are admitted, the heuristic's play first, at most "
    "2 per shape (div), la on a weak single lead, and sc8 probing singles on 8 worlds when a hand has more "
    "than 7 cards. 3, value pass: each trick is finished by greedy replies (lgf, lgfx, lgfd2000) and 512 "
    "positions are scored in batches of 128 as expected signed levels; ties within 0.02 go to trick points "
    "(tb); dtr and dtrx drop refused lead throws. 4, exact endgame at 7 cards or fewer a hand: partnership "
    "minimax with alpha-beta and a transposition table per world, averaged (ele, ed7, xf7, elm, elt, "
    "els1600), switching only on a strictly higher mean. 5, choose: the best mean wins; past the budget or "
    "on error the heuristic's choice is played. A 3 second budget timeline: the heuristic decides first, "
    "belief preparation up to 0.25 s, the exact lead stage starts only in the first half and its solve stops "
    "by 1.6 s, lgf stops at 2 s, both exact stages stop by 2.4 s, the budget ends at 3 s. Side lanes: "
    "declaration scores each option and passing on 64 deals (vd, vdef); the bury scores up to 64 candidate "
    "kitties on 32 belief-drawn worlds within 2 s (bwv, bbw)."
)

# Models figure data.

MODELS_TITLE = "The models"
MODELS_SUBTITLE = "Release 52's three networks: what each reads, its shape, how it was trained and where the search calls it."

# Each block: (label, kind, side lines, side input); kind is "in", "op", "join" or "stack".
MODELS = [
    ("belief", "BELIEF", "B1a · 028131a0", "transformer · 3.2M parameters", [
        ("history tokens", "in", ["the round's earlier plays"], None),
        ("causal encoder × 4", "op", ["width 192, 4 heads"], None),
        ("cross-attend × 4", "op", [], "54 card queries"),
        ("card self-attention × 1", "op", [], None),
        ("+", "join", [], "1,115 public features → MLP 2 × 256"),
        ("54 × 4 holder logits", "op", ["next · partner ·", "previous · kitty"], None),
        ("mask → softmax, T 1.019", "op", ["allowed holders only"], None),
     ],
     ["S58 fine-tune on 10.3M decisions from",
      "Y self-play; target: each hidden",
      "card's true holder."],
     ["belief sampling (bw);", "bury worlds (bbw)"]),
    ("value", "VALUE", "G3 Stage A · f4f4127e", "residual MLP · 620k parameters", [
        ("833 inputs", "in", ["561 public + 5 × 54 deal", "counts + 2 perspective"], None),
        ("linear stem → 165", "op", [], None),
        ("residual block × 4", "stack", ["LayerNorm → 330 ReLU", "→ 165, + block input"], None),
        ("LayerNorm + ReLU", "op", [], None),
        ("204 outcome classes", "op", ["softmax"], None),
        ("Σ p × signed level", "op", ["expected signed level", "for the scorer's team"], None),
     ],
     ["Cross-entropy on round outcomes",
      "from 200k Y self-play rounds, warm",
      "from SMV3's trunk."],
     ["value pass; declare (vd, vdef);", "bury (bwv, bbw)"]),
    ("prior", "PRIOR", "FT1 · 1fa201b2", "the same residual MLP, 54-card policy head", [
        ("one root position", "in", ["one per sampled world"], None),
        ("same trunk as value", "stack", ["833 in, stem 165,", "4 residual blocks"], None),
        ("policy head → 54", "op", ["card log-odds"], None),
        ("raw log-odds", "op", ["no softmax,", "no temperature"], None),
        ("Σ over a play's cards", "op", [], None),
        ("mean over 64 worlds", "op", ["the play's prior score"], None),
     ],
     ["The policy net fine-tuned toward",
      "about 37.8k expert-search labels;",
      "its value head is not used."],
     ["candidates (8 admitted);", "lgf follows (top 4)"]),
]
MODELS_FOOT_1 = "Trained in PyTorch, exported to .npz, run in NumPy on the server CPU"
MODELS_FOOT_2 = ("Value positions go in batches of 128 · on Fly a release 52 decision takes p95 0.855 s "
                 "with one game running (DEPLOY.md, Latency)")

MODELS_ARIA = (
    "The models, three cards. Belief, B1a 028131a0, a transformer with 3.2M parameters: history tokens go "
    "through a causal 4-layer encoder of width 192 with 4 heads; 54 card queries cross-attend to it through "
    "4 layers, then one card self-attention layer; a 2-layer MLP of width 256 over 1,115 public features is "
    "added; the output is 54 by 4 holder logits for next player, partner, previous player and kitty, masked "
    "and turned into probabilities by a softmax at temperature 1.019. Trained by the S58 fine-tune on 10.3M "
    "decisions from Y self-play; used in belief sampling and the bury worlds. Value, G3 Stage A f4f4127e, a "
    "residual MLP with 620k parameters: 833 inputs, 561 public features plus 5 by 54 deal counts plus 2 for "
    "perspective, a stem to width 165, 4 residual blocks of LayerNorm, a 330-wide ReLU layer and back to 165, "
    "a final LayerNorm and ReLU, and 204 outcome classes whose softmax gives the expected signed level. "
    "Trained with cross-entropy on 200k Y self-play rounds, warm from SMV3; used in the value pass, declare "
    "and bury. Prior, FT1 1fa201b2, the same residual MLP with a 54-card policy head: one root position per "
    "world gives 54 card log-odds, used raw with no softmax and summed per play; fine-tuned toward about "
    "37.8k expert-search labels; used for candidates and lgf follows. All are trained in PyTorch, exported to "
    ".npz and run in NumPy on the server CPU; value positions go in batches of 128; on Fly a release 52 "
    "decision takes p95 0.855 seconds."
)

# Palette and type, shared with build_decision_diagram.py.

THEME = {"bg": "#1d242c", "panel": "#151a20", "edge": "#323c47", "fg": "#e6ebf0", "dim": "#c3ccd5",
         "muted": "#98a4b0", "accent": "#4fc1b9", "chip": "#232c36", "bad": "#f08a80",
         "belief": "#b39cf0", "prior": "#f2a46b", "value": "#7fb8ef", "exact": "#ef8fbe"}
TOKENS = ("belief", "prior", "value", "exact", "accent", "bad", "muted", "fg")

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
MONO_W = 0.61                # monospace advance per px of font size


def _rules(c: dict[str, str]) -> str:
    return (
        f".bg{{fill:{c['bg']}}}"
        f".box{{fill:{c['panel']};stroke-width:1.5}}"
        f".tile{{fill:{c['panel']};stroke:{c['muted']};stroke-width:1}}"
        f".h1{{font:600 22px {SANS};fill:{c['fg']}}}"
        f".t{{font:600 18px {SANS};fill:{c['fg']}}}"
        f".s{{font:15px {SANS};fill:{c['dim']}}}"
        f".body{{font:14.5px {SANS};fill:{c['dim']}}}"
        f".cap{{font:13px {SANS};fill:{c['dim']}}}"
        f".lab{{font:14px {SANS};fill:{c['fg']}}}"
        f".labb{{font:600 14px {SANS};fill:{c['fg']}}}"
        f".num{{font:13px {MONO};fill:{c['dim']}}}"
        f".k{{font:600 14px {MONO};letter-spacing:.06em}}"
        f".m{{font:13px {MONO};fill:{c['muted']}}}"
        f".chipt{{font:600 12px {MONO}}}"
        f".rule{{stroke:{c['edge']}}}"
        f".arrow{{stroke:{c['muted']};stroke-width:1.8;fill:none}}"
        f".thin{{stroke:{c['muted']};stroke-width:1.2;fill:none}}"
        f".dash{{stroke:{c['muted']};stroke-width:1.2;fill:none;stroke-dasharray:3 3}}"
        f".ah{{fill:{c['muted']}}}"
        f".bar{{fill:{c['chip']};stroke:{c['accent']};stroke-width:1.5}}"
        f".chip{{fill:{c['chip']};stroke-width:1}}"
        f".ring{{fill:none;stroke:{c['fg']};stroke-width:1.5}}"
        f".xm{{stroke:{c['bad']};stroke-width:2;stroke-linecap:round}}"
        + "".join(f".c-{n}{{fill:{c[n]}}}.b-{n}{{stroke:{c[n]}}}" for n in TOKENS)
    )


def _f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _text(x: float, y: float, cls: str, body: str, anchor: str = "") -> str:
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{_f(x)}" y="{_f(y)}" class="{cls}"{a}>{escape(body)}</text>'


def _rect(x, y, w, h, cls, opacity=None, rx=None, dashed=False) -> str:
    extra = f' fill-opacity="{opacity:.2f}"' if opacity is not None else ""
    extra += f' rx="{_f(rx)}"' if rx is not None else ""
    extra += ' stroke-dasharray="4 3"' if dashed else ""
    return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" class="{cls}"{extra}/>'


def _line(x1, y1, x2, y2, cls) -> str:
    return f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" class="{cls}"/>'


def _arrow(d: str) -> str:
    return f'<path class="arrow" d="{d}" marker-end="url(#ah)"/>'


def _cross(cx, cy, r) -> list[str]:
    return [_line(cx - r, cy - r, cx + r, cy + r, "xm"), _line(cx - r, cy + r, cx + r, cy - r, "xm")]


def _shade(v: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.08, (v - lo) / (hi - lo)))


def _chip_w(code: str) -> float:
    return 12 + len(code) * 12 * MONO_W


def _chip(x: float, y: float, code: str, tok: str) -> list[str]:
    w = _chip_w(code)
    return [_rect(x, y, w, 20, f"chip b-{tok}", rx=10), _text(x + w / 2, y + 14, f"chipt c-{tok}", code, "middle")]


def _chips(x: float, y: float, codes: list[str], tok: str, max_w: float) -> tuple[list[str], float]:
    """Lay chips left to right, wrapping at max_w; return the drawing and the bottom y."""
    out, cx, cy = [], x, y
    for code in codes:
        w = _chip_w(code)
        if cx > x and cx + w > x + max_w:
            cx, cy = x, cy + 26
        out.extend(_chip(cx, cy, code, tok))
        cx += w + 6
    return out, cy + 20


def _svg_open(width: int, height: int, title: str, aria: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="{escape(aria, {chr(34): "&quot;"})}">',
        f"<title>{escape(title)}</title>",
        "<style>" + _rules(THEME) + "</style>",
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" class="ah"/></marker></defs>',
        f'<rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="16"/>',
    ]


# Search figure layout.

S_W = 1400
P_X0, P_W, P_GAP, P_Y, P_H = 26, 252, 22, 76, 500
PAD = 14
S_VIS = P_Y + 68             # top of each panel's visual
S_TXT = P_Y + 266            # first body line
B_Y = P_Y + P_H + 18         # bottom row: timeline and side lanes
B_H = 196
S_H = B_Y + B_H + 16


def _belief_visual(tx: float, rng: random.Random) -> list[str]:
    out = [_text(tx, S_VIS + 10, "cap", "history")]
    for i in range(7):
        out.append(_rect(tx + i * 9, S_VIS + 18, 7, 12, "c-belief", 0.3 + 0.1 * i, rx=1))
    out.append(_arrow(f"M{_f(tx + 68)} {_f(S_VIS + 24)} H{_f(tx + 88)}"))
    hx, hy, cw, ch = tx + 94, S_VIS, 16, 9
    for r in range(5):
        weights = [rng.random() ** 2 for _ in range(4)]
        masked = rng.randrange(4) if r % 2 == 0 else None
        if masked is not None:
            weights[masked] = 0.0
        total = sum(weights)
        for c, w in enumerate(weights):
            if c == masked:
                out.append(_rect(hx + c * cw, hy + r * ch, cw - 1, ch - 1, "tile", dashed=True))
            else:
                out.append(_rect(hx + c * cw, hy + r * ch, cw - 1, ch - 1, "c-belief", _shade(w / total, 0, 0.8)))
    out.append(_text(hx + 4 * cw + 8, hy + 12, "cap", "P(holder)"))
    out.append(_text(hx + 4 * cw + 8, hy + 28, "cap", "per card,"))
    out.append(_text(hx + 4 * cw + 8, hy + 44, "cap", "masked"))
    out.append(_text(tx, S_VIS + 62, "cap", "dashed: holder ruled out"))
    ty, tw, th = S_VIS + 74, 9, 7
    for i in range(WORLDS):
        x, y = tx + (i % 8) * 12, ty + (i // 8) * 10
        out.append(_rect(x, y, tw, th, "tile", rx=1.5))
        out.append(f'<circle cx="{_f(x + 4.5)}" cy="{_f(y + 3.5)}" r="1.4" class="c-belief" '
                   f'fill-opacity="{0.4 + 0.6 * rng.random():.2f}"/>')
    rx = tx + 106
    out.append(_text(rx, ty + 10, "labb", f"{WORLDS} worlds kept"))
    out.append(_text(rx, ty + 32, "cap c-bad", "✕ rejected by"))
    chips, _ = _chips(rx, ty + 40, BELIEF_REJECTS, "bad", P_W - 2 * PAD - 106)
    out.extend(chips)
    return out


def _prior_visual(tx: float, rng: random.Random) -> list[str]:
    out = []
    sw, sh, gap = 49, 52, 9
    for i, (who, label) in enumerate(SLOTS):
        x, y = tx + (i % 4) * (sw + gap), S_VIS + (i // 4) * (sh + 10)
        first = i == 0
        out.append(_rect(x, y, sw, sh, "box b-fg" if first else "box b-prior", rx=5))
        if not first:
            out.append(_rect(x + 6, y + 24, sw - 12, 12 * (1 - i / 10), "c-prior", 0.5, rx=2))
        out.append(_text(x + sw / 2, y + 17, "cap", who, "middle"))
        out.append(_text(x + sw / 2, y + sh - 6, "m", label, "middle"))
    note_y = S_VIS + 2 * (sh + 10) + 14
    out.append(_text(tx, note_y, "cap", "slot 1: heuristic's play (la may swap);"))
    out.append(_text(tx, note_y + 17, "cap", "then best prior; sc8 may take slot 8"))
    return out


def _value_visual(tx: float, rng: random.Random) -> list[str]:
    out = [_text(tx, S_VIS + 10, "cap", "finish the trick (lgf):")]
    cy = S_VIS + 20
    labels = ["play", "reply", "reply", "reply"]
    for i, lab in enumerate(labels):
        x = tx + i * 56
        out.append(_rect(x, cy, 44, 26, "box b-value" if i == 0 else "box b-muted", rx=4))
        out.append(_text(x + 22, cy + 17, "cap", lab, "middle"))
        if i < 3:
            out.append(_arrow(f"M{_f(x + 45)} {_f(cy + 13)} H{_f(x + 54)}"))
    out.append(_text(tx, cy + 44, "cap", "each reply: best of the prior's top 4"))
    out.append(_text(tx, cy + 60, "cap", "follows + the heuristic's, for its team"))
    by, bh = cy + 74, 64
    means = [0.55 + 0.4 * rng.random() for _ in range(8)]
    best = max(range(8), key=lambda i: means[i])
    for i, m in enumerate(means):
        h = bh * m
        x = tx + 4 + i * 22
        out.append(_rect(x, by + bh - h, 15, h, "c-value", 1.0 if i == best else 0.45, rx=2))
    out.append(_rect(tx + 4 + best * 22 - 3, by - 3, 21, bh + 6, "ring", rx=3))
    out.append(_line(tx, by + bh + 1, tx + 180, by + bh + 1, "thin"))
    out.append(_text(tx + 186, by + 16, "cap", "mean"))
    out.append(_text(tx + 186, by + 32, "cap", "over 64"))
    out.append(_text(tx + 186, by + 48, "cap", "worlds"))
    return out


def _exact_visual(tx: float, rng: random.Random) -> list[str]:
    out = []
    root = (tx + 100, S_VIS + 12)
    out.append(f'<circle cx="{_f(root[0])}" cy="{_f(root[1])}" r="6" class="c-exact"/>')
    level1 = [tx + 30, tx + 100, tx + 170]
    for li, x1 in enumerate(level1):
        y1 = S_VIS + 66
        out.append(_line(root[0], root[1] + 6, x1, y1 - 5, "thin"))
        out.append(f'<circle cx="{_f(x1)}" cy="{_f(y1)}" r="5" class="c-exact" fill-opacity="0.7"/>')
        for k, dx in enumerate((-20, 0, 20)):
            x2, y2 = x1 + dx, S_VIS + 116
            pruned = (li + k) % 3 == 2
            out.append(_line(x1, y1 + 5, x2, y2 - 4, "dash" if pruned else "thin"))
            if pruned:
                out.extend(_cross(x2, y2, 3.5))
            else:
                out.append(f'<circle cx="{_f(x2)}" cy="{_f(y2)}" r="3.5" class="c-exact" fill-opacity="0.5"/>')
    out.append(_text(root[0] + 12, root[1] + 5, "cap", "max (our side)"))
    out.append(_text(level1[2] + 10, S_VIS + 70, "cap", "min"))
    out.append(_text(tx, S_VIS + 146, "cap", "dashed ✕: alpha-beta cut; repeats"))
    out.append(_text(tx, S_VIS + 163, "cap", "read from the transposition table"))
    return out


def _choose_visual(tx: float, rng: random.Random) -> list[str]:
    out = []
    cx, cy = tx + 20, S_VIS + 6
    out.append(_rect(cx, cy, 70, 96, "box b-accent", rx=7))
    out.append(_text(cx + 35, cy + 42, "labb", "best", "middle"))
    out.append(_text(cx + 35, cy + 62, "labb", "mean", "middle"))
    out.append(_text(cx + 110, cy + 40, "cap", "play it"))
    out.append(_arrow(f"M{_f(cx + 72)} {_f(cy + 48)} H{_f(cx + 106)}"))
    fy = cy + 124
    out.append(_rect(cx, fy, 70, 34, "box b-muted", rx=6, dashed=True))
    out.append(_text(cx + 35, fy + 22, "cap", "heuristic", "middle"))
    out.append(_text(cx + 84, fy + 14, "cap", "budget passed"))
    out.append(_text(cx + 84, fy + 30, "cap", "or any error"))
    return out


S_VISUALS = [_belief_visual, _prior_visual, _value_visual, _exact_visual, _choose_visual]


def _timeline(x: float, y: float, w: float) -> list[str]:
    out = [_rect(x, y, w, B_H, "box b-muted", rx=12)]
    out.append(_text(x + PAD, y + 26, "k c-fg", "BUDGET · 3 s PER DECISION"))
    out.append(_text(x + w - PAD, y + 26, "cap", "card play and declaration; checked between draws and model batches",
                     "end"))
    ax0, ax1 = x + 52, x + w - 40
    sec = (ax1 - ax0) / BUDGET_S
    ly = y + 46
    for i, (label, s0, s1, tok) in enumerate(LANES):
        yy = ly + i * 24
        bw = (s1 - s0) * sec
        out.append(_rect(ax0 + s0 * sec, yy, bw, 17, f"c-{tok}", 0.28, rx=3))
        out.append(_line(ax0 + s1 * sec, yy - 2, ax0 + s1 * sec, yy + 19, f"b-{tok} thin"))
        if bw > len(label) * 7 + 16:
            out.append(_text(ax0 + s0 * sec + 8, yy + 13, "cap", label))
        else:
            out.append(_text(ax0 + s1 * sec + 8, yy + 13, "cap", label))
    lead_y = ly + 24
    sx = ax0 + LEAD_SOLVE_STOP * sec
    out.append(_line(ax0 + 1.5 * sec, lead_y + 8.5, sx, lead_y + 8.5, "b-exact thin"))
    out.append(_line(sx, lead_y - 2, sx, lead_y + 19, "b-exact thin"))
    out.append(_text(sx + 8, lead_y + 13, "cap", "lead solve stops by 1.6 s (els1600)"))
    axis_y = ly + len(LANES) * 24 + 10
    out.append(_line(ax0, axis_y, ax1, axis_y, "arrow"))
    for t, lab in MARKS:
        xx = ax0 + t * sec
        out.append(_line(xx, axis_y - 4, xx, axis_y + 4, "arrow"))
        out.append(_text(xx, axis_y + 18, "num", lab, "middle"))
    out.append(_line(ax1, ly - 6, ax1, axis_y, "dash"))
    out.append(_text(ax1 - 6, ly + 3 * 24 + 13, "cap", "budget ends", "end"))
    out.append(f'<circle cx="{_f(ax0)}" cy="{_f(axis_y)}" r="5" class="c-accent"/>')
    out.append(_text(x + PAD, axis_y + 40, "cap",
                     "0 s: the heuristic decides first, so a choice always exists. "
                     "3 s: the budget ends; past it the bot plays the heuristic's choice."))
    return out


def _side(x: float, y: float, w: float, spec, tok: str) -> list[str]:
    kicker, codes, lines = spec
    out = [_rect(x, y, w, B_H, f"box b-{tok}", rx=12), _text(x + PAD, y + 26, f"k c-{tok}", kicker)]
    cw = sum(_chip_w(c) + 6 for c in codes) - 6
    chips, _ = _chips(x + w - PAD - cw, y + 11, codes, tok, cw + 1)
    out.extend(chips)
    out.extend(_text(x + PAD, y + 52 + 19 * j, "cap", line) for j, line in enumerate(lines))
    return out


def build_search() -> str:
    rng = random.Random(SEED)
    out = _svg_open(S_W, S_H, SEARCH_TITLE, SEARCH_ARIA)
    out += [_text(P_X0, 36, "h1", SEARCH_TITLE), _text(P_X0, 60, "s", SEARCH_SUBTITLE)]
    for i, (tok, kicker, head, body, codes) in enumerate(PANELS):
        x = P_X0 + i * (P_W + P_GAP)
        tx = x + PAD
        out.append(_rect(x, P_Y, P_W, P_H, f"box b-{tok}", rx=12))
        out.append(_text(tx, P_Y + 28, f"k c-{tok}", kicker))
        out.append(_text(tx, P_Y + 53, "t", head))
        out.extend(S_VISUALS[i](tx, rng))
        out.append(_line(tx, S_TXT - 24, x + P_W - PAD, S_TXT - 24, "rule"))
        out.extend(_text(tx, S_TXT + 19.5 * j, "body", line) for j, line in enumerate(body))
        if codes:
            n_rows = 1
            cx = 0.0
            for c in codes:
                if cx and cx + _chip_w(c) > P_W - 2 * PAD:
                    n_rows, cx = n_rows + 1, 0.0
                cx += _chip_w(c) + 6
            chips, _ = _chips(tx, P_Y + P_H - 14 - 20 - 26 * (n_rows - 1), codes, tok, P_W - 2 * PAD)
            out.extend(chips)
        if i < len(PANELS) - 1:
            ay = P_Y + 40
            out.append(_arrow(f"M{_f(x + P_W + 2)} {_f(ay)} H{_f(x + P_W + P_GAP - 2)}"))
    tl_w = 3 * P_W + 2 * P_GAP
    out.extend(_timeline(P_X0, B_Y, tl_w))
    sx = P_X0 + tl_w + P_GAP
    out.extend(_side(sx, B_Y, P_W, DECLARE, "value"))
    out.extend(_side(sx + P_W + P_GAP, B_Y, P_W, BURY, "belief"))
    out.append("</svg>")
    return "\n".join(out) + "\n"


# Models figure layout.

M_W = 1200
C_X0, C_W, C_GAP, C_Y, C_H = 16, 380, 18, 76, 604
SK_Y = C_Y + 104             # top of the architecture sketch
BLK_W, BLK_H, BLK_STEP = 180, 30, 44
M_FOOT_Y = C_Y + C_H + 18
M_H = M_FOOT_Y + 62 + 16


def _model_sketch(tx: float, tok: str, blocks) -> tuple[list[str], float]:
    out = []
    y = SK_Y
    side_x = tx + BLK_W + 16
    for i, (label, kind, side, side_in) in enumerate(blocks):
        cx = tx + BLK_W / 2
        if kind == "join":
            out.append(f'<circle cx="{_f(cx)}" cy="{_f(y + BLK_H / 2)}" r="12" class="chip b-{tok}" '
                       f'stroke-width="1.5"/>')
            out.append(_text(cx, y + BLK_H / 2 + 6, "labb", label, "middle"))
            edge = cx + 14
        else:
            if kind == "stack":
                out.append(_rect(tx + 6, y - 6, BLK_W, BLK_H, f"box b-{tok}", rx=6))
                out.append(_rect(tx + 3, y - 3, BLK_W, BLK_H, f"box b-{tok}", rx=6))
            out.append(_rect(tx, y, BLK_W, BLK_H, f"box b-{tok}", rx=6, dashed=kind == "in"))
            if kind != "in":
                out.append(_rect(tx, y, BLK_W, BLK_H, f"c-{tok}", 0.16, rx=6))
            out.append(_text(cx, y + 20, "lab", label, "middle"))
            edge = tx + BLK_W + 2
        if side_in:
            words = side_in.split(" → ")
            lines = [side_in] if len(side_in) <= 22 else [words[0] + " →", words[1]] if len(words) == 2 else [side_in]
            for j, line in enumerate(lines):
                out.append(_text(side_x + 18, y + 12 + 16 * j - 8 * (len(lines) - 1) + 4, "cap", line))
            out.append(_arrow(f"M{_f(side_x + 14)} {_f(y + BLK_H / 2)} H{_f(edge + 2)}"))
        for j, line in enumerate(side):
            out.append(_text(side_x, y + 20 + 16 * j - 8 * (len(side) - 1), "cap", line))
        if i < len(blocks) - 1:
            out.append(_arrow(f"M{_f(cx)} {_f(y + BLK_H + 1)} V{_f(y + BLK_STEP - 2 - (6 if blocks[i + 1][1] == 'stack' else 0))}"))
        y += BLK_STEP
    return out, y


def build_models() -> str:
    out = _svg_open(M_W, M_H, MODELS_TITLE, MODELS_ARIA)
    out += [_text(C_X0, 36, "h1", MODELS_TITLE), _text(C_X0, 60, "s", MODELS_SUBTITLE)]
    for i, (tok, kicker, name, shape, blocks, trained, used) in enumerate(MODELS):
        x = C_X0 + i * (C_W + C_GAP)
        tx = x + 18
        out.append(_rect(x, C_Y, C_W, C_H, f"box b-{tok}", rx=12))
        out.append(_text(tx, C_Y + 28, f"k c-{tok}", kicker))
        out.append(_text(tx, C_Y + 55, "t", name))
        out.append(_text(tx, C_Y + 78, "s", shape))
        sketch, _ = _model_sketch(tx, tok, blocks)
        out.extend(sketch)
        ry = SK_Y + 7 * BLK_STEP + 4
        out.append(_line(tx, ry, x + C_W - 18, ry, "rule"))
        out.append(_text(tx, ry + 24, f"m c-{tok}", "TRAINED"))
        out.extend(_text(tx, ry + 46 + 19.5 * j, "body", line) for j, line in enumerate(trained))
        uy = ry + 46 + 19.5 * len(trained) + 14
        out.append(_text(tx, uy, f"m c-{tok}", "USED IN"))
        out.extend(_text(tx, uy + 22 + 19.5 * j, "body", line) for j, line in enumerate(used))
    bar_w = 3 * C_W + 2 * C_GAP
    out.append(_rect(C_X0, M_FOOT_Y, bar_w, 62, "bar", rx=12))
    out.append(_text(C_X0 + 16, M_FOOT_Y + 26, "t", MODELS_FOOT_1))
    out.append(_text(C_X0 + 16, M_FOOT_Y + 48, "s", MODELS_FOOT_2))
    out.append("</svg>")
    return "\n".join(out) + "\n"


TARGETS = [(OUT_SEARCH, build_search), (OUT_MODELS, build_models)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if a committed SVG is stale")
    args = ap.parse_args(argv)
    stale = 0
    for out, build in TARGETS:
        svg = build()
        if args.check:
            if not out.exists() or out.read_text(encoding="utf-8") != svg:
                print(f"{out.name} is stale: run python3 docs/visuals/build_search_models.py", file=sys.stderr)
                stale = 1
            else:
                print(f"{out.name}: up to date")
            continue
        out.write_text(svg, encoding="utf-8")
        print(f"wrote {out}")
    return stale


if __name__ == "__main__":
    sys.exit(main())
