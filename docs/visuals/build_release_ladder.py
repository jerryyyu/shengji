#!/usr/bin/env python3
"""Write docs/visuals/release-ladder.svg, the README's "Bot strength by release" step chart.

Edit the data block below, then run this script; `--check` exits 1 when the
committed SVG differs from what the data block generates. Stdlib only.

Each served release's step is its measured gain over the release before it
(AI_POLICIES.md ladder), in levels per round; the line is their running sum
from MC-LCB. The steps are separate measurements, so the sum approximates the
gap rather than measuring it. Same fixed dark palette as decision-steps.svg.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "release-ladder.svg"

TITLE = "Bot strength by release"
SUBTITLE = "Levels per round over MC-LCB, the sum of each release's measured step over the one before"
FOOTER = ("Steps are separate measurements, so the running sum is an approximation, not a single measured gap. "
          "MC-LCB screens through release 48, paired head-to-head duels from release 49.")

# (release, ISO date, step over the previous served release in levels/round, labelled)
RELEASES = [
    ("MC-LCB", "2026-09-01", 0.0, True),
    ("R22", "2026-09-09", 0.139, True),
    ("R25", "2026-09-15", 0.021, False),
    ("R28", "2026-09-16", 0.006, False),
    ("R29", "2026-09-22", 0.049, True),
    ("R36", "2026-09-30", 0.0393, False),
    ("R38", "2026-10-03", 0.0567, False),
    ("R43", "2026-10-09", 0.0, False),
    ("R44", "2026-10-11", 0.0388, False),
    ("R45", "2026-10-13", 0.0488, False),
    ("R46", "2026-10-16", 0.2284, True),
    ("R48", "2026-10-24", 0.0843, False),
    ("R49", "2026-11-01", 0.0306, False),
    ("R50", "2026-11-04", 0.0618, True),
    ("R51", "2026-11-06", -0.0133, False),
    ("R52", "2026-11-09", 0.0438, True),
]

# Callouts: release -> (note lines, label x as a date, label y in levels/round, text anchor).
CALLOUTS = {
    "R22": (["policy shortlist"], "2026-09-04", 0.36, "start"),
    "R25": (["value model"], "2026-09-11", 0.47, "start"),
    "R29": (["policy + value search"], "2026-09-19", 0.58, "start"),
    "R44": (["value-guided declare"], "2026-10-14", 0.17, "start"),
    "R46": (["belief + exact endgame"], "2026-10-13", 0.76, "end"),
    "R50": (["scaling win:", "retrained on 200k rounds"], "2026-11-01", 0.93, "end"),
    "R52": (["search rules"], "2026-11-09", 0.66, "start"),
}

X_TICKS = ["2026-09-01", "2026-09-15", "2026-10-01", "2026-10-15", "2026-11-01", "2026-11-15"]
Y_TICKS = [0.0, 0.2, 0.4, 0.6, 0.8]
T0, T1 = date(2026, 8, 29), date(2026, 11, 16)
Y0, Y1 = -0.06, 1.02

THEME = {"bg": "#1d242c", "panel": "#151a20", "edge": "#323c47", "fg": "#e6ebf0", "dim": "#c3ccd5",
         "muted": "#98a4b0", "accent": "#4fc1b9"}
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

WIDTH, HEIGHT = 1200, 600
PLOT_L, PLOT_R, PLOT_T, PLOT_B = 84, 1168, 92, 504


def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _x(iso: str | date) -> float:
    d = date.fromisoformat(iso) if isinstance(iso, str) else iso
    return PLOT_L + (d - T0).days / (T1 - T0).days * (PLOT_R - PLOT_L)


def _y(v: float) -> float:
    return PLOT_T + (Y1 - v) / (Y1 - Y0) * (PLOT_B - PLOT_T)


def _text(x, y, cls, body, anchor="") -> str:
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{_f(x)}" y="{_f(y)}" class="{cls}"{a}>{escape(body)}</text>'


def _signed(v: float) -> str:
    return f"{v:+.2f}"


def cumulative() -> list[tuple[str, str, float, bool]]:
    total, out = 0.0, []
    for name, iso, step, labelled in RELEASES:
        total = round(total + step, 4)
        out.append((name, iso, total, labelled))
    return out


def aria(points) -> str:
    final = points[-1][2]
    return (
        "Step chart of cumulative bot strength in levels per round over MC-LCB, by release date, "
        f"from 0 on 1 September 2026 to about {final:.2f} at release 52 on 9 November. "
        "Callouts mark the key steps: release 22, policy shortlist; release 25, value model; "
        "release 29, policy plus value search; release 44, value-guided declare; release 46, belief "
        "plus exact endgame, the biggest step; release 50, scaling win, retrained on 200k rounds; "
        "release 52, search rules. " + FOOTER
    )


def build() -> str:
    c = THEME
    pts = cumulative()
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
        f".line{{stroke:{c['accent']};stroke-width:2.5;fill:none;stroke-linejoin:round}}"
        f".dot{{fill:{c['panel']};stroke:{c['accent']};stroke-width:2}}"
        f".key{{fill:{c['accent']}}}"
        f".lead{{stroke:{c['muted']};stroke-width:1;fill:none}}"
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" '
        f'height="{HEIGHT}" role="img" aria-label="{escape(aria(pts), {chr(34): "&quot;"})}">',
        f"<title>{escape(TITLE)}</title>",
        f"<style>{style}</style>",
        f'<rect class="bg" x="0" y="0" width="{WIDTH}" height="{HEIGHT}" rx="16"/>',
        _text(24, 38, "h1", TITLE),
        _text(24, 62, "s", SUBTITLE),
    ]
    for v in Y_TICKS:
        out.append(f'<line class="{"zero" if v == 0 else "grid"}" x1="{PLOT_L}" x2="{PLOT_R}" '
                   f'y1="{_f(_y(v))}" y2="{_f(_y(v))}"/>')
        out.append(_text(PLOT_L - 10, _y(v) + 4.5, "tick", f"{v:.1f}" if v == 0 else f"+{v:.1f}", "end"))
    out.append(f'<text class="axis" text-anchor="middle" transform="translate(26 {_f((PLOT_T + PLOT_B) / 2)}) '
               f'rotate(-90)">levels/round over MC-LCB</text>')
    for iso in X_TICKS:
        d = date.fromisoformat(iso)
        out.append(_text(_x(d), PLOT_B + 24, "tick", f"{d.strftime('%b')} {d.day}", "middle"))
    path = [f"M{_f(_x(pts[0][1]))} {_f(_y(pts[0][2]))}"]
    for _, iso, cum, _ in pts[1:]:
        path.append(f"H{_f(_x(iso))} V{_f(_y(cum))}")
    out.append(f'<path class="line" d="{" ".join(path)}"/>')
    for name, iso, cum, labelled in pts:
        x, y = _x(iso), _y(cum)
        if name in CALLOUTS:
            lines, lx_iso, ly, anchor = CALLOUTS[name]
            lx, ly_px = _x(lx_iso), _y(ly)
            # the leader meets the label block at its side, never crossing its text
            ex = lx - 10 if anchor == "start" else lx + 10
            ey = ly_px - 5 + 9 * (len(lines) - 1)
            if anchor == "start" and abs(x - lx) < 8:
                ex, ey = lx + 4, ly_px - 28
            out.append(f'<path class="lead" d="M{_f(x)} {_f(y)} L{_f(ex)} {_f(ey)}"/>')
            label = f"{name} {_signed(cum)}" if labelled else name
            out.append(_text(lx, ly_px - 12, "rel", label, anchor))
            out.extend(_text(lx, ly_px + 6 + 18 * i, "note", line, anchor) for i, line in enumerate(lines))
        elif labelled:
            out.append(_text(x + 10, y - 10, "rel", name))
        out.append(f'<circle class="{"dot" if not labelled else "key"}" cx="{_f(x)}" cy="{_f(y)}" '
                   f'r="{5 if labelled else 3.5}"/>')
    out.append(_text(24, HEIGHT - 50, "s", FOOTER[:FOOTER.index(" MC-LCB screens")]))
    out.append(_text(24, HEIGHT - 28, "s", FOOTER[FOOTER.index("MC-LCB screens"):]))
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
