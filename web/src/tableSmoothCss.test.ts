// @vitest-environment node
/// <reference types="node" />
// Guards table rules jsdom cannot render: the header's "/ 80" and "No trump"
// read at 4.5:1 or more over the brightest felt, the touched card lifts and
// grows, a dimmed card stays drawn, and the points float stills under Reduce
// Motion.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");
function decls(selector: string): string {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(css); m; m = re.exec(css)) {
    if (m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ") === selector) return m[2];
  }
  throw new Error(`no rule ${selector}`);
}
const prop = (body: string, name: string) => new RegExp(`(?:^|;|\\s)${name}:\\s*([^;]+);`).exec(body)?.[1].trim() ?? null;

type RGB = [number, number, number];
const hex = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
const over = (fg: RGB, alpha: number, bg: RGB): RGB => fg.map((c, i) => c * alpha + bg[i] * (1 - alpha)) as RGB;
const lum = (c: RGB) => {
  const [r, g, b] = c.map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: RGB, b: RGB) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

describe("header contrast", () => {
  // the phone strip is rgba(8, 20, 14, 0.72) over the felt; its brightest stop is --felt-1
  const strip = over([8, 20, 14], 0.72, hex("#35845a"));
  const desktopChip = hex("#10131a");
  it.each([".points-target", ".trump-chip.none"])("%s reads at 4.5:1 or more", (sel) => {
    const color = prop(decls(sel), "color")!;
    expect(color).toMatch(/^#[0-9a-f]{6}$/i);
    expect(contrast(hex(color), strip)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(hex(color), desktopChip)).toBeGreaterThanOrEqual(4.5);
  });
  it("the placeholder is not italic", () => {
    expect(prop(decls(".trump-chip.none"), "font-style")).toBeNull();
  });
});

describe("hand touch", () => {
  it("lifts and scales the pressed card, and dims without hiding", () => {
    expect(prop(decls(".hand .hand-slot.pressed .card"), "transform")).toMatch(/translateY\(-\d+px\) scale\(1\.\d+\)/);
    const dim = decls(".hand .hand-slot.dimmed .card");
    expect(prop(dim, "filter")).toContain("brightness");
    expect(dim).not.toMatch(/display:\s*none|visibility:\s*hidden|opacity:\s*0[;\s]/);
  });
  it("lets a disabled Play's wrapper hear the tap", () => {
    expect(prop(decls(".play-wrap > .btn:disabled"), "pointer-events")).toBe("none");
  });
});

it("stills the points float under Reduce Motion", () => {
  expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.points-pop \{ display: none; \}/);
});
