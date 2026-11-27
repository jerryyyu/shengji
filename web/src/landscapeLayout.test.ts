// @vitest-environment node
/// <reference types="node" />
// Guards the phone table geometry in index.css (the `:where(.phone-landscape)`
// block, which applies at the table under 500px of height and to the rotated portrait table). jsdom does no layout, so this evaluates the block's own
// size tokens (calc, clamp, min, max, env, vw, vh, dvh) at real iPhone sizes and
// checks the regions the layout promises to keep apart: the trick cross sits
// between the header and your row, your action is centred on the table and,
// with the banker's crown beside it, never meets a trick slot, a seat or the
// hand, the hand fits one
// row at a thumb-sized pitch, and every control keeps a 44px hit area. Rendered checks live in the PR's screenshot sweep.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { SHORT_VIEWPORT, TABLET_SCREEN, TABLET_UPRIGHT } from "./phoneLayout";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");

const PHONE_BLOCK = ":where(.phone-landscape) {";
const TABLET_BLOCK = "\n.tablet-table {";
const UPRIGHT_BLOCK = `\n@media ${TABLET_UPRIGHT} {`;

/** Body of the phone block, braces balanced. */
function phoneBlock(): string {
  return blockAt(PHONE_BLOCK);
}

/** Body of the block opened by `head`, braces balanced. */
function blockAt(head: string): string {
  const start = css.indexOf(head);
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

it("holds the table's rules only: the lobby is one portrait design at every height", () => {
  expect(block).not.toMatch(/\.(lobby-panel|lobby-preview|game-title|play-tab|home-narrow|home-wide|tp-)\b/);
});

/** A length in px; a chrome text token (var(--fs-N)) is N px at the default text size. */
const px = (v: string) => {
  const token = /var\(--fs-(\d+)\)/.exec(v);
  return token ? Number(token[1]) : Number(/(-?[\d.]+)px/.exec(v)![1]);
};

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
    const v = eat(/^var\(--[\w-]+/);
    if (v) {
      const name = v.slice(4);
      // the fallback, if any, runs to this var()'s closing parenthesis
      let fallback: string | null = null;
      if (eat(/^,/)) {
        let depth = 0;
        const from = pos;
        for (; pos < s.length; pos++) {
          if (s[pos] === "(") depth++;
          else if (s[pos] === ")" && depth-- === 0) break;
        }
        fallback = s.slice(from, pos);
      }
      if (!eat(/^\)/)) throw new Error(`expected ) in ${s}`);
      const key = name.slice(2);
      if (key in ints) return ints[key];
      if (name in vars) return evalLength(vars[name], vp, vars, ints);
      if (fallback !== null) return evalLength(fallback, vp, vars, ints);
      throw new Error(`unknown ${name}`);
    }
    const num = eat(/^-?[\d.]+(px|d?vw|d?vh)?/);
    if (num) {
      const n = parseFloat(num);
      if (num.endsWith("vw")) return (n * vp.w) / 100;
      // vp is the page: its vh and dvh agree (Safari's taller 100vh is the e2e suite's to imitate)
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
/** The play layout's cross, which the bury and the round end share, so the
 *  table keeps one geometry from the kitty to the scores. */
const SPREAD = ".table-screen:is(.phase-play, .phase-bury, .phase-round_end)";
const handRule = rule(block, ".hand");
const smallRule = rule(block, ".hand.small-cards");

// Device frames: landscape safe areas from the simulator (side insets carry
// the Dynamic Island, the bottom one the home indicator); and the same sizes
// as a browser draws them, with no insets.
const PHONES: Record<string, Viewport> = {
  "iPhone SE 667x375": { w: 667, h: 375, left: 0, right: 0, bottom: 0, top: 0 },
  "iPhone 13 mini 812x375": { w: 812, h: 375, left: 50, right: 50, bottom: 21, top: 0 },
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

/** Evaluates a CSS position with its percentages taken of `base` px. */
function evalPos(expr: string, base: number, vp: Viewport, vars: Record<string, string>): number {
  return evalLength(expr.replace(/(-?[\d.]+)%/g, (_, n) => `${(Number(n) * base) / 100}px`), vp, vars);
}

/** A translate() of percentages, as fractions of the element's own size. */
function translateFrac(transform: string | undefined): [number, number] {
  const m = /translate\((-?[\d.]+)%?,\s*(-?[\d.]+)%?\)/.exec(transform ?? "");
  return m ? [Number(m[1]) / 100, Number(m[2]) / 100] : [0, 0];
}


/** The table's regions at one viewport, from the tokens and the rules below.
 *  `phase` picks the play layout (your slot is your row) or the setup one
 *  (the row sits under the cross). Every slot holds a `cards`-card play: four
 *  in play, a two-card declaration while setting up. */
function geometry(vp: Viewport, vars0: Record<string, string>, phase: "play" | "setup" = "play",
                  cards = phase === "play" ? 4 : 2) {
  const vars = phase === "play" ? { ...vars0, ...rule(block, SPREAD) }
    : vars0;
  const L = (name: string) => evalLength(vars[name], vp, vars);
  const has = (name: string) => vars[name] !== undefined;
  const tcw = L("--trick-cw");
  const tch = L("--trick-ch");
  const dyTop = has("--dy-top") ? L("--dy-top") : L("--slot-dy");
  const dyBottom = has("--dy-bottom") ? L("--dy-bottom") : L("--slot-dy");
  const sideDy = has("--side-dy") ? L("--side-dy") : 0;
  const trickTop = L("--trick-top");
  const liftLine = vp.h - L("--trick-bottom");        // the hand's lift line
  const crossBottom = vp.h - L("--cross-bottom");
  const cx = vp.w / 2;
  const cy = (trickTop + crossBottom) / 2;
  const tPitch = rule(block, ".trick-play")["--t-pitch"];
  const pitch = tPitch ? evalLength(tPitch, vp, vars, { n: cards }) : tcw * 0.72;
  const width = tcw + (cards - 1) * pitch;
  const card = (xc: number, yc: number): Rect => ({ x0: xc - width / 2, x1: xc + width / 2, y0: yc - tch / 2, y1: yc + tch / 2 });
  // side slots from their own rules: anchored by whichever edge is set
  const areaW = evalLength(rule(block, ".trick-area").width, vp, vars);
  const areaX0 = cx - areaW / 2;
  const side = (sel: string): Rect => {
    const r = rule(block, sel);
    const yc = cy + sideDy;
    if (r.left && r.left !== "auto") {
      const x0 = areaX0 + evalPos(r.left, areaW, vp, vars);
      return { x0, x1: x0 + width, y0: yc - tch / 2, y1: yc + tch / 2 };
    }
    const x1 = areaX0 + areaW - evalPos(r.right, areaW, vp, vars);
    return { x0: x1 - width, x1, y0: yc - tch / 2, y1: yc + tch / 2 };
  };
  const cardsAt: Record<string, Rect> = {
    top: card(cx, cy - dyTop), bottom: card(cx, cy + dyBottom),
    left: side(".trick-play.pos-left"), right: side(".trick-play.pos-right"),
  };
  // each slot's tag line (LEAD + WINS side by side: about 90 x 16) from the tag rule
  const tagRule = rule(block, ".trick-tag");
  const below = (tagRule.top ?? "").includes("100%");
  const tag = (c: Rect): Rect => {
    const xc = (c.x0 + c.x1) / 2;
    return below ? { x0: xc - 45, x1: xc + 45, y0: c.y1 + 4, y1: c.y1 + 20 } : { x0: xc - 45, x1: xc + 45, y0: c.y1 - 20, y1: c.y1 - 4 };
  };
  const tags = Object.fromEntries(Object.entries(cardsAt).map(([k, c]) => [k, tag(c)])) as Record<string, Rect>;
  const foot = (k: string): Rect => {
    const c = cardsAt[k], t = tags[k];
    return { x0: Math.min(c.x0, t.x0), x1: Math.max(c.x1, t.x1), y0: Math.min(c.y0, t.y0), y1: Math.max(c.y1, t.y1) };
  };
  const slots = Object.fromEntries(Object.keys(cardsAt).map((k) => [k, foot(k)])) as Record<string, Rect>;
  // side seats' labels from their rules, at their widest (--pill-max; 84 when absent)
  const pillW = has("--pill-max") ? L("--pill-max") : 84;
  const pillH = L("--header-h");
  const shared = rule(block, ".opponent.pos-left, .opponent.pos-right");
  const pill = (sel: string): Rect => {
    const r = { ...shared, ...rule(block, sel) };
    const [fx, fy] = translateFrac(r.transform);
    const x = r.left && r.left !== "auto"
      ? evalPos(r.left, vp.w, vp, vars) + fx * pillW
      : vp.w - evalPos(r.right, vp.w, vp, vars) - pillW + fx * pillW;
    const y = evalPos(r.top, vp.h, vp, vars) + fy * pillH;
    return { x0: x, x1: x + pillW, y0: y, y1: y + pillH };
  };
  // your row: Play (88) centred between the row's symmetric paddings, Clear
  // (8 + 76) just right of it, the banker's crown (28) 8px left of it
  const padL = L("--safe-l") + 8;
  const padR = L("--safe-r") + 8;
  const rowCentre = (padL + vp.w - padR) / 2;
  const rowRule = { ...rule(block, ".you-row"), ...(phase === "play" ? rule(block, ".phase-play .you-row") : {}) };
  const rowB = vp.h - evalLength(rowRule.bottom, vp, vars);
  const rowY0 = rowB - L("--row-h");
  const row: Rect = { x0: rowCentre - 44, x1: rowCentre + 44 + 84, y0: rowY0, y1: rowB };
  const crown: Rect = { x0: rowCentre - 44 - 8 - 28, x1: rowCentre - 44 - 8, y0: rowB - 25 - 14, y1: rowB - 25 + 14 };
  const header = 6 + vp.top + L("--header-h");
  return { tcw, cx, cy, sideDy, cards: cardsAt, tags, slots, pills: { left: pill(".opponent.pos-left"), right: pill(".opponent.pos-right") },
    pillW, topLabelBottom: header, row, crown, rowCentre, header, liftLine, crossBottom,
    zoneTop: vp.h - L("--zone-bottom"), handTop: vp.h - L("--hand-h"), safeW: L("--safe-w"), handCw: L("--hand-cw") };
}

const gap = (a: Rect, b: Rect) => Math.max(b.x0 - a.x1, a.x0 - b.x1, b.y0 - a.y1, a.y0 - b.y1);

describe("phone table geometry", () => {
  it("lays the trick out from the tokens", () => {
    expect(rule(block, ".trick-area").top).toBe("var(--trick-top)");
    expect(rule(block, ".trick-area").bottom).toBe("var(--cross-bottom)");
    expect(rule(block, ".trick-cards")["--cw"]).toBe("var(--trick-cw)");
    expect(rule(block, ".trick-cards .card + .card")["margin-left"]).toBe("calc(var(--t-pitch) - var(--trick-cw))");
    // up to four cards at a 60% pitch; longer plays pack into four cards' span
    const tp = rule(block, ".trick-play")["--t-pitch"];
    const vp14 = PHONES["iPhone 14 Pro 852x393"];
    const cw = evalLength(tokens["--trick-cw"], vp14, tokens);
    for (const n of [1, 2, 4, 8, 12]) {
      const pitch = evalLength(tp, vp14, tokens, { n });
      expect(cw + (n - 1) * pitch).toBeLessThanOrEqual(cw * 2.8 + 0.01);
      if (n <= 4) expect(pitch).toBeCloseTo(cw * 0.6, 5);
    }
    expect(rule(block, ".trick-play.pos-top").translate).toBe("-50% calc(-50% - var(--dy-top))");
    expect(rule(block, ".trick-play.pos-bottom").translate).toBe("-50% calc(-50% + var(--dy-bottom))");
    // side slots are anchored at their outer edge and grow inward
    expect(rule(block, ".trick-play.pos-left").left).toBe("calc(50% - var(--side-out))");
    expect(rule(block, ".trick-play.pos-left").right).toBe("auto");
    expect(rule(block, ".trick-play.pos-right").right).toBe("calc(50% - var(--side-out))");
    expect(rule(block, ".trick-play.pos-right").left).toBe("auto");
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
    expect(tokens["--cross-bottom"]).toBe("calc(var(--zone-bottom) + var(--row-reserve) + var(--gap-v))");
    expect(rule(block, SPREAD)["--row-reserve"]).toBe("0px");
    // side seats' labels stand at the felt's edges, level with their cards
    expect(rule(block, ".opponent.pos-left, .opponent.pos-right").top)
      .toBe("calc((var(--trick-top) + 100% - var(--cross-bottom)) / 2 + var(--side-dy))");
    expect(rule(block, ".opponent.pos-left, .opponent.pos-right").transform).toBe("translate(0, -50%)");
    expect(rule(block, ".opponent.pos-left").left).toBe("calc(var(--safe-l) + var(--space-s))");
    expect(rule(block, ".opponent.pos-left").right).toBe("auto");
    expect(rule(block, ".opponent.pos-right").right).toBe("calc(var(--safe-r) + var(--space-s))");
    expect(rule(block, ".opponent.pos-right").left).toBe("auto");
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
      const play = geometry(vp, tokens, "play");
      const setup = geometry(vp, tokens, "setup");

      const checkRegions = (g: ReturnType<typeof geometry>, phase: "play" | "setup") => {
        const slots = Object.values(g.slots);
        const pills = [g.pills.left, g.pills.right];
        // the cross between the header and the hand; no two slots (cards and
        // their tag line) come within 8pt, even with a four-card play in each
        expect(g.slots.top.y0).toBeGreaterThanOrEqual(g.header + 8 - 0.01);
        for (let i = 0; i < slots.length; i++) for (let j = i + 1; j < slots.length; j++) {
          expect(gap(slots[i], slots[j])).toBeGreaterThanOrEqual(8 - 0.01);
        }
        // side labels: 8pt in from the safe edges, level with their slot's
        // cards; at their widest 8pt clear of every slot (its cards and its
        // tag line, each on its own), your row and the hand, and under the
        // header
        expect(g.pills.left.x0).toBeCloseTo(vp.left + 8, 5);
        expect(g.pills.right.x1).toBeCloseTo(vp.w - vp.right - 8, 5);
        for (const p of pills) {
          expect((p.y0 + p.y1) / 2).toBeCloseTo(g.cy + g.sideDy, 5);
          expect(p.y0).toBeGreaterThanOrEqual(g.header + 4 - 0.01);
          for (const k of ["top", "bottom", "left", "right"]) {
            expect(gap(p, g.cards[k]), `pill and ${k} cards`).toBeGreaterThanOrEqual(8 - 0.01);
            expect(gap(p, g.tags[k]), `pill and ${k} tag`).toBeGreaterThanOrEqual(8 - 0.01);
          }
          expect(gap(p, g.row)).toBeGreaterThanOrEqual(8 - 0.01);
          expect(p.y1).toBeLessThanOrEqual(g.handTop - 8);
        }
        // a label has room for a crown and an 8-letter name beside a
        // four-card throw (100px), and grows where the width allows
        expect(g.pillW).toBeGreaterThanOrEqual(100 - 0.01);
        // your row: centred, above the hand's lift, clear of the side slots
        expect(Math.abs(g.rowCentre - g.cx)).toBeLessThanOrEqual(2);
        for (const r of [g.row, g.crown]) {
          for (const k of ["left", "right", "top"]) expect(gap(r, g.slots[k])).toBeGreaterThanOrEqual(8 - 0.01);
          expect(r.y1).toBeLessThanOrEqual(g.liftLine);
        }
        if (phase === "setup") expect(gap(g.row, g.slots.bottom)).toBeGreaterThanOrEqual(8 - 0.01);
        expect(overlaps(g.crown, g.row)).toBe(false);
        expect(g.liftLine).toBeLessThanOrEqual(g.handTop);
        expect(g.row.x1).toBeLessThanOrEqual(vp.w - vp.right);
        expect(g.row.x0).toBeGreaterThanOrEqual(vp.left);
      };

      it("keeps the cross, the seats, your row and the hand apart, in play and while setting up", () => {
        checkRegions(play, "play");
        checkRegions(setup, "setup");
      });

      it("puts no tag over any card: every tag sits in its slot's line under the cards", () => {
        for (const g of [play, setup]) {
          for (const t of Object.values(g.tags)) for (const c of Object.values(g.cards)) expect(overlaps(t, c)).toBe(false);
        }
      });

      it("in play, your row is your slot: Play stands where your cards land", () => {
        // the row overlaps your cards' place and ends at the hand's lift, not under the cross
        expect(overlaps(play.row, play.cards.bottom)).toBe(true);
        expect(play.row.y0).toBeGreaterThanOrEqual(play.cards.bottom.y0 - 0.5);
        expect(play.row.y1).toBeLessThanOrEqual(play.zoneTop + 0.5);
      });

      it("while setting up spaces the cross evenly: the header, the slots and the row a gap apart", () => {
        const setupGaps = [setup.slots.top.y0 - setup.header, setup.slots.bottom.y0 - setup.slots.top.y1,
          setup.row.y0 - setup.slots.bottom.y1];
        for (const x of setupGaps) expect(Math.abs(x - setupGaps[0])).toBeLessThanOrEqual(2);
        expect(setupGaps[0]).toBeGreaterThanOrEqual(8 - 0.01);
      });

      it("in play spreads the rows: the top slot 8pt under the header, your slot at least 8pt above the hand and the side slots 8pt above your row, the rest between", () => {
        expect(play.slots.top.y0 - play.header).toBeCloseTo(8, 0);
        const toHand = play.handTop - play.slots.bottom.y1;
        const sideToRow = Math.min(play.row.y0 - play.slots.left.y1, play.row.y0 - play.slots.right.y1);
        expect(toHand).toBeGreaterThanOrEqual(8 - 0.01);
        expect(sideToRow).toBeGreaterThanOrEqual(8 - 0.01);
        // never tighter than the evenly spaced cross, whose gaps are --gap-v
        const even = evalLength(tokens["--gap-v"], vp, { ...tokens, ...rule(block, SPREAD) });
        const between = play.slots.bottom.y0 - play.slots.top.y1;
        expect(between).toBeGreaterThanOrEqual(even - 0.01);
        expect(between).toBeGreaterThanOrEqual(play.slots.top.y0 - play.header - 0.01);
      });

      it("keeps the side slots level with the cross's centre", () => {
        // the side slots sit at the cross's vertical centre, left and right alike
        for (const g of [play, setup]) {
          const mid = (g.slots.top.y0 + g.slots.bottom.y1) / 2;
          for (const s of [g.slots.left, g.slots.right]) expect(Math.abs((s.y0 + s.y1) / 2 - mid)).toBeLessThanOrEqual(1);
          expect(Math.abs((g.cx - g.cards.left.x0) - (g.cards.right.x1 - g.cx))).toBeLessThanOrEqual(1);
        }
      });

      it("keeps a side seat's label at its edge, outside its slot, a gap from where its cards start", () => {
        for (const g of [play, setup]) {
          expect(g.cards.left.x0 - g.pills.left.x1).toBeGreaterThanOrEqual(8 - 0.01);
          expect(g.pills.right.x0 - g.cards.right.x1).toBeGreaterThanOrEqual(8 - 0.01);
        }
      });

      it("sizes the trick cards by width and height (about 62px on a 14 Pro)", () => {
        // the short browser frames, with their larger hand, give the cross less height
        expect(play.tcw).toBeGreaterThanOrEqual(44);
        expect(play.tcw).toBeLessThanOrEqual(72);
        expect(play.tcw).toBeGreaterThanOrEqual(setup.tcw - 0.01);
      });

      it("fits a 25-card hand in one row at a pitch of at least 27px (24 on SE and mini)", () => {
        const pitch = evalLength(handRule["--pitch"], vp, tokens, { n: 25 });
        expect(pitch).toBeGreaterThanOrEqual(vp.w >= 852 ? 27 : 24);
        expect(24 * pitch + play.handCw).toBeLessThanOrEqual(play.safeW - 16 + 0.01);
        // a short hand stays at the capped pitch and centres
        expect(evalLength(handRule["--pitch"], vp, tokens, { n: 12 })).toBeCloseTo(play.handCw * 0.55, 5);
      });

      it("fits the 33-card bury hand in one row at the hand's own card size, in play's layout", () => {
        const pitch = evalLength(smallRule["--pitch"], vp, tokens, { n: 33 });
        expect(32 * pitch + play.handCw).toBeLessThanOrEqual(play.safeW - 16 + 0.01);
        expect(pitch).toBeGreaterThanOrEqual(18);
        checkRegions(play, "play");
      });
    });
  }

  it("keeps the hand's card size above 25 (only the pitch tightens), with no layout transition", () => {
    expect(block).not.toMatch(/:has\(\.hand\.small-cards\)\s*\{[^}]*--hand-cw/);
    expect(smallRule["--cw"]).toBeUndefined();
    expect(block).not.toMatch(/transition:[^;]*\b(width|flex-basis)\b/);
  });

  it("lays the bury and the round end out as play: no row reserved under the cross", () => {
    expect(rule(block, SPREAD)["--row-reserve"]).toBe("0px");
  });
});

describe("phone controls", () => {
  it("keeps every control's hit area at 44px or more", () => {
    expect(rule(block, ".action-bar .btn")["min-height"]).toBe("var(--ctl-h-sm)");
    expect(px(/--ctl-h-sm: (\d+px)/.exec(css)![1])).toBeGreaterThanOrEqual(44);
    const more = rule(block, ".hud-bar .hud-more-btn");
    const hit = rule(block, ".hud-bar .hud-more-btn::after").inset.split(" ").map((x) => -px(x));
    const [vertical, horizontal] = hit;
    expect(32 + 2 * vertical).toBeGreaterThanOrEqual(44);
    expect(px(more["min-width"]) + 2 * horizontal).toBeGreaterThanOrEqual(44);
    expect(more.height).toBe("var(--header-h)");
    expect(px(tokens["--header-h"])).toBe(32);
    // the menu is one for phone and desktop: its rows are drawn outside the phone block
    expect(px(rule(css, ".hud-menu-row")["min-height"])).toBeGreaterThanOrEqual(44);
    expect(rule(block, ".modal > .round-end-actions").position).toBe("sticky");
    // Next round and Leave game are the action size everywhere, the phone included
    expect(rule(css, ".round-end-actions > .btn.big")["min-height"]).toBe("var(--ctl-h)");
    expect(css).not.toMatch(/\.round-end-actions > \.btn\.big \{[^}]*min-height: \d/);
    // a card's tap area runs the full card height plus 16px above the hand
    expect(rule(block, ".hand .card::after").top).toBe("calc(-1 * var(--lift))");
  });

  it("shortens a long seat name inside a bounded label: smaller, then an ellipsis", () => {
    expect(tokens["--pill-max"]).toContain("calc(var(--view-w) / 2 - max(var(--safe-l), var(--safe-r)) - var(--side-out) - 2 * var(--space-s))");
    expect(rule(block, ".opponent.pos-left, .opponent.pos-right")["max-width"]).toBe("var(--pill-max)");
    expect(rule(block, ".opponent.pos-top")["--top-w"]).toContain("min(200px");
    const text = rule(block, ".opp-name-text");
    expect([text.overflow, text["text-overflow"], text["white-space"], text["min-width"]])
      .toEqual(["hidden", "ellipsis", "nowrap", "0"]);
    // the readable floor is for names long enough to need one
    expect(rule(block, '.opponent:is([data-name-len="m"], [data-name-len="l"]) .opp-name-text')["min-width"])
      .toBe("min(3em, 100%)");
    // the status tags beside the name give way before it does
    const tags = rule(block, ".opponent .opp-name > :is(.away-tag, .off-tag)");
    expect([tags["flex-shrink"], tags["min-width"]]).toEqual(["100", "0"]);
    // a long name steps down once, never below 12px
    expect(px(rule(block, ".opp-name")["font-size"])).toBe(13);
    expect(px(rule(block, '.opponent[data-name-len="m"] .opp-name, .opponent[data-name-len="l"] .opp-name')["font-size"])).toBe(12);
    for (const m of block.matchAll(/\.opp-name[^{]*\{([^}]*)\}/g)) {
      const size = /font-size:\s*(?:var\(--fs-)?([\d.]+)/.exec(m[1]);
      if (size) expect(Number(size[1])).toBeGreaterThanOrEqual(12);
    }
    // a human's turn is the fill, not a second line of text
    expect(rule(block, ".opponent .their-turn").display).toBe("none");
    // the whole name is a tap away, drawn only by the phone layout
    expect(rule(block, ".opp-fullname").display).toBe("block");
    // the tablet table shows it too, on a long press; nothing else does
    expect(rule(css.replace(block, "").replace(blockAt(TABLET_BLOCK), ""), ".opp-fullname").display).toBe("none");
  });

  it("fits a short seat name whole beside the banker's crown, and the top seat's name in its stretch", () => {
    // a side label at its widest holds, left to right: padding, the crown,
    // the gaps, the name and the turn's "\u2026" room, then padding
    const pill = rule(block, ".opponent");
    const [pv, ph = pv] = pill.padding.split(" ");
    const pads = 2 * px(ph);
    const crownRule = { ...rule(block, ".banker-crown"), ...rule(block, ".opponent .banker-crown") };
    const crownW = 1.25 * px(crownRule["font-size"]) + (crownRule["margin-right"] ? px(crownRule["margin-right"]) : 0);
    const gap = px(rule(block, ".opponent .opp-name").gap.replace("var(--space-xs)", "4px"));
    const nameFont = px(rule(block, ".opp-name")["font-size"]);
    const dots = 1.1 * nameFont;
    // "Bot Wei" drawn in the system font is 4.1em
    const shortName = 4.1 * nameFont;
    for (const [name, vp] of FRAMES) {
      const pillMax = evalLength(tokens["--pill-max"], vp, tokens);
      const room = pillMax - pads - crownW - 2 * gap - dots;
      expect(room, `${name}: name room beside the crown`).toBeGreaterThanOrEqual(shortName);
    }
    // the top seat may take up to 150px of its stretch off centre ("Lucky Dragon" is 6.9em)
    const top = rule(block, ".opponent.pos-top");
    expect(top["--top-w"]).toContain("var(--top-cap, 150px)");
    const se = PHONES["iPhone SE 667x375"];
    const vars = { ...tokens, ...top, "--hud-strip-w": "264px", "--chat-w": "40px" };
    const topW = evalLength(top["--top-w"], se, vars);
    expect(topW).toBeGreaterThanOrEqual(6.9 * nameFont + 2 * px(ph) + 8 + 2 * gap + dots);
  });

  it("keeps table text at 11px or more", () => {
    for (const sel of [".lead-tag, .win-tag", ".declare-tag", ".you-tag, .host-tag, .off-tag", ".hand-line", ".chip"]) {
      expect(px(rule(block, sel)["font-size"])).toBeGreaterThanOrEqual(11);
    }
  });

  it("draws the trick tags at 12px inside the slot's 20px tag line", () => {
    for (const sel of [".lead-tag, .win-tag", ".declare-tag"]) {
      const r = rule(block, sel);
      expect(px(r["font-size"])).toBeGreaterThanOrEqual(12);
      const [py] = r.padding.split(" ").map(px);
      expect(px(r["line-height"]) + 2 * py).toBeLessThanOrEqual(20);
    }
  });

  it("shows whose turn as a filled gold label ending in \u2026, the team as a dot inside it", () => {
    const on = rule(block, ".opponent.on-turn");
    expect(on.background).toBe("var(--gold)");
    expect(on["box-shadow"]).toBe("none");
    expect(on.animation).toBeUndefined();
    expect(rule(block, ".opponent.on-turn .opp-name").color).toBe("#1a1a1a");
    expect(rule(block, ".opponent .turn-dots").display).toBe("inline-block");
    // on turn the fill stands for the seat: the dot is hidden but keeps its room
    expect(rule(block, ".opponent.on-turn .seat-dot").visibility).toBe("hidden");
    // no coloured edge: the team is the dot
    expect(/\.opponent[^{]*\{[^}]*border-left/.test(block)).toBe(false);
    expect(rule(block, ".opponent .seat-dot.t0").background).toBe("var(--team0)");
    expect(rule(block, ".opponent .seat-dot.t1").background).toBe("var(--team1)");
    // off the phone neither mark is drawn
    expect(rule(css.replace(block, ""), ".seat-dot, .turn-dots").display).toBe("none");
  });

  it("keeps a seat's label one width on and off turn, so its neighbours never shift", () => {
    // on turn the padding does not change
    expect(rule(block, ".opponent.on-turn").padding).toBeUndefined();
    expect(rule(block, ".opponent.on-turn")["padding-right"]).toBeUndefined();
    // the dot and the "…" both keep their room in both states; only visibility changes
    const dots = rule(block, ".opponent .turn-dots");
    expect([dots.display, dots.width, dots.visibility]).toEqual(["inline-block", "1.1em", "hidden"]);
    expect(rule(block, ".opponent .turn-dots.shown").visibility).toBe("visible");
    expect(rule(block, ".opponent.on-turn .seat-dot").display).toBeUndefined();
    // a running countdown takes the dots' place in both turn states alike
    const counting = ".opponent:has(.off-tag.counting) .turn-dots";
    expect(rule(block, counting).display).toBe("none");
    expect(block.split(counting).join("")).not.toMatch(/\.turn-dots[^{]*\{[^}]*display: none/);
  });

  it("gives a seat's label a 44px tall tap area", () => {
    const hit = rule(block, ".opponent::after");
    expect(hit.position).toBe("absolute");
    const [vertical] = hit.inset.split(" ").map((x) => -px(x));
    expect(32 + 2 * vertical).toBeGreaterThanOrEqual(44);
  });

  it("draws no hint under Your turn", () => {
    expect(css).not.toContain("lead-hint");
  });

  it("lets the banker's crown stand in for its team dot, so a short name fits beside the crown", () => {
    expect(rule(block, ".opponent:has(.banker-crown) .seat-dot").display).toBe("none");
  });

  it("hides the lone crown beside Bury", () => {
    expect(rule(block, ".phase-bury .you-row:has(.action-bar .btn) .you-tagline:has(.banker-crown)").display).toBe("none");
  });

  it("lets a finger slide across the hand without panning it", () => {
    expect(rule(block, ".hand.selectable")["touch-action"]).toBe("none");
  });

  it("turns the table's long-press callout and text selection off, except in text fields", () => {
    expect(tokens["-webkit-touch-callout"]).toBe("none");
    expect(tokens["-webkit-user-select"]).toBe("none");
    expect(rule(block, ".table-screen input, .table-screen textarea")["-webkit-user-select"]).toBe("text");
  });

  it("puts LEAD / WINS / declares by one rule for every seat, just under the cards", () => {
    const tag = rule(block, ".trick-tag");
    expect([tag.position, tag.top, tag.bottom, tag.left, tag.translate]).toEqual(["absolute", "calc(100% + var(--space-xs))", "auto", "50%", "-50% 0"]);
    expect(tag["flex-direction"]).toBe("row");
    expect(px(tokens["--tag-s"])).toBeGreaterThanOrEqual(20);
    // no seat overrides it
    expect(/\.trick-play\.pos-\w+[^{]*\.trick-tag/.test(block)).toBe(false);
  });

  it("draws no glow anywhere: not on the hand, the seats, the crown or the winning cards", () => {
    expect(block.includes(".hand::before")).toBe(false);
    expect(/box-shadow:[^;]*(gold|242, 193, 78)/.test(block)).toBe(false);
    expect(rule(block, ".banker-crown").filter).toBe("none");
    expect(rule(block, ".game-won-crown").filter).toBe("none");
    expect(rule(block, ".level-chip.level-up").animation).toBe("none");
    expect(rule(block, ".opponent.on-turn")["box-shadow"]).toBe("none");
    expect(block.includes(".opponent.on-turn::after")).toBe(false);
    expect(rule(block, ".trick-play.winner .trick-cards").animation).toBe("none");
    expect(rule(block, ".trick-play.winner .trick-cards .card")["box-shadow"]).not.toContain("gold");
    expect(rule(block, ".opp-cards").display).toBe("none");
  });

  it("gives every seat label one height, radius and type size; ready is a small check", () => {
    const o = rule(block, ".opponent");
    expect([o.height, o["border-radius"]]).toEqual(["var(--header-h)", "999px"]);
    for (const sel of [".opponent.pos-left, .opponent.pos-right", ".opponent.pos-left", ".opponent.pos-right", ".opponent.pos-top"]) {
      expect(rule(block, sel).height ?? "var(--header-h)").toBe("var(--header-h)");
      expect(rule(block, sel)["border-radius"]).toBeUndefined();
      expect(rule(block, sel)["font-size"]).toBeUndefined();
    }
    const ready = rule(block, ".opponent .ready-tag");
    expect([ready["font-size"], ready.width, ready["flex-shrink"]]).toEqual(["0", "14px", "0"]);
  });

  it("uses one spacing scale", () => {
    expect(["--space-xs", "--space-s", "--space-m", "--space-l"].map((t) => px(tokens[t]))).toEqual([4, 8, 12, 16]);
  });

  it("shows your turn as Play reading \"Your turn\", fully opaque, not a glow", () => {
    // no name pill on the phone table, ever
    expect(rule(block, ".you-tagline").display).toBe("none");
    expect(rule(block, ".you-tagline .you-name, .you-tagline .your-turn-tag, .you-tagline .ready-tag").display).toBe("none");
    expect(rule(block, ".phase-play .action-bar .btn.primary.your-turn .your-turn-text").display).toBe("inline");
    expect(rule(block, ".phase-play .action-bar .btn.primary.your-turn .play-text").display).toBe("none");
    expect(rule(block, ".phase-play .action-bar .btn.primary.your-turn:disabled").opacity).toBe("1");
    expect(rule(css.replace(block, ""), ".your-turn-text").display).toBe("none");
    // the row steps aside while a finished trick lingers on your slot
    expect(rule(block, ".phase-play.showing-last .you-row").visibility).toBe("hidden");
  });

  it("puts felt text on the dark pill", () => {
    for (const sel of [".lead-tag", ".declare-tag", ".deal-deck-count"]) {
      expect(rule(block, sel).background).toMatch(/^rgba\(8, 20, 14, 0\.7\d\)$/);
    }
  });
});

/** Whether a media query of `(min-|max-)(width|height)`, `pointer`, `hover`
 *  and `orientation` features, joined by `and` and listed by commas, matches a window. */
function mediaMatches(query: string, w: number, h: number, pointer: "fine" | "coarse"): boolean {
  return query.split(",").some((alt) => alt.trim().split(/\s+and\s+/).every((f) => {
    const m = /^\((min|max)-(width|height):\s*(\d+)px\)$/.exec(f.trim());
    if (m) {
      const v = m[2] === "width" ? w : h;
      return m[1] === "min" ? v >= Number(m[3]) : v <= Number(m[3]);
    }
    const p = /^\(pointer:\s*(\w+)\)$/.exec(f.trim());
    if (p) return p[1] === pointer;
    if (/^\(orientation:\s*landscape\)$/.test(f.trim())) return w > h;
    if (/^\(orientation:\s*portrait\)$/.test(f.trim())) return h >= w;
    // a mouse hovers, a finger does not
    if (/^\(hover:\s*hover\)$/.test(f.trim())) return pointer === "fine";
    throw new Error(`unread feature ${f}`);
  }));
}

describe("a desktop window", () => {
  // A desktop window at least 810x740 takes the tablet table, as an iPad
  // does; a smaller one keeps the wide table's fixed sizes, and only one
  // under 500px tall the phone table.
  const table = (w: number, h: number) =>
    mediaMatches(SHORT_VIEWPORT, w, h, "fine") ? "phone" : mediaMatches(TABLET_SCREEN, w, h, "fine") ? "tablet" : "wide";

  it("draws the tablet table from 810x740", () => {
    expect(table(1440, 900)).toBe("tablet");
    expect(table(1920, 1080)).toBe("tablet");
    expect(table(2560, 1440)).toBe("tablet");
    expect(table(810, 740)).toBe("tablet");
  });

  it("keeps the wide table below 810x740, the phone table under 500px tall", () => {
    expect(table(1024, 700)).toBe("wide");
    expect(table(1280, 739)).toBe("wide");
    expect(table(809, 900)).toBe("wide");
    expect(table(1024, 500)).toBe("phone");
  });

  it("keeps a desktop window of any shape off the upright layout", () => {
    expect(mediaMatches(TABLET_UPRIGHT, 820, 1180, "fine")).toBe(false);
    expect(table(820, 1180)).toBe("tablet");
  });

  it("draws the tablet table on every iPad, upright ones under 810px wide included", () => {
    const touch = (w: number, h: number) =>
      mediaMatches(SHORT_VIEWPORT, w, h, "coarse") ? "phone" : mediaMatches(TABLET_SCREEN, w, h, "coarse") ? "tablet" : "wide";
    expect(touch(1133, 744)).toBe("tablet");
    expect(touch(1366, 1024)).toBe("tablet");
    expect(touch(820, 1180)).toBe("tablet");
    expect(touch(1133, 700)).toBe("phone");
    // upright, each play lands at its seat, so a mini's 744px is wide enough
    expect(touch(744, 1133)).toBe("tablet");
    expect(touch(768, 1024)).toBe("tablet");
    expect(touch(768, 954)).toBe("tablet");
    expect(touch(744, 899)).toBe("wide");
    for (const [w, h] of [[744, 1133], [768, 1024], [820, 1180], [1024, 1366]]) expect(mediaMatches(TABLET_UPRIGHT, w, h, "coarse")).toBe(true);
    for (const [w, h] of [[1180, 820], [1366, 1024], [1133, 744]]) expect(mediaMatches(TABLET_UPRIGHT, w, h, "coarse")).toBe(false);
  });
});

describe("a large desktop window draws the pages off the table larger, whole", () => {
  const zooms = [...css.matchAll(/@media ([^{]+)\{\s*:root:not\(:has\(\.table-screen\)\) \{ zoom: ([\d.]+); \}/g)]
    .map((m) => ({ query: m[1].trim(), zoom: Number(m[2]) }));
  /** The page's zoom in a window: the last matching rule wins. */
  const zoomAt = (w: number, h: number, pointer: "fine" | "coarse") =>
    zooms.filter((z) => mediaMatches(z.query, w, h, pointer)).reduce((_, z) => z.zoom, 1);

  it("holds two steps, for a mouse only", () => {
    expect(zooms).toHaveLength(2);
    for (const z of zooms) expect(z.query.startsWith("(hover: hover) and (pointer: fine) and ")).toBe(true);
  });

  it("zooms by a quarter from 1600x900 and by two fifths from 2200x1200", () => {
    expect(zoomAt(1440, 900, "fine")).toBe(1);
    expect(zoomAt(1920, 880, "fine")).toBe(1);
    expect(zoomAt(1920, 1080, "fine")).toBe(1.25);
    expect(zoomAt(2560, 1440, "fine")).toBe(1.4);
    expect(zoomAt(2560, 1100, "fine")).toBe(1.25);
  });

  it("never zooms a touch screen, nor the table", () => {
    expect(zoomAt(2732, 2048, "coarse")).toBe(1);
    // the root is zoomed only while no table is drawn, and the page's frame
    // follows the window rather than a zoomed 100dvh
    expect(css).toMatch(/:root:not\(:has\(\.table-screen\)\) \.app \{ height: 100%; \}/);
    expect(css.match(/zoom: 1\.(25|4);/g)).toHaveLength(2);
  });
});

describe("a desktop leaves the small and the touch screen's rules alone", () => {
  // Everything the phone and the tablet blocks style for their screens must
  // live inside them, so a window that matches neither (the wide table) is
  // untouched.
  const outside = css.replace(block, "").replace(blockAt(TABLET_BLOCK), "").replace(blockAt(UPRIGHT_BLOCK), "");

  it("styles the phone-only classes only inside the phone block", () => {
    for (const cls of ["small-cards", "my-turn", "hud-menu-choice", "hud-menu-confirm", "deal-deck-"]) {
      expect(outside.includes(`.${cls}`), cls).toBe(false);
    }
    // the deck is hidden everywhere else
    expect(rule(outside, ".deal-deck").display).toBe("none");
  });

  it("keys the phone layout on one root class, never on a media query of its own", () => {
    expect(css.split(PHONE_BLOCK)).toHaveLength(2);
    // phoneLayout.ts sets the class from the height query
    expect(css.includes("@media (max-height: 500px)")).toBe(false);
  });
});

describe("the table's frame", () => {
  it("reads the viewport and safe areas only through the frame tokens", () => {
    // every vw, vh and env() in the block is a frame token's fallback
    const stripped = block
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/--(view-[wh]|safe-[tlrb]):[^;]*;/g, "");
    expect(stripped).not.toMatch(/\d(vw|vh)\b|env\(/);
  });

  it("turns a portrait phone's table a quarter turn into a landscape frame, safe areas with it", () => {
    const r = rule(css, ".app.rotated");
    expect([r.position, r.width, r.height, r["transform-origin"], r.transform])
      .toEqual(["fixed", "100dvh", "100dvw", "top left", "translateX(100dvw) rotate(90deg)"]);
    // the frame's left edge lies along the screen's top, its right along the bottom
    expect(r["--frame-safe-l"]).toBe("env(safe-area-inset-top, 0px)");
    expect(r["--frame-safe-r"]).toBe("env(safe-area-inset-bottom, 0px)");
    expect(r["--frame-safe-t"]).toBe("env(safe-area-inset-right, 0px)");
    expect(r["--frame-safe-b"]).toBe("env(safe-area-inset-left, 0px)");
    expect([r["--frame-w"], r["--frame-h"]]).toEqual(["100dvh", "100dvw"]);
    // no rotate card any more
    expect(css.includes(".rotate-hint")).toBe(false);
  });

  it("lays the rotated table out exactly as the same phone held sideways", () => {
    // a 14 Pro held upright: 393 x 852, the island on top, the home indicator below
    const portrait: Viewport = { w: 393, h: 852, left: 0, right: 0, bottom: 34, top: 59 };
    const frame = { "--frame-w": "852px", "--frame-h": "393px", "--frame-safe-t": "0px",
      "--frame-safe-l": "59px", "--frame-safe-r": "34px", "--frame-safe-b": "0px" };
    const sideways: Viewport = { w: 852, h: 393, left: 59, right: 34, bottom: 0, top: 0 };
    const a = geometry(portrait, { ...tokens, ...frame }, "play");
    const b = geometry(sideways, tokens, "play");
    expect(a.tcw).toBeCloseTo(b.tcw, 6);
    expect(a.handCw).toBeCloseTo(b.handCw, 6);
    expect(a.safeW).toBeCloseTo(b.safeW, 6);
    expect(a.pillW).toBeCloseTo(b.pillW, 6);
  });
});

describe("the one toast at the table", () => {
  const t = rule(block, ".table-screen .toast.at-table");
  it("stands just above your action row, centred, inside the cross's width", () => {
    expect(t.top).toBe("auto");
    expect(t.bottom).toBe("calc(var(--zone-bottom) + var(--row-h) + var(--space-s))");
    expect(t["max-width"]).toBe("calc(2 * var(--side-out) - 2 * var(--space-s))");
  });

  for (const [name, vp] of FRAMES) {
    it(`covers no side seat's label, your row, the hand or the top seat's play: ${name}`, () => {
      for (const phase of ["play", "setup"] as const) {
        const g = geometry(vp, tokens, phase);
        const vars = phase === "play" ? { ...tokens, ...rule(block, SPREAD) } : tokens;
        const L = (e: string) => evalLength(e, vp, vars);
        const y1 = vp.h - L(t.bottom);
        // two lines at most: 2 x 17 + 12 of padding
        const toast: Rect = { x0: g.cx - L(t["max-width"]) / 2, x1: g.cx + L(t["max-width"]) / 2, y0: y1 - 46, y1 };
        expect(toast.y0).toBeGreaterThanOrEqual(g.header);
        expect(toast.y1).toBeLessThanOrEqual(g.handTop);
        expect(overlaps(toast, g.row)).toBe(false);
        for (const p of [g.pills.left, g.pills.right]) expect(overlaps(toast, p)).toBe(false);
        // a one-line toast (17 + 12 of padding) clears the top seat's play
        expect(overlaps({ ...toast, y0: y1 - 29 }, g.cards.top)).toBe(false);
      }
    });
  }
});

describe("the round-end dialog in a turned portrait game", () => {
  it("takes the table's quarter turn itself, since the top layer ignores the .app transform", () => {
    const app = css.match(/\.app\.rotated \{[^}]*\}/)?.[0] ?? "";
    const modal = css.match(/\.app\.rotated dialog\.modal-backdrop:modal \{[^}]*\}/)?.[0] ?? "";
    const turn = /transform:\s*([^;]+);/;
    expect(modal).not.toBe("");
    expect(modal.match(turn)?.[1]).toBe(app.match(turn)?.[1]);
    for (const decl of ["width: 100dvh", "height: 100dvw", "transform-origin: top left", "--frame-w: 100dvh"]) {
      expect(modal).toContain(decl);
    }
  });
});

describe("the phone hand", () => {
  it("does not clip a selected card's gold ring above the lift band", () => {
    const hand = rule(phoneBlock(), ".hand");
    expect(hand.overflow).toBe("visible");
    expect(hand["overflow-x"]).toBeUndefined();
  });
});

describe("the header row on a phone", () => {
  // The level-and-points strip's width as drawn in Chromium: levels 10/J with
  // 65 points, levels 10/10 with 105 points, the same with the games score
  // (Games 3–2), and the first and last at the 1.3x text cap. The games chip
  // draws 25px (31px at 1.3x) wider than a star on each level chip did.
  const STRIPS = { "10/J 65": 259, "10/10 105": 287, "10/10 105 games": 375, "1.3x text": 290, "1.3x games": 431 };
  const top = rule(block, ".opponent.pos-top");
  const chat = rule(block, ".table-screen .chat-launch");
  /** The top label at its widest, the strip and Chat, for a strip `stripW` wide. */
  function header(vp: Viewport, stripW: number) {
    const vars = { ...tokens, ...top, "--hud-strip-w": `${stripW}px` };
    const L = (e: string) => evalLength(e, vp, vars);
    const w = Math.max(0, L(top["max-width"]));
    const left = L(top.left);
    const safeL = L("var(--safe-l)");
    const stripEnd = safeL + 4 + stripW;
    const chatX0 = vp.w - L(chat.right) - px(chat.width);
    return { label: { x0: left - w / 2, x1: left + w / 2 }, w, stripEnd, chatX0, centre: vp.w / 2 };
  }
  const turns = (vp: Viewport): [string, Viewport][] => [
    ["", vp],
    // the other landscape direction, and a lopsided inset either way
    [" turned", { ...vp, left: vp.right, right: vp.left }],
    [" inset left only", { ...vp, right: 0 }],
    [" inset right only", { ...vp, left: 0 }],
  ];

  it("draws the levels and the points as one strip, with no divider and no mode chip", () => {
    const points = rule(block, ".points-chip");
    expect(points["box-shadow"]).toBeUndefined();
    expect(points.background).toBe("var(--pill-bg)");
    expect(block.includes("points-bar")).toBe(false);
    expect(block.includes("mode-chip")).toBe(false);
    expect(css.includes("--hud-mode-w")).toBe(false);
  });

  it("places the top label from the measured strip, inside its own stretch", () => {
    expect(top["max-width"]).toBe("var(--top-w)");
    expect(top["--top-from"]).toBe("calc(var(--safe-l) + 4px + var(--hud-strip-w, 264px) + var(--space-s))");
    expect(top.transform).toBe("translateX(-50%)");
    expect(chat.right).toBe("calc(var(--safe-r) + 4px + 36px + var(--space-s))");
  });

  for (const [name, vp0] of FRAMES) for (const [turn, vp] of turns(vp0)) {
    it(`${name}${turn}: the strip, the top label and Chat keep an 8px gap`, () => {
      for (const [content, stripW] of Object.entries(STRIPS)) {
        const h = header(vp, stripW);
        if (h.w === 0) continue;
        expect(h.label.x0 - h.stripEnd, content).toBeGreaterThanOrEqual(8 - 0.01);
        expect(h.chatX0 - h.label.x1, content).toBeGreaterThanOrEqual(8 - 0.01);
      }
      // the label always keeps room for a name, and is centred over its slot
      // whenever the strip leaves it the room
      for (const content of Object.keys(STRIPS) as (keyof typeof STRIPS)[]) {
        const h = header(vp, STRIPS[content]);
        expect(h.w, content).toBeGreaterThanOrEqual(64);
        if (h.centre - h.stripEnd - 8 >= h.w / 2 && h.chatX0 - 8 - h.centre >= h.w / 2) {
          expect((h.label.x0 + h.label.x1) / 2, content).toBeCloseTo(h.centre, 5);
        }
      }
    });
  }
});

describe("the round-end card on a phone", () => {
  it("keeps Next round and Leave in one row pinned to the bottom, with 12px padding all round the card", () => {
    const block = phoneBlock();
    expect(rule(block, ".modal").gap).toBe("8px");
    expect(rule(block, ".modal").padding).toBe("12px 16px");
    const row = rule(block, ".modal > .round-end-actions");
    expect(row.position).toBe("sticky");
    expect(row.bottom).toBe("0");
    expect(rule(css, ".round-end-actions").display).toBe("flex");
    expect(rule(css, ".round-end-actions > .dialog-leave-btn").margin).toBe("0");
  });

  it("draws each fan at the fitted step and swaps Details into the lanes' cell instead of widening the card", () => {
    expect(rule(css, ".round-end-fan > .card + .card")["margin-left"]).toBe("calc(var(--fit-step, 18px) - var(--cw))");
    expect(rule(css, ".round-end-play").width).toBe("var(--fit-col, auto)");
    expect(rule(css, ".round-end-swap").display).toBe("grid");
    expect(rule(css, ".round-end-swap > *")["grid-area"]).toBe("1 / 1");
    expect(rule(css, ".round-end-row")["flex-wrap"]).toBeUndefined();
    expect(css).not.toContain(".details-open");
  });

  it("sizes the cell to the view shown, the other out of the flow, the bar after it at the card's own gap, and keeps the bar's 14px rhythm above the buttons", () => {
    const hidden = rule(css, ".round-end-swap.details > .round-end-lanes,\n.round-end-swap:not(.details) > .round-end-details".replace("\n", " "));
    expect(hidden.position).toBe("absolute");
    expect(hidden.visibility).toBe("hidden");
    expect(rule(css, ".round-end-swap").position).toBe("relative");
    // the title's gap gets a little more air, one value for both views
    expect(rule(css, ".round-end-swap")["margin-top"]).toBe("10px");
    expect(rule(phoneBlock(), ".modal.round-end .round-end-swap")["margin-top"]).toBe("6px");
    // Details sits straight on the card, like the lanes: no box of its own
    expect(rule(css, ".round-end-details").background).toBeUndefined();
    expect(rule(css, ".round-end-details").padding).toBeUndefined();
    expect(rule(css, ".modal.round-end > .round-end-ladder").display).toBe("contents");
    expect(rule(css, ".round-end-actions")["margin-top"]).toBe(rule(css, ".points-bar")["padding-bottom"]);
  });
});

describe("the lobby on a phone, upright or sideways", () => {
  it("fills the screen with the panel colour instead of a card on felt", () => {
    const i = css.indexOf("@media (max-width: 600px) and (pointer: coarse), (max-height: 500px) and (pointer: coarse) {\n  .lobby-screen,");
    expect(i).toBeGreaterThan(-1);
    const block = css.slice(i, css.indexOf("\n}\n", i));
    expect(block).toContain("background: linear-gradient(180deg, var(--panel)");
    expect(block).toMatch(/\.lobby-screen > \.panel,[\s\S]*border: 0;[\s\S]*box-shadow: none;/);
  });
});

describe("the tablet table's trick cross", () => {
  // The tablet block's own size tokens, evaluated at iPad sizes: the iOS app
  // (the status bar and the home indicator take the top and bottom insets)
  // and the same screens with no insets.
  const tablet = blockAt(TABLET_BLOCK);
  const root = rule(tablet, "&");
  const hand = rule(tablet, ".hand");
  const small = rule(tablet, ".hand.small-cards");
  const IPADS: Record<string, Viewport> = {
    "touch 810x740": { w: 810, h: 740, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad mini 1133x744": { w: 1133, h: 744, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 1024x768": { w: 1024, h: 768, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 11\" 1180x820": { w: 1180, h: 820, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 13\" 1366x1024": { w: 1366, h: 1024, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 13\" 1376x1032": { w: 1376, h: 1032, left: 0, right: 0, bottom: 20, top: 24 },
  };
  // desktop browser windows, which take the same block
  const DESKTOPS: Record<string, Viewport> = {
    "desktop 1440x900": { w: 1440, h: 900, left: 0, right: 0, bottom: 0, top: 0 },
    "desktop 1920x1080": { w: 1920, h: 1080, left: 0, right: 0, bottom: 0, top: 0 },
    "desktop 2560x1440": { w: 2560, h: 1440, left: 0, right: 0, bottom: 0, top: 0 },
    "desktop 1280x760": { w: 1280, h: 760, left: 0, right: 0, bottom: 0, top: 0 },
  };
  const SIZES: [string, Viewport][] = [...Object.entries(IPADS).flatMap(([name, vp]) => [
    [`${name} (app)`, vp] as [string, Viewport],
    [`${name} (browser)`, { ...vp, top: 0, bottom: 0 }] as [string, Viewport],
  ]), ...Object.entries(DESKTOPS)];
  const at = (vp: Viewport) => {
    const L = (name: string) => evalLength(`var(${name})`, vp, root);
    const pitch = (r: Record<string, string>, n: number, vars = root) => evalLength(r["--pitch"], vp, { ...vars, "--cw": r["--cw"] ?? "var(--hcw)" }, { n });
    return {
      pitch33Full: pitch(small, 33, { ...root, "--hcw": root["--hcw-full"] }),
      hcw: L("--hcw"), full: L("--hcw-full"), tcw: L("--tcw"), side: L("--tcw-side"),
      avail: L("--cross-avail"), tags: L("--tag-room"), pitch25: pitch(hand, 25), pitch33: pitch(small, 33),
    };
  };

  it("sizes the hand and the trick from the tablet block alone", () => {
    const outside = css.replace(tablet, "").replace(blockAt(UPRIGHT_BLOCK), "");
    for (const token of ["--hcw", "--hcw-full", "--tcw", "--tcw-side", "--tag-room", "--cross-room", "--you-rest", "--size-rest", "--row-free", "--cross-fit"]) {
      expect(outside.includes(`${token}:`), token).toBe(false);
    }
    expect(outside).not.toMatch(/var\(--(hcw|tcw)\b/);
  });

  for (const [name, vp] of SIZES) {
    it(`fits the stacked plays between the top seat and your row, and keeps the hand tappable: ${name}`, () => {
      const g = at(vp);
      // the hand gives up at most a fifth of its card
      expect(g.hcw).toBeGreaterThanOrEqual(g.full * 0.8 - 0.01);
      expect(g.hcw).toBeLessThanOrEqual(g.full + 0.01);
      // the top and bottom plays, a tag line and a winner's lift fit the cross
      expect(2.8 * g.tcw + g.tags).toBeLessThanOrEqual(g.avail + 0.01);
      // a four-card throw in a side slot stops short of that side's seat
      expect(g.tcw).toBeLessThanOrEqual(g.side + 0.01);
      // never under the wide table's 52px card
      expect(g.tcw).toBeGreaterThanOrEqual(51.5);
      // the hand shrinks only while that lets the trick card grow
      if (g.hcw < g.full - 0.01) expect(g.tcw).toBeLessThanOrEqual(g.side + 0.01);
      // a finger's strip of every card in a 25-card hand; the banker's 33
      // take the screen's width whatever the card, as on the full hand
      expect(g.pitch25).toBeGreaterThanOrEqual(28);
      expect(g.pitch33).toBeGreaterThanOrEqual(g.pitch33Full - 0.01);
    });
  }

  // One row above the hand (your name, the hint, your controls) frees the
  // height your name's own row took; the cards are sized as before it, so
  // that height goes to the cross alone.
  for (const [name, vp] of SIZES) {
    it(`keeps the cards' size and gives the cross the height the one row frees: ${name}`, () => {
      const L = (expr: string) => evalLength(expr, vp, root);
      const u = L("var(--u)");
      // sized as the name above the controls was: 74u and a row besides the hand
      expect(L("var(--size-rest)")).toBeCloseTo(L("calc(74 * var(--u) + var(--row-h) + 12px + var(--safe-b))"), 6);
      expect(L("var(--you-rest)")).toBeCloseTo(L("var(--size-rest)") - 38 * u, 6);
      // the card reads the sizing height; the cross is drawn in the height as laid out
      expect(root["--tcw"]).toContain("var(--cross-fit)");
      expect(root["--cross-room"]).toContain("var(--size-rest)");
      expect(L("var(--cross-avail)") - L("var(--cross-fit)")).toBeCloseTo(38 * u, 6);
      const area = rule(tablet, ".trick-area");
      const tall = evalLength(area.height, vp, root);
      expect(tall).toBeLessThanOrEqual(L("var(--cross-avail)") + 0.01);
      expect(tall).toBeGreaterThanOrEqual(2.8 * L("var(--tcw)") + L("var(--tag-room)") - 0.01);
    });
  }

  it("lays your row as the phone's: the action centred, your name and timer left of it, Clear right", () => {
    // the tablet block places nothing in the row: the wide table's row rules do
    expect(rule(tablet, ".you-area").display).toBeUndefined();
    for (const sel of [".you-tagline", ".action-bar", ".hand-line, .hand-line.help", ".hand"]) {
      expect(rule(tablet, sel)["grid-area"]).toBeUndefined();
      expect(rule(tablet, sel)["justify-self"]).toBeUndefined();
    }
    // the hint stays out of the flow (the base rule), so showing it never moves a control
    expect(rule(tablet, ".hand-line, .hand-line.help").position).toBeUndefined();
    const W = ":root:not(.phone-landscape)";
    const row = rule(css, `${W} .you-row`);
    expect(row.display).toBe("grid");
    // both sides keep the name pill's least room, so the middle stays centred and gives way first
    const side = "minmax(calc(var(--pill-min) + var(--name-room)), 1fr)";
    expect(row["grid-template-columns"]).toBe(`${side} minmax(0, max-content) ${side}`);
    expect(rule(css, `${W} .you-row > .action-bar`)["grid-area"]).toBe("1 / 2");
    expect(rule(css, `${W} :is(.phase-play, .phase-bury) .you-row :is(.play-wrap, .bury-btn)`)["grid-area"]).toBe("1 / 2");
    expect(rule(css, `${W} :is(.phase-play, .phase-bury) .you-row .action-bar > :is(.btn.subtle, .bury-points)`)["grid-area"]).toBe("1 / 3");
    expect(rule(css, `${W} :is(.phase-play, .phase-bury) .you-row .action-bar > .timer-ring`)["grid-area"]).toBe("1 / 1");
    const name = rule(css, `${W} .you-row > .you-tagline`);
    expect(name["grid-area"]).toBe("1 / 1");
    expect(name["justify-self"]).toBe("end");
  });

  it("stands the joining pill in your row, its bottom level with the row's", () => {
    // the row's bottom: the area's padding, the hand's card and padding, the gap
    expect(rule(tablet, ".away-pill").bottom).toBe("calc(var(--you-rest) - var(--row-h) + var(--hcw) * 1.4)");
  });

  it("draws the iPad 11\" app's trick cards at about three quarters of its hand's", () => {
    const g = at(IPADS["iPad 11\" 1180x820"]);
    expect(g.hcw).toBeCloseTo(g.full * 0.8, 1);
    expect(g.tcw / g.hcw).toBeGreaterThan(0.72);
  });

  it("keeps the smallest tablet table's hand and trick cards, whose side seats leave no room to grow", () => {
    const g = at(IPADS["touch 810x740"]);
    expect(g.hcw).toBeCloseTo(g.full, 6);
    expect(g.tcw).toBeCloseTo(g.side, 6);
  });
});

describe("the tablet table held upright: each play in front of its seat", () => {
  const tablet = blockAt(TABLET_BLOCK);
  const upright = blockAt(UPRIGHT_BLOCK);
  const vars0 = { ...rule(tablet, "&"), ...rule(upright, "&") };
  const hand = rule(tablet, ".hand");
  const pitchRule = rule(upright, ".trick-play")["--t-pitch"];
  // the iOS app (status bar and home indicator insets) and a browser
  const UPRIGHTS: Record<string, Viewport> = {
    "iPad mini 744x1133": { w: 744, h: 1133, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 768x1024": { w: 768, h: 1024, left: 0, right: 0, bottom: 20, top: 20 },
    "iPad 810x1080": { w: 810, h: 1080, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 11\" 820x1180": { w: 820, h: 1180, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 11\" 834x1194": { w: 834, h: 1194, left: 0, right: 0, bottom: 20, top: 24 },
    "iPad 13\" 1024x1366": { w: 1024, h: 1366, left: 0, right: 0, bottom: 20, top: 24 },
  };
  const SIZES: [string, Viewport][] = [...Object.entries(UPRIGHTS).flatMap(([name, vp]) => [
    [`${name} (app)`, vp] as [string, Viewport],
    [`${name} (browser)`, { ...vp, top: 0, bottom: 0 }] as [string, Viewport],
  ]),
  // Safari's toolbars upright, the shortest window the query admits
  ["iPad 768x954 Safari", { w: 768, h: 954, left: 0, right: 0, bottom: 0, top: 0 }],
  ["touch 744x900", { w: 744, h: 900, left: 0, right: 0, bottom: 0, top: 0 }]];

  it("keys the layout on TABLET_UPRIGHT, once, and holds only the tablet class's rules", () => {
    expect(css.split(UPRIGHT_BLOCK)).toHaveLength(2);
    expect(upright.trim().startsWith(".tablet-table {")).toBe(true);
    expect(rule(upright, ".trick-area").inset).toBe("0");
    expect(rule(upright, ".trick-area").transform).toBe("none");
  });

  it("turns each seat into a one-line tag with its count, no card backs and no line under it", () => {
    const seat = rule(upright, ".opponent");
    expect(seat["flex-direction"]).toBe("row");
    expect(seat.height).toBe("var(--l1-tag-h)");
    expect(rule(upright, ".back-stack, .opponent .their-turn, .opponent .bot-banter").display).toBe("none");
    expect(rule(upright, ".opponent .opp-cards")["flex-shrink"]).toBe("0");
  });

  for (const [name, vp] of SIZES) {
    it(`stacks the top play, the side seats and your play apart, at 80px cards or more: ${name}`, () => {
      const L = (e: string, v: Record<string, string> = vars0) => evalLength(e, vp, v);
      const u = L("var(--u)");
      const felt = vp.h - L("var(--hud-h)");
      // 100% in a seat's top is the felt's height
      const inFelt = Object.fromEntries(Object.entries(vars0).map(([k, v]) => [k, v.replace(/100%/g, `${felt}px`)]));
      const tcw = L("var(--tcw)");
      expect(tcw).toBeGreaterThanOrEqual(80 - 0.01);
      const tagH = L("var(--l1-tag-h)");
      const playH = L("var(--l1-play-h)");
      const topTagB = 12 * u + tagH;
      const topT = L("var(--l1-top-t)");
      const topB = L("var(--l1-top-b)");
      const sideT = L("var(--l1-side-t)", inFelt);
      const sideB = sideT + L("var(--l1-side-h)");
      const bottomB = felt - L("var(--l1-bottom)");
      const bottomT = bottomB - playH;
      const youTop = felt - L("var(--you-h)");
      // A winner's cards rise by win-lift's translate, grow about their
      // centre by its scale, and wear a 2px ring: that much above the cards
      // must stay clear of the tag over them, with 8u to spare.
      const [, rise, grow] = /@keyframes win-lift \{\s*to \{\s*transform: translateY\(-(\d+)px\) scale\(([\d.]+)\);/.exec(css)!;
      const lift = Number(rise) + ((Number(grow) - 1) / 2) * tcw * 1.4 + 2;
      expect(topT - topTagB).toBeGreaterThanOrEqual(lift + 8 * u - 0.01);
      const sidePlayT = sideT + tagH + L("var(--l1-tag-gap)");
      expect(sidePlayT - (sideT + tagH)).toBeGreaterThanOrEqual(lift + 8 * u - 0.01);
      expect(L("var(--l1-side-h)")).toBeCloseTo(tagH + L("var(--l1-tag-gap)") + playH, 6);
      expect(sideT - topB).toBeGreaterThanOrEqual(lift + 16);
      expect(bottomT - sideB).toBeGreaterThanOrEqual(lift + 16);
      expect(youTop - bottomB).toBeGreaterThanOrEqual(12);
      // the side plays split the gaps above and below them evenly
      expect(sideT - topB).toBeCloseTo(bottomT - sideB, 4);
    });

    it(`keeps a side seat's play on its own half, and the hand at its width's card: ${name}`, () => {
      const L = (e: string, ints: Record<string, number> = {}) => evalLength(e, vp, vars0, ints);
      const tcw = L("var(--tcw)");
      const half = vp.w / 2 - 8 - L("var(--edge-l)");
      for (const n of [2, 4, 6, 8, 12, 25]) {
        const span = tcw + (n - 1) * L(pitchRule, { n });
        expect(span, `${n} cards`).toBeLessThanOrEqual(half + 0.01);
      }
      // up to four cards keep the landscape table's 60% pitch
      expect(L(pitchRule, { n: 4 })).toBeCloseTo(tcw * 0.6, 4);
      expect(L("var(--hcw)")).toBeCloseTo(L("var(--hcw-full)"), 6);
      const pitch25 = evalLength(hand["--pitch"], vp, { ...vars0, "--cw": "var(--hcw)" }, { n: 25 });
      // a finger's strip of every card: 26px on a mini upright, about a
      // phone's 27px
      expect(pitch25).toBeGreaterThanOrEqual(26 - 0.01);
    });
  }
});
