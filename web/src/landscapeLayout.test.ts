// @vitest-environment node
/// <reference types="node" />
// Guards the short-landscape table geometry in index.css (Jerry's phone,
// 2026-10-05). jsdom does no layout, so this checks the rules that keep the
// regions apart: the trick box ends where the hand begins, the action cluster
// never reaches into the trick box, and the failed-throw notice takes no
// height from the felt. Rendered checks live in the PR's screenshot sweep.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

/** Body of the first `@media (max-height: 500px)` block, braces balanced. */
function shortLandscapeBlock(): string {
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

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");

const px = (v: string) => Number(/(-?[\d.]+)px/.exec(v)![1]);

describe("short landscape table layout", () => {
  const block = shortLandscapeBlock();
  const vars = rule(block, ".table-screen");

  it("sizes --hand-h from the fan it reserves room for", () => {
    const hand = rule(block, ".hand");
    const you = rule(block, ".you-area");
    // "16px calc(8px + …) 4px calc(8px + …)": top and bottom are the plain lengths
    const [, padTop, padBottom] = /^([\d.]+)px calc\(.*?\) ([\d.]+)px calc/.exec(hand.padding)!.map(Number);
    const cardH = px(hand["--cw"]) * 7 / 5; // .card aspect-ratio: 5 / 7
    const youPad = px(you["padding-bottom"]);
    expect(px(vars["--hand-h"])).toBeCloseTo(padTop + cardH + padBottom + youPad, 1);
  });

  it("anchors the trick box between the top seat and the hand", () => {
    const trick = rule(block, ".trick-area");
    expect(trick.top).toBe("var(--trick-top)");
    expect(trick.bottom).toBe("var(--hand-h)");
    expect(trick.width).toBe("calc(var(--trick-half) * 2)");
  });

  it("keeps the turn pill and action buttons beside the trick box in play only", () => {
    const cluster = rule(block, ".phase-play .you-tagline, .phase-play .action-bar");
    expect(cluster["align-self"]).toBe("flex-end");
    expect(cluster["max-width"]).toBe("calc(50% - var(--trick-half) - 16px)");
    // Unscoped, the side column also squeezed the declare buttons into a tall
    // stack over the HUD and the right seat (Codex HOLD on #829).
    expect(rule(block, ".you-tagline, .action-bar")).toEqual({});
    expect(rule(block, ".action-bar")["max-width"]).toBeUndefined();
    expect(rule(block, ".action-bar")["align-self"]).toBeUndefined();
  });

  it("gives deal, declare and bury one full-width row above the hand", () => {
    const setup = (sel: string) => ["deal", "declare", "bury"].map((p) => `.phase-${p} ${sel}`).join(", ");
    const bar = rule(block, setup(".action-bar"));
    expect(bar["flex-wrap"]).toBe("nowrap"); // never grows up into the table
    expect(bar["overflow-x"]).toBe("auto");  // many declare options scroll sideways
    expect(bar["max-width"]).toBe("100%");
    expect(rule(block, setup(".trick-area")).bottom).toBe("calc(var(--hand-h) + var(--setup-bar-h))");
    // the bar row: 44px buttons, 3px padding above and below, the 4px gap
    expect(px(vars["--setup-bar-h"])).toBeGreaterThanOrEqual(44 + 3 * 2 + 4);
    // the banker's pill stands above the Bury row
    expect(rule(block, ".phase-bury .trick-area").bottom).toBe("calc(var(--hand-h) + var(--setup-bar-h) + 26px)");
  });

  it("floats the failed-throw notice instead of pushing the table down", () => {
    const notice = rule(block, ".hud-notice");
    expect(notice.position).toBe("fixed");
    expect(notice.bottom).toBe("calc(var(--hand-h) + 6px)");
    expect(notice.width).toBe("calc(50% - var(--trick-half) - 16px)");
  });

  it("lays the points chip out as wrapping flex, not a grid", () => {
    expect(rule(block, ".points-chip").display).toBe("flex");
  });
});
