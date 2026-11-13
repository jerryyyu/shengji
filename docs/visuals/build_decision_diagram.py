#!/usr/bin/env python3
"""Write docs/visuals/decision-steps.svg, the README's "One decision, four steps" figure.

Edit the data block below, then run this script; `--check` exits 1 when the
committed SVG differs from what the data block generates. Stdlib only.

GitHub shows README images through <img>, which ignores the page's CSS, so the
SVG carries its own colours: light by default, dark under an internal
`prefers-color-scheme: dark` rule, with system font stacks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "decision-steps.svg"

TITLE = "One decision, four steps"
SUBTITLE = "Example: a bot leading with 7 cards left in a live game"

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

FINAL = "Plays J♦ in 0.49 s"
FOOTER = ("All models run in NumPy on the server CPU · budget 3 s per decision · "
          "trump call and bury reuse the value model")

ARIA = (
    "How each decision calls the models, with one real decision as the example. "
    "Belief: one call on the public history returns each card's odds of being in each hand; "
    "66 deals were drawn and 64 kept. "
    "Prior: one call on 64 positions scores every card; the top 8 of 64 legal plays are kept. "
    "Value: 4 calls of 128 positions score each of the 8 plays in all 64 deals; "
    "the best average was the ace of clubs at 1.799. "
    "Endgame: with 7 cards or fewer, no model call, each deal is solved exactly; "
    "it switched to the jack of diamonds, 1.797 against 1.719 for the ace of clubs. "
    "It played the jack of diamonds in 0.49 seconds. "
    "All models run in NumPy on the server CPU with a 3 second budget per decision; "
    "the trump call and the bury reuse the value model."
)

LIGHT = {"bg": "#f6f7f5", "panel": "#ffffff", "edge": "#dfe2dc", "fg": "#15181a", "dim": "#4f555a",
         "muted": "#6f767a", "accent": "#1f6f54", "chip": "#eef1ec", "belief": "#7c4dbb",
         "prior": "#b4501f", "value": "#2667c9", "exact": "#a8326e"}
DARK = {"bg": "#141716", "panel": "#1c201e", "edge": "#2e3431", "fg": "#eef1ee", "dim": "#b3bab5",
        "muted": "#8a918c", "accent": "#5fc49d", "chip": "#242a27", "belief": "#b393ec",
        "prior": "#f0925f", "value": "#7aa9f0", "exact": "#e978b0"}

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

WIDTH, HEIGHT = 760, 476
COL_X0, COL_W, COL_GAP, COL_Y, COL_H = 20, 170, 16, 70, 300


def _rules(theme: dict[str, str]) -> str:
    c = theme
    return (
        f".bg{{fill:{c['bg']}}}"
        f".box{{fill:{c['panel']};stroke-width:1.5}}"
        f".t{{font:600 15px {SANS};fill:{c['fg']}}}"
        f".s{{font:13px {SANS};fill:{c['dim']}}}"
        f".f{{font:12.5px {SANS};fill:{c['dim']}}}"
        f".k{{font:600 12px {MONO};letter-spacing:.06em}}"
        f".m{{font:12px {MONO};fill:{c['muted']}}}"
        f".rule{{stroke:{c['edge']}}}"
        f".arrow{{stroke:{c['muted']};stroke-width:1.8;fill:none}}"
        f".ah{{fill:{c['muted']}}}"
        f".bar{{fill:{c['chip']};stroke:{c['accent']};stroke-width:1.5}}"
        + "".join(f".c-{n}{{fill:{c[n]}}}.b-{n}{{stroke:{c[n]}}}" for n in ("belief", "prior", "value", "exact"))
    )


def _text(x: float, y: float, cls: str, body: str) -> str:
    return f'<text x="{x:g}" y="{y:g}" class="{cls}">{escape(body)}</text>'


def build() -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" '
        f'height="{HEIGHT}" role="img" aria-label="{escape(ARIA, {chr(34): "&quot;"})}">',
        f"<title>{escape(TITLE)}</title>",
        "<style>" + _rules(LIGHT) + "@media (prefers-color-scheme: dark){" + _rules(DARK) + "}</style>",
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto"><path d="M0,0 L10,5 L0,10 z" class="ah"/></marker></defs>',
        f'<rect class="bg" x="0" y="0" width="{WIDTH}" height="{HEIGHT}"/>',
        _text(20, 30, "t", TITLE),
        _text(20, 52, "s", SUBTITLE),
    ]
    for i, (tok, kicker, question, calls, returns, example) in enumerate(STEPS):
        x = COL_X0 + i * (COL_W + COL_GAP)
        tx = x + 14
        out.append(f'<rect class="box b-{tok}" x="{x}" y="{COL_Y}" width="{COL_W}" height="{COL_H}" rx="12"/>')
        out.append(_text(tx, COL_Y + 26, f"k c-{tok}", kicker))
        out.append(_text(tx, COL_Y + 50, "t", question))
        for label, lines, y0, cls in (("CALLS", calls, COL_Y + 82, "m"), ("RETURNS", returns, COL_Y + 166, "m")):
            out.append(_text(tx, y0, cls, label))
            out.extend(_text(tx, y0 + 20 + 18 * j, "s", line) for j, line in enumerate(lines))
        out.append(f'<line class="rule" x1="{tx}" x2="{x + COL_W - 14}" y1="{COL_Y + 230}" y2="{COL_Y + 230}"/>')
        out.append(_text(tx, COL_Y + 252, f"m c-{tok}", "EXAMPLE"))
        out.extend(_text(tx, COL_Y + 272 + 18 * j, "s", line) for j, line in enumerate(example))
        if i < len(STEPS) - 1:
            ax = x + COL_W
            out.append(f'<path class="arrow" d="M{ax} {COL_Y + 150} H{ax + COL_GAP}" marker-end="url(#ah)"/>')
    bar_y = COL_Y + COL_H + 20
    bar_w = len(STEPS) * COL_W + (len(STEPS) - 1) * COL_GAP
    out.append(f'<rect class="bar" x="{COL_X0}" y="{bar_y}" width="{bar_w}" height="62" rx="12"/>')
    out.append(_text(COL_X0 + 16, bar_y + 26, "t", FINAL))
    out.append(_text(COL_X0 + 16, bar_y + 47, "f", FOOTER))
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
