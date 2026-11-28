// The table's pop-ups in the iOS Simulator's own WebKit, which paints what
// Chromium and Playwright's WebKit do not always paint the same way (a menu
// hanging outside a clipping header is left undrawn there, while its rows
// take taps). It serves web/dist with a scripted socket and stubbed reads,
// opens it in the simulator's Mobile Safari, visits Play, Collection, Me, the
// watch screen and a table against bots, opens each ⋯ menu, and takes a
// simulator screenshot of every state. A menu is reported invisible when the
// screenshot's pixels where the page says the menu stands did not change
// between the closed and the open state.
//   node scripts/ios_sim_smoke.mjs [--dist web/dist] [--out dir] [--udid <udid>] [--orient portrait,left,right]
// Needs Xcode's simctl and no signing. A landscape orientation needs a
// command that turns the simulator, given as SIM_ROTATE ("<cmd> {udid} {orientation}",
// orientation 1 portrait, 3 landscape left, 4 landscape right); without it
// landscape runs are reported as skipped, never as passed.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { base, fakeSocketScript } from "../e2e/fake.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.dirname(HERE);
// the PNG codec playwright-core already ships, by path: the package does not export it
const { PNG } = createRequire(import.meta.url)(path.join(WEB, "node_modules/playwright-core/lib/utilsBundle.js"));
const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt; };
const DIST = path.resolve(arg("dist", path.join(WEB, "dist")));
const OUT = path.resolve(arg("out", path.join(WEB, "e2e/out/ios-sim")));
const ORIENTS = arg("orient", "portrait,left,right").split(",");
const ORIENT_CODE = { portrait: 1, left: 3, right: 4 };
/** The share of the menu's pixels that must change when it opens. */
const DRAWN = 0.3;
fs.mkdirSync(OUT, { recursive: true });
if (!fs.existsSync(path.join(DIST, "index.html"))) { console.error(`no build at ${DIST}: run npm run build`); process.exit(2); }

const simctl = (...a) => execFileSync("xcrun", ["simctl", ...a], { encoding: "utf8" }).trim();
/** The smoke's own simulator, an iPhone 17 named shengji-smoke, made once and booted. */
function device() {
  const given = arg("udid", null);
  if (given) return given;
  const list = JSON.parse(simctl("list", "devices", "-j")).devices;
  const mine = Object.values(list).flat().find((d) => d.name === "shengji-smoke" && d.isAvailable);
  const udid = mine?.udid ?? simctl("create", "shengji-smoke", "com.apple.CoreSimulator.SimDeviceType.iPhone-17");
  if (mine?.state !== "Booted") { try { simctl("boot", udid); } catch { /* already booting */ } simctl("bootstatus", udid, "-b"); }
  return udid;
}

// the watch feed: a finished round from the replay fixture
const fixture = JSON.parse(fs.readFileSync(path.join(WEB, "src/replay/server-round-finished.fixture.json"), "utf8"));
const NAMES = ["Srig", "Bot 1", "Alice", "Bot 3"];
const events = fixture.events.map((e) => { const c = { ...e }; delete c.room; return c; });
events[0] = { ...events[0], players: events[0].players.map((p) => ({ seat: p.seat, name: NAMES[p.seat], is_bot: p.seat !== 0 })) };
const live = { table: "a1b2c3d4", watcher: "f".repeat(32), mode: "ranked", live_round: 2, code: null, rerun: false, waiting: false,
  round: 1, seat: events.find((e) => e.e === "trump").banker, players: NAMES, finished: true, events };
const presence = { type: "presence", tables: 1, playing: 1, waiting: 0, ranked: 1, casual: 0, watch: 1, rerun: true };

/** Runs in the page: walks the states, asking the server for a screenshot of each. */
const DRIVER = `(() => {
  try { localStorage.setItem("shengji.coach", "off"); localStorage.setItem("shengji.muted", "1"); localStorage.setItem("shengji.name", "Smoke"); localStorage.setItem("shengji.automated", "1"); } catch {}
  const TABLE = ${JSON.stringify(base())};
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const until = async (sel, ms = 8000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { const e = document.querySelector(sel); if (e) return e; await sleep(100); } throw new Error("no " + sel); };
  const shot = (name, extra = {}) => fetch("/__smoke/shot", { method: "POST", body: JSON.stringify({ name, ...extra }) }).then((r) => r.json());
  const box = (el) => { const b = el.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; };
  async function menu(name, button) {
    await shot(name + "-closed");
    button.click();
    await sleep(700);
    const m = document.querySelector(".hud-menu[role=menu]");
    await shot(name + "-open", { menu: m ? box(m) : null });
    button.click();
    await sleep(500);
  }
  async function run() {
    await sleep(1500);
    // the page's own frame on the screen: a full-page magenta sheet, measured in the screenshot
    const cal = document.createElement("div");
    cal.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:#ff00ff";
    document.body.appendChild(cal);
    await sleep(400);
    await shot("calibrate", { calibrate: { w: innerWidth, h: innerHeight } });
    cal.remove();
    location.hash = "#/play"; await sleep(1200); await shot("play");
    location.hash = "#/collection"; await sleep(1200); await shot("collection");
    location.hash = "#/me"; await sleep(1200); await shot("me");
    location.hash = "#/play"; await sleep(1000);
    (await until(".play-presence-watch")).click();
    await until(".watch-tabs"); await sleep(1500);
    await shot("watch");
    await menu("watch-menu", await until('.watch-hud [aria-haspopup="menu"]'));
    window.__fake.push(TABLE);
    await until(".table-screen .hud-more-btn"); await sleep(1500);
    await shot("table");
    await menu("table-menu", document.querySelector(".table-screen:not(.watch-screen) .hud-more-btn"));
    await fetch("/__smoke/done", { method: "POST", body: "{}" });
  }
  window.addEventListener("load", () => run().catch((e) => fetch("/__smoke/done", { method: "POST", body: JSON.stringify({ error: String(e) }) })));
})();`;

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
  ".png": "image/png", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json", ".ico": "image/x-icon", ".mp3": "audio/mpeg" };

/** One orientation's run: resolves with its report once the driver says done. */
function serve(udid, orient) {
  return new Promise((resolve, reject) => {
    const report = { orient, shots: {}, menus: {} };
    let cal = null;
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://x");
      const json = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
      if (url.pathname === "/__smoke/driver.js") { res.writeHead(200, { "content-type": "text/javascript" }); res.end(fakeSocketScript([presence]) + DRIVER); return; }
      if (req.method === "POST" && url.pathname.startsWith("/__smoke/")) {
        let body = ""; req.on("data", (c) => { body += c; }); req.on("end", () => {
          const msg = JSON.parse(body || "{}");
          if (url.pathname === "/__smoke/done") { json(200, {}); server.close(); if (msg.error) reject(new Error(msg.error)); else resolve(report); return; }
          const file = path.join(OUT, `${orient}-${msg.name}.png`);
          simctl("io", udid, "screenshot", file);
          report.shots[msg.name] = file;
          if (msg.calibrate) cal = calibrate(file, msg.calibrate);
          if (msg.menu !== undefined) report.menus[msg.name.replace(/-open$/, "")] = judge(path.join(OUT, `${orient}-${msg.name.replace(/-open$/, "-closed")}.png`), file, msg.menu, cal);
          json(200, {});
        });
        return;
      }
      if (url.pathname === "/api/auth/config") return json(200, { google_client_id: null, device_accounts: false, collection: true });
      if (url.pathname.startsWith("/api/watch/")) return json(200, { ...live, waiting: true, events: undefined });
      if (url.pathname === "/api/watch") return json(200, live);
      if (url.pathname.startsWith("/api/")) return json(404, {});
      let p = path.join(DIST, decodeURIComponent(url.pathname));
      if (!p.startsWith(DIST) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) p = path.join(DIST, "index.html");
      let data = fs.readFileSync(p);
      if (p.endsWith("index.html")) data = Buffer.from(String(data).replace("<head>", '<head><script src="/__smoke/driver.js"></script>'));
      res.writeHead(200, { "content-type": TYPES[path.extname(p)] ?? "application/octet-stream", "cache-control": "no-store" });
      res.end(data);
    });
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      // a fresh page each run: a query the service worker and the cache have not seen
      simctl("openurl", udid, `http://127.0.0.1:${port}/?smoke=${orient}-${Date.now()}`);
    });
    setTimeout(() => { server.close(); reject(new Error("timed out after 120 s")); }, 120000).unref();
  });
}

/** The page's frame in the screenshot: the bounding box of the magenta sheet. */
function calibrate(file, page) {
  const png = PNG.sync.read(fs.readFileSync(file));
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
  for (let y = 0; y < png.height; y++) for (let x = 0; x < png.width; x++) {
    const i = (y * png.width + x) * 4;
    if (png.data[i] > 230 && png.data[i + 1] < 30 && png.data[i + 2] > 230) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  }
  if (x1 < 0) return null;
  return { x: x0, y: y0, sx: (x1 - x0 + 1) / page.w, sy: (y1 - y0 + 1) / page.h };
}

/** Whether the menu was drawn: the share of its pixels that changed when it opened. */
function judge(closedFile, openFile, menu, cal) {
  if (!menu) return { ok: false, why: "the page has no open menu" };
  if (!cal) return { ok: false, why: "the page's frame was not found on the screen" };
  const a = PNG.sync.read(fs.readFileSync(closedFile)), b = PNG.sync.read(fs.readFileSync(openFile));
  const X0 = Math.max(0, Math.round(cal.x + menu.x * cal.sx)), Y0 = Math.max(0, Math.round(cal.y + menu.y * cal.sy));
  const X1 = Math.min(a.width, Math.round(cal.x + (menu.x + menu.w) * cal.sx)), Y1 = Math.min(a.height, Math.round(cal.y + (menu.y + menu.h) * cal.sy));
  let n = 0, changed = 0;
  for (let y = Y0; y < Y1; y++) for (let x = X0; x < X1; x++) {
    const i = (y * a.width + x) * 4;
    n++;
    if (Math.abs(a.data[i] - b.data[i]) + Math.abs(a.data[i + 1] - b.data[i + 1]) + Math.abs(a.data[i + 2] - b.data[i + 2]) > 30) changed++;
  }
  const share = n ? changed / n : 0;
  return { ok: share >= DRAWN, share: Number(share.toFixed(3)), region: [X0, Y0, X1, Y1], why: share >= DRAWN ? null : "INVISIBLE: the screen under the menu did not change when it opened" };
}

const udid = device();
const rotate = process.env.SIM_ROTATE;
const results = [];
for (const orient of ORIENTS) {
  if (orient !== "portrait" && !rotate) { results.push({ orient, skipped: "no SIM_ROTATE command to turn the simulator" }); continue; }
  if (rotate) execFileSync("/bin/sh", ["-c", rotate.replace("{udid}", udid).replace("{orientation}", String(ORIENT_CODE[orient]))], { stdio: "inherit" });
  try { results.push(await serve(udid, orient)); } catch (e) { results.push({ orient, error: String(e.message ?? e) }); }
}
let bad = 0;
for (const r of results) {
  if (r.skipped) { console.log(`${r.orient}: SKIPPED (${r.skipped})`); continue; }
  if (r.error) { bad++; console.log(`${r.orient}: ERROR ${r.error}`); continue; }
  for (const [name, m] of Object.entries(r.menus)) {
    if (!m.ok) bad++;
    console.log(`${r.orient} ${name}: ${m.ok ? "drawn" : m.why}${m.share !== undefined ? ` (changed ${m.share})` : ""}`);
  }
}
fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify({ results }, null, 1));
console.log(`screenshots and report.json in ${OUT}`);
process.exit(bad ? 1 : 0);
