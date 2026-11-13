#!/usr/bin/env python3
"""Write docs/visuals/release-ladder.svg, the README's release-by-release step chart.

Edit the data block below, then run this script; `--check` exits 1 when the
committed SVG differs from what the data block generates. Stdlib only.

Each step is one row of the AI_POLICIES.md ladder: a served change's measured
effect against its own comparator, in signed levels per round, with its 95% CI
(the confirmation where one exists, else the screen). The line is an arithmetic
index, the running sum of those separate measurements from different
instruments; it is not a measured or calibrated strength gap (AI_POLICIES.md
"Reading the ladder"). A change the ladder lists as not measured is drawn as a
hollow zero-height marker; no value is filled in for it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "release-ladder.svg"

TITLE = "Release by release: each measured step"
SUBTITLE = ("Each step is one served change against its own comparator, signed levels per round, "
            "with its 95% CI; the line adds them up as an index")
FOOTER = [
    "An arithmetic index of separate measurements from different instruments, each against its own comparator "
    "(the confirmation",
    "where one exists, else the screen). It is not a measured or calibrated strength gap. Hollow markers: "
    "changes the ladder lists as not measured.",
]

OTHER, SCREEN, DUEL, NONE = "other", "screen", "duel", "none"
INSTRUMENTS = [
    (OTHER, "before R29: other instruments"),
    (SCREEN, "R29–R48: MC-LCB screens"),
    (DUEL, "from R49: paired duels"),
]

# (tick label, step, CI low, CI high, instrument, comparator); step None = not measured.
# Source: AI_POLICIES.md ladder rows 2-21.
STEPS = [
    ("R22", 0.139, 0.065, 0.217, OTHER, "MC-LCB"),
    ("R25/27", 0.021, 0.004, 0.039, OTHER, "release-24 package"),
    ("R27", -0.0003, -0.0017, 0.0012, OTHER, "M1, paired"),
    ("R28", 0.006, -0.016, 0.028, OTHER, "R27"),
    ("R29", 0.049, 0.003, 0.095, SCREEN, "R28"),
    ("R30", None, None, None, NONE, "R29"),
    ("R36", 0.0393, 0.0033, 0.0752, SCREEN, "R30"),
    ("R38", 0.0461, 0.0242, 0.0681, SCREEN, "R36"),
    ("+la", 0.0106, 0.0006, 0.0205, SCREEN, "div + rc + tb"),
    ("R42", -0.0002, -0.0102, 0.0099, SCREEN, "R38"),
    ("R43", -0.0004, -0.0122, 0.0114, SCREEN, "R42"),
    ("R44", 0.0497, 0.0379, 0.0615, SCREEN, "R43, first-round deals"),
    ("R45", 0.0488, 0.0286, 0.0690, SCREEN, "R44"),
    ("R46", 0.2284, 0.2046, 0.2521, SCREEN, "R45"),
    ("R48", 0.0843, 0.0575, 0.1111, SCREEN, "R46"),
    ("R49", 0.0306, 0.0167, 0.0441, DUEL, "R48"),
    ("R50", 0.0618, 0.0507, 0.0729, DUEL, "R49"),
    ("R51", -0.0133, -0.0232, -0.0033, DUEL, "R50, cloud read"),
    ("R52", 0.0438, 0.0381, 0.0497, DUEL, "R51"),
]

# Callouts: tick label -> (lines, label position in step units, label index value, anchor).
# The first line is bold; the step size is filled in from STEPS.
CALLOUTS = {
    "R22": (["{name} {step}", "policy shortlist"], -0.9, 0.38, "start"),
    "R25/27": (["{name} {step}", "value model"], 1.3, 0.55, "start"),
    "R29": (["{name} {step}", "policy + value search"], 3.6, 0.72, "start"),
    "R30": (["R30 not measured", "(hybrid-bury fix)"], 5.0, 0.10, "middle"),
    "R36": (["R36 {step}", "measured vs R30"], 6.6, 0.12, "start"),
    "R44": (["{name} {step}", "value-guided declare", "(first-round deals)"], 11.4, 0.20, "start"),
    "R46": (["{name} {step}", "belief + exact endgame"], 12.6, 0.80, "end"),
    "R50": (["{name} {step}", "new value, prior + belief", "(trained on 200k rounds)"], 15.7, 1.0, "end"),
    "R51": (["R51 {step} on cloud;", "the Ultra read, +0.008,", "disagrees"], 17.0, 0.62, "middle"),
    "R52": (["{name} {step}", "search rules"], 18.0, 1.04, "middle"),
}

Y_TICKS = [0.0, 0.2, 0.4, 0.6, 0.8]
Y0, Y1 = -0.06, 1.1

THEME = {"bg": "#1d242c", "panel": "#151a20", "edge": "#323c47", "fg": "#e6ebf0", "dim": "#c3ccd5",
         "muted": "#98a4b0", "accent": "#4fc1b9", "ci": "#e0b25a"}
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
DASH = {OTHER: "2 4", SCREEN: None, DUEL: "8 5"}

WIDTH, HEIGHT = 1200, 660
PLOT_L, PLOT_R, PLOT_T, PLOT_B = 84, 1168, 124, 540


def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _x(i: float) -> float:
    return PLOT_L + 24 + (i + 1) * (PLOT_R - PLOT_L - 48) / len(STEPS)


def _y(v: float) -> float:
    return PLOT_T + (Y1 - v) / (Y1 - Y0) * (PLOT_B - PLOT_T)


def _text(x, y, cls, body, anchor="") -> str:
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{_f(x)}" y="{_f(y)}" class="{cls}"{a}>{escape(body)}</text>'


def _signed(v: float, places: int = 2) -> str:
    return f"{v:+.{places}f}".replace("-", "−")


def points() -> list[tuple[float, float]]:
    """(index before, index after) per step; an unmeasured step adds nothing."""
    total, out = 0.0, []
    for _, step, *_ in STEPS:
        before = total
        total = round(total + (step or 0.0), 4)
        out.append((before, total))
    return out


def aria() -> str:
    return (
        "Step chart, by release, of each served change's measured step against its own comparator in signed "
        "levels per round, with 95% CI whiskers, and a line that adds the steps up as an arithmetic index. "
        "Dotted before release 29 (other instruments), solid for MC-LCB common-control screens from release 29 "
        "to 48, dashed for paired head-to-head duels from release 49. Callouts: release 22 +0.14, policy "
        "shortlist; release 25/27 +0.02, value model; release 29 +0.05, policy plus value search; release 30 not "
        "measured; release 36 +0.04, measured against release 30; release 44 +0.05, value-guided declare, "
        "first-round deals; release 46 +0.23, belief plus exact endgame; release 50 +0.06, new value, prior and "
        "belief, trained on 200k rounds; release 51 −0.01 on cloud, where the Ultra read, +0.008, disagrees; "
        "release 52 +0.04, search rules. " + " ".join(FOOTER)
    )


def build() -> str:
    c = THEME
    style = (
        f".bg{{fill:{c['bg']}}}"
        f".h1{{font:600 20px {SANS};fill:{c['fg']}}}"
        f".s{{font:14px {SANS};fill:{c['dim']}}}"
        f".tick{{font:13px {SANS};fill:{c['muted']}}}"
        f".axis{{font:13px {SANS};fill:{c['dim']}}}"
        f".rel{{font:600 14px {SANS};fill:{c['fg']}}}"
        f".note{{font:14px {SANS};fill:{c['dim']}}}"
        f".grid{{stroke:{c['edge']};stroke-width:1}}"
        f".zero{{stroke:{c['muted']};stroke-width:1.2}}"
        f".line{{stroke:{c['accent']};stroke-width:2.5;fill:none}}"
        f".ci{{stroke:{c['ci']};stroke-width:2}}"
        f".dot{{fill:{c['accent']}}}"
        f".hollow{{fill:{c['bg']};stroke:{c['muted']};stroke-width:1.8}}"
        f".lead{{stroke:{c['muted']};stroke-width:1;fill:none}}"
        f".gap{{stroke:{c['muted']};stroke-width:1.5}}"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" '
        f'height="{HEIGHT}" role="img" aria-label="{escape(aria(), {chr(34): "&quot;"})}">',
        f"<title>{escape(TITLE)}</title>",
        f"<style>{style}</style>",
        f'<rect class="bg" x="0" y="0" width="{WIDTH}" height="{HEIGHT}" rx="16"/>',
        _text(24, 38, "h1", TITLE),
        _text(24, 62, "s", SUBTITLE),
    ]
    # legend
    lx = 24
    for kind, label in INSTRUMENTS:
        dash = f' stroke-dasharray="{DASH[kind]}"' if DASH[kind] else ""
        out.append(f'<line class="line" x1="{lx}" x2="{lx + 34}" y1="91" y2="91"{dash}/>')
        out.append(_text(lx + 42, 96, "tick", label))
        lx += 42 + 7 * len(label) + 28
    out.append(f'<line class="ci" x1="{lx + 6}" x2="{lx + 6}" y1="83" y2="99"/>')
    out.append(_text(lx + 16, 96, "tick", "95% CI of the step"))
    lx += 16 + 7 * len("95% CI of the step") + 28
    out.append(f'<circle class="hollow" cx="{lx + 6}" cy="91" r="5"/>')
    out.append(_text(lx + 16, 96, "tick", "not measured"))

    for v in Y_TICKS:
        out.append(f'<line class="{"zero" if v == 0 else "grid"}" x1="{PLOT_L}" x2="{PLOT_R}" '
                   f'y1="{_f(_y(v))}" y2="{_f(_y(v))}"/>')
        out.append(_text(PLOT_L - 10, _y(v) + 4.5, "tick", f"{v:.1f}", "end"))
    out.append(f'<text class="axis" text-anchor="middle" transform="translate(28 {_f((PLOT_T + PLOT_B) / 2)}) '
               f'rotate(-90)">running sum of measured steps (index)</text>')

    pts = points()
    out.append(_text(_x(-1), PLOT_B + 22, "tick", "MC-LCB", "middle"))
    for i, ((name, step, lo, hi, kind, _), (before, after)) in enumerate(zip(STEPS, pts)):
        x = _x(i)
        x_next = _x(i + 1) if i + 1 < len(STEPS) else PLOT_R - 8
        out.append(_text(x, PLOT_B + 22, "tick", name, "middle"))
        if step is None:
            out.append(f'<line class="gap" x1="{_f(x)}" x2="{_f(x_next)}" y1="{_f(_y(after))}" '
                       f'y2="{_f(_y(after))}"/>')
            continue
        dash = f' stroke-dasharray="{DASH[kind]}"' if DASH[kind] else ""
        if i == 0:
            out.append(f'<line class="line" x1="{_f(_x(-1))}" x2="{_f(x)}" y1="{_f(_y(0))}" y2="{_f(_y(0))}"{dash}/>')
        out.append(f'<path class="line" d="M{_f(x)} {_f(_y(before))} V{_f(_y(after))} H{_f(x_next)}"{dash}/>')
        out.append(f'<line class="ci" x1="{_f(x + 7)}" x2="{_f(x + 7)}" y1="{_f(_y(before + lo))}" '
                   f'y2="{_f(_y(before + hi))}"/>')
    out.append(f'<circle class="dot" cx="{_f(_x(-1))}" cy="{_f(_y(0))}" r="4"/>')
    for i, ((name, step, *_), (before, after)) in enumerate(zip(STEPS, pts)):
        x, y = _x(i), _y(after)
        if step is None:
            out.append(f'<circle class="hollow" cx="{_f(x)}" cy="{_f(y)}" r="5"/>')
        else:
            out.append(f'<circle class="dot" cx="{_f(x)}" cy="{_f(y)}" r="3.5"/>')
        if name in CALLOUTS:
            lines, li, lv, anchor = CALLOUTS[name]
            lx_, ly = _x(li), _y(lv)
            text = [line.format(name=name, step="" if step is None else _signed(step)) for line in lines]
            top, bottom = ly - 14, ly + 18 * (len(text) - 1) + 4
            ex = {"start": lx_ - 8, "end": lx_ + 8, "middle": lx_}[anchor]
            ey = bottom + 4 if y > bottom else top - 4
            if anchor != "middle":
                ey = min(max(y, top), bottom)
            out.append(f'<path class="lead" d="M{_f(x)} {_f(y)} L{_f(ex)} {_f(ey)}"/>')
            for k, line in enumerate(text):
                out.append(_text(lx_, ly + 18 * k, "rel" if k == 0 else "note", line, anchor))
    for k, line in enumerate(FOOTER):
        out.append(_text(24, HEIGHT - 44 + 20 * k, "s", line))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed SVG is stale")
    args = ap.parse_args(argv)
    svg = build()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != svg:
            print(f"{OUT.name} is stale: run python3 docs/visuals/build_release_ladder.py", file=sys.stderr)
            return 1
        print(f"{OUT.name}: up to date")
        return 0
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
