// The watch screen's geometry, against a stubbed feed (no game server): the
// trick never covers a seat's name tag, the watcher's row (transport, tabs,
// kitty) or the LEAD / WINS labels, on the phones and the iPad, from every
// tab, with narrow and wide tricks; and the hand keeps its size when the bury
// ends; a live table's menu stays as a tap left it while plays arrive; in the
// iOS app sideways the menu opens on top and Leave leaves, and the watcher's
// own companion stands in the safe area and walks to a tap; and a replay is
// left in one tap, by back or by Escape; Next table goes on to another table
// and back, or keeps the only one as it was; and a watcher who leaves and
// comes back counts once, even when it leaves before its first answer lands.
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
// one long name: the tabs shrink names rather than run off the row
const NAMES = ["Srig", "Bot 1", "Maximilian Featherst", "Bot 3"];

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

/** Each watcher control's tap reach as rendered: the height around its centre
 *  over which a tap lands on it (its extender included, unless clipped). */
const reach = (page) => page.evaluate(() => {
  const out = [];
  for (const el of document.querySelectorAll(".watch-ctl, [role=tab], .watch-kitty")) {
    const b = el.getBoundingClientRect();
    if (b.width === 0) continue;
    const x = b.left + b.width / 2, cy = b.top + b.height / 2;
    let up = 0, down = 0;
    while (up < 30 && el.contains(document.elementFromPoint(x, cy - up - 1))) up++;
    while (down < 30 && el.contains(document.elementFromPoint(x, cy + down + 1))) down++;
    const h = up + down + 1;
    if (h < 44) out.push(`${el.getAttribute("aria-label") ?? el.textContent.trim()} is tapped over ${h}px`);
  }
  return out;
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
      await rep.check(`${name}: every watcher control is tapped over at least 44px`, await reach(page), page);
      await rep.check(`${name}: the top strip is a pill, round at both ends`, await page.evaluate(() => {
        const strip = document.querySelector(".watch-hud .hud-bar > .hud-group:nth-child(2)");
        if (!strip) return "no top strip";
        const cs = getComputedStyle(strip);
        const h = strip.getBoundingClientRect().height;
        const r = (v) => Math.min(parseFloat(v) || 0, h / 2);
        const [tl, tr, br, bl] = [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius].map(r);
        return tl > 0 && tl === tr && tr === br && br === bl ? null : `radii ${[tl, tr, br, bl].map((x) => x.toFixed(1)).join(" ")} (height ${h.toFixed(1)})`;
      }), page);
      await rep.check(`${name}: the tab strip fits its row and the screen`, await page.evaluate(() => {
        const t = document.querySelector(".watch-tabs"), row = document.querySelector(".watch-tabs-row");
        const b = t.getBoundingClientRect(), r = row.getBoundingClientRect();
        return [t.scrollWidth > t.clientWidth + 1 ? `tabs overflow by ${t.scrollWidth - t.clientWidth}px` : null,
          b.left < r.left - 0.5 || b.right > r.right + 0.5 || b.right > innerWidth ? `tabs ${b.left.toFixed(0)}-${b.right.toFixed(0)} outside the row ${r.left.toFixed(0)}-${r.right.toFixed(0)}` : null];
      }), page);
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
// A live table's ⋯, tapped while the plays arrive: one tap opens it and it
// stays open across the plays, one more closes it and it stays closed.
for (const device of ["phone-land", "ipad11-land"]) {
  const name = `watch-menu-steady-${device}`;
  if (only && !only.test(name)) continue;
  const page = await open(browser, device, {
    storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
    fakeSocket: fakeSocketScript([presence]),
    setup: async (p) => {
      await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
      await p.route("**/api/watch/**", (r) => r.fulfill({ json: { ...doc(0), waiting: true, events: undefined } }));
      await p.route("**/api/watch?**", (r) => r.fulfill({ json: doc(0) }));
    },
  });
  await scenario(rep, name, page, async () => {
    await page.waitForSelector(".play-presence-watch");
    await page.tap(".play-presence-watch");
    await page.waitForSelector(".watch-tabs");
    // every change of the menu's state, and every play, from here on
    await page.evaluate(() => {
      const q = (window.__menu = { states: [], plays: 0 });
      const felt = document.querySelector(".felt");
      let html = felt.innerHTML;
      new MutationObserver(() => {
        const s = document.querySelector('.watch-hud [aria-haspopup="menu"]')?.getAttribute("aria-expanded") ?? "none";
        if (q.states[q.states.length - 1] !== s) q.states.push(s);
        if (felt.innerHTML !== html) { html = felt.innerHTML; q.plays++; }
      }).observe(document.querySelector(".watch-screen"), { subtree: true, childList: true, attributes: true, characterData: true });
    });
    const across = async (want) => {
      const t0 = await page.evaluate(() => { window.__menu.states = []; return window.__menu.plays; });
      for (let i = 0; i < 40 && (await page.evaluate(() => window.__menu.plays)) < t0 + 3; i++) await sleep(250);
      const q = await page.evaluate(() => window.__menu);
      const shown = await page.evaluate(() => document.querySelector(".watch-screen [role=menu]") !== null);
      return q.plays < t0 + 3 ? `only ${q.plays - t0} plays arrived`
        : q.states.some((s) => s !== String(want)) || shown !== want ? `menu went ${q.states.join(" > ")} (shown ${shown})` : null;
    };
    await rep.check(`${name}: closed across plays with no tap`, await across(false), page);
    await page.tap('.watch-hud [aria-haspopup="menu"]');
    await rep.check(`${name}: one tap opens it`, await page.evaluate(() => document.querySelector(".watch-screen [role=menu]") ? null : "not open"), page);
    await rep.check(`${name}: open across plays`, await across(true), page);
    await page.tap('.watch-hud [aria-haspopup="menu"]');
    await rep.check(`${name}: one tap closes it`, await page.evaluate(() => document.querySelector(".watch-screen [role=menu]") ? "still open" : null), page);
    await rep.check(`${name}: closed across plays after the tap`, await across(false), page);
    if (SHOTS?.test(name)) await shot(page, name);
  });
  await page.context().close();
}
// The iOS app sideways, the Dynamic Island's inset on the left and the right
// (it changes sides as the phone turns), the table turned once (portrait and
// back) and the plays arriving: one tap on ⋯ opens a menu that is on screen
// and on top where its rows are, Leave there lands on the Play tab; and the
// watcher's own companion stands inside the safe area, walks to a tap on the
// felt, and a tap on a watched player's companion walks it there instead of
// moving that player's.
for (const device of ["phone-land", "phone-land-se", "ipad11-land"]) {
  for (const side of ["left", "right"]) {
    const name = `watch-app-${side}-${device}`;
    if (only && !only.test(name)) continue;
    const insets = { t: 0, b: 21, l: side === "left" ? 59 : 0, r: side === "right" ? 59 : 0 };
    const live = { ...doc(0) };
    live.events = live.events.map((e, i) => (i === 0 ? { ...e, players: e.players.map((p) => (p.seat === 2 ? { ...p, is_bot: false, look: "bun/cream" } : p)) } : e));
    const page = await open(browser, device, {
      native: true, insets,
      storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
      fakeSocket: fakeSocketScript([presence]),
      setup: async (p) => {
        await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
        await p.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: null, device_accounts: false, collection: true } }));
        await p.route("**/api/watch/**", (r) => r.fulfill({ json: { ...live, waiting: true, events: undefined } }));
        await p.route("**/api/watch?**", (r) => r.fulfill({ json: live }));
      },
    });
    await scenario(rep, name, page, async () => {
      await page.waitForSelector(".play-presence-watch");
      await page.tap(".play-presence-watch");
      await page.waitForSelector(".watch-tabs");
      const { w, h } = page.qa.d;
      await page.setViewportSize({ width: h, height: w });
      await sleep(400);
      await page.setViewportSize({ width: w, height: h });
      await sleep(900);
      const own = '.table-companions .tc-seat[data-seat="-1"] .tc-move';
      const boxOf = (sel) => page.evaluate((s) => {
        const b = document.querySelector(s)?.getBoundingClientRect();
        return b ? { x: b.left, y: b.top, r: b.right, b: b.bottom } : null;
      }, sel);
      const start = await boxOf(own);
      await rep.check(`${name}: the watcher's companion stands inside the safe area, clear of the row and the top strip`, await page.evaluate(({ s, ins }) => {
        if (!s) return "no watcher companion";
        const out = [];
        if (s.x < ins.l || s.r > innerWidth - ins.r) out.push(`at ${s.x.toFixed(0)}-${s.r.toFixed(0)}, outside the safe area ${ins.l}-${innerWidth - ins.r}`);
        for (const sel of [".watch-controls", ".watch-tabs", ".watch-hud .hud-group .chip", ".hud-more-btn"]) {
          for (const e of document.querySelectorAll(sel)) {
            const b = e.getBoundingClientRect();
            if (Math.min(b.right, s.r) - Math.max(b.left, s.x) > 0.5 && Math.min(b.bottom, s.b) - Math.max(b.top, s.y) > 0.5) out.push(`over ${sel}`);
          }
        }
        return out;
      }, { s: start, ins: insets }), page);
      await page.tap('.watch-hud [aria-haspopup="menu"]');
      await sleep(250);
      await rep.check(`${name}: one tap on ⋯ opens the menu, on screen and on top`, await page.evaluate(() => {
        const rows = [...document.querySelectorAll(".watch-screen [role=menu] [role=menuitem]")];
        if (!rows.length) return "not open";
        return rows.map((r) => {
          const b = r.getBoundingClientRect();
          const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
          return b.right > innerWidth || b.left < 0 ? `${r.textContent} off screen` : r.contains(hit) ? null : `${r.textContent} under ${hit?.className}`;
        });
      }), page);
      await rep.check(`${name}: nothing runs past the screen`, await page.evaluate(() =>
        document.documentElement.scrollWidth > innerWidth ? `page ${document.documentElement.scrollWidth}px wide` : null), page);
      // the header the menu opens under clips nothing: iOS WebKit leaves a menu outside a clipped header undrawn
      await rep.check(`${name}: the menu's header clips nothing`, await page.evaluate(() => {
        const cs = getComputedStyle(document.querySelector(".watch-hud"));
        return cs.overflowX === "visible" && cs.overflowY === "visible" ? null : `overflow ${cs.overflowX} ${cs.overflowY}`;
      }), page);
      await page.tap('.watch-hud [aria-haspopup="menu"]');
      await sleep(600);
      // a tap on empty felt walks the watcher's own there
      const felt = await boxOf(".felt");
      const to = { x: Math.round(felt.x + (felt.r - felt.x) * 0.3), y: Math.round(felt.y + (felt.b - felt.y) * 0.3) };
      await page.touchscreen.tap(to.x, to.y);
      await sleep(3600);
      const walked = await boxOf(own);
      // to the clear spot nearest the tap: a seat's figure or plate may stand on the tap itself
      const off = (f) => Math.hypot((f.x + f.r) / 2 - to.x, f.b - to.y);
      await rep.check(`${name}: a tap on the felt walks the watcher's companion there`,
        walked && start && off(walked) < 120 && off(walked) < off(start) - 40 ? null
          : `tap ${to.x},${to.y}, figure ${JSON.stringify(start)} then ${JSON.stringify(walked)}`, page);
      const theirs = '.table-companions .tc-seat[data-seat="2"] .tc-move';
      const before = await boxOf(theirs);
      if (before) {
        await page.touchscreen.tap(Math.round((before.x + before.r) / 2), Math.round((before.y + before.b) / 2));
        await sleep(250);
        await rep.check(`${name}: a watched player's companion takes no tap`, await page.evaluate(() =>
          document.querySelector('.table-companions .tc-seat[data-seat="2"] .tc-move')?.getAttribute("data-move") === "react" ? "it played its special" : null), page);
      }
      await page.tap('.watch-hud [aria-haspopup="menu"]');
      await sleep(250);
      await page.tap('.watch-screen [role=menu] .leave');
      const back = await page.waitForSelector(".play-presence-watch", { timeout: 3000 }).then(() => true, () => false);
      await rep.check(`${name}: Leave lands on the Play tab`, back && !(await page.$(".watch-screen")) ? null : "still watching", page);
      if (SHOTS?.test(name)) await shot(page, name);
    });
    await page.context().close();
  }
}
// Next table and the watcher count against a stub that keeps the server's
// rules: Next goes on from the skipped table in a fixed order and wraps
// (staying put only with one table), a request with no token mints one, a
// leave drops that token. Two tables: Next reaches the other and comes back,
// and the bottom seat is each table's banker every time; one table: Next keeps
// the round where it was. Then watch, leave, watch again: a count of 1.
for (const tables of [["a1b2c3d4", "e5f6a7b8"], ["a1b2c3d4"]]) {
  const device = "phone-land";
  const name = `watch-next-${tables.length}-tables-${device}`;
  if (only && !only.test(name)) continue;
  const counted = new Map(tables.map((t) => [t, new Set()]));
  let minted = 0;
  const docOf = (table, w) => {
    for (const set of counted.values()) set.delete(w);
    counted.get(table).add(w);
    const i = tables.indexOf(table);
    return { ...doc(0), table, watcher: w, round: 1 + i, live_round: 2 + i, watchers: counted.get(table).size };
  };
  const page = await open(browser, device, {
    storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
    fakeSocket: fakeSocketScript([presence]),
    setup: async (p) => {
      await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
      await p.route("**/api/watch/**", (r) => {
        const u = new URL(r.request().url());
        const [, , , table, act] = u.pathname.split("/");
        const w = u.searchParams.get("w");
        if (act === "leave") { counted.get(table)?.delete(w); return r.fulfill({ status: 204, body: "" }); }
        return r.fulfill({ json: { ...docOf(table, w), waiting: true, events: undefined } });
      });
      await p.route("**/api/watch?**", (r) => {
        const u = new URL(r.request().url());
        const skip = u.searchParams.get("skip");
        const w = u.searchParams.get("w") || `${String(++minted).padStart(4, "0")}${"c".repeat(28)}`;
        const table = skip && tables.includes(skip) ? tables[(tables.indexOf(skip) + 1) % tables.length] : tables[0];
        return r.fulfill({ json: docOf(table, w) });
      });
    },
  });
  await scenario(rep, name, page, async () => {
    // the round label, without the watcher count before it
    const strip = () => page.evaluate(() => {
      const c = document.querySelector(".watch-round")?.cloneNode(true);
      c?.querySelector(".watch-count")?.remove();
      return c?.textContent ?? "";
    });
    const bottom = () => page.evaluate(() => document.querySelector("[role=tab][aria-selected=true]")?.textContent ?? "");
    const next = async () => {
      await page.click('.watch-hud [aria-haspopup="menu"]');
      await page.click(".watch-screen [role=menu] [role=menuitem]:first-child");
      await sleep(700);
    };
    await page.waitForSelector(".play-presence-watch");
    await page.click(".play-presence-watch");
    await page.waitForSelector(".watch-tabs");
    await page.click('button[aria-label="Pause"]');
    const first = { strip: await strip(), seat: await bottom() };
    const seen = [];
    for (let i = 0; i < 3; i++) {
      if (tables.length === 1) {
        await page.click('button[aria-label="Next trick"]');
        await page.click("[role=tab]:nth-child(2)");
      }
      const before = { strip: await strip(), seat: await bottom(),
        felt: await page.evaluate(() => document.querySelector(".felt").innerHTML) };
      await next();
      const after = { strip: await strip(), seat: await bottom(),
        felt: await page.evaluate(() => document.querySelector(".felt").innerHTML) };
      seen.push(after.strip);
      if (tables.length === 1) {
        await rep.check(`${name}: Next ${i + 1} keeps the only table as it was`,
          after.strip === before.strip && after.seat === before.seat && after.felt === before.felt ? null
            : `${JSON.stringify(before.strip)} ${before.seat} then ${JSON.stringify(after.strip)} ${after.seat}`, page);
      } else {
        await rep.check(`${name}: Next ${i + 1} lands behind that table's banker`,
          after.seat === first.seat ? null : `${after.seat}, not ${first.seat}`, page);
      }
    }
    if (tables.length > 1) {
      await rep.check(`${name}: Next goes to the other table and back, never the same one twice running`,
        JSON.stringify([first.strip, ...seen]) === JSON.stringify(["Round 1 · previous round", "Round 2 · previous round",
          "Round 1 · previous round", "Round 2 · previous round"])
          ? null : `strips ${JSON.stringify([first.strip, ...seen])}`, page);
    }
    // watch, leave, watch again: one watcher
    const count = () => page.evaluate(() => document.querySelector(".watch-count")?.textContent ?? "none");
    await page.click('.watch-hud [aria-haspopup="menu"]');
    await page.click(".watch-screen [role=menu] .leave");
    await page.waitForSelector(".play-presence-watch");
    await sleep(300);
    const left = [...counted.values()].reduce((n, s) => n + s.size, 0);
    await page.click(".play-presence-watch");
    await page.waitForSelector(".watch-tabs");
    await rep.check(`${name}: leaving stops the count, and watching again counts 1`,
      left === 0 && (await count()) === "1" && minted === 0 ? null
        : `after leaving ${left} counted, then the eye says ${await count()}, ${minted} tokens minted for reads with none`, page);
    if (SHOTS?.test(name)) await shot(page, name);
  });
  await page.context().close();
}
// The count against a stub that counts by token as the server answers (and
// mints one for a read with none): Leave from the loading screen while the
// first pick's answer is held, the answer then lands, and the table counts
// nobody; a fresh tab left and opened again before that answer counts one;
// and a replay's end that finds a live table, left during the round end card,
// counts nobody.
for (const how of ["loading", "reopen", "replay-end"]) {
  const device = "phone-land";
  const name = `watch-count-${how}-${device}`;
  if (only && !only.test(name)) continue;
  const counted = new Set();
  let minted = 0, reads = 0;
  let release = null;
  const held = new Promise((r) => { release = r; });
  const page = await open(browser, device, {
    storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
    fakeSocket: fakeSocketScript([presence]),
    setup: async (p) => {
      await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
      await p.route("**/api/watch/**", (r) => {
        const u = new URL(r.request().url());
        const w = u.searchParams.get("w");
        if (u.pathname.endsWith("/leave")) { counted.delete(w); return r.fulfill({ status: 204, body: "" }); }
        counted.add(w);
        return r.fulfill({ json: { ...doc(0), watcher: w, waiting: true, events: undefined, watchers: counted.size } });
      });
      await p.route("**/api/watch?**", async (r) => {
        const u = new URL(r.request().url());
        const w = u.searchParams.get("w") || `${String(++minted).padStart(4, "0")}${"c".repeat(28)}`;
        const n = ++reads;
        if (how === "replay-end" && n === 1) return r.fulfill({ json: { ...doc(0), rerun: true, live_round: null, watcher: w } });
        counted.add(w);                    // counted as the server answers
        if (how !== "replay-end" && n === 1) await held;
        await r.fulfill({ json: { ...doc(0), watcher: w, watchers: counted.size } }).catch(() => {});
      });
    },
  });
  await scenario(rep, name, page, async () => {
    await page.waitForSelector(".play-presence-watch");
    await page.click(".play-presence-watch");
    if (how === "replay-end") {
      await page.waitForSelector(".watch-tabs");
      await page.click('button[aria-label="Pause"]');
      for (let i = 0; i < 40 && await page.$('button[aria-label="Next trick"]:not([disabled])'); i++) {
        await page.click('button[aria-label="Next trick"]');
      }
      for (let i = 0; i < 30 && reads < 2; i++) await sleep(100);
      await page.keyboard.press("Escape");   // the card closes first
      await page.click('.watch-hud button[aria-label="Leave"]');
    } else {
      await page.waitForSelector(".watch-empty .btn");
      await page.click(".watch-empty .btn");
    }
    await page.waitForSelector(".play-presence-watch");
    if (how === "reopen") {
      await page.click(".play-presence-watch");
      await page.waitForSelector(".watch-tabs");
    }
    release();
    const want = how === "reopen" ? 1 : 0;
    for (let i = 0; i < 20 && counted.size !== want; i++) await sleep(100);
    await sleep(300);
    const eye = await page.evaluate(() => document.querySelector(".watch-count")?.textContent ?? "none");
    await rep.check(`${name}: the table counts ${want} for this one viewer`,
      counted.size === want && minted === 0 && (how !== "reopen" || eye === "1") ? null
        : `${counted.size} counted, eye ${eye}, ${minted} tokens minted for reads with none`, page);
  });
  await page.context().close();
}
// A replay's top right is one Leave control: a tap, the browser's back or
// Escape each land on the Play tab with its presence line.
for (const device of ["phone-land", "ipad11-land"]) {
  for (const how of ["tap", "back", "escape"]) {
    const name = `watch-leave-${how}-${device}`;
    if (only && !only.test(name)) continue;
    const replay = { ...doc(0), rerun: true };
    const page = await open(browser, device, {
      storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
      fakeSocket: fakeSocketScript([presence]),
      setup: async (p) => {
        await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
        await p.route("**/api/watch?**", (r) => r.fulfill({ json: replay }));
      },
    });
    await scenario(rep, name, page, async () => {
      await page.waitForSelector(".play-presence-watch");
      await page.click(".play-presence-watch");
      await page.waitForSelector(".watch-tabs");
      await rep.check(`${name}: no menu, one Leave control`, await page.evaluate(() =>
        document.querySelector(".watch-hud [aria-haspopup=menu]") ? "a menu button is drawn"
          : document.querySelector('.watch-hud button[aria-label="Leave"]') ? null : "no Leave control"), page);
      if (how === "tap") await page.click('.watch-hud button[aria-label="Leave"]');
      else if (how === "back") await page.goBack();
      else await page.keyboard.press("Escape");
      const back = await page.waitForSelector(".play-presence-watch", { timeout: 3000 }).then(() => true, () => false);
      await rep.check(`${name}: lands on the Play tab`, back && !(await page.$(".watch-screen")) ? null : "still watching", page);
      if (how === "back") {
        // forward opens the watch again, and back leaves it again
        await page.goForward();
        const again = await page.waitForSelector(".watch-tabs", { timeout: 3000 }).then(() => true, () => false);
        await rep.check(`${name}: forward opens the watch again`, again ? null : "no watch after forward", page);
        await page.goBack();
        const out = await page.waitForSelector(".play-presence-watch", { timeout: 3000 }).then(() => true, () => false);
        await rep.check(`${name}: back again lands on the Play tab`, out ? null : "still watching", page);
      }
      if (SHOTS?.test(name)) await shot(page, name);
    });
    await page.context().close();
  }
}

await browser.close();
process.exit(rep.done());
