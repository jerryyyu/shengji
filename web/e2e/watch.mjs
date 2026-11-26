// The watch screen's geometry, against a stubbed feed (no game server): the
// trick never covers a seat's name tag, the watcher's row (transport, tabs,
// kitty) or the LEAD / WINS labels, on the phones and the iPad, from every
// tab, with narrow and wide tricks; and the hand keeps its size when the bury
// ends.
//   node e2e/watch.mjs [device-regex]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Report, launch, open, scenario, shot, sleep } from "./lib.mjs";
import { fakeSocketScript } from "./fake.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const rep = new Report("watch", { partial: !!only });
const SHOTS = process.env.SHOTS ? new RegExp(process.env.SHOTS) : null;

const fixture = JSON.parse(fs.readFileSync(path.join(HERE, "../src/replay/server-round-finished.fixture.json"), "utf8"));
const NAMES = ["Srig", "Bot 1", "Bot 2", "Bot 3"];

/** The fixture's round, with `k` of its last single-card tricks folded into
 *  the first, so every seat plays 1 + k cards there (a wide trick). */
function events(k) {
  let ev = fixture.events.map((e) => { const c = { ...e }; delete c.room; return c; });
  ev[0] = { ...ev[0], players: ev[0].players.map((p) => ({ seat: p.seat, name: NAMES[p.seat], is_bot: p.seat !== 0 })) };
  if (k > 0) {
    const endI = ev.findIndex((e) => e.e === "round_end");
    const tail = ev.slice(endI - 5 * k, endI);
    const add = { 0: [], 1: [], 2: [], 3: [] };
    for (const e of tail) if (e.e === "play") add[e.seat].push(...e.cards);
    ev = [...ev.slice(0, endI - 5 * k), ...ev.slice(endI)];
    let n = 0;
    ev = ev.map((e) => {
      if (e.e === "play" && n < 4) { n++; return { ...e, cards: [...e.cards, ...add[e.seat]] }; }
      if (e.e === "trick" && n === 4) { n++; return { ...e, plays: e.plays.map((p) => ({ ...p, cards: [...p.cards, ...add[p.seat]] })) }; }
      return e;
    });
  }
  return ev;
}

function doc(k) {
  const ev = events(k);
  const banker = ev.find((e) => e.e === "trump").banker;
  return { table: "a1b2c3d4", watcher: "f".repeat(32), mode: "ranked", live_round: 2, code: null, rerun: false,
    waiting: false, round: 1, seat: banker, players: NAMES, finished: true, events: ev };
}

const presence = { type: "presence", tables: 1, playing: 1, waiting: 0, ranked: 1, casual: 0, watch: 1, rerun: true };

/** Every overlap of a trick card or a trick label with what must stay clear of it. */
const measure = (page) => page.evaluate(() => {
  const shown = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; };
  const pos = (e) => [...e.closest(".trick-play").classList].find((c) => c.startsWith("pos-"));
  const R = (e, name) => { const b = e.getBoundingClientRect(); return { name, x: b.left, y: b.top, r: b.right, b: b.bottom }; };
  const all = (sel, name) => [...document.querySelectorAll(sel)].filter(shown).map((e) => R(e, typeof name === "function" ? name(e) : name));
  const trick = [
    ...all(".trick-play:not(.declaration) .trick-cards .card", (e) => `trick ${pos(e)}`),
    ...all(".trick-tag > span", (e) => `${e.className} ${pos(e)}`),
  ];
  const clear = [
    ...all(".opponent .opp-name", (e) => `name tag ${[...e.closest(".opponent").classList].find((c) => c.startsWith("pos-"))}`),
    ...all(".watch-tabs", "tab strip"), ...all(".watch-controls", "transport"), ...all(".watch-kitty", "kitty"),
    ...all(".hud-bar .chip, .hud-more-btn", "top strip"),
  ];
  const out = [];
  for (const a of trick) for (const o of clear) {
    const w = Math.min(a.r, o.r) - Math.max(a.x, o.x), h = Math.min(a.b, o.b) - Math.max(a.y, o.y);
    if (w > 0.5 && h > 0.5) out.push(`${a.name} x ${o.name}: ${w.toFixed(1)} x ${h.toFixed(1)}`);
  }
  // the controls' 44px reach must not land on a neighbour's face
  const ctls = [...document.querySelectorAll(".watch-ctl")].filter(shown);
  for (let i = 0; i + 1 < ctls.length; i++) {
    const a = ctls[i].getBoundingClientRect(), b = ctls[i + 1].getBoundingClientRect();
    const reach = parseFloat(getComputedStyle(ctls[i], "::after").right) || 0;
    if (a.right - reach > b.left + 0.5) out.push(`${ctls[i].getAttribute("aria-label")} reaches over its neighbour`);
  }
  return [...new Set(out)];
});

const handWidth = (page) => page.evaluate(() => document.querySelector(".watch-hand .card")?.getBoundingClientRect().width ?? 0);

const browser = await launch();
for (const device of ["phone-land-max", "phone-land", "phone-land-se", "ipad11-land"]) {
  for (const k of [0, 3, 9]) {
    const name = `watch-${device}-${1 + k}c`;
    if (only && !only.test(name)) continue;
    const page = await open(browser, device, {
      storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
      fakeSocket: fakeSocketScript([presence]),
      setup: async (p) => {
        await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
        await p.route("**/api/watch/**", (r) => r.fulfill({ json: { ...doc(k), waiting: true, events: undefined } }));
        await p.route("**/api/watch?**", (r) => r.fulfill({ json: doc(k) }));
      },
    });
    await scenario(rep, name, page, async () => {
      await page.waitForSelector(".play-presence-watch");
      await page.click(".play-presence-watch");
      await page.waitForSelector(".watch-tabs");
      await page.click('button[aria-label="Pause"]');
      const bury = await handWidth(page);
      // the first trick, complete, with its LEAD and WINS labels
      await page.click('button[aria-label="Next trick"]');
      await page.click('button[aria-label="Next trick"]');
      await sleep(400);
      await rep.check(`${name}: the hand keeps its size when the bury ends`,
        Math.abs((await handWidth(page)) - bury) < 0.5 ? null : `card width ${bury} then ${await handWidth(page)}`, page);
      const tabs = await page.$$("[role=tab]");
      for (let i = 0; i < tabs.length; i++) {
        await tabs[i].click();
        await sleep(650);
        await rep.check(`${name} tab ${i}: the trick clears the name tags, the watcher's row and its labels`, await measure(page), page);
        if (SHOTS?.test(`${name}-tab${i}`)) await shot(page, `${name}-tab${i}`);
      }
    });
    await page.context().close();
  }
}
await browser.close();
process.exit(rep.done());
