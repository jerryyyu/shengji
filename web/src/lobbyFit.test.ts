// @vitest-environment node
/// <reference types="node" />
// Guards the Play tab's vertical budget on a phone. jsdom does no layout, so
// this resolves the lobby's padding, gap and tab-bar rules from index.css at
// real iPhone sizes and adds the panel's content height as rendered in Chrome
// (the guest lobby, the tallest: the name field instead of the rating chip).
// The whole stack, down to the connection line, must fit between the status
// bar and the tab bar on a 375x812 or larger phone; a shorter phone scrolls
// inside a container that ends at the tab bar's top edge.
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

/** The first value of a property across `selectors`, the last selector that sets it winning. */
function cascade(prop: string, ...selectors: string[]): string | undefined {
  let v: string | undefined;
  for (const s of selectors) v = rule(s)[prop] ?? v;
  return v;
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

/** The top value of a padding shorthand, or a padding-top. */
function topOf(padding: string): string {
  const parts: string[] = [];
  let depth = 0;
  let cur = "";
  for (const c of padding) {
    if (c === "(") depth++;
    if (c === ")") depth--;
    if (c === " " && depth === 0) { if (cur) parts.push(cur); cur = ""; } else cur += c;
  }
  if (cur) parts.push(cur);
  return parts[0];
}

// Phones in CSS px, portrait, with their status-bar and home-indicator insets.
const IPHONE_15: Phone = { name: "iPhone 15/16", w: 393, h: 852, top: 59, bottom: 34 };
const IPHONE_13_MINI: Phone = { name: "iPhone 13 mini", w: 375, h: 812, top: 50, bottom: 34 };
const IPHONE_SE: Phone = { name: "iPhone SE", w: 375, h: 667, top: 20, bottom: 0 };

/** The guest lobby panel's ten children (title down to the connection line)
 *  summed without gaps, as Chrome renders them at each width; the preview
 *  scales with the width. */
const CONTENT: Record<number, { height: number; children: number }> = {
  393: { height: 540.3, children: 10 },
  375: { height: 530.9, children: 10 },
};

const PANEL = [".panel", ".lobby-panel", ".lobby-panel:has(.lobby-preview)",
  ".home .lobby-panel:has(.lobby-preview)", ".home-narrow .lobby-panel:has(.lobby-preview)"];

function lobbyTop(phone: Phone): number {
  const narrow = rule(".home-narrow .screen.lobby-screen")["padding-top"];
  return length(narrow ?? topOf(rule(".screen").padding), phone);
}

/** Height the Play stack needs from the top of the screen to the tab bar's bottom. */
function needed(phone: Phone): number {
  const panelPad = (side: "top" | "bottom") => {
    const own = cascade(`padding-${side}`, ...PANEL);
    const short = cascade("padding", ...PANEL);
    return length(own ?? topOf(short!), phone);
  };
  const gap = length(cascade("gap", ...PANEL)!, phone);
  const content = CONTENT[phone.w];
  const bottomPad = length(rule(".home-narrow .home-body > .screen")["padding-bottom"], phone);
  const tabbar = length(rule(".tabbar").height, phone);
  return lobbyTop(phone) + panelPad("top") + content.height + gap * (content.children - 1)
    + panelPad("bottom") + bottomPad + tabbar;
}

describe("the Play tab on a phone", () => {
  it("keeps the plain screen's top padding above the lobby on both layouts", () => {
    expect(rule(".home-narrow .screen.lobby-screen")["padding-top"]).toBeUndefined();
    for (const phone of [IPHONE_15, IPHONE_13_MINI, IPHONE_SE]) {
      expect(lobbyTop(phone)).toBe(Math.max(12, phone.top));
    }
    const wide = rule(".home-wide .home-body > .screen.lobby-screen")["padding-top"]
      ?? rule(".home-wide .home-body > .screen")["padding-top"];
    expect(wide).toBe("12px");
  });

  for (const phone of [IPHONE_15, IPHONE_13_MINI]) {
    it(`fits the whole stack above the tab bar on an ${phone.name} (${phone.w}x${phone.h})`, () => {
      expect(needed(phone)).toBeLessThanOrEqual(phone.h);
    });
  }

  it("scrolls on an iPhone SE inside a container that ends at the tab bar", () => {
    expect(needed(IPHONE_SE)).toBeGreaterThan(IPHONE_SE.h);
    const screen = rule(".screen");
    expect(screen["overflow-y"]).toBe("auto");
    expect(rule(".panel").margin).toBe("auto");
    expect(rule(".home").display).toBe("flex");
    expect(rule(".home")["flex-direction"]).toBe("column");
    expect(rule(".home-body")["min-height"]).toBe("0");
    expect(rule(".home-body > .screen").height).toBe("100%");
    const bar = rule(".tabbar");
    expect(bar.flex).toBe("none");
    expect(bar.position ?? "static").toBe("static");
    expect(length(bar.height, IPHONE_15)).toBe(49 + IPHONE_15.bottom);
  });
});
