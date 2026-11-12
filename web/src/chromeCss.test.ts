// @vitest-environment node
/// <reference types="node" />
// Guards chrome rules in index.css that jsdom cannot render: the toast's fade
// timing, Reduce Motion on the deal deck, How to play tap areas, one focus
// ring on fields, the turned table's hand inset, the dimmed-card veil, the
// capped text scale and the home tabs' touch targets.
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

  it("keeps the picture's content out of the controls' strip, taps included", () => {
    // top 6px + 30px button + 7px of tap below it ends at 43px
    expect(decls(".howto-anim-controls")).toMatch(/top: 6px/);
    expect(decls(".howto-visual:has(> .howto-anim-controls)")).toMatch(/padding-top: 44px/);
    expect(css).toMatch(/\.howto-step > \.howto-visual:has\(> \.howto-anim-controls\) \{ padding-top: 44px; \}/);
  });

  it("draws the step dots as an indicator that takes no taps", () => {
    expect(decls(".howto-dots")).toMatch(/pointer-events: none/);
    expect(decls(".howto-dot")).not.toMatch(/cursor: pointer/);
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

describe("home touch targets", () => {
  const px = (body: string, prop: string) => Number(new RegExp(`(?:^|[;\\s])${prop}:\\s*(-?\\d+)px`).exec(body)?.[1]);
  it("the segmented buttons draw 28px in a 32px track and reach 44px with ::before", () => {
    const track = px(decls(".segmented"), "height");
    const padding = px(decls(".segmented"), "padding");
    const drawn = track - 2 * padding;
    expect(drawn).toBe(28);
    expect(decls(".segmented-btn")).toContain("position: relative");
    const inset = /inset:\s*-(\d+)px 0/.exec(decls(".segmented-btn::before"))!;
    expect(drawn + 2 * Number(inset[1])).toBeGreaterThanOrEqual(44);
    // the overhang stays inside the gap to the column's next item
    expect(Number(inset[1]) - padding).toBeLessThan(px(decls(".home-col"), "gap") / 2);
  });

  it("the account chip reaches 44px inside the 56px top bar", () => {
    const chip = px(decls(".account-pill"), "height");
    const inset = /inset:\s*-(\d+)px 0/.exec(decls(".account-pill::before"))!;
    expect(chip + 2 * Number(inset[1])).toBeGreaterThanOrEqual(44);
    expect(chip + 2 * Number(inset[1])).toBeLessThanOrEqual(56);
  });
});

describe("the charcoal page", () => {
  /** Every rule as [selector, body], media blocks included. */
  const rules = (): [string, string][] => {
    const out: [string, string][] = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    for (let m = re.exec(css); m; m = re.exec(css)) {
      out.push([m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " "), m[2]]);
    }
    return out;
  };

  it("is the redesign's charcoal token", () => {
    expect(css).toMatch(/--page: #1b1f27;/);
    expect(decls(".home")).toMatch(/background: var\(--page\)/);
  });

  it("is every screen's ground at every width, the replay and saved games included", () => {
    expect(decls(".screen")).toMatch(/background: var\(--page\);/);
    expect(decls(".screen")).not.toMatch(/--felt/);
    expect(decls(".screen.games-screen")).toMatch(/background: var\(--page\);/);
    expect(decls(".games-screen > .panel")).toMatch(/background: none;/);
  });

  it("leaves no lobby, room, games, how-to or info screen on the felt", () => {
    const pages = /(^|[\s,])\.(screen|lobby-screen|room-screen|games-screen|howto-screen|info-screen|home|home-body|home-wide)\b/;
    for (const [selector, body] of rules()) {
      if (!pages.test(selector) || /table-screen/.test(selector)) continue;
      expect(body, selector).not.toMatch(/background[^;]*--felt/);
    }
  });

  it("keeps the felt for the table itself, the replay's table and the lobby preview", () => {
    expect(decls(".felt")).toMatch(/var\(--felt-1\)/);
    expect(decls(".replay-felt")).toMatch(/var\(--felt-1\)/);
    expect(decls(".lobby-preview")).toMatch(/var\(--felt-1\)/);
  });

  it("draws the replay's chrome on the grouped surface, not the old dark card", () => {
    const chrome = rules().find(([s]) => s.startsWith(".games-screen .games-row.static,"));
    expect(chrome?.[0]).toContain(".games-screen .replay-seat");
    expect(chrome?.[0]).toContain(".games-screen .replay-jump");
    expect(chrome?.[1]).toMatch(/background: var\(--grp\);/);
  });
});

describe("the home Play column", () => {
  it("sits on the page with no card at any width, 420px wide and centred from 700px", () => {
    const flat = decls(".home .play-tab > .lobby-panel");
    expect(flat).toContain("background: none");
    expect(flat).toContain("border: 0");
    expect(flat).toContain("border-radius: 0");
    expect(flat).toContain("box-shadow: none");
    const wide = decls(".home-wide .play-tab > .lobby-panel");
    expect(wide).toContain("width: 420px");
    expect(wide).not.toMatch(/background|border|box-shadow/);
    // the card the panel draws elsewhere (room, offline lobby) is still there
    expect(decls(".panel")).toContain("box-shadow");
  });
});
