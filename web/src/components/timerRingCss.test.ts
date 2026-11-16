// @vitest-environment node
/// <reference types="node" />
// Guards the timer ring's fit, which jsdom cannot lay out: at every ring
// size the stylesheet uses, the widest number ("60") fits inside the band
// with 2px clear on each side.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../index.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** "60" in bold tabular system-ui, per em of font size, as Chromium lays it
 *  out on macOS (SF): the advance width of the pair, and the text's content
 *  box height rounded up for small sizes' whole-pixel snapping. Other
 *  platforms' system fonts have narrower digits. */
const PAIR_WIDTH_EM = 1.32;
const LINE_HEIGHT_EM = 1.25;

interface Ring { selector: string; size: number; band: number; fontSize: string | null }

/** Every rule whose selector names `.timer-ring`, with the size it sets. */
function rings(): Ring[] {
  const out: Ring[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let base: { size: number; band: number } | null = null;
  for (let m = re.exec(css); m; m = re.exec(css)) {
    const selector = m[1].replace(/@media[^{]*$/, "").trim().replace(/\s+/g, " ");
    if (!/\.timer-ring(?![-\w])/.test(selector) || selector.includes("::")) continue;
    const body = m[2];
    const px = (name: string) => {
      const v = new RegExp(`${name}:\\s*([\\d.]+)px`).exec(body);
      return v ? Number(v[1]) : null;
    };
    const size = px("--size");
    const band = px("--band");
    const font = /(?:^|;)\s*font-size:\s*([^;]+);/.exec(body);
    if (selector === ".timer-ring") base = { size: size!, band: band! };
    if (size === null && band === null && !font) continue;
    out.push({ selector, size: size ?? base!.size, band: band ?? base!.band, fontSize: font ? font[1].trim() : null });
  }
  return out;
}

describe("the timer ring", () => {
  it("derives its font from its size and band, and no size overrides the font", () => {
    const all = rings();
    const base = all.find((r) => r.selector === ".timer-ring")!;
    expect(base.fontSize).toBe("calc((var(--size) - 4 * var(--band) - 4px) / 1.4)");
    for (const r of all.filter((x) => x !== base)) expect(r.fontSize, r.selector).toBeNull();
  });

  it("keeps the widest number inside the band with 2px clear at every size", () => {
    const all = rings();
    // the table's ring, the thin seat ring, and the small ring on buttons and the strip
    expect(new Set(all.map((r) => `${r.size}/${r.band}`))).toEqual(new Set(["44/4", "26/1.5", "32/2.5"]));
    for (const r of all) {
      const font = (r.size - 4 * r.band - 4) / 1.4;
      const inner = r.size - 2 * r.band;
      const room = inner - 2 * (r.band + 2);
      expect(font * PAIR_WIDTH_EM, `${r.selector} width`).toBeLessThanOrEqual(room);
      expect(font * LINE_HEIGHT_EM, `${r.selector} height`).toBeLessThanOrEqual(room);
      // and legible: never below 11px
      expect(font, `${r.selector} font`).toBeGreaterThanOrEqual(11);
    }
  });
});
