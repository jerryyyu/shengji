// @vitest-environment node
/// <reference types="node" />
// Guards interface-feel rules that jsdom cannot render, as literal lists: no
// transition on every property, live numbers in fixed-width digits, a press
// state on every listed control, and a 44px tap on every listed control
// (drawn, or drawn plus an invisible extender). A new control joins its list.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const files = ["./index.css", "./queue/playLines.css", "./components/ChatPanel.css"];
const sources = files.map((f) => readFileSync(new URL(f, import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, ""));
const css = sources.join("\n");

type Rule = { sels: string[]; body: string };
/** Every innermost rule, its selector list split on top-level commas. */
const rules: Rule[] = (() => {
  const out: Rule[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(css); m; m = re.exec(css)) {
    const sels: string[] = [];
    let depth = 0;
    let cur = "";
    for (const ch of m[1].trim().replace(/\s+/g, " ")) {
      if (ch === "(") depth++;
      if (ch === ")") depth--;
      if (ch === "," && depth === 0) { sels.push(cur.trim()); cur = ""; } else cur += ch;
    }
    sels.push(cur.trim());
    out.push({ sels, body: m[2].replace(/\s+/g, " ") });
  }
  return out;
})();
const reduced = (() => {
  const blocks: string[] = [];
  const re = /@media \(prefers-reduced-motion: reduce\) \{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g;
  for (let m = re.exec(css); m; m = re.exec(css)) blocks.push(m[1].replace(/\s+/g, " "));
  return blocks.join("\n");
})();
const bodies = (sel: string) => rules.filter((r) => r.sels.includes(sel)).map((r) => r.body);
const px = (v: string) => (v === "0" ? 0 : Number(/^(-?\d+(?:\.\d+)?)px$/.exec(v)?.[1] ?? NaN));

describe("transitions", () => {
  it("never animate every property", () => {
    expect(css).not.toMatch(/transition(-property)?:\s*all\b/);
  });
});

describe("live numbers", () => {
  const LIVE = [
    ".off-tag.counting", ".card-count", ".chat-badge", ".tp-chat-badge", ".play-presence",
    ".bury-points", ".table-pill", ".account-pill-rating", ".tp",
  ];
  it.each(LIVE)("%s keeps fixed-width digits", (sel) => {
    expect(bodies(sel).some((b) => b.includes("font-variant-numeric: tabular-nums"))).toBe(true);
  });
});

describe("press feedback", () => {
  const SCALE = [
    ".btn", ".tp-primary", ".tp-secondary", ".tp-invite", ".table-pill", ".reconnect-retry",
    ".leave-sheet-actions button",
  ];
  const DIM = [
    ".tabbar-item", ".topbar-tab", ".segmented-btn", ".howto-link", "button.tp-seat", ".tp-chat",
    ".play-mode-opt", ".chat-quick-btn", "button.q-link", ".account-pill", ".last-trick-close",
  ];
  const active = (sel: string) => rules.filter((r) => r.sels.some((s) => s.startsWith(`${sel}:active`)));

  it.each(SCALE)("%s scales on press and stays still under Reduce Motion", (sel) => {
    expect(active(sel).some((r) => r.body.includes("transform: scale(0.97)"))).toBe(true);
    expect(reduced).toContain(`${sel}:active`);
  });

  it.each(DIM)("%s dims on press at once", (sel) => {
    expect(active(sel).some((r) => r.body.includes("opacity: 0.55") && r.body.includes("transition-duration: 0ms"))).toBe(true);
  });
});

describe("tap targets", () => {
  // controls drawn at 44px or more
  const DRAWN = [".tp-primary", ".tp-secondary", ".tp-seat", ".q-link", ".leave-sheet-actions button"];
  it.each(DRAWN)("%s is drawn at least 44px tall", (sel) => {
    const h = bodies(sel).flatMap((b) => [...b.matchAll(/(?:^|[ ;])(?:min-)?height: (\d+)px/g)].map((m) => Number(m[1])));
    expect(h.length).toBeGreaterThan(0);
    expect(Math.min(...h)).toBeGreaterThanOrEqual(44);
  });

  // smaller controls: their smallest drawn height, and the extender that makes up the rest
  const EXTENDED: [string, number][] = [
    [".last-trick-btn", 28], [".reconnect-retry", 26], [".play-mode-opt", 36], [".tp-invite", 40],
    [".btn.join-leave", 40], [".table-pill", 40], [".last-trick-close", 32], [".chat-quick-btn", 36],
    [".account-pill", 40], [".segmented-btn", 28],
  ];
  it.each(EXTENDED)("%s reaches 44px with an invisible extender", (sel, drawn) => {
    expect(css).toMatch(new RegExp(`(?:^|[ ;{])(?:min-)?height: ${drawn}px`));
    const ext = [`${sel}::after`, `${sel}::before`].flatMap(bodies).find((b) => /position: absolute/.test(b) && /inset:/.test(b));
    expect(ext, `${sel} has no extender`).toBeDefined();
    expect(ext).toContain('content: ""');
    const v = /inset: ([^;]+);/.exec(ext!)![1].trim().split(" ").map(px);
    const [top, bottom] = [v[0], v.length >= 3 ? v[2] : v[0]];
    expect(drawn - top - bottom).toBeGreaterThanOrEqual(44);
    expect(bodies(sel).some((b) => /position: (relative|absolute)/.test(b))).toBe(true);
  });
});
