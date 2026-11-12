// @vitest-environment node
/// <reference types="node" />
// Guards the native-feel rules in index.css that jsdom cannot render: no
// long-press selection or callout outside fields and chat, a press state on
// the home tabs, segmented controls, switch and How to play link, and the
// menu and chat pop with its Reduce Motion fallback.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8");
/** Every rule body whose selector list (comments stripped) is exactly `selector`. */
function all(selector: string, source = css): string[] {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  const out: string[] = [];
  for (let m = re.exec(source); m; m = re.exec(source)) {
    if (m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim().replace(/\s+/g, " ") === selector) out.push(m[2]);
  }
  return out;
}
const has = (selector: string, decl: string, source = css) =>
  all(selector, source).some((body) => body.replace(/\s+/g, " ").includes(decl));
const reduced = (() => {
  const blocks: string[] = [];
  const re = /@media \(prefers-reduced-motion: reduce\) \{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g;
  for (let m = re.exec(css); m; m = re.exec(css)) blocks.push(m[1]);
  return blocks.join("\n");
})();

describe("long press", () => {
  it("selects nothing and raises no callout anywhere in the app", () => {
    expect(has(".app", "-webkit-user-select: none;")).toBe(true);
    expect(has(".app", "user-select: none;")).toBe(true);
    expect(has(".app", "-webkit-touch-callout: none;")).toBe(true);
  });

  it("still selects in fields and chat messages", () => {
    const sel = ".app input, .app textarea, .app [contenteditable], .app .chat-text";
    expect(has(sel, "-webkit-user-select: text;")).toBe(true);
    expect(has(sel, "user-select: text;")).toBe(true);
    expect(has(sel, "-webkit-touch-callout: default;")).toBe(true);
  });
});

describe("press states", () => {
  it("dim the tabs, segmented buttons and How to play link while pressed, and the switch in its row", () => {
    expect(has(".tabbar-item:active, .topbar-tab:active, .segmented-btn:active, .howto-link:active", "opacity: 0.55;")).toBe(true);
    expect(has('button[role="switch"]:active .ios-switch', "opacity: 0.7;")).toBe(true);
  });

  it("let go within 100 ms, and without a fade under Reduce Motion", () => {
    expect(has(".tabbar-item, .topbar-tab, .segmented-btn, .howto-link", "transition: opacity 80ms")).toBe(true);
    expect(has(".tabbar-item, .topbar-tab, .segmented-btn, .howto-link, .ios-switch, .ios-switch::after",
      "transition: none;", reduced)).toBe(true);
  });
});

describe("menu and chat pop", () => {
  it("scales and fades over 200 ms each way, and not at all under Reduce Motion", () => {
    expect(has(".hud-menu.pop-in, .chat-panel.pop-in", "animation: pop-in 200ms")).toBe(true);
    expect(has(".hud-menu.pop-out, .chat-panel.pop-out", "animation: pop-out 200ms")).toBe(true);
    expect(css).toMatch(/@keyframes pop-in \{ from \{ opacity: 0; transform: scale\(0\.94\); \} \}/);
    expect(has(".hud-menu.pop-in, .chat-panel.pop-in, .hud-menu.pop-out, .chat-panel.pop-out",
      "animation: none;", reduced)).toBe(true);
  });
});
