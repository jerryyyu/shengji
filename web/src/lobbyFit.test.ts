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
    // ...and on a screen too short for it (a phone held sideways) it grows to its
    // content, so the screen's tab-bar clearance comes after the last row
    expect(panel["min-height"]).toBe("min-content");
    // every other item keeps its height; the art takes what is left, 120 to 200px
    expect(rule(".home-narrow .play-tab:not(.play-table-up) .lobby-panel > :not(.lobby-preview), "
                + ".home-narrow .play-tab:not(.play-table-up) .play-art > :not(.lobby-preview), "
                + ".home-narrow .play-tab:not(.play-table-up) .play-side > *")["flex-shrink"]).toBe("0");
    const art = rule(".home-narrow .play-tab .lobby-preview");
    expect(art.flex).toBe("1 1 120px");
    expect(art["min-height"]).toBe("120px");
    expect(art["max-height"]).toBe("200px");
    // the whole stage is drawn inside whatever height is left
    expect(art["container-type"]).toBe("size");
    expect(rule(".home-narrow .play-tab .lp-stage")["--u"]).toBe("min(100cqw / 1200, 100cqh / 630)");
  });

  it("a phone's table panel fits above the tab bar: no title, compact rows with 44px hit areas, a sticky button row", () => {
    expect(rule(".home-narrow .play-tab.play-table-up .game-title").display).toBe("none");
    expect(rule(".home-narrow .play-table-up .tp").gap).toBe("8px");
    expect(rule(".home-narrow .play-table-up .tp-seat")["min-height"]).toBe("48px");
    const rows = rule(".home-narrow .play-table-up .tp .q-wait, .home-narrow .play-table-up .tp-chat, "
                      + ".home-narrow .play-table-up .tp-set");
    expect(rows["min-height"]).toBe("40px");
    // a 40px row is a 44px target: its hit area reaches 2px past each edge
    const hit = rule(".home-narrow .play-table-up .tp .q-wait::before, .home-narrow .play-table-up .tp-chat::before");
    expect(hit.position).toBe("absolute");
    expect(hit.inset).toBe("-2px 0");
    // Start and Leave stick to the bottom of the screen's content box, which
    // ends --tabbar-clear above the screen's bottom: never under the pill
    const acts = rule(".home-narrow .play-table-up .tp-acts, .home-narrow .play-table-up .tp-led");
    expect(acts.position).toBe("sticky");
    expect(acts.bottom).toBe("0");
    expect(rule(".home-narrow .home-body > .screen")["padding-bottom"]).toBe("var(--tabbar-clear)");
    // stuck, the row's backing runs on through the 16px above the pill, so
    // no setting shows between them; the panel clips it at rest
    expect(rule(".home-narrow .play-table-up .tp").overflow).toBe("clip");
    const below = rule(".home-narrow .play-table-up .tp-acts::after, .home-narrow .play-table-up .tp-led::after");
    expect(below.background).toBe(acts.background);
    expect(below.top).toBe("calc(100% - 16px)");
    expect(below.height).toBe("32px");
    expect(rule(".home-narrow")["--tabbar-clear"]).toBe("calc(var(--tabbar-h) + var(--tabbar-bottom) + 16px)");
  });

  it("held sideways in a browser, the preview gives way so Play and Duo sit clear of the tab bar", () => {
    const sideways = /@media \(orientation: landscape\) and \(max-height: 500px\) \{\s*\.home-narrow \.play-tab \.lobby-preview \{ display: none; \}/;
    expect(css).toMatch(sideways);
  });
});

describe("the Play tab on a wide screen", () => {
  it("is the phone's one column: no art column beside the controls, a small preview, none at a table", () => {
    expect(rule(".play-art, .play-side").display).toBe("contents");
    expect(css).not.toMatch(/\.home-wide \.play-tab \.play-(art|side) \{/);
    expect(css).not.toMatch(/\.home-wide \.play-tab > \.lobby-panel:has\(\.play-side\)/);
    expect(rule(".home-wide .play-tab > .lobby-panel").width).toBe("420px");
    expect(rule(".home-wide .play-tab.play-table-up .lobby-preview").display).toBe("none");
  });

  // The preview's stage is 1200x630 stage units scaled into the felt. A felt
  // of another shape letterboxes the stage: on a 420x150 felt the stage was
  // 286px wide, its side hands floated 67px inside the rim and its cards were
  // a quarter of the phone's. The felt's box is resolved here from the rules
  // a wide screen applies, base first.
  it("keeps the felt at the stage's shape, so the stage fills it and the cards scale with it", () => {
    const base = rule(".lobby-preview");
    const wide = { ...base, ...rule(".home-wide .play-tab .lobby-preview") };
    const stage = { ...rule(".lp-stage"), ...rule(".home-wide .play-tab .lp-stage") };
    const column = parseFloat(rule(".home-wide .play-tab > .lobby-panel").width);
    expect(wide.width ?? "100%").toBe("100%");
    expect(wide.height).toBeUndefined();
    const [aw, ah] = wide["aspect-ratio"].split("/").map((n) => parseFloat(n));
    const felt = { w: column, h: column * ah / aw };
    const u = stage["--u"] === "calc(100cqw / 1200)" ? felt.w / 1200
      : stage["--u"] === "min(100cqw / 1200, 100cqh / 630)" ? Math.min(felt.w / 1200, felt.h / 630) : NaN;
    // the stage reaches both side edges and both top and bottom edges
    expect(Math.abs(u * 1200 - felt.w)).toBeLessThan(1);
    expect(Math.abs(u * 630 - felt.h)).toBeLessThan(1);
    // a played card (104 stage units) is at least the phone's 33px
    const card = 104 * u;
    expect(card).toBeGreaterThanOrEqual(34);
    expect(felt.w / felt.h).toBeGreaterThan(1.8);
    expect(felt.w / felt.h).toBeLessThan(2);
  });
});
