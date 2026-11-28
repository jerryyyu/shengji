// Every pop-up the table opens from its header, its seats or its bar (the
// game's ⋯ menu, the watch screen's ⋯ menu, chat, a seat's full name) is
// drawn where nothing can cut it off: open, no box it sits in clips or
// scrolls on either axis, it lies inside the screen, and the point at the
// middle of each of its rows hits that row. iOS WebKit leaves a pop-up
// outside a clipping ancestor's box undrawn while Chromium and Playwright's
// WebKit draw it, so the clip itself is what this checks. In the iOS app
// sideways, the Dynamic Island's inset on the left and on the right, the
// phone turned once, with and without Reduce Motion.
//   node e2e/menus.mjs [name-regex]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Report, launch, open, scenario, sleep } from "./lib.mjs";
import { base, fakeSocketScript } from "./fake.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const rep = new Report("menus", { partial: !!only });

const fixture = JSON.parse(fs.readFileSync(path.join(HERE, "../src/replay/server-round-finished.fixture.json"), "utf8"));
const NAMES = ["Srig", "Bot 1", "Maximilian Featherst", "Bot 3"];
const watched = () => {
  const events = fixture.events.map((e) => { const c = { ...e }; delete c.room; return c; });
  events[0] = { ...events[0], players: events[0].players.map((p) => ({ seat: p.seat, name: NAMES[p.seat], is_bot: p.seat !== 0 })) };
  const banker = events.find((e) => e.e === "trump").banker;
  return { table: "a1b2c3d4", watcher: "f".repeat(32), mode: "ranked", live_round: 2, code: null, rerun: false,
    waiting: false, round: 1, seat: banker, players: NAMES, finished: true, events };
};
const presence = { type: "presence", tables: 1, playing: 1, waiting: 0, ranked: 1, casual: 0, watch: 1, rerun: true };

/** The violations of one open pop-up: hidden or clipped by an ancestor, off
 *  the screen, or a row that a tap at its middle would miss. */
const probe = (page, sel, rows) => page.evaluate(({ sel, rows }) => {
  const el = document.querySelector(sel);
  if (!el) return ["not open"];
  const out = [];
  const b = el.getBoundingClientRect();
  if (b.width < 1 || b.height < 1) out.push("has no size");
  const cs = getComputedStyle(el);
  if (cs.visibility !== "visible" || cs.display === "none") out.push(`not shown (${cs.display}, ${cs.visibility})`);
  // the root and the body pass their overflow to the viewport, which clips nothing on the screen
  for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
    const s = getComputedStyle(a);
    if (s.overflowX !== "visible" || s.overflowY !== "visible") {
      out.push(`inside ${a.tagName.toLowerCase()}.${[...a.classList].join(".")} (overflow ${s.overflowX} ${s.overflowY})`);
    }
  }
  if (b.left < -0.5 || b.top < -0.5 || b.right > innerWidth + 0.5 || b.bottom > innerHeight + 0.5) {
    out.push(`off the screen: ${b.left.toFixed(0)},${b.top.toFixed(0)} to ${b.right.toFixed(0)},${b.bottom.toFixed(0)} of ${innerWidth}x${innerHeight}`);
  }
  // the rows the pop-up itself shows (a long menu scrolls its own rows)
  const items = rows ? [...el.querySelectorAll(rows)] : [el];
  // a tooltip takes no taps: for the hit test it is made to, so the test reads what is drawn on top
  const pe = el.style.pointerEvents;
  if (!rows) el.style.pointerEvents = "auto";
  if (!items.length) out.push("no rows");
  for (const r of items) {
    const rb = r.getBoundingClientRect();
    const x = rb.left + rb.width / 2, y = rb.top + rb.height / 2;
    // a row its own pop-up has scrolled out of view, or under its sticky foot, is the pop-up's to show
    let shown = true;
    for (let s = r.parentElement; s && el.contains(s); s = s.parentElement) {
      const ss = getComputedStyle(s), sb = s.getBoundingClientRect();
      if ((ss.overflowX !== "visible" || ss.overflowY !== "visible") && (x < sb.left || x > sb.right || y < sb.top || y > sb.bottom)) shown = false;
    }
    const hit = document.elementFromPoint(x, y);
    if (!shown || (hit && hit !== r && !r.contains(hit) && el.contains(hit) && getComputedStyle(hit.closest("[role=menuitem], [role=menuitemcheckbox]") ?? hit).position === "sticky")) continue;
    if (!hit || !(r === hit || r.contains(hit))) out.push(`"${r.textContent.trim().slice(0, 24)}" under ${hit ? `${hit.tagName.toLowerCase()}.${[...hit.classList].join(".")}` : "nothing"}`);
  }
  el.style.pointerEvents = pe;
  return out;
}, { sel, rows });

const ROWS = "[role=menuitem], [role=menuitemcheckbox]";

/** The table's pop-ups, from a scripted table: each opened, probed, closed. */
async function table(page, name) {
  await page.waitForSelector(".table-screen .hud-more-btn", { timeout: 10000 });
  await page.tap(".hud-more-btn");
  await sleep(300);
  await rep.check(`${name}: the game's ⋯ menu`, await probe(page, ".hud-menu[role=menu]", ROWS), page);
  await page.keyboard.press("Escape");
  await sleep(300);
  await rep.check(`${name}: Escape closes the game's ⋯ menu`, await page.$(".hud-menu:not([aria-hidden])") ? "still open" : null, page);
  await page.tap(".chat-launch");
  await sleep(300);
  await rep.check(`${name}: chat`, await probe(page, ".chat-panel", ".chat-quick-btn, .chat-close"), page);
  await page.tap(".chat-panel .chat-close");
  await sleep(300);
  const seat = await page.locator(".opponent.pos-top .opp-name").boundingBox();
  await page.touchscreen.tap(seat.x + seat.width / 2, seat.y + seat.height / 2);
  await sleep(250);
  await rep.check(`${name}: a seat's full name`, await probe(page, ".opp-fullname", null), page);
}

const browser = await launch();
for (const device of ["phone-land", "phone-land-se"]) {
  for (const side of ["left", "right"]) {
    for (const still of [false, true]) {
      const insets = { t: 0, b: 21, l: side === "left" ? 59 : 0, r: side === "right" ? 59 : 0 };
      const tag = `${device}-${side}${still ? "-still" : ""}`;
      const turn = async (page) => {
        const { w, h } = page.qa.d;
        await page.setViewportSize({ width: h, height: w });
        await sleep(300);
        await page.setViewportSize({ width: w, height: h });
        await sleep(500);
      };
      if (!only || only.test(`table-${tag}`)) {
        const page = await open(browser, device, { native: true, insets, still,
          storage: { "shengji.coach": "off", "shengji.muted": "1" }, fakeSocket: fakeSocketScript([base()]) });
        await scenario(rep, `table-${tag}`, page, async () => {
          await page.waitForSelector(".table-screen", { timeout: 10000 });
          await turn(page);
          await table(page, `table-${tag}`);
        });
        await page.context().close();
      }
      if (!only || only.test(`watch-${tag}`)) {
        const live = watched();
        const page = await open(browser, device, { native: true, insets, still,
          storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.name": "Jerry" },
          fakeSocket: fakeSocketScript([presence]),
          setup: async (p) => {
            await p.route("**/api/**", (r) => r.fulfill({ status: 404, json: {} }));
            await p.route("**/api/watch/**", (r) => r.fulfill({ json: { ...live, waiting: true, events: undefined } }));
            await p.route("**/api/watch?**", (r) => r.fulfill({ json: live }));
          } });
        await scenario(rep, `watch-${tag}`, page, async () => {
          await page.waitForSelector(".play-presence-watch");
          await page.tap(".play-presence-watch");
          await page.waitForSelector(".watch-tabs");
          await turn(page);
          await page.tap('.watch-hud [aria-haspopup="menu"]');
          await sleep(300);
          await rep.check(`watch-${tag}: the watch ⋯ menu`, await probe(page, ".hud-menu[role=menu]", ROWS), page);
          await page.keyboard.press("Escape");
          await sleep(300);
          await rep.check(`watch-${tag}: Escape closes the watch ⋯ menu`, await page.$(".hud-menu") ? "still open" : null, page);
        });
        await page.context().close();
      }
    }
  }
}
await browser.close();
process.exit(rep.done());
