#!/usr/bin/env python3
"""Write docs/visuals/decision-steps.svg, the README's "One decision, four steps" figure.

Edit the data block below, then run this script; `--check` exits 1 when the
committed SVG differs from what the data block generates. Stdlib only.

GitHub shows README images through <img>, which ignores the page's CSS, so the
SVG carries its own colours: one dark palette on a rounded dark panel, the
same on GitHub's light and dark pages, with system font stacks.

The heatmap cells, deal tiles, faint bars and tree shape are illustrative,
drawn from a fixed seed; the example numbers (deal counts, policy log-odds of
the admitted plays, value means, exact means, timing) come from one live
decision.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "decision-steps.svg"
SEED = 52

TITLE = "One decision, four steps"
SUBTITLE = ("Example: one live lead with 7 cards left. Numbers are real; "
            "cell shades, tiles and tree shape are illustrative.")

# Each step: (colour token, kicker, question, calls lines, returns lines, example lines).
STEPS = [
    ("belief", "1 · BELIEF", "Who holds what?",
     ["1 call", "public history in"],
     ["odds for 54 cards", "× 4 hands"],
     ["66 deals drawn,", "64 kept (2 illegal)"]),
    ("prior", "2 · PRIOR", "Which plays?",
     ["1 call", "64 positions in"],
     ["a score per card;", "top 8 plays kept"],
     ["8 of 64 legal", "plays shortlisted"]),
    ("value", "3 · VALUE", "How good is each?",
     ["4 calls × 128", "= 8 plays × 64 deals"],
     ["one score per", "play per deal"],
     ["best average:", "A♣ 1.799"]),
    ("exact", "4 · ENDGAME", "Solve it exactly",
     ["no model call;", "≤ 7 cards left"],
     ["exact result", "per deal"],
     ["switches to J♦:", "1.797 vs A♣ 1.719"]),
]
FLOWS = [("64", "deals"), ("8", "plays"), ("512", "scores")]

# Belief: hidden cards shown in the holder heatmap; columns are the other hands.
HIDDEN_CARDS = ["Q♣", "K♣", "10♠", "9♥", "6♦", "3♠"]
DEALS_DRAWN, DEALS_REJECTED = 66, (17, 48)
# Prior: the 8 admitted plays and their policy log-odds; 64 legal plays in all.
ADMITTED = [("J♦", -0.06), ("A♣", -0.22), ("7♣", -0.39), ("7♣A♣", -0.61),
            ("7♣A♣Q♣", -1.40), ("8♣Q♣", -1.71), ("5♣8♣A♣", -2.30), ("7♣8♣A♣Q♣", -2.32)]
LEGAL_PLAYS = 64
# Value: the mean value of each admitted play over the 64 deals.
VALUE_MEANS = [("A♣", 1.799), ("J♦", 1.731), ("7♣", 1.673), ("7♣A♣", 1.673),
               ("7♣A♣Q♣", 1.673), ("8♣Q♣", 1.670), ("5♣8♣A♣", 1.614), ("7♣8♣A♣Q♣", 1.673)]
DEALS = 64
# Endgame: exact means over the same deals for the two leading plays.
EXACT_MEANS = [("J♦", 1.797), ("A♣", 1.719)]

FINAL = "Plays J♦ in 0.49 s"
FOOTER = ("All models run in NumPy on the server CPU · budget 3 s per decision · "
          "trump call and bury reuse the value model")

ARIA = (
    "How each decision calls the models, with one real decision as the example. "
    "Belief: one call on the public history returns each card's odds of being in each hand, "
    "drawn as a heatmap; 66 deals are sampled from it, drawn as tiles, and 2 that break earlier "
    "play are crossed out, leaving 64 sampled deals. "
    "Prior: one call on 64 positions scores every card; the 64 legal plays are drawn as bars and "
    "the top 8 are admitted, J♦ at log-odds −0.06 and A♣ at −0.22 first. "
    "Value: 4 calls of 128 positions score each of the 8 plays in all 64 deals, drawn as an 8 by 64 "
    "heatmap with a row-mean column; the best average was the ace of clubs at 1.799. "
    "Endgame: with 7 cards or fewer, no model call; each deal is solved exactly by a game tree "
    "with all hands face up and pruned branches, and the per-deal results are averaged; "
    "it switched to the jack of diamonds, 1.797 against 1.719 for the ace of clubs. "
    "It played the jack of diamonds in 0.49 seconds. "
    "All models run in NumPy on the server CPU with a 3 second budget per decision; "
    "the trump call and the bury reuse the value model."
)

# One fixed dark palette, the release ladder's (docs/visuals/release-ladder.svg); every
# text colour clears 4.5:1 contrast on the panel, the column boxes and the result bar.
THEME = {"bg": "#1d242c", "panel": "#151a20", "edge": "#323c47", "fg": "#e6ebf0", "dim": "#c3ccd5",
         "muted": "#98a4b0", "accent": "#4fc1b9", "chip": "#232c36", "bad": "#f08a80",
         "belief": "#b39cf0", "prior": "#f2a46b", "value": "#7fb8ef", "exact": "#ef8fbe"}
TOKENS = ("belief", "prior", "value", "exact", "bad", "muted", "fg")

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

WIDTH, HEIGHT = 1200, 720
COL_X0, COL_W, COL_GAP, COL_Y, COL_H = 16, 250, 56, 76, 544
PAD = 14
VIS_Y = COL_Y + 70          # top of each column's model-work visual
TXT_Y = COL_Y + 342         # top of the CALLS / RETURNS / EXAMPLE block


def _rules(c: dict[str, str]) -> str:
    return (
        f".bg{{fill:{c['bg']}}}"
        f".box{{fill:{c['panel']};stroke-width:1.5}}"
        f".tile{{fill:{c['panel']};stroke:{c['muted']};stroke-width:1}}"
        f".h1{{font:600 20px {SANS};fill:{c['fg']}}}"
        f".t{{font:600 17px {SANS};fill:{c['fg']}}}"
        f".s{{font:15px {SANS};fill:{c['dim']}}}"
        f".cap{{font:13px {SANS};fill:{c['dim']}}}"
        f".lab{{font:13px {SANS};fill:{c['fg']}}}"
        f".num{{font:13px {MONO};fill:{c['dim']}}}"
        f".numb{{font:600 13px {MONO};fill:{c['fg']}}}"
        f".k{{font:600 14px {MONO};letter-spacing:.06em}}"
        f".m{{font:13px {MONO};fill:{c['muted']}}}"
        f".flow{{font:600 13px {SANS};fill:{c['dim']}}}"
        f".rule{{stroke:{c['edge']}}}"
        f".arrow{{stroke:{c['muted']};stroke-width:1.8;fill:none}}"
        f".thin{{stroke:{c['muted']};stroke-width:1.2;fill:none}}"
        f".dash{{stroke:{c['muted']};stroke-width:1.2;fill:none;stroke-dasharray:3 3}}"
        f".ah{{fill:{c['muted']}}}"
        f".bar{{fill:{c['chip']};stroke:{c['accent']};stroke-width:1.5}}"
        f".ring{{fill:none;stroke:{c['fg']};stroke-width:1.5}}"
        f".xm{{stroke:{c['bad']};stroke-width:2;stroke-linecap:round}}"
        + "".join(f".c-{n}{{fill:{c[n]}}}.b-{n}{{stroke:{c[n]}}}" for n in TOKENS)
    )


def _f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _text(x: float, y: float, cls: str, body: str, anchor: str = "") -> str:
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{_f(x)}" y="{_f(y)}" class="{cls}"{a}>{escape(body)}</text>'


def _rect(x, y, w, h, cls, opacity=None, rx=None) -> str:
    extra = f' fill-opacity="{opacity:.2f}"' if opacity is not None else ""
    extra += f' rx="{_f(rx)}"' if rx is not None else ""
    return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" class="{cls}"{extra}/>'


def _line(x1, y1, x2, y2, cls) -> str:
    return f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" class="{cls}"/>'


def _cross(cx, cy, r) -> list[str]:
    return [_line(cx - r, cy - r, cx + r, cy + r, "xm"), _line(cx - r, cy + r, cx + r, cy - r, "xm")]


def _centred_noise(rng: random.Random, n: int, sd: float) -> list[float]:
    xs = [rng.gauss(0, sd) for _ in range(n)]
    mean = sum(xs) / n
    return [x - mean for x in xs]


def _shade(v: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.08, (v - lo) / (hi - lo)))


def belief_visual(tx: float, rng: random.Random) -> list[str]:
    out = []
    cw, ch, hx, hy = 20, 14, tx + 32, VIS_Y + 4
    for r, card in enumerate(HIDDEN_CARDS):
        out.append(_text(hx - 6, hy + r * ch + 11, "lab", card, "end"))
        weights = [rng.random() ** 2.2 for _ in range(4)]
        total = sum(weights)
        for c, w in enumerate(weights):
            out.append(_rect(hx + c * cw, hy + r * ch, cw - 1, ch - 1, "c-belief", _shade(w / total, 0, 0.8)))
    cap_x = hx + 4 * cw + 12
    for i, line in enumerate(["P(card is in", "each hand):", "next, partner,", "prev, kitty"]):
        out.append(_text(cap_x, hy + 12 + i * 18, "cap", line))
    arrow_y = hy + len(HIDDEN_CARDS) * ch + 4
    out.append(f'<path class="arrow" d="M{_f(hx + 2 * cw)} {_f(arrow_y)} V{_f(arrow_y + 18)}" marker-end="url(#ah)"/>')
    out.append(_text(hx + 2 * cw + 10, arrow_y + 15, "cap", f"sample {DEALS_DRAWN} deals"))
    ty, tw, th, cols = arrow_y + 26, 16, 10, 11
    for i in range(DEALS_DRAWN):
        x, y = tx + (i % cols) * 20, ty + (i // cols) * 14
        out.append(_rect(x, y, tw, th, "tile", rx=2))
        for d in range(4):
            out.append(f'<circle cx="{_f(x + 2.5 + d * 3.7)}" cy="{_f(y + 5)}" r="1.3" class="c-belief" '
                       f'fill-opacity="{0.35 + 0.65 * rng.random():.2f}"/>')
        if i in DEALS_REJECTED:
            out.extend(_cross(x + tw / 2, y + th / 2, 6))
    cy = ty + (DEALS_DRAWN + cols - 1) // cols * 14 + 16
    out.append(_text(tx, cy, "lab", f"{DEALS_DRAWN - len(DEALS_REJECTED)} sampled deals"))
    out.append(_text(tx, cy + 18, "cap c-bad", f"✕ {len(DEALS_REJECTED)} rejected: break earlier play"))
    return out


def prior_visual(tx: float, rng: random.Random) -> list[str]:
    out = [_text(tx + 76, VIS_Y + 12, "cap", "play", "end"), _text(tx + 82, VIS_Y + 12, "cap", "policy score"),
           _text(tx + 222, VIS_Y + 12, "cap", "log-odds", "end")]
    bx, scale, floor = tx + 82, 92, -6.0
    y = VIS_Y + 22
    for play, score in ADMITTED:
        out.append(_text(tx + 76, y + 11, "lab", play, "end"))
        out.append(_rect(bx, y + 2, scale * (score - floor) / -floor, 10, "c-prior", rx=2))
        out.append(_text(tx + 222, y + 11, "num", f"{score:+.2f}".replace("-", "−"), "end"))
        y += 16
    rest = sorted((rng.uniform(floor + 0.2, ADMITTED[-1][1] - 0.05) for _ in range(LEGAL_PLAYS - len(ADMITTED))),
                  reverse=True)
    fy = y + 6
    for i, score in enumerate(rest):
        out.append(_rect(bx, fy + i * 1.1, scale * (score - floor) / -floor, 0.7, "c-prior", 0.4))
    mid = fy + len(rest) * 0.55
    out.append(_text(tx + 76, mid - 3, "cap", f"{len(rest)} more", "end"))
    out.append(_text(tx + 76, mid + 13, "cap", "legal", "end"))
    cy = fy + len(rest) * 1.1 + 22
    out.append(_text(tx, cy, "lab", f"top {len(ADMITTED)} of {LEGAL_PLAYS} admitted"))
    return out


def value_visual(tx: float, rng: random.Random) -> list[str]:
    gx, cw, rh = tx + 82, 1.5, 17
    out = [_text(gx, VIS_Y + 12, "cap", f"{DEALS} deals →"), _text(tx + 222, VIS_Y + 12, "cap", "mean", "end")]
    best = max(range(len(VALUE_MEANS)), key=lambda i: VALUE_MEANS[i][1])
    y0 = VIS_Y + 22
    for r, (play, mean) in enumerate(VALUE_MEANS):
        y = y0 + r * rh
        out.append(_text(gx - 6, y + 12, "lab", play, "end"))
        for c, n in enumerate(_centred_noise(rng, DEALS, 0.45)):
            out.append(_rect(gx + c * cw, y + 1, cw, rh - 3, "c-value", _shade(mean + n, 0.6, 2.6)))
        out.append(_text(tx + 222, y + 12, "numb" if r == best else "num", f"{mean:.3f}", "end"))
    by = y0 + best * rh
    out.append(_rect(gx - 3, by - 1, tx + 228 - gx, rh + 1, "ring", rx=3))
    cy = y0 + len(VALUE_MEANS) * rh + 18
    out.append(_text(tx, cy, "cap", f"rows: {len(VALUE_MEANS)} plays · columns: {DEALS} deals"))
    out.append(_text(tx, cy + 18, "lab", f"best row: {VALUE_MEANS[best][0]} {VALUE_MEANS[best][1]:.3f}"))
    return out


def exact_visual(tx: float, rng: random.Random) -> list[str]:
    out = []
    ry = VIS_Y + 50
    out.append(_rect(tx, ry - 22, 30, 44, "tile", rx=3))
    for i in range(4):
        out.append(_line(tx + 6, ry - 14 + i * 9.5, tx + 24, ry - 14 + i * 9.5, "thin"))
    out.append(_text(tx + 15, ry + 40, "cap", "face up", "middle"))
    l1 = [("J♦", ry - 34), ("A♣", ry), ("…", ry + 34)]
    for li, (label, y1) in enumerate(l1):
        out.append(_line(tx + 30, ry, tx + 72, y1, "thin"))
        out.append(f'<circle cx="{_f(tx + 76)}" cy="{_f(y1)}" r="4" class="c-exact"/>')
        out.append(_text(tx + 76, y1 - 10, "lab", label, "middle"))
        for k, dy in enumerate((-11, 0, 11)):
            pruned = (li + k) % 3 == 2 or (li == 2 and k)
            x2, y2 = tx + 112, y1 + dy
            out.append(_line(tx + 80, y1, x2, y2, "dash" if pruned else "thin"))
            if pruned:
                out.extend(_cross(x2 + 3, y2, 3))
            else:
                out.append(f'<circle cx="{_f(x2 + 3)}" cy="{_f(y2)}" r="2.5" class="c-exact"/>')
    for i, line in enumerate(["every play to", "the round end;", "dashed =", "pruned"]):
        out.append(_text(tx + 130, ry - 22 + i * 18, "cap", line))
    sy = ry + 74
    out.append(_text(tx, sy, "cap", f"exact result per deal, {DEALS} deals"))
    gx, cw = tx + 28, 1.75
    for r, (play, mean) in enumerate(EXACT_MEANS):
        y = sy + 10 + r * 20
        out.append(_text(gx - 6, y + 12, "lab", play, "end"))
        for c, n in enumerate(_centred_noise(rng, DEALS, 0.55)):
            out.append(_rect(gx + c * cw, y + 1, cw, 15, "c-exact", _shade(mean + n, 0.6, 2.6)))
        out.append(_text(tx + 222, y + 13, "numb" if r == 0 else "num", f"{mean:.3f}", "end"))
    out.append(_rect(gx - 3, sy + 9, tx + 228 - gx, 19, "ring", rx=3))
    out.append(_text(tx, sy + 66, "lab", "average → J♦ beats A♣"))
    return out


VISUALS = {"belief": belief_visual, "prior": prior_visual, "value": value_visual, "exact": exact_visual}


def build() -> str:
    rng = random.Random(SEED)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" '
        f'height="{HEIGHT}" role="img" aria-label="{escape(ARIA, {chr(34): "&quot;"})}">',
        f"<title>{escape(TITLE)}</title>",
        "<style>" + _rules(THEME) + "</style>",
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" class="ah"/></marker></defs>',
        f'<rect class="bg" x="0" y="0" width="{WIDTH}" height="{HEIGHT}" rx="16"/>',
        _text(COL_X0, 34, "h1", TITLE),
        _text(COL_X0, 58, "s", SUBTITLE),
    ]
    for i, (tok, kicker, question, calls, returns, example) in enumerate(STEPS):
        x = COL_X0 + i * (COL_W + COL_GAP)
        tx = x + PAD
        out.append(_rect(x, COL_Y, COL_W, COL_H, f"box b-{tok}", rx=12))
        out.append(_text(tx, COL_Y + 28, f"k c-{tok}", kicker))
        out.append(_text(tx, COL_Y + 54, "t", question))
        out.extend(VISUALS[tok](tx, rng))
        out.append(_line(tx, TXT_Y - 22, x + COL_W - PAD, TXT_Y - 22, "rule"))
        for label, lines, y0 in (("CALLS", calls, TXT_Y), ("RETURNS", returns, TXT_Y + 66)):
            out.append(_text(tx, y0, "m", label))
            out.extend(_text(tx, y0 + 20 + 19 * j, "s", line) for j, line in enumerate(lines))
        out.append(_text(tx, TXT_Y + 132, f"m c-{tok}", "EXAMPLE"))
        out.extend(_text(tx, TXT_Y + 152 + 19 * j, "s", line) for j, line in enumerate(example))
        if i < len(STEPS) - 1:
            ax, ay, mid = x + COL_W, COL_Y + 250, x + COL_W + COL_GAP / 2
            out.append(_text(mid, ay - 26, "flow", FLOWS[i][0], "middle"))
            out.append(_text(mid, ay - 10, "flow", FLOWS[i][1], "middle"))
            out.append(f'<path class="arrow" d="M{ax + 2} {ay} H{ax + COL_GAP - 2}" marker-end="url(#ah)"/>')
    bar_y = COL_Y + COL_H + 18
    bar_w = len(STEPS) * COL_W + (len(STEPS) - 1) * COL_GAP
    out.append(_rect(COL_X0, bar_y, bar_w, 62, "bar", rx=12))
    out.append(_text(COL_X0 + 16, bar_y + 26, "t", FINAL))
    out.append(_text(COL_X0 + 16, bar_y + 48, "s", FOOTER))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed SVG is stale")
    args = ap.parse_args(argv)
    svg = build()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != svg:
            print(f"{OUT.name} is stale: run python3 docs/visuals/build_decision_diagram.py", file=sys.stderr)
            return 1
        print(f"{OUT.name}: up to date")
        return 0
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
