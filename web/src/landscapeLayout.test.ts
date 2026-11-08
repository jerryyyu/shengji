// @vitest-environment node
/// <reference types="node" />
// Guards the phone table geometry in index.css (the `@media (max-height:
// 500px)` block). jsdom does no layout, so this evaluates the block's own
// size tokens (calc, clamp, min, max, env, vw, vh) at real iPhone sizes and
// checks the regions the layout promises to keep apart: the trick cross sits
// between the header and your row, your action is centred on the table and,
// with the banker's crown beside it, never meets a trick slot, a seat or the
// hand, the hand fits one
// row at a thumb-sized pitch, and every control keeps a 44px hit area. Rendered checks live in the PR's screenshot sweep.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");

/** Body of the first `@media (max-height: 500px)` block, braces balanced. */
function phoneBlock(): string {
  const start = css.indexOf("@media (max-height: 500px)");
  expect(start).toBeGreaterThan(-1);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(open + 1, i);
  }
  throw new Error("unbalanced media block");
}

/** Declarations of every top-level rule in `block` whose selector is exactly `selector`, merged. */
function rule(block: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(block); m; m = re.exec(block)) {
    const sel = m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ");
    if (sel !== selector) continue;
    for (const decl of m[2].replace(/\/\*[\s\S]*?\*\//g, "").split(";")) {
      const i = decl.indexOf(":");
      if (i > 0) out[decl.slice(0, i).trim()] = decl.slice(i + 1).trim().replace(/\s+/g, " ");
    }
  }
  return out;
}

const block = phoneBlock();
const px = (v: string) => Number(/(-?[\d.]+)px/.exec(v)![1]);

interface Viewport { w: number; h: number; left: number; right: number; bottom: number; top: number }

/** Evaluates a CSS length expression to px. Custom properties resolve from
 *  `vars` (themselves expressions), `--n` from `ints`. */
function evalLength(expr: string, vp: Viewport, vars: Record<string, string>, ints: Record<string, number> = {}): number {
  let s = expr;
  let pos = 0;
  const peek = () => s.slice(pos).match(/^\s*/)![0].length + pos;
  const eat = (re: RegExp): string | null => {
    const at = peek();
    const m = re.exec(s.slice(at));
    if (!m || m.index !== 0) return null;
    pos = at + m[0].length;
    return m[0];
  };
  const args = (): number[] => {
    const out = [sum()];
    while (eat(/^,/)) out.push(sum());
    if (!eat(/^\)/)) throw new Error(`expected ) in ${s}`);
    return out;
  };
  const atom = (): number => {
    if (eat(/^\(/)) { const v = sum(); eat(/^\)/); return v; }
    if (eat(/^calc\(/)) return args()[0];
    if (eat(/^min\(/)) return Math.min(...args());
    if (eat(/^max\(/)) return Math.max(...args());
    if (eat(/^clamp\(/)) { const [lo, v, hi] = args(); return Math.min(Math.max(v, lo), hi); }
    const env = eat(/^env\(safe-area-inset-(left|right|top|bottom)(,\s*[-\d.]+px)?\)/);
    if (env) return vp[/inset-(\w+)/.exec(env)![1] as "left"];
    const v = eat(/^var\(--[\w-]+(,\s*[-\d.]+)?\)/);
    if (v) {
      const name = /--[\w-]+/.exec(v)![0];
      const key = name.slice(2);
      if (key in ints) return ints[key];
      if (name in vars) return evalLength(vars[name], vp, vars, ints);
      const fallback = /,\s*([-\d.]+)/.exec(v);
      if (fallback) return Number(fallback[1]);
      throw new Error(`unknown ${name}`);
    }
    const num = eat(/^-?[\d.]+(px|vw|vh)?/);
    if (num) {
      const n = parseFloat(num);
      if (num.endsWith("vw")) return (n * vp.w) / 100;
      if (num.endsWith("vh")) return (n * vp.h) / 100;
      return n;
    }
    if (eat(/^-/)) return -atom();
    throw new Error(`cannot parse "${s.slice(pos)}" in ${expr}`);
  };
  const product = (): number => {
    let v = atom();
    for (;;) {
      if (eat(/^\*/)) v *= atom();
      else if (eat(/^\//)) v /= atom();
      else return v;
    }
  };
  function sum(): number {
    let v = product();
    for (;;) {
      if (eat(/^\+/)) v += product();
      else if (eat(/^-(?=\s)/)) v -= product();
      else return v;
    }
  }
  s = expr.trim();
  return sum();
}

const tokens = rule(block, ".table-screen");
const smallTokens = { ...tokens, ...rule(block, ".table-screen:has(.hand.small-cards)") };
const handRule = rule(block, ".hand");
const smallRule = rule(block, ".hand.small-cards");

// Device frames: landscape safe areas from the simulator (side insets carry
// the Dynamic Island, the bottom one the home indicator); and the same sizes
// as a browser draws them, with no insets.
const PHONES: Record<string, Viewport> = {
  "iPhone 14 Pro 852x393": { w: 852, h: 393, left: 59, right: 59, bottom: 21, top: 0 },
  "iPhone 18 Pro 874x402": { w: 874, h: 402, left: 62, right: 62, bottom: 21, top: 0 },
  "iPhone 18 Pro Max 956x440": { w: 956, h: 440, left: 62, right: 62, bottom: 21, top: 0 },
};
const FRAMES: [string, Viewport][] = Object.entries(PHONES).flatMap(([name, vp]) => [
  [`${name} (app)`, vp] as [string, Viewport],
  [`${name} (browser)`, { ...vp, left: 0, right: 0, bottom: 0 }] as [string, Viewport],
]);

interface Rect { x0: number; y0: number; x1: number; y1: number }
const overlaps = (a: Rect, b: Rect) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

/** The table's regions at one viewport, from the tokens and the rules below. */
function geometry(vp: Viewport, vars: Record<string, string>) {
  const L = (name: string) => evalLength(vars[name], vp, vars);
  const tcw = L("--trick-cw");
  const tch = L("--trick-ch");
  const dx = L("--slot-dx");
  const dy = L("--slot-dy");
  const trickTop = L("--trick-top");
  const liftLine = vp.h - L("--trick-bottom");        // the hand's lift line
  const crossBottom = vp.h - L("--cross-bottom");
  const cx = vp.w / 2;
  const cy = (trickTop + crossBottom) / 2;
  const width = (cards: number) => tcw + (cards - 1) * tcw * 0.72;
  const slots: Record<string, Rect> = {
    top: { x0: cx - width(2) / 2, x1: cx + width(2) / 2, y0: cy - dy - tch / 2, y1: cy - dy + tch / 2 },
    // your slot holds up to a four-card throw
    bottom: { x0: cx - width(4) / 2, x1: cx + width(4) / 2, y0: cy + dy - tch / 2, y1: cy + dy + tch / 2 },
    left: { x1: cx - dx + tcw / 2, x0: cx - dx + tcw / 2 - width(2), y0: cy - tch / 2, y1: cy + tch / 2 },
    right: { x0: cx + dx - tcw / 2, x1: cx + dx - tcw / 2 + width(2), y0: cy - tch / 2, y1: cy + tch / 2 },
  };
  // the side seats' labels: 28px tall, 6px above their slot, ~110px wide
  const pill = (x: number): Rect => ({ x0: x - 55, x1: x + 55, y0: cy - tch / 2 - 6 - 28, y1: cy - tch / 2 - 6 });
  // your row: Play (88) centred between the row's symmetric paddings, Clear
  // (8 + 76) just right of it, the banker's crown (28) 8px left of it
  const padL = L("--safe-l") + 8;
  const padR = L("--safe-r") + 8;
  const rowCentre = (padL + vp.w - padR) / 2;
  const rowB = vp.h - L("--zone-bottom");
  const rowY0 = rowB - L("--row-h");
  const row: Rect = { x0: rowCentre - 44, x1: rowCentre + 44 + 84, y0: rowY0, y1: rowB };
  const crown: Rect = { x0: rowCentre - 44 - 8 - 28, x1: rowCentre - 44 - 8, y0: rowB - 25 - 14, y1: rowB - 25 + 14 };
  const header = 6 + vp.top + L("--header-h");
  return { tcw, cx, cy, slots, pills: [pill(cx - dx), pill(cx + dx)], row, crown, rowCentre, header, liftLine,
    crossBottom, handTop: vp.h - L("--hand-h"), safeW: L("--safe-w"), handCw: L("--hand-cw") };
}

describe("phone table geometry", () => {
  it("lays the trick out from the tokens", () => {
    expect(rule(block, ".trick-area").top).toBe("var(--trick-top)");
    expect(rule(block, ".trick-area").bottom).toBe("var(--cross-bottom)");
    expect(rule(block, ".trick-cards")["--cw"]).toBe("var(--trick-cw)");
    expect(rule(block, ".trick-cards .card + .card")["margin-left"]).toBe("calc(var(--trick-cw) * -0.28)");
    expect(rule(block, ".trick-play.pos-top").translate).toBe("-50% calc(-50% - var(--slot-dy))");
    expect(rule(block, ".trick-play.pos-bottom").translate).toBe("-50% calc(-50% + var(--slot-dy))");
    expect(rule(block, ".trick-play.pos-left").right).toBe("calc(50% + var(--slot-dx) - var(--trick-cw) / 2)");
    expect(rule(block, ".trick-play.pos-right").left).toBe("calc(50% + var(--slot-dx) - var(--trick-cw) / 2)");
    const row = rule(block, ".you-row");
    expect([row.position, row.left, row.right, row.bottom]).toEqual(["absolute", "0", "0", "var(--zone-bottom)"]);
    expect(row.padding).toBe("0 calc(var(--safe-r) + 8px) 0 calc(var(--safe-l) + 8px)");
    // equal flexible edges around the action: the action alone is centred
    expect(row["grid-template-columns"]).toBe("minmax(0, 1fr) auto minmax(0, 1fr)");
    expect(rule(block, ".action-bar")["grid-column"]).toBe("2");
    expect(rule(block, ".action-bar")["justify-content"]).toBe("safe center");
    expect(rule(block, ".phase-play .action-bar .btn.primary")["grid-column"]).toBe("2");
    expect(rule(block, ".phase-play .action-bar .btn.subtle")["grid-column"]).toBe("3");
    // the crown stands outside the middle column, so it never moves the action
    const crown = rule(block, ".you-row:has(.action-bar .btn) .you-tagline:has(.banker-crown)");
    expect([crown["grid-column"], crown["justify-self"], crown.width]).toEqual(["1", "end", "28px"]);
    expect(tokens["--cross-bottom"]).toBe("calc(var(--zone-bottom) + var(--row-h) + 4px)");
    expect(rule(block, ".opponent.pos-left").left).toBe("calc(50% - var(--slot-dx))");
    expect(rule(block, ".opponent.pos-right").left).toBe("calc(50% + var(--slot-dx))");
    expect(rule(block, ".opponent.pos-left, .opponent.pos-right").top)
      .toBe("calc((var(--trick-top) + 100% - var(--cross-bottom)) / 2 - var(--trick-ch) / 2 - 6px)");
  });

  it("reserves exactly the hand's height: lift above, card, 16px under the home indicator", () => {
    expect(handRule["--cw"]).toBe("var(--hand-cw)");
    expect(handRule.padding).toBe("var(--lift) calc(8px + var(--safe-r)) var(--hand-under) calc(8px + var(--safe-l))");
    expect(tokens["--hand-h"]).toBe("calc(var(--hand-cw) * 1.4 + var(--hand-under))");
    expect(tokens["--trick-bottom"]).toBe("calc(var(--hand-h) + var(--lift))");
    const vp = PHONES["iPhone 14 Pro 852x393"];
    expect(evalLength(tokens["--hand-under"], vp, tokens)).toBe(5);   // 21 - 16
  });

  for (const [name, vp] of FRAMES) {
    describe(name, () => {
      const g = geometry(vp, tokens);

      const checkRegions = (g: ReturnType<typeof geometry>) => {
        // the cross between the header and your row
        expect(g.slots.top.y0).toBeGreaterThanOrEqual(g.header);
        expect(g.slots.bottom.y1).toBeLessThanOrEqual(g.crossBottom);
        for (const p of g.pills) {
          expect(p.y0).toBeGreaterThanOrEqual(g.header);
          for (const slot of Object.values(g.slots)) expect(overlaps(p, slot)).toBe(false);
        }
        // your row: centred, clear of every slot and seat, above the hand's lift
        expect(Math.abs(g.rowCentre - g.cx)).toBeLessThanOrEqual(2);
        for (const r of [g.row, g.crown]) {
          for (const slot of Object.values(g.slots)) expect(overlaps(r, slot)).toBe(false);
          for (const p of g.pills) expect(overlaps(r, p)).toBe(false);
          expect(r.y1).toBeLessThanOrEqual(g.liftLine);
        }
        expect(overlaps(g.crown, g.row)).toBe(false);
        expect(g.liftLine).toBeLessThanOrEqual(g.handTop);
        expect(g.row.x1).toBeLessThanOrEqual(vp.w - vp.right);
        expect(g.row.x0).toBeGreaterThanOrEqual(vp.left);
      };

      it("keeps the cross, the seats, your centred row and the hand apart", () => checkRegions(g));

      it("scales the trick cards with the width (about 48px on a 14 Pro)", () => {
        expect(g.tcw).toBeGreaterThanOrEqual(48);
        expect(g.tcw).toBeLessThanOrEqual(60);
      });

      it("fits a 25-card hand in one row at a pitch of at least 27px", () => {
        const pitch = evalLength(handRule["--pitch"], vp, tokens, { n: 25 });
        expect(pitch).toBeGreaterThanOrEqual(27);
        expect(24 * pitch + g.handCw).toBeLessThanOrEqual(g.safeW - 16 + 0.01);
        // a short hand stays at the capped pitch and centres
        expect(evalLength(handRule["--pitch"], vp, tokens, { n: 12 })).toBeCloseTo(g.handCw * 0.55, 5);
      });

      it("fits the 33-card bury hand in one row of ~52px cards", () => {
        const gs = geometry(vp, smallTokens);
        expect(gs.handCw * 1.4).toBeCloseTo(52, 0);
        const pitch = evalLength(smallRule["--pitch"], vp, smallTokens, { n: 33 });
        expect(32 * pitch + gs.handCw).toBeLessThanOrEqual(gs.safeW - 16 + 0.01);
        // 24px slivers wherever the safe width allows; inside a 14 Pro's or an
        // 18 Pro's landscape safe area 33 cards leave about 21px
        expect(pitch).toBeGreaterThanOrEqual(vp.left === 0 || vp.w >= 956 ? 24 : 21);
        checkRegions(gs);
      });
    });
  }

  it("shrinks the hand's cards above 25, briefly animated", () => {
    expect(rule(block, ".table-screen:has(.hand.small-cards)")["--hand-cw"]).toBe("37px");
    expect(rule(block, ".hand .card").transition).toContain("width 150ms");
  });
});

describe("phone controls", () => {
  it("keeps every control's hit area at 44px or more", () => {
    expect(px(rule(block, ".action-bar .btn")["min-height"])).toBeGreaterThanOrEqual(44);
    const more = rule(block, ".hud-bar .hud-more-btn");
    const hit = rule(block, ".hud-bar .hud-more-btn::after").inset.split(" ").map((x) => -px(x));
    const [vertical, horizontal] = hit;
    expect(32 + 2 * vertical).toBeGreaterThanOrEqual(44);
    expect(px(more["min-width"]) + 2 * horizontal).toBeGreaterThanOrEqual(44);
    expect(more.height).toBe("var(--header-h)");
    expect(px(tokens["--header-h"])).toBe(32);
    expect(px(rule(block, ".hud-menu-row")["min-height"])).toBeGreaterThanOrEqual(44);
    expect(px(rule(block, ".hud-menu-choice")["min-height"])).toBeGreaterThanOrEqual(44);
    const modalBtn = rule(block, ".modal > .btn.big");
    expect(modalBtn.position).toBe("sticky");
    expect(px(modalBtn["min-height"])).toBeGreaterThanOrEqual(44);
    // a card's tap area runs the full card height plus 16px above the hand
    expect(rule(block, ".hand .card::after").top).toBe("calc(-1 * var(--lift))");
  });

  it("keeps table text at 10px or more", () => {
    for (const sel of [".lead-tag, .win-tag", ".declare-tag", ".you-tag, .host-tag, .off-tag, .ready-tag", ".action-hint", ".chip"]) {
      expect(px(rule(block, sel)["font-size"])).toBeGreaterThanOrEqual(10);
    }
  });

  it("turns the table's long-press callout and text selection off, except in text fields", () => {
    expect(tokens["-webkit-touch-callout"]).toBe("none");
    expect(tokens["-webkit-user-select"]).toBe("none");
    expect(rule(block, ".table-screen input, .table-screen textarea")["-webkit-user-select"]).toBe("text");
  });

  it("shows your turn as the hand's glow, not a pill in the trick", () => {
    // no name pill on the phone table, ever
    expect(rule(block, ".you-tagline").display).toBe("none");
    expect(rule(block, ".you-tagline .you-name, .you-tagline .your-turn-tag, .you-tagline .ready-tag").display).toBe("none");
    expect(rule(block, ".my-turn .hand::before").opacity).toBe("1");
    expect(rule(block, ".hand::before").opacity).toBe("0");
  });

  it("floats messages and the failed-throw notice in the bottom-left corner", () => {
    for (const sel of [".hud-message", ".hud-notice"]) {
      expect(rule(block, sel).position).toBe("fixed");
      expect(rule(block, sel).left).toBe("var(--corner-l)");
    }
  });

  it("puts felt text on the dark pill", () => {
    for (const sel of [".lead-tag", ".declare-tag", ".action-hint", ".deal-deck-count"]) {
      expect(rule(block, sel).background).toMatch(/^rgba\(8, 20, 14, 0\.7\d\)$/);
    }
  });
});

describe("desktop and iPad are untouched", () => {
  // Desktop and iPad never match the phone block (an iPad is at least 744px
  // tall), so everything phone-only must live inside it.
  const outside = css.replace(block, "");

  it("styles the phone-only classes only inside the phone block", () => {
    for (const cls of ["small-cards", "my-turn", "hud-menu-choice", "hud-menu-confirm", "deal-deck-"]) {
      expect(outside.includes(`.${cls}`), cls).toBe(false);
    }
    // the deck is hidden everywhere else
    expect(rule(outside, ".deal-deck").display).toBe("none");
  });

  it("keys the phone layout on height, never on a coarse pointer alone", () => {
    expect(css.indexOf("@media (max-height: 500px) {")).toBeGreaterThan(-1);
    expect(css.match(/@media \(max-height: 500px\)/g)).toHaveLength(1);
  });
});

describe("portrait phones in a browser", () => {
  it("takes the table out of layout so the rotate hint centres, and offers Leave", () => {
    const start = css.indexOf("@media (orientation: portrait) and (max-width: 600px)");
    const body = css.slice(start, css.indexOf("\n}\n", start));
    expect(rule(body + "}", ".table-screen").display).toBe("none");
    expect(rule(css, ".rotate-hint").background).toContain("var(--felt-");
  });
});
