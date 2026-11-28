/** The home felt at rest, timed: start `vite preview` on a build, then
 *   BASE=http://127.0.0.1:<port>/ LOOK=lamb/newyear node e2e/homePerf.mjs [label]
 * Chromium at 4x CPU throttling, phone portrait, the Play tab signed in with
 * LOOK worn (COMPANIONS=off switches companions off). After a 3 s settle it
 * records PERF_MS (default 20000) of frame intervals (requestAnimationFrame)
 * and a timeline trace, and prints one JSON line: frame interval median, p90
 * and p99, gaps of 25 ms or more, and script, style, layout and paint ms per
 * second of the main thread. Desktop Chromium, not a phone.
 */
import { launch, open, sleep } from "./lib.mjs";

const look = process.env.LOOK ?? "lamb/newyear";
const ms = Number(process.env.PERF_MS ?? 20000);
const label = process.argv[2] ?? "";
const user = { name: "Perf", email: "p@x", picture: null, display_name: null, name_shown: "Perf", rounds_played: 40, ranked_wins: 2,
  ranked_games: 30, look, companions: process.env.COMPANIONS ?? "individual", products: ["com.jerryyu.shengji.companion.lamb",
    "com.jerryyu.shengji.companion.panda"], features: { collection: true }, looks: [] };
const setup = async (page) => {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: "test.apps", device_accounts: false, collection: true } }));
  await page.route("**/api/me", (r) => r.fulfill({ json: user }));
};

const q = (a, p) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : NaN; };
const browser = await launch();
try {
  const page = await open(browser, "phone-port", { setup, storage: { "shengji.coach": "off", "shengji.muted": "1" } });
  await page.waitForSelector(".lobby-preview .lp-stage");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await sleep(3000);
  const events = [];
  cdp.on("Tracing.dataCollected", (e) => events.push(...e.value));
  const done = new Promise((r) => cdp.once("Tracing.tracingComplete", r));
  await cdp.send("Tracing.start", { categories: "devtools.timeline,disabled-by-default-devtools.timeline,blink.animations,devtools.timeline.async,disabled-by-default-devtools.timeline.frame", transferMode: "ReportEvents" });
  const gaps = await page.evaluate((ms) => new Promise((res) => {
    const out = [];
    let last = 0;
    const t0 = performance.now();
    const step = (t) => { if (last) out.push(t - last); last = t; if (t - t0 < ms) requestAnimationFrame(step); else res(out); };
    requestAnimationFrame(step);
  }), ms);
  await cdp.send("Tracing.end");
  await done;
  // the renderer's main thread: the thread its frames' layouts run on
  const main = events.find((e) => e.name === "Layout" || e.name === "UpdateLayoutTree");
  const onMain = events.filter((e) => main && e.pid === main.pid && e.tid === main.tid && e.ph === "X");
  const sum = (names) => onMain.filter((e) => names.includes(e.name)).reduce((s, e) => s + (e.dur ?? 0), 0) / 1000;
  const secs = ms / 1000;
  const per = (v) => Math.round((v / secs) * 10) / 10;
  const result = {
    label, look: user.companions === "off" ? "off" : look, frames: gaps.length,
    median: Math.round(q(gaps, 0.5) * 10) / 10, p90: Math.round(q(gaps, 0.9) * 10) / 10, p99: Math.round(q(gaps, 0.99) * 10) / 10,
    gaps25: gaps.filter((g) => g >= 25).length,
    scriptMsPerS: per(sum(["FunctionCall", "EvaluateScript", "RunMicrotasks"])),
    styleMsPerS: per(sum(["UpdateLayoutTree", "RecalculateStyles"])),
    layoutMsPerS: per(sum(["Layout"])),
    paintMsPerS: per(sum(["Paint", "PrePaint", "Layerize", "PaintImage", "UpdateLayer"])),
    errors: page.qa.errors,
  };
  // DUMP=1: the main thread's costliest event kinds, for finding what to fix
  if (process.env.DUMP) {
    const by = {};
    for (const e of onMain) { const b = (by[e.name] ??= { n: 0, ms: 0 }); b.n++; b.ms += (e.dur ?? 0) / 1000; }
    result.top = Object.entries(by).sort((a, b) => b[1].ms - a[1].ms).slice(0, 14).map(([k, v]) => `${k} n=${v.n} ${Math.round(v.ms)}ms`);
    const fns = {};
    for (const e of onMain.filter((x) => x.name === "FunctionCall" || x.name === "TimerFire" || x.name === "FireAnimationFrame")) {
      const d = e.args?.data ?? {};
      const k = `${e.name} ${d.functionName ?? ""} ${(d.url ?? "").split("/").pop()}:${d.lineNumber ?? ""}`;
      const b = (fns[k] ??= { n: 0, ms: 0 }); b.n++; b.ms += (e.dur ?? 0) / 1000;
    }
    // animations the compositor could not take, by reason (Chrome's own flags)
    const failed = {};
    for (const e of events.filter((x) => x.name === "Animation" && x.args?.data?.compositeFailed !== undefined)) {
      const k = `${e.args.data.compositeFailed} ${(e.args.data.unsupportedProperties ?? []).join(",")}`;
      failed[k] = (failed[k] ?? 0) + 1;
    }
    result.compositeFailed = failed;
    result.fns = Object.entries(fns).sort((a, b) => b[1].ms - a[1].ms).slice(0, 10).map(([k, v]) => `${k} n=${v.n} ${Math.round(v.ms)}ms`);
  }
  console.log(JSON.stringify(result, null, process.env.DUMP ? 1 : 0));
} finally {
  await browser.close();
}
