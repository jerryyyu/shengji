import fs from "node:fs";
import { launch, DEVICES, sleep } from "../lib.mjs";
import { mockApi } from "./demo.mjs";
import { fakeSocketScript, base, push } from "../fake.mjs";
const HERE = new URL(".", import.meta.url).pathname;
const INJECT = fs.readFileSync(HERE + "../inject.js", "utf8");
export const OUT = "/Users/jerryyu/.claude/jobs/d0498cda/tmp/zh_mocks/raw/";
const SERVER = "http://127.0.0.1:8000/";
const NATIVE = (nearby) => `(() => {
  const L = (window.__nbL = {});
  const emit = (window.__nbEmit = (ev, payload) => { for (const f of L[ev] ?? []) f(payload); });
  let role = null;
  const relay = (m) => { try { window.__nbRelay?.(m); } catch {} };
  const NB = {
    capabilities: () => Promise.resolve(${nearby} ? { beta: true } : {}),
    addListener: (ev, fn) => { (L[ev] ??= []).push(fn); return { remove() { L[ev] = (L[ev] ?? []).filter((g) => g !== fn); } }; },
    host: () => { role = "host"; return Promise.resolve({}); },
    join: () => { role = "join"; setTimeout(() => { relay({ ev: "peer", payload: { peer: "p1", state: "connected", device: "iPhone" } }); emit("peer", { peer: "host", state: "connected", via: "wifi" }); }, 150); return Promise.resolve({}); },
    send: ({ text }) => { relay({ ev: "message", payload: role === "host" ? { peer: "host", text } : { peer: "p1", text } }); return Promise.resolve({}); },
    close: () => Promise.resolve({}), stop: () => Promise.resolve({}), openSettings: () => Promise.resolve({}),
  };
  window.Capacitor = { isNativePlatform: () => true, isPluginAvailable: () => true,
    registerPlugin: (name) => name === "ShengjiNearby" ? NB : new Proxy({}, { get: (_, m) => (...a) => {
      if (name === "ShengjiShell" && m === "idiom") return Promise.resolve({ idiom: "phone" });
      if (m === "addListener") return Promise.resolve({ remove() {} });
      return Promise.resolve(undefined); } }) };
})();`;

export async function page(browser, device, lang, { url = "", storage = {}, fake = null, signedIn = false, nearby = false, scheme = "dark" } = {}) {
  const d = DEVICES[device];
  const ctx = await browser.newContext({ viewport: { width: d.w, height: d.h }, deviceScaleFactor: 2, colorScheme: scheme, hasTouch: true, isMobile: true, reducedMotion: "reduce", locale: lang === "zh" ? "zh-CN" : "en-US" });
  await mockApi(ctx, { signedIn });
  const p = await ctx.newPage();
  p.setDefaultTimeout(8000);
  p.on("pageerror", (e) => console.error("pageerror", e.message));
  const st = { "shengji.muted": "1", "shengji.name": "Cheerful Tractor", "shengji.nameChosen": "1", "shengji.telemetry.seen": "1", ...storage };
  await p.addInitScript(`for (const [k, v] of Object.entries(${JSON.stringify(st)})) { try { if (localStorage.getItem(k) === null) localStorage.setItem(k, v); } catch {} }`);
  await p.addInitScript(INJECT);
  await p.addInitScript(NATIVE(nearby));
  if (nearby) await p.addInitScript(`(() => { let x = 12345; const r = () => { x = (x * 1103515245 + 12345) % 2147483648; return x / 2147483648; };
    Math.random = r; const g = crypto.getRandomValues.bind(crypto); crypto.getRandomValues = (b) => { for (let i = 0; i < b.length; i++) b[i] = Math.floor(r() * 256); return b; }; })();`);
  if (fake) await p.addInitScript(fake);
  if (lang === "zh") {
    await p.addInitScript({ path: HERE + "zh_strings.js" });
    await p.addInitScript({ path: HERE + "zh_apply.js" });
  }
  await p.goto(SERVER + url);
  return p;
}

/** Every visible text node and labelled attribute, for the string table. */
export function dump(p) {
  return p.evaluate(() => {
    const out = new Set();
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) { const t = n.nodeValue.trim(); if (t && n.parentElement && n.parentElement.offsetParent !== null || (t && n.parentElement?.closest("dialog,[role=dialog]"))) if (t) out.add(t); }
    for (const e of document.querySelectorAll("[aria-label],[title],[placeholder]")) for (const a of ["aria-label", "title", "placeholder"]) { const v = e.getAttribute(a); if (v) out.add(`@${a}:${v}`); }
    return [...out];
  });
}
export function overflow(p) {
  return p.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => {
    if (!e.offsetParent || e.children.length > 2) return false;
    const t = e.textContent.trim(); if (!t) return false;
    return e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== "visible" || /…$/.test(t) && t.length > 3;
  }).map((e) => `${e.className || e.tagName}: ${e.textContent.trim().slice(0, 40)}`));
}
export async function snap(p, name, lang, strings) {
  await sleep(400);
  strings["__overflow__" + name] = await overflow(p);
  await p.screenshot({ path: `${OUT}${name}_${lang}.png` });
  strings[name] = await dump(p);
}
