// Renders scene.html deterministically: seeks its paused GSAP timeline to each
// frame time and screenshots at 2x, plus the poster frame.
//
//   node render.mjs --out /tmp/og-scene --fps 60
import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : dflt;
};
const out = arg("out", "/tmp/og-scene");
const fps = Number(arg("fps", "60"));
const only = arg("frames");  // optional "t1,t2,..." seconds for spot checks

mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 2 });
await page.goto(pathToFileURL(join(here, "scene.html")).href + "#render");
await page.waitForFunction(() => typeof window.seekScene === "function");
await page.evaluate(() => document.fonts.ready);

const shot = async (t, path) => {
  await page.evaluate((s) => window.seekScene(s), t);
  await page.screenshot({ path, type: "png" });
};
if (only) {
  for (const t of only.split(",")) await shot(Number(t), join(out, `t${t}.png`));
} else {
  const duration = await page.evaluate(() => window.sceneDuration);
  const n = Math.round(duration * fps);
  for (let i = 0; i < n; i++) await shot(i / fps, join(out, `f${String(i).padStart(5, "0")}.png`));
  await shot(await page.evaluate(() => window.posterTime), join(out, "poster.png"));
  writeFileSync(join(out, "meta.json"), JSON.stringify({ duration, fps, frames: n }));
  console.log(`${n} frames (${duration.toFixed(3)} s at ${fps} fps) -> ${out}`);
}
await browser.close();
