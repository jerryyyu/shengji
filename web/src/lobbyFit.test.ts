// @vitest-environment node
/// <reference types="node" />
// Guards the phone's tab pages against the floating tab bar. jsdom does no
// layout, so this resolves the pill's geometry and the pages' bottom padding
// from index.css at real iPhone insets: every page scrolls under the pill and
// its last item ends clear of it.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Declarations of every rule outside an at-rule whose selector is exactly `selector`, merged in source order. */
function rule(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  let depth = 0;
  let start = 0;
  for (let i = 0; i < css.length; i++) {
    const c = css[i];
    if (c === "{") {
      if (depth === 0) {
        const sel = css.slice(start, i).trim().replace(/\s+/g, " ");
        const end = css.indexOf("}", i);
        const body = css.slice(i + 1, end);
        if (!sel.startsWith("@") && sel === selector) {
          for (const decl of body.split(";")) {
            const k = decl.indexOf(":");
            if (k > 0) out[decl.slice(0, k).trim()] = decl.slice(k + 1).trim().replace(/\s+/g, " ");
          }
        }
        if (!sel.startsWith("@") && !body.includes("{")) { i = end; start = end + 1; continue; }
      }
      depth++;
    } else if (c === "}") {
      depth--;
      if (depth === 0) start = i + 1;
    }
  }
  return out;
}

interface Phone { name: string; w: number; h: number; top: number; bottom: number }

/** A px length expression (calc, max, min, env) at a phone's safe-area insets. */
function length(expr: string, phone: Phone): number {
  const js = expr
    .replace(/env\(safe-area-inset-top(,\s*0px)?\)/g, `${phone.top}px`)
    .replace(/env\(safe-area-inset-bottom(,\s*0px)?\)/g, `${phone.bottom}px`)
    .replace(/env\(safe-area-inset-(left|right)(,\s*0px)?\)/g, "0px")
    .replace(/calc\(/g, "(")
    .replace(/\bmax\(/g, "Math.max(")
    .replace(/\bmin\(/g, "Math.min(")
    .replace(/(-?[\d.]+)px/g, "$1");
  expect(js).toMatch(/^(?:[\d.\s+\-*/(),]|Math\.max|Math\.min)+$/);
  return Function(`return (${js});`)() as number;
}

// Phones in CSS px, portrait, with their status-bar and home-indicator insets.
const IPHONE_15: Phone = { name: "iPhone 15/16", w: 393, h: 852, top: 59, bottom: 34 };
const IPHONE_13_MINI: Phone = { name: "iPhone 13 mini", w: 375, h: 812, top: 50, bottom: 34 };
const IPHONE_SE: Phone = { name: "iPhone SE", w: 375, h: 667, top: 20, bottom: 0 };

/** The pill's top edge, measured up from the screen's bottom. */
const pillTop = (phone: Phone) =>
  length(rule(".home-narrow")["--tabbar-h"], phone) + length(rule(".home-narrow")["--tabbar-bottom"].replace(/var\(--[\w-]+\)/g, "0px"), phone);
/** --tabbar-clear with the other two custom properties substituted. */
function clear(phone: Phone): number {
  const vars = rule(".home-narrow");
  const expr = vars["--tabbar-clear"]
    .replace("var(--tabbar-h)", vars["--tabbar-h"])
    .replace("var(--tabbar-bottom)", vars["--tabbar-bottom"]);
  return length(expr, phone);
}

describe("the Play tab on a phone", () => {
  it("keeps the plain screen's top padding above the lobby on both layouts", () => {
    expect(rule(".home-narrow .screen.lobby-screen")["padding-top"]).toBeUndefined();
    const wide = rule(".home-wide .home-body > .screen.lobby-screen")["padding-top"]
      ?? rule(".home-wide .home-body > .screen")["padding-top"];
    expect(wide).toBe("12px");
  });

  it("the tab bar floats: a 64px pill, 16px in from the sides, above the home indicator", () => {
    const bar = rule(".tabbar");
    expect(bar.position).toBe("absolute");
    expect(bar.height).toBe("var(--tabbar-h)");
    expect(rule(".home-narrow")["--tabbar-h"]).toBe("64px");
    expect(bar["border-radius"]).toBe("32px");
    expect(bar.left).toBe("max(16px, env(safe-area-inset-left, 0px))");
    expect(bar.right).toBe("max(16px, env(safe-area-inset-right, 0px))");
    expect(rule(".home-narrow")["--tabbar-bottom"]).toBe("max(8px, env(safe-area-inset-bottom, 0px))");
    expect(bar["backdrop-filter"]).toBe("blur(24px) saturate(180%)");
    expect(bar["-webkit-backdrop-filter"]).toBe("blur(24px) saturate(180%)");
  });

  for (const phone of [IPHONE_15, IPHONE_13_MINI, IPHONE_SE]) {
    it(`every tab page scrolls under the pill and ends clear of it on an ${phone.name}`, () => {
      expect(pillTop(phone)).toBe(64 + Math.max(8, phone.bottom));
      expect(clear(phone)).toBeGreaterThan(pillTop(phone));
      expect(rule(".home-narrow .home-body > .screen")["padding-bottom"]).toBe("var(--tabbar-clear)");
      expect(rule(".home-narrow .home-col")["padding-bottom"]).toBe("var(--tabbar-clear)");
      // the scroller is the whole screen, so the page passes under the pill
      expect(rule(".screen")["overflow-y"]).toBe("auto");
      expect(rule(".home-body > .screen").height).toBe("100%");
      expect(rule(".home-body")["min-height"]).toBe("0");
    });
  }

  it("the idle Play tab fits its first view: the panel is the screen's height and the art alone gives way", () => {
    // the panel fills the space between the status bar and the tab bar's clearance
    const panel = rule(".home-narrow .play-tab:not(.play-table-up) > .lobby-panel");
    expect(panel["align-self"]).toBe("stretch");
    expect(panel["margin-bottom"]).toBe("0");      // an auto margin would stop the stretch
    // every other item keeps its height; the art takes what is left, 120 to 200px
    expect(rule(".home-narrow .play-tab:not(.play-table-up) .lobby-panel > :not(.lobby-preview), "
                + ".home-narrow .play-tab:not(.play-table-up) .play-art > :not(.lobby-preview), "
                + ".home-narrow .play-tab:not(.play-table-up) .play-side > *")["flex-shrink"]).toBe("0");
    const art = rule(".home-narrow .play-tab .lobby-preview");
    expect(art.flex).toBe("1 1 200px");
    expect(art["min-height"]).toBe("120px");
    expect(art["max-height"]).toBe("200px");
    // the whole stage is drawn inside whatever height is left
    expect(art["container-type"]).toBe("size");
    expect(rule(".home-narrow .play-tab .lp-stage")["--u"]).toBe("min(100cqw / 1200, 100cqh / 630)");
  });
});
