// Browser hit test for the phone table's notice close button: renders the
// notice from src/index.css at an iPhone landscape size with touch, then
// samples elementFromPoint around the button and reports the area that
// dismisses the notice, for a one-line and a wrapped notice.
//
//   node scripts/notice-hit-test.mjs [--chrome <path>] [--css <path>]
//
// Exits 1 when either notice's dismiss area is under 44x44 px or does not
// reach 9px past the visible glyph on every side.
import { chromium } from "playwright-core";
import { readFileSync, existsSync } from "node:fs";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const chromes = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`,
];
const executablePath = arg("--chrome", chromes.find((p) => existsSync(p)));
const css = readFileSync(arg("--css", new URL("../src/index.css", import.meta.url)), "utf8");

const notices = {
  short: 'Throw failed. Play <span class="hud-notice-cards forced">S2</span>.',
  wrapped:
    'Your throw failed. You must play <span class="hud-notice-cards forced">S2 S2</span> because West holds a higher pair in spades.',
};

const browser = await chromium.launch({ executablePath, headless: true });
const results = {};
let ok = true;
for (const [name, body] of Object.entries(notices)) {
  const page = await browser.newPage({
    viewport: { width: 852, height: 393 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 1,
  });
  await page.setContent(
    `<meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}</style>` +
      `<style>*{animation:none!important;transition:none!important}</style>` +
      `<div class="table-screen phase-play"><div class="hud-notice" role="status">` +
      `<div class="hud-notice-body">${body}</div>` +
      `<button class="hud-notice-close" aria-label="Dismiss notice">×</button></div></div>`,
  );
  await page.waitForTimeout(200);
  results[name] = await page.evaluate(() => {
    const button = document.querySelector(".hud-notice-close");
    const notice = document.querySelector(".hud-notice");
    const textBody = document.querySelector(".hud-notice-body");
    const r = (e) => {
      const b = e.getBoundingClientRect();
      return { x: b.x, y: b.y, width: b.width, height: b.height };
    };
    const b = button.getBoundingClientRect();
    const hit = (x, y) => document.elementFromPoint(x, y)?.closest("button") === button;
    const xs = [];
    const ys = [];
    for (let y = Math.floor(b.top) - 30; y < b.bottom + 30; y++)
      for (let x = Math.floor(b.left) - 30; x < b.right + 30; x++)
        if (hit(x + 0.5, y + 0.5)) {
          xs.push(x);
          ys.push(y);
        }
    // the glyph is the content box: the button's box less its padding
    const s = getComputedStyle(button);
    const g = {
      left: b.left + parseFloat(s.paddingLeft),
      right: b.right - parseFloat(s.paddingRight),
      top: b.top + parseFloat(s.paddingTop),
      bottom: b.bottom - parseFloat(s.paddingBottom),
    };
    const cx = (g.left + g.right) / 2;
    const cy = (g.top + g.bottom) / 2;
    return {
      coarse: matchMedia("(pointer: coarse)").matches,
      notice: r(notice),
      body: r(textBody),
      bodyClipped: textBody.scrollHeight > textBody.clientHeight + 1,
      button: r(button),
      glyph: { width: g.right - g.left, height: g.bottom - g.top },
      hitBounds: {
        width: Math.max(...xs) - Math.min(...xs) + 1,
        height: Math.max(...ys) - Math.min(...ys) + 1,
      },
      topExtensionHits: hit(cx, g.top - 9),
      bottomExtensionHits: hit(cx, g.bottom + 9),
      leftExtensionHits: hit(g.left - 9, cy),
      rightExtensionHits: hit(g.right + 9, cy),
    };
  });
  const v = results[name];
  const pass =
    v.hitBounds.width >= 44 &&
    v.hitBounds.height >= 44 &&
    v.topExtensionHits &&
    v.bottomExtensionHits &&
    v.leftExtensionHits &&
    v.rightExtensionHits;
  v.pass = pass;
  ok &&= pass;
  await page.close();
}
await browser.close();
console.log(JSON.stringify(results, null, 2));
process.exit(ok ? 0 : 1);
