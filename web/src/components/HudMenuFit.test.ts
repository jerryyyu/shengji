// @vitest-environment node
/// <reference types="node" />
// Guards that the table's ⋯ menu stays inside the visible screen: jsdom does
// no layout, so this evaluates the menu's max-height from index.css at real
// screen sizes and checks the menu's foot against the screen's foot and its
// bottom safe area. Past that height the menu scrolls, holding the scroll.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../index.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Body of the block opened by `head`, braces balanced. */
function blockAt(source: string, head: string): string {
  const start = source.indexOf(head);
  expect(start).toBeGreaterThan(-1);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(open + 1, i);
  }
  throw new Error("unbalanced block");
}

/** Every declaration, in order, of the innermost rules in `block` whose selector is exactly `selector`. */
function decls(block: string, selector: string): [string, string][] {
  const out: [string, string][] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(block); m; m = re.exec(block)) {
    if (m[1].trim().replace(/\s+/g, " ") !== selector) continue;
    for (const d of m[2].split(";")) {
      const i = d.indexOf(":");
      if (i > 0) out.push([d.slice(0, i).trim(), d.slice(i + 1).trim().replace(/\s+/g, " ")]);
    }
  }
  return out;
}
const last = (ds: [string, string][], prop: string) => ds.filter(([p]) => p === prop).map(([, v]) => v).pop();

const phone = blockAt(css, ":where(.phone-landscape) {");
/** The top-level rules alone: the source with the phone block cut out. */
const outside = css.replace(phone, "");

type Screen = { h: number; dvh: number; safeT: number; safeB: number };
/** A length expression in px at `s`, the phone frame's tokens resolved from its .table-screen rule. */
function evalPx(expr: string, s: Screen): number {
  const tokens = Object.fromEntries(decls(phone, ".table-screen").filter(([p]) => p.startsWith("--")));
  const fixed: Record<string, string> = {
    "--view-h": `${s.h}px`, "--safe-t": `${s.safeT}px`, "--safe-b": `${s.safeB}px`,
  };
  let e = expr;
  for (let n = 0; n < 10 && e.includes("var("); n++) {
    e = e.replace(/var\((--[\w-]+)\)/g, (_, name: string) => {
      const v = fixed[name] ?? tokens[name];
      if (v === undefined) throw new Error(`unknown token ${name}`);
      return `(${v})`;
    });
  }
  e = e
    .replace(/env\(safe-area-inset-top, 0px\)/g, `${s.safeT}px`)
    .replace(/env\(safe-area-inset-bottom, 0px\)/g, `${s.safeB}px`)
    .replace(/(\d+(?:\.\d+)?)dvh/g, (_, n: string) => `${(Number(n) * s.dvh) / 100}`)
    .replace(/(\d+(?:\.\d+)?)px/g, "$1")
    .replace(/\bcalc\(/g, "(")
    .replace(/\bmax\(/g, "Math.max(")
    .replace(/\bmin\(/g, "Math.min(");
  expect(e).toMatch(/^(?:[\d\s.+\-*/(),]|Math\.m(?:ax|in))+$/);
  return Function(`return (${e});`)() as number;
}

describe("the ⋯ menu's height", () => {
  const base = decls(outside, ".hud-menu");

  it("is capped by the visible screen everywhere, with a vh fallback before dvh, and scrolls within", () => {
    const caps = base.filter(([p]) => p === "max-height").map(([, v]) => v);
    expect(caps.length).toBeGreaterThanOrEqual(2);
    expect(caps[caps.length - 2]).toMatch(/\b100vh\b/);
    expect(caps[caps.length - 1]).toMatch(/\b100dvh\b/);
    expect(caps[caps.length - 1]).toContain("env(safe-area-inset-bottom");
    expect(last(base, "overflow-y")).toBe("auto");
    expect(last(base, "overscroll-behavior")).toBe("contain");
  });

  it("ends above the foot of a wide screen, below its header", () => {
    const cap = last(base, "max-height")!;
    // the menu opens 48px down on the desktop table, 58px on the tablet table
    for (const [top, s] of [
      [48, { h: 800, dvh: 800, safeT: 0, safeB: 0 }],
      [58, { h: 744, dvh: 744, safeT: 0, safeB: 0 }],
      [58, { h: 744, dvh: 744, safeT: 24, safeB: 20 }],
    ] as const) {
      expect(top + s.safeT + evalPx(cap, s)).toBeLessThanOrEqual(s.dvh - s.safeB);
    }
  });

  // a phone sideways, its toolbar over the page's top or taking height away, the
  // iOS app with the home indicator, and a portrait phone's turned frame, whose
  // height is the screen's width and not 100dvh
  const PHONES: [string, Screen][] = [
    ["iPhone 14 Pro", { h: 390, dvh: 390, safeT: 0, safeB: 0 }],
    ["iPhone SE", { h: 375, dvh: 375, safeT: 0, safeB: 0 }],
    ["iOS app", { h: 390, dvh: 390, safeT: 0, safeB: 21 }],
    ["Safari, toolbar over the top", { h: 390, dvh: 390, safeT: 64, safeB: 21 }],
    ["Safari, toolbar shown", { h: 326, dvh: 326, safeT: 0, safeB: 21 }],
    ["Safari, short with tabs", { h: 300, dvh: 300, safeT: 0, safeB: 21 }],
    ["portrait phone, turned frame", { h: 390, dvh: 844, safeT: 0, safeB: 0 }],
  ];
  it.each(PHONES)("on a phone (%s) ends above the frame's foot and its bottom safe area", (_, s) => {
    const cap = last(decls(phone, ".hud-menu"), "max-height");
    expect(cap).toBeDefined();
    // the menu opens 6px under the ⋯ button, whose foot is the header's
    const top = evalPx("var(--header-bottom)", s) + 6;
    const height = evalPx(cap!, s);
    expect(top + height).toBeLessThanOrEqual(s.h - Math.max(6, s.safeB));
    // and still shows the 44px Leave row with three rows above it to scroll through
    expect(height).toBeGreaterThanOrEqual(4 * 44);
  });

  it("keeps Leave game in view at the phone menu's foot while the rows scroll", () => {
    expect(last(decls(phone, ".hud-menu-row.leave"), "position")).toBe("sticky");
  });
});
