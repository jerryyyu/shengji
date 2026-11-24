// @vitest-environment node
/// <reference types="node" />
// Contrast and text size rules in index.css that jsdom cannot render: the
// text tokens meet WCAG AA (4.5:1) on the grounds they are drawn on,
// computed from the token values themselves, and the small labels follow the
// reader's text size through the --fs-* tokens.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");
const AA = 4.5;

/** The body of the first rule whose selector (comments stripped) is exactly `selector`. */
function decls(selector: string): string {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(css); m; m = re.exec(css)) {
    if (m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ") === selector) return m[2];
  }
  throw new Error(`no rule ${selector}`);
}

/** A colour token's hex value from the first :root block. */
function token(name: string): string {
  const m = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(decls(":root"));
  if (!m) throw new Error(`no colour token --${name}`);
  return m[1];
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("the contrast helper", () => {
  it("gives the WCAG reference values", () => {
    expect(contrast("#ffffff", "#000000")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });
});

describe("text tokens meet AA on their ground", () => {
  it("the table panel's seat sub-line is --text-dim on the panel", () => {
    expect(decls(".tp-seat-sub")).toContain("color: var(--text-dim)");
    expect(contrast(token("text-dim"), token("panel"))).toBeGreaterThanOrEqual(AA);
    expect(contrast(token("text-dim"), token("chrome"))).toBeGreaterThanOrEqual(AA);
  });

  it("the How to play picture's felt has no bright centre, so its text holds AA everywhere on it", () => {
    const visual = decls(".howto-visual");
    expect(visual).toContain("var(--felt-2) 0%, var(--felt-3) 100%");
    expect(visual).not.toContain("--felt-1");
    for (const ground of ["felt-2", "felt-3"]) {
      for (const fg of ["text", "felt-text-dim", "gold"]) {
        expect(contrast(token(fg), token(ground)), `${fg} on ${ground}`).toBeGreaterThanOrEqual(AA);
      }
    }
  });

  it("secondary text on the felt is --felt-text-dim, not --text faded by opacity", () => {
    for (const sel of [".howto-label", ".howto-note", ".howto-ticks", ".howto-seat-name"]) {
      const body = decls(sel);
      expect(body, sel).toContain("color: var(--felt-text-dim)");
      expect(body, sel).not.toMatch(/opacity/);
    }
    // still a step below --text, so the hierarchy survives
    expect(luminance(token("felt-text-dim"))).toBeLessThan(luminance(token("text")));
  });
});

describe("small labels follow the reader's text size", () => {
  it("draw their size from an --fs-* token, not fixed px", () => {
    for (const sel of [
      ".declare-tag", ".round-end-col-label", ".round-end-play-who", ".lb-new",
      ".howto-label", ".howto-note", ".howto-arrow-up", ".howto-kitty-head", ".howto-scale-line span",
      ".howto-ticks", ".howto-seat-name", ".topbar-mark span", ".tp-team-label", ".tp-seat-sub",
    ]) {
      expect(decls(sel), sel).toMatch(/font-size: var\(--fs-\d+\)/);
    }
  });

  it("the scale's tick row grows with its text", () => {
    expect(decls(".howto-ticks")).toContain("height: 1.4em");
  });
});

describe("the panel's controls hold AA without dimming", () => {
  const playLines = readFileSync(new URL("./queue/playLines.css", import.meta.url), "utf8");
  const ruleIn = (src: string, selector: string): string => {
    const re = /([^{}]+)\{([^{}]*)\}/g;
    for (let m = re.exec(src); m; m = re.exec(src)) {
      if (m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ") === selector) return m[2];
    }
    throw new Error(`no rule ${selector}`);
  };
  const color = (body: string) => /(?:^|;)\s*color:\s*(#[0-9a-fA-F]{6})/.exec(body)?.[1] ?? "";
  // the gold face's lighter end, where its text is hardest to read
  const GOLD_TOP = "#8a6a22";

  it("the gold panel button's text and its ring's seconds are at least 4.5:1 on the gold", () => {
    // Start's ink is the shared primary rule's, whose selector list names .tp-primary
    const shared = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .find((m) => m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim()).includes(".tp-primary") && color(m[2]));
    const button = color(shared?.[2] ?? "");
    expect(shared?.[2]).toContain("linear-gradient(180deg, #8a6a22, #6b5219)");
    expect(contrast(button, GOLD_TOP)).toBeGreaterThanOrEqual(AA);
    expect(contrast(color(decls(".tp-primary .timer-ring-secs")), GOLD_TOP)).toBeGreaterThanOrEqual(AA);
  });

  it("the shared gold of every other main action (.btn.gold, Next round, Next, Save) holds 4.5:1 on its face", () => {
    const shared = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .find((m) => m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim()).includes(".btn.gold") && color(m[2]));
    expect(shared?.[2]).toContain("linear-gradient(180deg, #8a6a22, #6b5219)");
    expect(contrast(color(shared?.[2] ?? ""), GOLD_TOP)).toBeGreaterThanOrEqual(AA);
  });

  it("the mode a seated player cannot switch to is drawn whole, in AA text, with a lock", () => {
    const held = ruleIn(playLines, ".play-section .play-mode-opt:disabled:not(.on)");
    expect(held).toContain("opacity: 1");
    expect(held).toContain("color: var(--text-dim)");
    expect(contrast(token("text-dim"), token("panel"))).toBeGreaterThanOrEqual(AA);
    expect(ruleIn(playLines, ".play-section .play-mode-opt:disabled:not(.on)::before")).toMatch(/mask: url\(/);
  });

  it("Bury is drawn at full opacity with light text on opaque filled and empty parts", () => {
    expect(decls(".btn.primary.bury-btn:disabled")).toContain("opacity: 1");
    const bury = decls(".btn.primary.bury-btn, .btn.primary.bury-btn:hover:not(:disabled)");
    const text = color(bury);
    // both stops are opaque colours, so the face is what is drawn whatever the felt under it
    const stops = /linear-gradient\(90deg, (#[0-9a-fA-F]{6}) var\(--bury-fill, 0%\), (#[0-9a-fA-F]{6}) var\(--bury-fill, 0%\)\)/.exec(bury);
    expect(stops, "two opaque hex stops at --bury-fill").not.toBeNull();
    const [, filled, empty] = stops!;
    // a full face (8 of 8) is all `filled`; a partial one has the text over both
    expect(contrast(text, filled)).toBeGreaterThanOrEqual(AA);
    expect(contrast(text, empty)).toBeGreaterThanOrEqual(AA);
  });
});

describe("the leaderboard's marks hold AA on their rows", () => {
  it("the week's movement colours and the medal discs' digits", () => {
    const grp = /--grp:\s*(#[0-9a-fA-F]{6})/.exec(css)![1];
    for (const dir of ["up", "down", "flat"]) {
      const c = /color:\s*(#[0-9a-fA-F]{6})/.exec(decls(`.lb-move.${dir}`))![1];
      expect(contrast(c, grp), dir).toBeGreaterThanOrEqual(AA);
      expect(contrast(c, "#2d3a2f"), `${dir} on your own row`).toBeGreaterThanOrEqual(AA);
    }
    for (const n of [2, 3]) {
      const disc = /background:\s*(#[0-9a-fA-F]{6})/.exec(decls(`.lb-rank.medal-${n}`))![1];
      expect(contrast("#14171e", disc)).toBeGreaterThanOrEqual(AA);
    }
    expect(contrast("#14171e", token("gold"))).toBeGreaterThanOrEqual(AA);
  });
});
