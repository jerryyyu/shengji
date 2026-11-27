// Companions through a real reconnect and a rejoin, against a real server
// whose Collection is on for everyone (COLLECTION_ENABLED=1) and which makes
// device accounts (SHENGJI_DEVICE_ACCOUNTS=1), so a player has a look of
// their own. The socket is dropped mid-walk, mid-special and mid-deal; the
// table is left and joined again by code; a Duo is left and taken back with
// Rejoin Duo; another account signs in on the same seat. After each, every
// companion must stand where it may, drawn once, with no jump on the way,
// no pose left running, and the page's timers, observers and listeners back
// at the count they had before.
//   BASE=<server> node e2e/companions.mjs [scenario-regex]
import { BASE, Report, launch, open, scenario, sleep, state, until } from "./lib.mjs";
import { act, playUntil, startWithBots, toTable } from "./drive.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const want = (name) => !only || only.test(name);
const rep = new Report("companions", { partial: !!only });
const browser = await launch();
const STORE = { "shengji.coach": "off", "shengji.muted": "1" };

/** Init script: live timers, observers and window/document listeners, and each
 *  figure's place every frame (a jump is a move faster than any walk). */
function probe() {
  const Q = (window.__cq = { timers: new Map(), obs: new Set(), listeners: new Set(), jumps: [], seen: {}, frames: 0 });
  const st = window.setTimeout, ct = window.clearTimeout, si = window.setInterval, ci = window.clearInterval;
  window.setTimeout = function (fn, ms, ...a) {
    const id = st.call(window, function () { Q.timers.delete(id); return typeof fn === "function" ? fn.apply(this, a) : undefined; }, ms);
    Q.timers.set(id, "t");
    return id;
  };
  window.clearTimeout = (id) => { Q.timers.delete(id); return ct.call(window, id); };
  window.setInterval = function (fn, ms, ...a) { const id = si.call(window, fn, ms, ...a); Q.timers.set(id, "i"); return id; };
  window.clearInterval = (id) => { Q.timers.delete(id); return ci.call(window, id); };
  for (const name of ["ResizeObserver", "MutationObserver", "IntersectionObserver"]) {
    const Real = window[name];
    if (!Real) continue;
    window[name] = class extends Real {
      observe(...a) { Q.obs.add(this); return super.observe(...a); }
      disconnect() { Q.obs.delete(this); return super.disconnect(); }
    };
  }
  const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
  const key = (t, type, fn, o) => (t === window || t === document ? [t === window ? "w" : "d", type, fn, typeof o === "boolean" ? o : !!o?.capture] : null);
  const ids = new WeakMap();
  let n = 0;
  const idOf = (fn) => { if (!fn || (typeof fn !== "function" && typeof fn !== "object")) return 0; if (!ids.has(fn)) ids.set(fn, ++n); return ids.get(fn); };
  EventTarget.prototype.addEventListener = function (type, fn, o) {
    const k = key(this, type, fn, o);
    if (k && !(typeof o === "object" && o?.once)) Q.listeners.add(`${k[0]}:${k[1]}:${idOf(k[2])}:${k[3]}`);
    return add.call(this, type, fn, o);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, o) {
    const k = key(this, type, fn, o);
    if (k) Q.listeners.delete(`${k[0]}:${k[1]}:${idOf(k[2])}:${k[3]}`);
    return remove.call(this, type, fn, o);
  };
  let last = 0;
  const loop = (t) => {
    Q.frames++;
    const dt = last ? t - last : 16;
    last = t;
    const now = {};
    for (const el of document.querySelectorAll(".table-companions .tc-seat")) {
      const seat = el.getAttribute("data-seat"), w = el.querySelector(".tc-walk");
      if (!w) continue;
      const r = w.getBoundingClientRect();
      now[seat] = [r.left, r.top, r.width];
      const was = Q.seen[seat];
      if (was) {
        const d = Math.hypot(r.left - was[0], r.top - was[1]);
        // the quickest walk (a hop-walk off cards) covers a figure's width or so in 0.3 s
        if (d > 8 && d / Math.max(dt, 8) > Math.max(0.6, (4 * r.width) / 1000)) Q.jumps.push({ t: Math.round(t), seat, d: Math.round(d), dt: Math.round(dt) });
      }
    }
    Q.seen = now;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

/** What the page holds now: the counts that must come back, and the figures as drawn. */
const snap = (page) => page.evaluate(() => {
  const Q = window.__cq;
  const seats = [...document.querySelectorAll(".table-companions .tc-seat")];
  const anims = document.getAnimations().filter((a) => a.effect?.target?.closest?.(".table-companions") && a.playState === "running");
  return {
    timers: Q.timers.size, intervals: [...Q.timers.values()].filter((v) => v === "i").length, obs: Q.obs.size, listeners: Q.listeners.size,
    figures: seats.map((s) => s.getAttribute("data-seat")), anims: anims.length,
    infinite: anims.filter((a) => a.effect.getTiming().iterations === Infinity).length,
    poses: seats.map((s) => s.querySelector(".tc-move")?.getAttribute("data-move") ?? "?"),
    looks: seats.map((s) => [...(s.querySelector("svg.cmp")?.classList ?? [])].find((c) => /^cmp-(tractor|bun|chick|sparrow|lamb|panda|rabbit|cat|fox|lion|dragon)$/.test(c)) ?? "?"),
  };
});

/** The lowest of each count over `ms` (a timer set and fired between samples is not a leak). */
async function floor(page, ms = 2400) {
  let low = null;
  for (let t = 0; t < ms; t += 300) {
    const s = await snap(page);
    low = low ? { ...s, timers: Math.min(low.timers, s.timers), intervals: Math.min(low.intervals, s.intervals), obs: Math.min(low.obs, s.obs),
      listeners: Math.min(low.listeners, s.listeners), anims: Math.min(low.anims, s.anims) } : s;
    await sleep(300);
  }
  return low;
}

/** Each figure clear of the cards, the hand, the nameplates, the buttons and the felt's edge. */
const placed = (page) => page.evaluate(() => {
  const out = [];
  const shown = (el) => { for (let p = el; p; p = p.parentElement) { const cs = getComputedStyle(p); if (cs.display === "none" || cs.visibility === "hidden") return false; } return true; };
  const felt = document.querySelector(".felt")?.getBoundingClientRect();
  const things = [".hand .hand-slot .card", ".opponent", ".trick-play .trick-cards", ".action-bar .btn", ".hud .hud-group button"]
    .flatMap((s) => [...document.querySelectorAll(s)].filter(shown).map((el) => [s, el.getBoundingClientRect()]));
  for (const seat of document.querySelectorAll(".table-companions .tc-seat")) {
    const svg = seat.querySelector("svg.cmp");
    if (!svg) continue;
    const a = svg.getBoundingClientRect();
    // the drawing's own square is larger than what it paints: a figure is held to its middle 80%
    const m = { left: a.left + a.width * 0.1, right: a.right - a.width * 0.1, top: a.top + a.height * 0.1, bottom: a.bottom - a.height * 0.05 };
    if (felt && (m.left < felt.left - 1 || m.right > felt.right + 1 || m.top < felt.top - 1 || m.bottom > felt.bottom + 1)) out.push(`seat ${seat.dataset.seat} off the felt`);
    for (const [s, b] of things) {
      const w = Math.min(m.right, b.right) - Math.max(m.left, b.left), h = Math.min(m.bottom, b.bottom) - Math.max(m.top, b.top);
      if (w > 3 && h > 3) { out.push(`seat ${seat.dataset.seat} over ${s} by ${Math.round(w)}x${Math.round(h)}`); break; }
    }
  }
  return out;
});

/** The checks after a disturbance, against `base` (taken at rest before it). */
async function after(rep, name, page, base, { people }) {
  await until(page, () => window.__qa.openSockets() === 1 && !document.querySelector(".reconnect-banner"), { timeout: 15000 });
  // every pose has ended: the longest special is 2.6 s, a level gained 1.7 s
  await sleep(3500);
  const s = await floor(page);
  const jumps = await page.evaluate(() => window.__cq.jumps.splice(0));
  const dup = s.figures.filter((x, i) => s.figures.indexOf(x) !== i);
  console.log(`   ${name}: ${JSON.stringify({ ...s, jumps: jumps.length })} base ${JSON.stringify({ timers: base.timers, intervals: base.intervals, obs: base.obs, listeners: base.listeners })}`);
  await rep.check(`${name}: one figure a person`, [dup.length ? `seats drawn twice: ${dup}` : null,
    s.figures.length !== people ? `${s.figures.length} figures for ${people} people` : null], page);
  await rep.check(`${name}: no jump`, jumps.map((j) => `seat ${j.seat} moved ${j.d} px in ${j.dt} ms`), page);
  await rep.check(`${name}: no pose left running`, [s.anims ? `${s.anims} companion animations still running` : null,
    s.infinite ? `${s.infinite} infinite companion animations` : null,
    ...s.poses.filter((p) => p === "react" || p === "levelup").map((p) => `a figure still in ${p}`)], page);
  await rep.check(`${name}: lands clear`, await placed(page), page);
  await rep.check(`${name}: counts back to the base`, [
    s.obs > base.obs ? `observers ${base.obs} -> ${s.obs}` : null,
    s.listeners > base.listeners ? `window/document listeners ${base.listeners} -> ${s.listeners}` : null,
    s.intervals > base.intervals ? `intervals ${base.intervals} -> ${s.intervals}` : null,
    s.timers > base.timers + 2 ? `timers ${base.timers} -> ${s.timers}` : null], page);
  return s;
}

/** Drop the socket (and the network) for `ms`, then bring both back. */
async function drop(page, ms) {
  await page.context().setOffline(true);
  await page.evaluate(() => window.__qa.drop(true));
  await sleep(ms);
  await page.evaluate(() => window.__qa.unblock());
  await page.context().setOffline(false);
}

/** A device account of its own with `look` in use: the iOS app's sign-in, made from the page. */
async function account(page, look) {
  const r = await page.evaluate(async (look) => {
    const made = await fetch("/api/auth/device", { method: "POST", headers: { "X-Shengji-Client": "ios-app", "content-type": "application/json" }, body: "{}" });
    if (!made.ok) return `device account: ${made.status}`;
    const put = await fetch("/api/me/look", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ look }) });
    return put.ok ? null : `look ${look}: ${put.status} ${await put.text()}`;
  }, look);
  await page.reload();
  await page.waitForSelector(".play-main");
  return r;
}

/** Tap clear felt until your companion walks; returns whether it did. */
async function tapWalk(page) {
  const f = await page.evaluate(() => { const r = document.querySelector(".felt").getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; });
  for (const [px, py] of [[0.3, 0.42], [0.7, 0.42], [0.35, 0.3], [0.65, 0.3], [0.5, 0.25]]) {
    const was = await page.evaluate(() => document.querySelector(".tc-mine")?.style.transform);
    await page.touchscreen.tap(f[0] + f[2] * px, f[1] + f[3] * py);
    await sleep(120);
    const walking = await page.evaluate((was) => {
      const w = document.querySelector(".tc-mine");
      return !!w && w.style.transform !== was && w.getAnimations().some((a) => a.playState === "running");
    }, was);
    if (walking) return true;
    await sleep(600);
  }
  return false;
}

const atRest = async (page) => { await sleep(3500); return floor(page); };

for (const device of ["phone-land", "phone-land-se"]) {
  if (!want(`solo-${device}`)) continue;
  const a = await open(browser, device, { storage: { ...STORE, "shengji.name": "Solo" }, setup: (p) => p.addInitScript(probe) });
  await scenario(rep, `solo-${device}`, a, async () => {
    await a.waitForSelector(".play-main");
    await rep.check(`solo-${device}: a device account with a look`, await account(a, "sparrow/tree"), a);
    await toTable(a, "casual");
    await a.evaluate(() => { window.__qa.state = null; });
    await startWithBots(a);
    // mid-deal
    const dealing = await until(a, () => window.__qa.state?.phase === "deal", { timeout: 15000 });
    const base0 = await snap(a);
    if (dealing) {
      await drop(a, 2500);
      await after(rep, `solo-${device} drop mid-deal`, a, base0, { people: 1 });
    } else await rep.check(`solo-${device}: saw the deal`, "no deal phase within 15 s", a);
    await playUntil(a, () => window.__qa.state?.phase === "play", { timeout: 60000 });
    for (let i = 0; i < 6; i++) { await act(a).catch(() => null); await sleep(300); }
    const base = await atRest(a);
    console.log(`   base ${JSON.stringify(base)}`);
    // the probe sees a jump: yours put 100 px over for two frames
    await a.evaluate(() => new Promise((r) => { const w = document.querySelector(".tc-mine"), was = w.style.transform;
      w.style.translate = "100px 0"; requestAnimationFrame(() => requestAnimationFrame(() => { w.style.translate = ""; void was; r(); })); }));
    await sleep(100);
    const seen = await a.evaluate(() => window.__cq.jumps.splice(0));
    await rep.check(`solo-${device}: the probe sees a 100 px jump`, seen.length >= 1 ? null : "no jump recorded", a);
    // mid-walk
    const walked = await tapWalk(a);
    await rep.check(`solo-${device}: a tap walks it`, walked ? null : "no walk from five taps on the felt", a);
    await sleep(250);
    await drop(a, 2500);
    await after(rep, `solo-${device} drop mid-walk`, a, base, { people: 1 });
    // mid-special
    await sleep(3200);
    const mine = await a.locator(".tc-mine").boundingBox().catch(() => null);
    if (mine) await a.touchscreen.tap(mine.x + mine.width / 2, mine.y + mine.height * 0.7);
    const special = await until(a, () => document.querySelector(".tc-mine .tc-move")?.getAttribute("data-move") === "react", { timeout: 1500, every: 50 });
    await rep.check(`solo-${device}: a tap on yours plays its special`, special ? null : "no special within 1.5 s of the tap", a);
    await sleep(400);
    await drop(a, 2500);
    await after(rep, `solo-${device} drop mid-special`, a, base, { people: 1 });
    // a long drop: past the away time, a bot holds the seat until we are back
    for (let i = 0; i < 4; i++) { await act(a).catch(() => null); await sleep(300); }
    await drop(a, 12000);
    await after(rep, `solo-${device} 12 s drop`, a, base, { people: 1 });
    // 20 drops in a row, a walk or a special before each
    for (let i = 0; i < 20; i++) {
      if (i % 2) await tapWalk(a);
      else { const b = await a.locator(".tc-mine").boundingBox().catch(() => null); if (b) await a.touchscreen.tap(b.x + b.width / 2, b.y + b.height * 0.7); }
      await sleep(200 + (i * 97) % 600);
      await drop(a, 800 + (i * 131) % 1200);
      await until(a, () => window.__qa.openSockets() === 1, { timeout: 15000 });
      await act(a).catch(() => null);
    }
    await after(rep, `solo-${device} 20 drops`, a, base, { people: 1 });
    // a reload mid-special: the page comes back to its seat and draws the table afresh
    const lookBefore = (await snap(a)).looks;
    const seatBefore = (await state(a))?.you;
    const b0 = await a.locator(".tc-mine").boundingBox().catch(() => null);
    if (b0) await a.touchscreen.tap(b0.x + b0.width / 2, b0.y + b0.height * 0.7);
    await sleep(400);
    await a.evaluate(() => { window.__qa.state = null; });
    await a.reload();
    await until(a, () => window.__qa.state !== null, { timeout: 20000 });
    const back = await after(rep, `solo-${device} reload mid-special`, a, base, { people: 1 });
    await rep.check(`solo-${device} reload mid-special: the same seat and look`, [(await state(a))?.you !== seatBefore ? `seat ${seatBefore} -> ${(await state(a))?.you}` : null,
      JSON.stringify(back.looks) === JSON.stringify(lookBefore) ? null : `${lookBefore} -> ${back.looks}`], a);
    // another account signs in on the same device and seat: the seat shows its look
    // (once a run: the server makes 5 device accounts an hour for one address)
    if (device !== "phone-land") return;
    await a.evaluate(async () => { await fetch("/api/auth/device", { method: "POST", headers: { "X-Shengji-Client": "ios-app", "content-type": "application/json" }, body: "{}" }); });
    await a.evaluate(async () => { await fetch("/api/me/look", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ look: "chick/yellow" }) }); });
    await a.evaluate(() => { window.__qa.state = null; });
    await a.reload();
    await until(a, () => window.__qa.state !== null, { timeout: 20000 });
    const sw = await after(rep, `solo-${device} account switch`, a, base, { people: 1 });
    const seat = await state(a);
    await rep.check(`solo-${device} account switch: the same seat, the new look`, [seat?.you !== seatBefore ? `seat ${seatBefore} -> ${seat?.you}` : null,
      JSON.stringify(sw.looks) !== JSON.stringify(["cmp-chick"]) ? `drawn ${sw.looks}` : null], a);
  });
  await a.context().close();
}

if (want("duo")) {
  const a = await open(browser, "phone-land", { storage: { ...STORE, "shengji.name": "Opener" }, setup: (p) => p.addInitScript(probe) });
  const b = await open(browser, "phone-land", { storage: { ...STORE, "shengji.name": "Partner" }, setup: (p) => p.addInitScript(probe) });
  await scenario(rep, "duo", a, async () => {
    await a.waitForSelector(".play-main");
    await b.waitForSelector(".play-main");
    await rep.check("duo: each player has an account with a look", [await account(a, "bun/plain"), await account(b, "sparrow/tree")], a);
    await a.click(".play-mode-opt:has-text('Casual')");
    await a.click(".play-duo");
    await a.waitForSelector(".tp-primary");
    const code = await until(a, () => window.__qa.last.queue_state?.code ?? null);
    await b.goto(`${BASE}?code=${code}`);
    await b.waitForSelector(".tp-primary");
    await b.click(".tp-primary");
    await until(a, () => (window.__qa.last.queue_state?.table?.seats ?? []).filter(Boolean).length === 2, { timeout: 15000 });
    await sleep(500);
    await a.click(".tp-primary");
    await b.click(".tp-primary").catch(() => {});
    await until(a, () => window.__qa.state?.phase === "play", { timeout: 60000 });
    for (let i = 0; i < 8; i++) { await act(a).catch(() => null); await act(b).catch(() => null); await sleep(250); }
    const baseA = await atRest(a), baseB = await floor(b);
    const seatA = (await state(a)).you;
    const lookA = baseB.looks[baseB.figures.indexOf(String(seatA))];
    console.log(`   duo base A ${JSON.stringify(baseA)} B ${JSON.stringify(baseB)}`);
    await rep.check("duo: both companions drawn on both screens", [baseA.figures.length !== 2 ? `A draws ${baseA.figures}` : null, baseB.figures.length !== 2 ? `B draws ${baseB.figures}` : null], a);
    // A's partner screen keeps playing while A leaves mid-special
    const mine = await a.locator(".tc-mine").boundingBox().catch(() => null);
    if (mine) await a.touchscreen.tap(mine.x + mine.width / 2, mine.y + mine.height * 0.7);
    await sleep(400);
    await a.click(".hud-more-btn"); await sleep(250);
    await a.click(".hud-menu-row.leave");
    await a.click(".leave-sheet-leave");
    await a.waitForSelector(".play-main", { timeout: 8000 });
    await sleep(1500);
    const gone = await snap(b);
    await rep.check("duo: a partner who left is drawn by no one (the bot plays the seat)", gone.figures.includes(String(seatA)) ? `B still draws seat ${seatA}` : null, b);
    const rejoin = a.locator(".play-main:has-text('Rejoin Duo')");
    await rep.check("duo: the Play tab offers Rejoin Duo", (await rejoin.count()) ? null : `Play reads ${JSON.stringify(await a.locator(".play-main").innerText().catch(() => "?"))}`, a);
    if (await rejoin.count()) {
      await a.evaluate(() => { window.__qa.state = null; });
      await rejoin.click();
      await until(a, () => window.__qa.state !== null && !window.__qa.state.joining_you, { timeout: 30000 });
      const backA = await after(rep, "duo rejoin (opener)", a, baseA, { people: 2 });
      const backB = await after(rep, "duo rejoin (partner's screen)", b, baseB, { people: 2 });
      await rep.check("duo rejoin: the same seat and the same look on both screens", [(await state(a)).you !== seatA ? `seat ${seatA} -> ${(await state(a)).you}` : null,
        backB.looks[backB.figures.indexOf(String(seatA))] !== lookA ? `B draws ${backB.looks} for ${backB.figures}, was ${lookA}` : null,
        JSON.stringify([...backA.looks].sort()) !== JSON.stringify([...baseA.looks].sort()) ? `A draws ${backA.looks}, was ${baseA.looks}` : null], a);
    }
    // the partner drops mid-walk while the opener plays on
    await tapWalk(b);
    await sleep(250);
    await drop(b, 2500);
    await after(rep, "duo partner drop mid-walk (partner)", b, baseB, { people: 2 });
    await after(rep, "duo partner drop mid-walk (opener's screen)", a, baseA, { people: 2 });
    // the partner leaves mid-walk and comes back by code
    const seatB = (await state(b)).you;
    await tapWalk(b);
    await b.click(".hud-more-btn"); await sleep(250);
    await b.click(".hud-menu-row.leave");
    await b.click(".leave-sheet-leave");
    await b.waitForSelector(".room-input", { timeout: 8000 });
    await sleep(1500);
    await b.evaluate(() => { window.__qa.state = null; });
    await b.fill(".room-input", code);
    await b.keyboard.press("Enter");
    const how = await until(b, () => (window.__qa.state ? "seated" : document.querySelector(".tp-primary") ? "panel" : null), { timeout: 10000 });
    if (how === "panel") await b.click(".tp-primary");
    await until(b, () => window.__qa.state !== null && !window.__qa.state.joining_you, { timeout: 90000 });
    const backB2 = await after(rep, "duo partner back by code (partner)", b, baseB, { people: 2 });
    const backA2 = await after(rep, "duo partner back by code (opener's screen)", a, baseA, { people: 2 });
    await rep.check("duo partner back by code: the same seat and look", [(await state(b)).you !== seatB ? `seat ${seatB} -> ${(await state(b)).you}` : null,
      backA2.looks[backA2.figures.indexOf(String(seatB))] !== baseA.looks[baseA.figures.indexOf(String(seatB))] ? `A draws ${backA2.looks} for ${backA2.figures}` : null,
      JSON.stringify([...backB2.looks].sort()) !== JSON.stringify([...baseB.looks].sort()) ? `B draws ${backB2.looks}, was ${baseB.looks}` : null], b);
  });
  await a.context().close();
  await b.context().close();
}

await browser.close();
process.exit(rep.done());
