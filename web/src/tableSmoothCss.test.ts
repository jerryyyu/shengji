// @vitest-environment node
/// <reference types="node" />
// Guards table rules jsdom cannot render: the header's "/ 80" and "No trump"
// read at 4.5:1 or more over the brightest felt, the touched card lifts and
// grows, and the points float stills under Reduce Motion.
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
  it("lifts and scales the pressed card", () => {
    expect(prop(decls(".hand .hand-slot.pressed .card"), "transform")).toMatch(/translateY\(-\d+px\) scale\(1\.\d+\)/);
  });
  it("lets a disabled Play's wrapper hear the tap", () => {
    expect(prop(decls(".play-wrap > .btn:disabled"), "pointer-events")).toBe("none");
  });
});

it("stills the points float under Reduce Motion", () => {
  expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.points-pop \{ display: none; \}/);
});

describe("the follow hint floats", () => {
  // every .hand-line rule, desktop and phone, takes the hint out of the
  // flow, so showing it never moves the action bar
  it("the base and phone .hand-line rules are absolutely positioned", () => {
    const re = /([^{}]+)\{([^{}]*)\}/g;
    const bodies: string[] = [];
    for (let m = re.exec(css); m; m = re.exec(css)) {
      if (m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ") === ".hand-line") bodies.push(m[2]);
    }
    const positions = bodies.map((body) => prop(body, "position")).filter((p) => p !== null);
    expect(positions.length).toBeGreaterThanOrEqual(2);
    for (const p of positions) expect(p).toBe("absolute");
    expect(prop(bodies[0], "position")).toBe("absolute");
  });
});

/** A pseudo-element with no background (a glow drawn outside the border box,
 *  a hit area) paints nothing over the face, so its own opacity cannot fade it. */
const paintsNothingOnFace = (sel: string, body: string) =>
  /::(before|after)$/.test(sel) && ["background", "background-color", "background-image"].every((n) => prop(body, n) === null);

describe("hand cards are never dimmed", () => {
  // Every card in your hand keeps full strength: the coach points with the
  // idle pulse, never by darkening the rest. Only a press darkens, briefly.
  const re = /([^{}]+)\{([^{}]*)\}/g;
  const handRules: { sel: string; body: string }[] = [];
  for (let m = re.exec(css); m; m = re.exec(css)) {
    const sel = m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ");
    if (/\.hand(-slot)?\b/.test(sel) && /\.card\b/.test(sel) && !sel.includes(":active")) handRules.push({ sel, body: m[2] });
  }
  it("finds the hand's card rules", () => {
    expect(handRules.length).toBeGreaterThan(5);
  });
  it.each(handRules.map((r) => [r.sel, r.body]))("%s neither filters nor fades the card", (sel, body) => {
    expect(prop(body, "filter")).toBeNull();
    if (paintsNothingOnFace(sel, body)) return;
    const opacity = prop(body, "opacity");
    expect(opacity === null || Number(opacity) >= 1).toBe(true);
  });
  it("a card face is opaque under its gradient", () => {
    expect(prop(decls(".card"), "background")).toMatch(/linear-gradient\([^)]*\)\s+#[0-9a-f]{6}$/i);
  });
  // A face's white is never thinned or taken away in any state (chosen, the
  // coach's, a follow): no rule on a face, anywhere, makes it see-through.
  const faceRules: { sel: string; body: string }[] = [];
  const all = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = all.exec(css); m; m = all.exec(css)) {
    for (const one of m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",")) {
      const sel = one.trim().replace(/\s+/g, " ");
      const last = sel.split(" ").pop() ?? "";
      if (/\.card(?![-\w])/.test(last) && !/\.back\b/.test(last)) faceRules.push({ sel, body: m[2] });
    }
  }
  it("finds the card face rules", () => {
    expect(faceRules.length).toBeGreaterThan(10);
  });
  it.each(faceRules.map((r) => [r.sel, r.body]))("%s keeps the face opaque", (sel, body) => {
    const opacity = prop(body, "opacity");
    expect(paintsNothingOnFace(sel, body) || opacity === null || Number(opacity) >= 1).toBe(true);
    for (const name of ["background", "background-color", "background-image"]) {
      expect(prop(body, name) ?? "").not.toMatch(/^(transparent|none)$|rgba\([^)]*,\s*0(\.\d+)?\)\s*$/);
    }
  });
});
