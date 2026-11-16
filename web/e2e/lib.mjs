// Shared pieces of the interaction suite: the browser, the device sizes, the
// page probes (rectangles, overlaps, clipping) and the environment levers
// from inject.js (socket drop, audio interruption, background, keyboard).
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const BASE = process.env.BASE || "http://127.0.0.1:8765/";
export const OUT = process.env.OUT || path.join(HERE, "out");
fs.mkdirSync(OUT, { recursive: true });

/** Layout sizes in CSS px. `kb` is the on-screen keyboard's height there. */
export const DEVICES = {
  "phone-land": { w: 844, h: 390, touch: true, kb: 210 },     // iPhone 14 Pro, table
  "phone-land-se": { w: 667, h: 375, touch: true, kb: 200 },  // iPhone SE, table
  // The iOS app, sideways: the notch and the home indicator take the safe areas.
  "phone-land-app": { w: 844, h: 390, touch: true, kb: 210, safe: { t: 0, r: 59, b: 21, l: 59 } },
  // Mobile Safari, sideways. Its toolbar (about 64 px) either floats over the page's
  // top (the page is told through the top safe area) or takes the height away; its
  // keyboard brings an accessory bar, so it is taller than the app's.
  "phone-land-safari": { w: 844, h: 390, touch: true, kb: 286, safe: { t: 64, r: 59, b: 21, l: 59 } },
  // ...and there 100vh stays the toolbar-less height (390) while the page is 326 tall
  "phone-land-safari-short": { w: 844, h: 326, touch: true, kb: 222, safe: { t: 0, r: 59, b: 21, l: 59 }, vh: 390 },
  "phone-port": { w: 390, h: 844, touch: true, kb: 336 },     // iPhone 14 Pro, lobby
  "phone-port-se": { w: 375, h: 667, touch: true, kb: 260 },
  ipad: { w: 1024, h: 768, touch: true, kb: 400 },
  desktop: { w: 1280, h: 800, touch: false, kb: 0 },
};

function chromePath() {
  if (process.env.CHROME) return process.env.CHROME;
  const root = path.join(process.env.HOME ?? "", "Library/Caches/ms-playwright");
  try {
    const dir = fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().pop();
    const p = path.join(root, dir, "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing");
    if (fs.existsSync(p)) return p;
  } catch { /* fall through: playwright's own lookup */ }
  return undefined;
}

export async function launch() {
  return chromium.launch({ executablePath: chromePath(), headless: true });
}

const INJECT = fs.readFileSync(path.join(HERE, "inject.js"), "utf8");

/** The iOS app's bridge, as its WebView injects it: the page takes itself
 *  for the app, and every plugin call resolves to nothing. */
const NATIVE = `window.Capacitor = { isNativePlatform: () => true,
  registerPlugin: () => new Proxy({}, { get: () => () => Promise.resolve(undefined) }) };`;

/** A page at one device size with the taps installed. `storage` seeds localStorage;
 *  `native` makes it the iOS app's page rather than a browser's. */
export async function open(browser, device, { url = "", storage = {}, base = BASE, fakeSocket = null, still = false, native = false } = {}) {
  const d = DEVICES[device];
  const ctx = await browser.newContext({
    viewport: { width: d.w, height: d.h }, deviceScaleFactor: 2, colorScheme: "dark",
    hasTouch: d.touch, isMobile: d.touch && d.w < 1000,
    reducedMotion: still ? "reduce" : "no-preference",
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(8000);
  page.qa = { device, d, errors: [], console: [] };
  page.on("pageerror", (e) => page.qa.errors.push(String(e.message)));
  page.on("console", (m) => { if (m.type() === "error") page.qa.console.push(m.text().slice(0, 300)); });
  if (Object.keys(storage).length) {
    await page.addInitScript(`for (const [k, v] of Object.entries(${JSON.stringify(storage)})) { try { if (localStorage.getItem(k) === null) localStorage.setItem(k, v); } catch {} }`);
  }
  await page.addInitScript(INJECT);
  if (native) await page.addInitScript(NATIVE);
  // The table reads its safe areas through --frame-safe-* (index.css), so a notch and a
  // toolbar can be put there. The lobby reads env() directly, which no browser lets a test set.
  if (d.safe) {
    await page.addInitScript(`document.addEventListener("DOMContentLoaded", () => { const s = document.createElement("style");
      s.textContent = ":root{--frame-safe-t:${d.safe.t}px;--frame-safe-r:${d.safe.r}px;--frame-safe-b:${d.safe.b}px;--frame-safe-l:${d.safe.l}px${d.vh ? `;--frame-h:${d.vh}px` : ""}}"; document.head.appendChild(s); });`);
  }
  if (fakeSocket) await page.addInitScript(fakeSocket);
  await page.goto(base + url);
  return page;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function shot(page, name) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  return file;
}

/** Turn the phone: a new layout size, as the app's rotation gives the WebView. */
export async function rotate(page, device) {
  const d = DEVICES[device];
  page.qa.device = device; page.qa.d = d;
  await page.setViewportSize({ width: d.w, height: d.h });
  await sleep(350);
}

/** Raise or drop the keyboard. "safari": the page keeps its size and the visual
 *  viewport shrinks. "app": the WebView itself shrinks (Capacitor resize: native). */
export async function keyboard(page, up, mode = "safari") {
  const { d } = page.qa;
  if (mode === "app") {
    await page.setViewportSize({ width: d.w, height: up ? d.h - d.kb : d.h });
    // what src/native.ts does on the Keyboard plugin's events: the class that
    // steps the tab bar aside, and the focused field brought back into view
    await page.evaluate((up) => {
      document.body.classList.toggle("keyboard-open", up);
      if (up) document.activeElement?.scrollIntoView?.({ block: "center" });
    }, up);
  } else {
    await page.evaluate((px) => window.__qa.setKeyboard(px), up ? d.kb : 0);
  }
  await sleep(350);
}

/** Leave for the background and come back, as iOS does it: hidden, socket dead,
 *  audio interrupted; then visible with the network back. */
export async function background(page, ms, { audio = "interrupted", stuck = true } = {}) {
  await page.evaluate(([a, s]) => { const q = window.__qa; q.setHidden(true); q.drop(true); if (a) q.interruptAudio(a, s); }, [audio, stuck]);
  await sleep(ms);
  await page.evaluate(() => { const q = window.__qa; q.unblock(); q.setHidden(false); });
}

export async function dropNetwork(page, ms) {
  await page.context().setOffline(true);
  await page.evaluate(() => window.__qa.drop(true));
  await sleep(ms);
  await page.evaluate(() => window.__qa.unblock());
  await page.context().setOffline(false);
}

/** The elements whose boxes must stay readable. name -> selector. */
export const KEY = {
  crown: ".banker-crown",
  leadTag: ".lead-tag",
  winTag: ".win-tag",
  trickTag: ".trick-tag",
  declareTag: ".declare-tag",
  trickCards: ".trick-play .trick-cards",
  oppName: ".opponent .opp-name",
  oppCards: ".opponent .opp-cards",
  youName: ".you-name",
  yourTurn: ".your-turn-tag",
  theirTurn: ".their-turn",
  handLine: ".hand-line",
  hand: ".hand",
  action: ".action-bar .btn",
  chatLaunch: ".chat-launch",
  lastTrick: ".last-trick-btn",
  hud: ".hud .chip",
  hudMore: ".hud-more-btn",
  toast: ".toast",
  pill: ".reconnect-banner, .away-pill",
  chat: ".chat-panel",
  sheet: ".leave-sheet, .chat-sheet, .sheet, .round-end, .hud-menu",
  botBanter: ".bot-banter",
  chatBubble: ".chat-bubble",
  clock: ".move-clock, .timer-ring",
};

/** Visible boxes of the key elements, in visual order, with what paints them. */
export async function boxes(page, extra = {}) {
  return page.evaluate((KEY) => {
    const vw = innerWidth, vh = innerHeight;
    const out = [];
    for (const [name, sel] of Object.entries(KEY)) {
      let i = 0;
      for (const el of document.querySelectorAll(sel)) {
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        // a box wholly off the screen is not on show
        if (r.right <= 0 || r.bottom <= 0 || r.left >= vw || r.top >= vh) continue;
        // an ancestor may hide it
        let hiddenBy = false;
        for (let p = el.parentElement; p; p = p.parentElement) {
          const pc = getComputedStyle(p);
          if (pc.display === "none" || pc.visibility === "hidden" || Number(pc.opacity) < 0.05) { hiddenBy = true; break; }
        }
        if (hiddenBy) continue;
        el.dataset.qa = `${name}#${i}`;
        out.push({ name, id: `${name}#${i++}`, x: r.left, y: r.top, w: r.width, h: r.height,
          text: (el.innerText || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").slice(0, 40) });
      }
    }
    return out;
  }, { ...KEY, ...extra });
}

const inter = (a, b) => {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? { w, h } : null;
};

/** Overlaps between key elements. A tag may sit on its own slot's cards and a
 *  panel holds its parts; a modal sheet covers the table on purpose. `slack` px of touch is fine. */
export async function overlaps(page, { ignore = [], slack = 3 } = {}) {
  const bs = await boxes(page);
  const pairs = [];
  for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) {
    const a = bs[i], b = bs[j];
    if (a.name === "sheet" || b.name === "sheet") continue;
    const o = inter(a, b);
    if (!o || o.w <= slack || o.h <= slack) continue;
    const pair = [a.name, b.name].sort().join("+");
    if (ignore.includes(pair)) continue;
    pairs.push({ pair, ia: a.id, ib: b.id, a: `${a.id} "${a.text}"`, b: `${b.id} "${b.text}"`, px: `${Math.round(o.w)}x${Math.round(o.h)}` });
  }
  if (!pairs.length) return [];
  const rel = await page.evaluate((ps) => ps.map(([ia, ib]) => {
    const ea = document.querySelector(`[data-qa="${ia}"]`), eb = document.querySelector(`[data-qa="${ib}"]`);
    if (!ea || !eb) return true;
    if (ea.contains(eb) || eb.contains(ea)) return true;
    const sa = ea.closest(".trick-play"), sb = eb.closest(".trick-play");
    return sa !== null && sa === sb;
  }), pairs.map((p) => [p.ia, p.ib]));
  return pairs.filter((_, i) => !rel[i]).map(({ pair, a, b, px }) => ({ pair, a, b, px }));
}

/** Key elements cut by the screen edge, or below the keyboard line. */
export async function clipped(page, { only = null } = {}) {
  const bs = await boxes(page);
  const { vw, vh, kb } = await page.evaluate(() => ({ vw: innerWidth, vh: innerHeight, kb: window.__qa?.kb ?? 0 }));
  const out = [];
  for (const b of bs) {
    if (only && !only.includes(b.name)) continue;
    if (b.name === "hand" || b.name === "sheet") continue; // scrollers and backdrops reach the edges
    const cut = [];
    if (b.x < -1) cut.push(`left ${Math.round(-b.x)}`);
    if (b.y < -1) cut.push(`top ${Math.round(-b.y)}`);
    if (b.x + b.w > vw + 1) cut.push(`right ${Math.round(b.x + b.w - vw)}`);
    if (b.y + b.h > vh - kb + 1) cut.push(`${kb ? "under keyboard" : "bottom"} ${Math.round(b.y + b.h - (vh - kb))}`);
    if (cut.length) out.push({ id: b.id, text: b.text, cut: cut.join(", ") });
  }
  return out;
}

/** Inside `rootSel`: children that paint outside the root's box, and whether the root is opaque. */
export async function contained(page, rootSel) {
  return page.evaluate((sel) => {
    const root = document.querySelector(sel);
    if (!root) return { missing: true };
    const rr = root.getBoundingClientRect();
    const bg = getComputedStyle(root).backgroundColor;
    const m = bg.match(/rgba?\(([^)]+)\)/);
    const parts = m ? m[1].split(/[, /]+/).map(Number) : [];
    const alpha = parts.length >= 4 ? parts[3] : bg === "transparent" ? 0 : 1;
    const spill = [];
    for (const el of root.querySelectorAll("button, input, textarea, a, [role=button], li, p, h1, h2, h3, span")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      // clipped away by a scroller inside the root: not painted, so not a spill
      let clip = false;
      for (let p = el.parentElement; p; p = p.parentElement) {
        const o = getComputedStyle(p);
        if (/(hidden|auto|scroll|clip)/.test(o.overflowX + o.overflowY)) {
          const pr = p.getBoundingClientRect();
          if (r.bottom <= pr.top + 1 || r.top >= pr.bottom - 1 || r.right <= pr.left + 1 || r.left >= pr.right - 1) { clip = true; break; }
          if (r.bottom > pr.bottom + 1 || r.top < pr.top - 1 || r.right > pr.right + 1 || r.left < pr.left - 1) { clip = "part"; }
        }
        if (p === root) break;
      }
      if (clip === true) continue;
      if (clip !== "part" && (r.bottom > rr.bottom + 1 || r.top < rr.top - 1 || r.right > rr.right + 1 || r.left < rr.left - 1)) {
        spill.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${(el.innerText || el.value || "").slice(0, 20)}"`);
      }
    }
    return { box: { x: rr.left, y: rr.top, w: rr.width, h: rr.height }, alpha, spill: [...new Set(spill)].slice(0, 8) };
  }, rootSel);
}

/** Text that is cut without an ellipsis, or a page that scrolls sideways. */
export async function textCuts(page) {
  return page.evaluate(() => {
    const out = [];
    if (document.documentElement.scrollWidth > innerWidth + 1) out.push(`page scrolls sideways: ${document.documentElement.scrollWidth} > ${innerWidth}`);
    for (const el of document.querySelectorAll("body *")) {
      if (el.children.length || !el.textContent.trim()) continue;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || cs.display === "inline") continue;
      if (el.closest("[aria-hidden=true], .sr-only")) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 2 || r.height <= 2) continue; // 1px boxes are screen-reader text
      if (el.scrollWidth > el.clientWidth + 1 && cs.overflowX !== "visible" && cs.textOverflow !== "ellipsis" && !/(auto|scroll)/.test(cs.overflowX)) {
        out.push(`cut without ellipsis: ${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${el.textContent.trim().slice(0, 30)}"`);
      }
    }
    return [...new Set(out)].slice(0, 12);
  });
}

/** Buttons a finger cannot hit well (under 40 px in either direction), on touch devices. */
export async function smallTargets(page, min = 40) {
  return page.evaluate((min) => {
    const out = [];
    for (const el of document.querySelectorAll("button, a[href], [role=button], input, [role=switch], [role=tab]")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || el.disabled) continue;
      if (el.closest(".hand")) continue; // cards overlap by design
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > innerHeight) continue;
      if (r.width < min || r.height < min) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${(el.innerText || el.getAttribute("aria-label") || "").slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
    return [...new Set(out)];
  }, min);
}

export const state = (page) => page.evaluate(() => window.__qa.state);

/** Poll `fn` (run in the page) until truthy. */
export async function until(page, fn, { timeout = 20000, arg = undefined, every = 150 } = {}) {
  const t0 = Date.now();
  for (;;) {
    const v = await page.evaluate(fn, arg).catch(() => null);
    if (v) return v;
    if (Date.now() - t0 > timeout) return null;
    await sleep(every);
  }
}

/** Collects checks; a check with violations fails and keeps one screenshot. */
export class Report {
  /** `partial`: only some checks ran (a filter was given), so an unmatched known issue proves nothing. */
  constructor(suite, { partial = false } = {}) {
    this.suite = suite; this.rows = []; this.t0 = Date.now(); this.partial = partial;
    // Open findings the suite already fails on: [{ suite, match, why }]. A known failure does not
    // fail the run; a known entry that no longer fails does, so the list only ever shrinks.
    const file = path.join(HERE, "known.json");
    this.known = (fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : [])
      .filter((k) => k.suite === suite).map((k) => ({ ...k, re: new RegExp(k.match), hits: 0 }));
  }
  async check(id, violations, page = null) {
    const bad = (Array.isArray(violations) ? violations : violations ? [violations] : []).filter(Boolean);
    const row = { id, ok: bad.length === 0, violations: bad };
    if (!row.ok && !process.env.NO_KNOWN) {
      // every violation must be a known one: a new problem beside an old one still fails
      const ks = bad.map((v) => this.known.find((k) => k.re.test(`${id} ${typeof v === "string" ? v : JSON.stringify(v)}`)));
      if (ks.every(Boolean)) { for (const k of ks) k.hits++; row.known = [...new Set(ks.map((k) => k.why))].join("; "); }
    }
    if (!row.ok && !row.known && page) row.shot = await shot(page, `FAIL_${this.suite}_${id}`.replace(/[^\w.-]+/g, "_")).catch(() => null);
    this.rows.push(row);
    if (!row.ok && !row.known) console.log(`FAIL ${id}\n  ${bad.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join("\n  ")}`);
    else if (process.env.VERBOSE) console.log(`${row.ok ? "ok   " : "known"} ${id}`);
    return row.ok;
  }
  /** Writes the JSON report and returns the process exit code. */
  done() {
    const failed = this.rows.filter((r) => !r.ok && !r.known);
    const known = this.rows.filter((r) => r.known);
    const stale = this.partial || process.env.NO_KNOWN ? [] : this.known.filter((k) => k.hits === 0);
    for (const k of stale) console.log(`FIXED? known issue no longer fails, remove it from e2e/known.json: ${k.match} (${k.why})`);
    const file = path.join(OUT, `${this.suite}.json`);
    fs.writeFileSync(file, JSON.stringify({ suite: this.suite, seconds: (Date.now() - this.t0) / 1000, checks: this.rows.length, failed: failed.length, known: known.length, stale: stale.map((k) => k.match), rows: this.rows }, null, 1));
    console.log(`\n${this.suite}: ${this.rows.length} checks, ${failed.length} failed, ${known.length} known, ${((Date.now() - this.t0) / 1000).toFixed(0)} s -> ${file}`);
    return failed.length || stale.length ? 1 : 0;
  }
}

/** Whether `sel` (a Playwright selector) is wholly on show: inside the screen and above the keyboard.
 *  Returns a violation or null. */
export async function onShow(page, sel, label = sel) {
  const loc = page.locator(sel).first();
  if (!(await loc.count())) return `${label}: not in the page`;
  const r = await loc.boundingBox();
  if (!r || r.width < 1 || r.height < 1) return `${label}: has no size`;
  const { vw, vh, kb } = await page.evaluate(() => ({ vw: innerWidth, vh: innerHeight, kb: window.__qa?.kb ?? 0 }));
  const bottom = vh - kb;
  // a toolbar floating over the top of the page (Mobile Safari, sideways) hides what is under it
  const top = kb ? (page.qa.d.safe?.t ?? 0) : 0;
  if (r.y < top - 1) return `${label}: ${Math.round(top - r.y)}px under the browser's toolbar`;
  if (r.y < -1 || r.x < -1 || r.x + r.width > vw + 1) return `${label}: off the screen (${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)})`;
  if (r.y + r.height > bottom + 1) return `${label}: ${Math.round(r.y + r.height - bottom)}px ${kb ? "behind the keyboard" : "below the screen"}`;
  // on the screen, but is something else painted over its middle?
  const over = await loc.evaluate((el) => {
    const b = el.getBoundingClientRect();
    const top = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    if (!top || top === el || el.contains(top) || top.contains(el) || top.id === "__qa_kb") return null;
    return `${top.tagName.toLowerCase()}.${[...top.classList].join(".")}`;
  });
  if (over) return `${label}: covered by ${over}`;
  return null;
}

/** Text fields iOS would zoom into on focus (font under 16px). */
export async function zoomingInputs(page) {
  return page.evaluate(() => [...document.querySelectorAll("input, textarea, select")]
    .filter((e) => e.type !== "checkbox" && e.type !== "radio" && e.getBoundingClientRect().width > 0 && parseFloat(getComputedStyle(e).fontSize) < 16)
    .map((e) => `iOS zooms on focus: ${e.tagName.toLowerCase()}.${[...e.classList].join(".")} font ${getComputedStyle(e).fontSize}`));
}

/** One named scenario: a thrown error is a failed check, not a dead suite. */
export async function scenario(rep, name, page, fn) {
  const t0 = Date.now();
  try { await fn(); } catch (e) { await rep.check(`${name}: crashed`, String(e?.message ?? e).split("\n")[0].slice(0, 300), page); }
  if (page?.qa?.errors.length) await rep.check(`${name}: page errors`, page.qa.errors.splice(0), page);
  console.log(`-- ${name} (${((Date.now() - t0) / 1000).toFixed(1)} s)`);
}

/** overlaps + clipped + textCuts in one visit to the page (the matrix calls this a thousand times). */
export async function lint(page, { slack = 3 } = {}) {
  return page.evaluate(([KEY, slack]) => {
    const vw = innerWidth, vh = innerHeight, kb = window.__qa?.kb ?? 0;
    const shown = (el) => {
      for (let p = el; p; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) return false;
      }
      return true;
    };
    const bs = [];
    for (const [name, sel] of Object.entries(KEY)) {
      let i = 0;
      for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1 || r.right <= 0 || r.bottom <= 0 || r.left >= vw || r.top >= vh) continue;
        if (!shown(el)) continue;
        bs.push({ el, name, id: `${name}#${i++}`, x: r.left, y: r.top, w: r.width, h: r.height,
          text: (el.innerText || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").slice(0, 40) });
      }
    }
    const out = [];
    for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) {
      const a = bs[i], b = bs[j];
      if (a.name === "sheet" || b.name === "sheet") continue;
      const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (w <= slack || h <= slack) continue;
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const sa = a.el.closest(".trick-play"), sb = b.el.closest(".trick-play");
      if (sa !== null && sa === sb) continue;
      out.push({ pair: [a.name, b.name].sort().join("+"), a: `${a.id} "${a.text}"`, b: `${b.id} "${b.text}"`, px: `${Math.round(w)}x${Math.round(h)}` });
    }
    for (const b of bs) {
      if (b.name === "hand" || b.name === "sheet") continue;
      const cut = [];
      if (b.x < -1) cut.push(`left ${Math.round(-b.x)}`);
      if (b.y < -1) cut.push(`top ${Math.round(-b.y)}`);
      if (b.x + b.w > vw + 1) cut.push(`right ${Math.round(b.x + b.w - vw)}`);
      if (b.y + b.h > vh - kb + 1) cut.push(`${kb ? "under keyboard" : "bottom"} ${Math.round(b.y + b.h - (vh - kb))}`);
      if (cut.length) out.push({ id: b.id, text: b.text, cut: cut.join(", ") });
    }
    if (document.documentElement.scrollWidth > vw + 1) out.push(`page scrolls sideways: ${document.documentElement.scrollWidth} > ${vw}`);
    const cuts = new Set();
    for (const el of document.querySelectorAll("body *")) {
      if (el.children.length || !el.textContent.trim()) continue;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || cs.display === "inline") continue;
      if (el.scrollWidth <= el.clientWidth + 1 || cs.overflowX === "visible" || cs.textOverflow === "ellipsis" || /(auto|scroll)/.test(cs.overflowX)) continue;
      if (el.closest("[aria-hidden=true], .sr-only")) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 2 || r.height <= 2) continue;
      cuts.add(`cut without ellipsis: ${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${el.textContent.trim().slice(0, 30)}"`);
    }
    return [...out, ...cuts].slice(0, 12);
  }, [KEY, slack]);
}

/** Wait until nothing on the page is mid-move (cards in flight, a sheet sliding): a box read
 *  during a flight is not a layout. Endless animations (a turn pulse) do not count. */
export async function settled(page, timeout = 2500) {
  const t0 = Date.now();
  for (;;) {
    const moving = await page.evaluate(() => document.getAnimations().filter((a) =>
      a.playState === "running" && Number.isFinite(a.effect?.getComputedTiming().endTime ?? Infinity)).length).catch(() => 0);
    if (!moving) return true;
    if (Date.now() - t0 > timeout) return false;
    await sleep(60);
  }
}
