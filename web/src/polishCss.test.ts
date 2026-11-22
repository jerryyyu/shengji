// @vitest-environment node
/// <reference types="node" />
// Guards interface-feel rules that jsdom cannot render, as literal lists: no
// transition on every property, live numbers in fixed-width digits, a press
// state on every listed control, and a 44px tap on every listed control in
// every state the CSS draws it (drawn, or drawn plus an invisible extender),
// but for the named exceptions. A new control joins its list.
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
    ".tabbar-item", ".topbar-tab", ".segmented-btn", ".howto-link", "button.tp-seat", ".tp-chat", ".tp-settings",
    ".play-mode-opt", ".chat-quick-btn", "button.q-link", ".account-pill", ".last-trick-close", ".rating-signin",
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
  const DRAWN = [".tp-primary", ".tp-secondary", ".tp-seat", ".tp-invite", ".q-link", ".leave-sheet-actions button"];
  it.each(DRAWN)("%s is drawn at least 44px tall", (sel) => {
    const h = bodies(sel).flatMap((b) => [...b.matchAll(/(?:^|[ ;])(?:min-)?height: (\d+)px/g)].map((m) => Number(m[1])));
    expect(h.length).toBeGreaterThan(0);
    expect(Math.min(...h)).toBeGreaterThanOrEqual(44);
  });

  // Smaller controls: each state's drawn height is read from every rule whose
  // selector ends at the control (".x", ".state .x"), so a state override
  // that shrinks the control is measured, not assumed.
  const EXTENDED = [
    ".last-trick-btn", ".reconnect-retry", ".play-mode-opt", ".tp-settings", ".btn.join-leave",
    ".table-pill", ".last-trick-close", ".chat-quick-btn", ".account-pill", ".segmented-btn", ".rating-signin",
  ];
  // States drawn under 44px on purpose, each with its reason.
  const EXCEPTIONS: Record<string, string> = {
    // the keyboard-up compact chat has no height to spare: its 30px chips sit
    // under a 4px row padding and the scrolling row clips the extender there
    ".chat-panel.chat-short .chat-quick-btn": "compact chat, about 35px",
  };
  // An extender inside a scrolling row is clipped at the row's padding box,
  // so it reaches no further than that padding.
  const CLIPPED: Record<string, string> = { ".chat-quick-btn": ".chat-quick" };
  // A control stretched to its track draws the track's height less its padding.
  const TRACK: Record<string, string> = { ".segmented-btn": ".segmented" };

  const heights = (sel: string) =>
    rules.flatMap((r) => r.sels.filter((s) => s === sel || s.endsWith(` ${sel}`)).flatMap((s) =>
      [...r.body.matchAll(/(?:^|[ ;])(?:min-)?height: (\d+)px/g)].map((m) => ({ state: s, px: Number(m[1]) }))));
  const box = (v: string) => {
    const n = v.trim().split(" ").map(px);
    return { top: n[0], bottom: n.length >= 3 ? n[2] : n[0] };
  };

  it.each(EXTENDED)("%s reaches 44px with an invisible extender in every state", (sel) => {
    const ext = [`${sel}::after`, `${sel}::before`].flatMap(bodies).find((b) => /position: absolute/.test(b) && /inset:/.test(b));
    expect(ext, `${sel} has no extender`).toBeDefined();
    expect(ext).toContain('content: ""');
    expect(bodies(sel).some((b) => /position: (relative|absolute)/.test(b))).toBe(true);
    const { top, bottom } = box(/inset: ([^;]+);/.exec(ext!)![1]);
    const row = CLIPPED[sel];
    if (row) {
      const pad = bodies(row).map((b) => /(?:^|[ ;])padding: ([^;]+);/.exec(b)?.[1]).find(Boolean);
      expect(pad, `${row} has no padding`).toBeDefined();
      const p = box(pad!);
      expect(-top).toBeLessThanOrEqual(p.top);
      expect(-bottom).toBeLessThanOrEqual(p.bottom);
    }
    const track = TRACK[sel];
    const states = track
      ? heights(track).map((h) => {
          const pad = bodies(h.state).map((x) => /(?:^|[ ;])padding: ([^;]+);/.exec(x)?.[1]).find(Boolean);
          const p = pad ? box(pad) : { top: 0, bottom: 0 };
          return { state: `${h.state} ${sel}`, px: h.px - p.top - p.bottom };
        })
      : heights(sel);
    expect(states.length, `${sel} has no drawn height`).toBeGreaterThan(0);
    for (const { state, px: drawn } of states) {
      if (state in EXCEPTIONS) continue;
      expect(drawn - top - bottom, `${state} at ${drawn}px`).toBeGreaterThanOrEqual(44);
    }
  });

  it.each(Object.keys(EXCEPTIONS))("%s is a drawn state of a listed control", (state) => {
    expect(EXTENDED.some((sel) => heights(sel).some((h) => h.state === state))).toBe(true);
  });
});
