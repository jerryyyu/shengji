// @vitest-environment node
/// <reference types="node" />
// Guards the phone table geometry in index.css (the `:where(.phone-landscape)`
// block, which applies under 500px of height and to the rotated portrait table). jsdom does no layout, so this evaluates the block's own
// size tokens (calc, clamp, min, max, env, vw, vh) at real iPhone sizes and
// checks the regions the layout promises to keep apart: the trick cross sits
// between the header and your row, your action is centred on the table and,
// with the banker's crown beside it, never meets a trick slot, a seat or the
// hand, the hand fits one
// row at a thumb-sized pitch, and every control keeps a 44px hit area. Rendered checks live in the PR's screenshot sweep.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");

const PHONE_BLOCK = ":where(.phone-landscape) {";

/** Body of the phone block, braces balanced. */
function phoneBlock(): string {
  const start = css.indexOf(PHONE_BLOCK);
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
  const vars = phase === "play" ? { ...vars0, ...rule(block, ".table-screen.phase-play") }
    : { ...vars0, ...rule(block, ".table-screen.phase-deal, .table-screen.phase-declare, .table-screen.phase-bury") };
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
  return { tcw, cx, cy, cards: cardsAt, tags, slots, pills: { left: pill(".opponent.pos-left"), right: pill(".opponent.pos-right") },
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
    expect(rule(block, ".table-screen.phase-play")["--row-reserve"]).toBe("0px");
    expect(rule(block, ".opponent.pos-left, .opponent.pos-right").top)
      .toBe("max(calc(var(--header-bottom) + var(--space-xs)), calc((var(--trick-top) + 100% - var(--cross-bottom)) / 2 + var(--side-dy) - var(--trick-ch) / 2 - var(--space-s) - var(--header-h)))");
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
        // side labels: centred over their slot's first card, above its
        // cards; at their widest 8pt clear of the top and bottom slots, your
        // row and the safe-area edges, and under the header
        expect((g.pills.left.x0 + g.pills.left.x1) / 2).toBeCloseTo(g.cards.left.x0 + g.tcw / 2, 5);
        expect((g.pills.right.x0 + g.pills.right.x1) / 2).toBeCloseTo(g.cards.right.x1 - g.tcw / 2, 5);
        for (const [p, s] of [[g.pills.left, g.cards.left], [g.pills.right, g.cards.right]] as const) {
          expect(p.y1).toBeLessThanOrEqual(s.y0 + 0.01);
        }
        for (const p of pills) {
          expect(p.y0).toBeGreaterThanOrEqual(g.header + 4 - 0.01);
          // the cards and the tag line under them, each on its own
          for (const k of ["top", "bottom"]) {
            expect(gap(p, g.cards[k])).toBeGreaterThanOrEqual(8 - 0.01);
            expect(gap(p, g.tags[k])).toBeGreaterThanOrEqual(8 - 0.01);
          }
          expect(gap(p, g.row)).toBeGreaterThanOrEqual(8 - 0.01);
          expect(p.x0).toBeGreaterThanOrEqual(vp.left + 4 - 0.01);
          expect(p.x1).toBeLessThanOrEqual(vp.w - vp.right - 4 + 0.01);
        }
        // a label has room for a crown and a 13-letter name (138px); the
        // 13 mini, narrow between its insets, for about 11 letters
        expect(g.pillW).toBeGreaterThanOrEqual(name.includes("mini") ? 120 : 138);
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

      it("spaces the cross evenly: the header, the slots and the row (or the hand) a gap apart", () => {
        const playGaps = [play.slots.top.y0 - play.header, play.slots.bottom.y0 - play.slots.top.y1,
          play.zoneTop - play.slots.bottom.y1];
        const setupGaps = [setup.slots.top.y0 - setup.header, setup.slots.bottom.y0 - setup.slots.top.y1,
          setup.row.y0 - setup.slots.bottom.y1];
        for (const gaps of [playGaps, setupGaps]) {
          for (const x of gaps) expect(Math.abs(x - gaps[0])).toBeLessThanOrEqual(2);
          expect(gaps[0]).toBeGreaterThanOrEqual(8 - 0.01);
        }
        // the side slots sit at the cross's vertical centre, left and right alike
        for (const g of [play, setup]) {
          const mid = (g.slots.top.y0 + g.slots.bottom.y1) / 2;
          for (const s of [g.slots.left, g.slots.right]) expect(Math.abs((s.y0 + s.y1) / 2 - mid)).toBeLessThanOrEqual(1);
          expect(Math.abs((g.cx - g.cards.left.x0) - (g.cards.right.x1 - g.cx))).toBeLessThanOrEqual(1);
        }
      });

      it("keeps a side seat's label above its cards, never closer than the top seat's label is to its own", () => {
        for (const g of [play, setup]) {
          const top = Math.min(8, g.cards.top.y0 - g.topLabelBottom);
          for (const [p, c] of [[g.pills.left, g.cards.left], [g.pills.right, g.cards.right]] as const) {
            expect(c.y0 - p.y1).toBeGreaterThanOrEqual(Math.min(4, top) - 0.01);
          }
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

      it("fits the 33-card bury hand in one row, larger than 37px wherever the width allows", () => {
        const gs = geometry(vp, smallTokens, "setup");
        expect(gs.handCw).toBeGreaterThanOrEqual(44);
        expect(gs.handCw).toBeLessThanOrEqual(56);
        const pitch = evalLength(smallRule["--pitch"], vp, smallTokens, { n: 33 });
        expect(32 * pitch + gs.handCw).toBeLessThanOrEqual(gs.safeW - 16 + 0.01);
        expect(pitch).toBeGreaterThanOrEqual(18);
        checkRegions(gs, "setup");
      });
    });
  }

  it("shrinks the hand's cards above 25, briefly animated", () => {
    expect(rule(block, ".table-screen:has(.hand.small-cards)")["--hand-cw"]).toBe("clamp(37px, calc(var(--safe-w) * 0.07), 56px)");
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
    const modalBtn = rule(block, ".modal > .btn.big");
    expect(modalBtn.position).toBe("sticky");
    expect(px(modalBtn["min-height"])).toBeGreaterThanOrEqual(44);
    // a card's tap area runs the full card height plus 16px above the hand
    expect(rule(block, ".hand .card::after").top).toBe("calc(-1 * var(--lift))");
  });

  it("gives the in-play notice's close a 44px box that the notice does not clip", () => {
    const close = rule(block, ".phase-play .hud-notice .hud-notice-close");
    for (const k of ["width", "height", "min-width", "min-height"]) expect(px(close[k]), k).toBe(44);
    // the glyph is the 24px content box, drawn in the notice's top right corner
    expect(px(close.width) - 2 * px(close.padding)).toBe(24);
    expect(close.position).toBe("absolute");
    // the box overhangs the notice's corner, so only the text may be clipped
    expect(px(close.top)).toBeLessThan(0);
    expect(px(close.right)).toBeLessThan(0);
    expect(rule(block, ".phase-play .hud-notice").overflow).toBeUndefined();
    expect(rule(block, ".phase-play .hud-message, .phase-play .hud-notice").overflow).toBeUndefined();
    expect(rule(block, ".phase-play .hud-notice .hud-notice-body").overflow).toBe("hidden");
    expect(rule(block, ".phase-play .hud-message").overflow).toBe("hidden");
  });

  it("shortens a long seat name inside a bounded label: smaller, then an ellipsis", () => {
    expect(tokens["--pill-max"]).toContain("calc(2 * (var(--side-out) - var(--top-reach) - var(--space-s)) - var(--trick-cw))");
    expect(rule(block, ".opponent.pos-left, .opponent.pos-right")["max-width"]).toBe("var(--pill-max)");
    expect(rule(block, ".opponent.pos-top")["--top-w"]).toContain("min(200px");
    const text = rule(block, ".opp-name-text");
    expect([text.overflow, text["text-overflow"], text["white-space"], text["min-width"]])
      .toEqual(["hidden", "ellipsis", "nowrap", "0"]);
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
    expect(rule(css.replace(block, ""), ".opp-fullname").display).toBe("none");
  });

  it("keeps table text at 11px or more", () => {
    for (const sel of [".lead-tag, .win-tag", ".declare-tag", ".you-tag, .host-tag, .off-tag", ".action-hint", ".chip"]) {
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
    expect([dots.display, dots.width, dots.visibility]).toEqual(["inline-block", "10px", "hidden"]);
    expect(rule(block, ".opponent .turn-dots.shown").visibility).toBe("visible");
    expect(rule(block, ".opponent.on-turn .seat-dot").display).toBeUndefined();
    expect(block).not.toMatch(/\.turn-dots[^{]*\{[^}]*display: none/);
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

  it("tells a declaration once, by its tag, not again in the corner", () => {
    expect(rule(block, ".hud-message.declare-message").display).toBe("none");
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

  it("keys the phone layout on one root class, never on a media query of its own", () => {
    expect(css.split(PHONE_BLOCK)).toHaveLength(2);
    // phoneLayout.ts sets the class from the height query
    expect(css.includes("@media (max-height: 500px)")).toBe(false);
  });
});

describe("the table's frame", () => {
  it("reads the viewport and safe areas only through the frame tokens", () => {
    // every vw, vh and env() in the block is a frame token's fallback, or the
    // off-table toast (a lobby screen is never rotated)
    const offTable = rule(block, ".toast");
    const stripped = block
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/--(view-[wh]|safe-[tlrb]):[^;]*;/g, "")
      .replace(/\.toast \{[^}]*\}/, "");
    expect(stripped).not.toMatch(/\d(vw|vh)\b|env\(/);
    expect(offTable.top).toContain("env(safe-area-inset-top");
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

describe("the error toast at the table", () => {
  const t = rule(block, ".table-screen .toast");
  it("passes just above your row, centred, inside the cross's width", () => {
    expect(t.top).toBe("auto");
    expect(t.bottom).toBe("calc(var(--zone-bottom) + var(--row-h) + var(--space-xs))");
    expect(t["max-width"]).toBe("calc(2 * var(--side-out) - 2 * var(--space-s))");
  });

  for (const [name, vp] of FRAMES) {
    it(`covers no seat label, your row or the hand: ${name}`, () => {
      for (const phase of ["play", "setup"] as const) {
        const g = geometry(vp, tokens, phase);
        const vars = phase === "play" ? { ...tokens, ...rule(block, ".table-screen.phase-play") } : tokens;
        const L = (e: string) => evalLength(e, vp, vars);
        const y1 = vp.h - L(t.bottom);
        // two lines at most: 2 x 17 + 12 of padding
        const toast: Rect = { x0: g.cx - L(t["max-width"]) / 2, x1: g.cx + L(t["max-width"]) / 2, y0: y1 - 46, y1 };
        expect(y1).toBeLessThanOrEqual(vp.h - L("var(--zone-bottom)") - L("var(--row-h)"));
        expect(y1).toBeLessThanOrEqual(g.handTop);
        expect(overlaps(toast, g.row)).toBe(false);
        expect(toast.y0).toBeGreaterThanOrEqual(g.header);
        for (const p of [g.pills.left, g.pills.right]) expect(overlaps(toast, p)).toBe(false);
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
  it("spaces Next round and Leave by the card's gap and keeps Leave 12px off the bottom", () => {
    const block = phoneBlock();
    expect(rule(block, ".modal > .btn.big")["margin-bottom"]).toBeUndefined();
    expect(rule(block, ".modal").gap).toBe("8px");
    expect(rule(block, ".modal > .dialog-leave-btn").margin).toBe("0 auto 12px");
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
