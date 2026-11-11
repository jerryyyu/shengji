// @vitest-environment node
/// <reference types="node" />
// Guards chrome rules in index.css that jsdom cannot render: the toast's fade
// timing, Reduce Motion on the deal deck, How to play tap areas, one focus
// ring on fields, the turned table's hand inset, the dimmed-card veil and the
// capped text scale.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
/** The body of the first rule whose selector (comments stripped) is exactly `selector`. */
function decls(selector: string, source = css): string {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(source); m; m = re.exec(source)) {
    if (m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ") === selector) return m[2];
  }
  throw new Error(`no rule ${selector}`);
}

describe("the error toast", () => {
  it("fades out over its last 0.4 s, timed from the same number that unmounts it", () => {
    expect(decls(".toast")).toContain("toast-out 0.4s ease-in calc(var(--toast-ms, 4000ms) - 0.4s) forwards");
    expect(css).toContain(".toast { animation: toast-out 0.01ms linear calc(var(--toast-ms, 4000ms) - 0.01ms) forwards; }");
    expect(css).not.toMatch(/toast-out[^;]*3\.6s/);
  });
});

describe("Reduce Motion", () => {
  it("stills the deal deck with a selector as heavy as the pulsing card's", () => {
    expect(css).toContain(".deal-deck-stack .card:nth-child(3) { animation: deck-pulse");
    const i = css.indexOf(".deal-deck-stack .card:nth-child(n),");
    expect(i).toBeGreaterThan(css.indexOf(".deal-deck-stack .card:nth-child(3) { animation: deck-pulse"));
    expect(css.lastIndexOf("@media (prefers-reduced-motion: reduce)", i)).toBeGreaterThan(-1);
  });

  it("leaves no infinite animation without a reduce rule", () => {
    for (const m of css.matchAll(/animation:\s*([\w-]+)[^;]*infinite/g)) {
      expect(css, m[1]).toMatch(new RegExp(`prefers-reduced-motion[\\s\\S]*(${m[1]}|animation: none)`));
    }
  });
});

describe("How to play targets", () => {
  it("gives each 30px picture control a 44px tap, and the controls do not share one", () => {
    expect(decls(".howto-anim-btn::after")).toMatch(/inset: -7px/);
    expect(decls(".howto-anim-btn")).toMatch(/position: relative/);
    expect(decls(".howto-anim-controls")).toMatch(/gap: 14px/);
  });

  it("gives each step dot a 44px-tall tap up to 44px wide", () => {
    const dot = decls(".howto-dot");
    expect(dot).toMatch(/min-height: 44px/);
    expect(dot).toMatch(/max-width: 44px/);
    expect(dot).toMatch(/flex: 1 1 0/);
  });
});

describe("fields", () => {
  it("show focus once: the border, not the border and the outline", () => {
    const f = decls(".field input:focus, .field select:focus, .start-level-row select:focus, .room-input:focus");
    expect(f).toMatch(/border-color: var\(--team0\)/);
    expect(f).toMatch(/outline: none/);
  });
});

describe("the turned table on a phone browser", () => {
  it("keeps the hand 8px off the phone's edge", () => {
    expect(decls(".app.rotated .table-screen")).toMatch(/--hand-under: max\(8px, calc\(var\(--safe-b\) - 16px\)\)/);
  });
});

describe("text size", () => {
  it("scales chrome text with 1rem, from the default up to 1.3x", () => {
    expect(decls(":root")).toContain("--tu: calc(1rem / 16);");
    for (const n of [10, 11, 12, 13, 14, 15, 16, 17, 18, 20]) {
      expect(decls(":root")).toContain(`--fs-${n}: clamp(${n}px, calc(${n} * var(--tu)), ${+(n * 1.3).toFixed(2)}px);`);
    }
    // WebKit's Dynamic Type size is the root's, 17px at the default setting
    expect(css).toMatch(/@supports \(font: -apple-system-body\) \{\s*html \{\s*font: -apple-system-body;/);
    expect(css).toContain("--tu: calc(1rem / 17);");
  });

  it("leaves card faces and the table's geometry in px, and no other rem length", () => {
    expect(decls(".card .corner-rank")).toContain("var(--cw, 70px)");
    expect(decls(".lead-tag, .win-tag")).not.toContain("--fs-");
    const lengths = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/--tu: calc\(1rem \/ 1[67]\);/g, "");
    expect(lengths).not.toMatch(/[\d.]rem\b/);
  });
});

describe("the boot page", () => {
  it("keeps the title out of the safe areas and offers Retry once the app is late", () => {
    expect(html).toMatch(/padding: max\(16px, env\(safe-area-inset-top\)\)/);
    expect(html).toContain("Connecting… check your network");
    expect(html).toMatch(/setTimeout\(function \(\) \{[\s\S]*boot-retry[\s\S]*\}, 4000\)/);
  });
});
