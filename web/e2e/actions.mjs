// Your row lays out at every width as on the phone: the action (Play, Bury,
// the declare options) stands centred under the trick, with Clear to its
// right and your name, crown and the move timer to its left. In every state
// the row uses, nothing in it covers the hand, a seat or the trick.
//   node e2e/actions.mjs [device-regex] [state-regex]
import { Report, launch, lint, open, shot, sleep } from "./lib.mjs";
import { HAND25, LONG_NAMES, NAMES, base, fakeSocketScript, hand, plays, push } from "./fake.mjs";

const onlyDev = process.argv[2] ? new RegExp(process.argv[2]) : null;
const onlyState = process.argv[3] ? new RegExp(process.argv[3]) : null;
const SHOTS = process.env.SHOTS ? new RegExp(process.env.SHOTS) : null;

const dealt = { phase: "declare", banker: null, trump: null, turn: null, trick: null, attacker_points: 0, declare_deadline: 12 };
const ranked = (over, opts) => { const s = base({ matched: true, ranked: true, ...over }, opts); s.players[0].turn_deadline = 8; return s; };
// the most declarations one hand can offer at once: every suit's 2 alone and as a pair,
// and both jokers as pairs (no trump); and the five of a hand holding H2 H2 C2 C2 D2
const TWOS = ["H2", "H2", "C2", "C2", "D2", "D2", "S2", "S2", "LJ", "LJ", "BJ", "BJ"];
const REST = HAND25.filter((c) => !/2$|J$/.test(c));
const OPTS10 = [[1], [1, 2], [3], [3, 4], [5], [5, 6], [7], [7, 8], [9, 10], [11, 12]];
const OPTS5 = [[1], [1, 2], [3], [3, 4], [5]];
/** [id, frame, act]: `act(page)` runs after the frame (a card chosen, a refused Play tapped). */
const STATES = [
  ["play_lead", base({ banker: 0, turn: 0, trick: { leader: 0, plays: [] } }, { banker: 0 })],
  ["play_lead_chosen", base({ banker: 0, turn: 0, trick: { leader: 0, plays: [] } }, { banker: 0 }),
    (page) => page.locator(".hand .hand-slot .card").last().click()],
  ["play_follow", base({ turn: 0, trick: { leader: 1, plays: plays(1, 3, 1) } }, { banker: 1 })],
  ["play_follow_refused", base({ turn: 0, trick: { leader: 1, plays: plays(1, 3, 1) } }, { banker: 1 }),
    (page) => page.locator(".action-bar .play-wrap").click()],
  ["play_clock", ranked({ turn: 0, trick: { leader: 1, plays: plays(1, 3, 2) } }, { banker: 0 })],
  ["play_clock_chosen", ranked({ turn: 0, trick: { leader: 0, plays: [] } }, { banker: 0 }),
    (page) => page.locator(".hand .hand-slot .card").last().click()],
  // the widest name pill, crowned, with the clock beside it: it stays on the screen
  ["play_clock_long", ranked({ turn: 0, trick: { leader: 1, plays: plays(1, 3, 1) } }, { banker: 0, names: [LONG_NAMES[1], ...NAMES.slice(1)] })],
  ["play_waiting", base({ turn: 2, trick: { leader: 1, plays: plays(1, 1, 1) } }, { banker: 0 })],
  ["play_wide", base({ turn: 0, trick: { leader: 1, plays: plays(1, 3, 6) } }, { banker: 1 })],
  ["deal_open", base({ ...dealt, phase: "deal", hand: hand(HAND25.slice(0, 14)), declare_options: [[12], [13]] }, { banker: null })],
  ["declare_open", base({ ...dealt, declare_options: [[18], [24]] }, { banker: null })],
  ["declare_five", base({ ...dealt, hand: hand(["H2", "H2", "C2", "C2", "D2", ...REST]), declare_options: OPTS5 }, { banker: null })],
  ["declare_ten", base({ ...dealt, hand: hand([...TWOS, ...REST]), declare_options: OPTS10 }, { banker: null })],
  ["deal_ten", base({ ...dealt, phase: "deal", hand: hand([...TWOS, ...REST.slice(0, 6)]), declare_options: OPTS10 }, { banker: null })],
  ["declare_by1", base({ ...dealt, declare_options: [[18]], current_declaration: { seat: 1, cards: ["H2"] }, passed: [1] }, { banker: null })],
  ["declare_passed", base({ ...dealt, passed: [0, 1, 3] }, { banker: null })],
  ["bury_me", base({ phase: "bury", banker: 0, turn: 0, trick: null, attacker_points: 0, hand: hand([...HAND25, "S7", "S10", "H5", "H9", "D3", "DK", "C6", "LJ"]) }, { banker: 0 })],
  ["bury_other", base({ phase: "bury", banker: 1, turn: 1, trick: null, attacker_points: 0 }, { banker: 1 })],
].filter(([id]) => !onlyState || onlyState.test(id));

/** Whether your row is the phone's declare row scrolled sideways: the phone, the deal or the declare
 *  window, horizontal scrolling on (overflow-x auto or scroll) and the controls really wider than the
 *  row. Only then may a declare control sit past a side edge until scrolled. One predicate for the row
 *  checks and the lint, so neither excuses a control the player cannot scroll to. */
function phoneDeclareRowScrolls(page) {
  return page.evaluate(() => {
    const bar = document.querySelector(".you-row .action-bar");
    if (!bar || !document.documentElement.classList.contains("phone-landscape")) return false;
    if (!document.querySelector(".table-screen.phase-deal, .table-screen.phase-declare")) return false;
    return ["auto", "scroll"].includes(getComputedStyle(bar).overflowX) && bar.scrollWidth > bar.clientWidth + 1;
  });
}

/** The action's centre against the table's: Play or Bury (Clear, the points and the
 *  timer stand beside it), otherwise the whole bar; and the row's parts clear of the
 *  hand's cards, the seats and the trick. */
function rowChecks(page, scrolls) {
  return page.evaluate((scrolls) => {
    const out = [];
    const shown = (el) => {
      if (!el) return false;
      for (let p = el; p; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) return false;
      }
      const r = el.getBoundingClientRect();
      return r.width >= 1 && r.height >= 1;
    };
    const felt = document.querySelector(".felt").getBoundingClientRect();
    const mid = felt.left + felt.width / 2;
    const bar = document.querySelector(".you-row .action-bar");
    // the phone centres Bury and the coach's points together; the wider tables centre Bury
    const phone = document.documentElement.classList.contains("phone-landscape");
    const play = bar?.querySelector(phone ? ".play-wrap" : ".play-wrap, .bury-btn");
    const parts = bar ? [...bar.querySelectorAll(".btn, .timer-ring")].filter(shown) : [];
    let anchor = null;
    if (shown(play)) anchor = play.getBoundingClientRect();
    else if (parts.length) {
      const rs = [...bar.children].filter(shown).map((c) => c.getBoundingClientRect());
      const b = bar.getBoundingClientRect();
      // the bar's own box: its ::before label ("Declare") is part of the row
      const l = Math.min(b.left, ...rs.map((r) => r.left)), rr = Math.max(b.right, ...rs.map((r) => r.right));
      anchor = { left: l, right: rr, width: rr - l };
    }
    // the phone's declare row scrolled sideways ("safe center") starts at its left edge, its far controls
    // off the screen until scrolled: only centring and initial visibility are relaxed then
    if (anchor && !scrolls) {
      const dx = anchor.left + anchor.width / 2 - mid;
      if (Math.abs(dx) > 8) out.push(`the action's centre is ${Math.round(dx)}px off the table's centre (${Math.round(anchor.left)}..${Math.round(anchor.right)} vs ${Math.round(mid)})`);
    }
    // every control in the row takes a tap at its centre, whole on the screen
    for (const p of parts) {
      if (!p.matches(".btn")) continue;
      const r = p.getBoundingClientRect();
      const off = r.left < 0 || r.right > innerWidth || r.top < 0 || r.bottom > innerHeight;
      if (off && scrolls && bar.contains(p) && r.top >= 0 && r.bottom <= innerHeight) continue;
      if (off) { out.push(`"${p.textContent.trim()}" leaves the screen (${Math.round(r.left)}..${Math.round(r.right)})`); continue; }
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const takes = hit && (p.contains(hit) || hit.contains(p));
      if (!takes) out.push(`"${p.textContent.trim()}" is covered at its centre by ${hit ? hit.className || hit.tagName : "nothing"}`);
    }
    const tag = document.querySelector(".you-row .you-tagline");
    // off the phone your name pill shows, whole, with some of your name in it
    if (!document.documentElement.classList.contains("phone-landscape") && tag) {
      const t = tag.getBoundingClientRect(), n = tag.querySelector(".you-name")?.getBoundingClientRect();
      if (!n || n.width < 1) out.push(`your name is ${n ? n.width.toFixed(1) : "not"} px wide`);
      if (t.left < 0 || t.right > innerWidth) out.push(`your name pill leaves the screen (${Math.round(t.left)}..${Math.round(t.right)})`);
    }
    const rowParts = [...parts, ...(shown(tag) ? [tag] : [])];
    const others = [
      ...[...document.querySelectorAll(".hand .hand-slot .card")].map((el) => ["hand card", el]),
      ...[...document.querySelectorAll(".opponent")].map((el) => ["seat", el]),
      ...[...document.querySelectorAll(".trick-play .trick-cards, .trick-play .trick-tag > *")].map((el) => ["trick", el]),
      ...[...document.querySelectorAll(".hand-line")].map((el) => ["hand line", el]),
    ].filter(([, el]) => shown(el));
    for (const p of rowParts) {
      const a = p.getBoundingClientRect();
      for (const [kind, el] of others) {
        const b = el.getBoundingClientRect();
        const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (w > 2 && h > 2) { out.push(`${p.className.split(" ")[0]} "${p.textContent.trim().slice(0, 20)}" covers a ${kind} by ${Math.round(w)}x${Math.round(h)}`); break; }
      }
    }
    return out;
  }, scrolls);
}

/** A guest the server shows the Collection to, so the table draws companions. */
async function companions(page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: null, device_accounts: false, collection: true } }));
}

/** Your companion is drawn, and neither it nor its "You" tag covers your row, the hint or the hand. */
function companionClear(page) {
  return page.evaluate(() => {
    const mine = document.querySelector(".tc-mine");
    if (!mine) return ["your companion is not drawn"];
    const a = mine.getBoundingClientRect();
    if (a.width < 1) return [];
    const out = [];
    for (const el of document.querySelectorAll(".you-row .btn, .you-row .timer-ring, .you-row .you-tagline, .hand-line, .hand .hand-slot .card")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      const b = el.getBoundingClientRect();
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 2 && h > 2) { out.push(`your companion covers ${el.className.split(" ")[0]} "${el.textContent.trim().slice(0, 20)}" by ${Math.round(w)}x${Math.round(h)}`); break; }
    }
    return out;
  });
}

/** The row checks and the lint, with one exemption: on the phone's scrolled declare row a declare
 *  control's sideways cut. */
async function rowAndLint(page) {
  const scrolls = await phoneDeclareRowScrolls(page);
  const linted = (await lint(page)).filter((v) => !(scrolls && v && v.cut && /^action#/.test(v.id) && /^(left|right) \d+(, (left|right) \d+)?$/.test(v.cut)));
  return [...await rowChecks(page, scrolls), ...linted];
}

/** A negative control: the last declare option pushed past the screen's right edge, on a row that does
 *  not scroll, must fail the row checks. Returns a violation when it passes. */
async function offscreenOptionFails(page) {
  const moved = await page.evaluate(() => {
    const el = [...document.querySelectorAll(".you-row .action-bar .btn.gold")].pop();
    if (!el) return false;
    el.dataset.qaMoved = el.style.marginLeft;
    el.style.marginLeft = `${innerWidth * 2}px`;
    return el.getBoundingClientRect().left > innerWidth;
  });
  if (!moved) return ["the negative control could not move the last declare option off the screen"];
  await sleep(50);
  const bad = await rowAndLint(page);
  await page.evaluate(() => {
    const el = [...document.querySelectorAll(".you-row .action-bar .btn.gold")].pop();
    el.style.marginLeft = el.dataset.qaMoved ?? ""; delete el.dataset.qaMoved;
  });
  return bad.length ? [] : ["an offscreen declare option passed the row checks"];
}

/** The last declare option (Pass, in the declare window, stands after it), scrolled into view if its row overflows, takes a tap and sends that declaration. */
async function lastOptionDelivers(page, ids) {
  const btn = page.locator(".you-row .action-bar .btn.gold").last();
  if (!(await btn.count())) return ["no declare option is drawn"];
  await btn.scrollIntoViewIfNeeded();
  const out = await page.evaluate(() => {
    const el = [...document.querySelectorAll(".you-row .action-bar .btn.gold")].pop();
    const r = el.getBoundingClientRect();
    if (r.left < 0 || r.right > innerWidth) return [`the last declare option is off the screen after scrolling (${Math.round(r.left)}..${Math.round(r.right)})`];
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return hit && (el.contains(hit) || hit.contains(el)) ? [] : [`the last declare option is covered at its centre by ${hit ? hit.className || hit.tagName : "nothing"}`];
  });
  if (out.length) return out;
  const n = await page.evaluate(() => window.__fake.sent.length);
  await btn.click();
  await sleep(150);
  const sent = await page.evaluate((k) => window.__fake.sent.slice(k).filter((m) => m.type === "declare").map((m) => m.card_ids), n);
  return sent.length === 1 && JSON.stringify(sent[0]) === JSON.stringify(ids) ? [] : [`the last declare option sent ${JSON.stringify(sent)}, not ${JSON.stringify(ids)}`];
}

const devices = ["desktop", "desktop-1440", "desktop-1920", "desktop-1280x700", "ipad", "ipad11-land", "ipad11-port", "ipad-mini-land", "ipad-mini-port", "ipad13-land", "phone-land", "phone-land-se"]
  .filter((d) => !onlyDev || onlyDev.test(d));
const rep = new Report("actions", { partial: !!(onlyDev || onlyState) });
const browser = await launch();
async function runDevice(device) {
  // the third pass draws the companions: yours stands by your hand, clear of the row
  for (const pass of ["off", "on", "companions"]) {
    const coach = pass === "on" ? "on" : "off";
    const page = await open(browser, device, { storage: { "shengji.coach": coach, "shengji.muted": "1" }, fakeSocket: fakeSocketScript([STATES[0][1]]), still: true,
      setup: pass === "companions" ? companions : null });
    await page.waitForSelector(".table-screen", { timeout: 10000 });
    for (const [id, frame, act] of STATES) {
      // a clean slate: the last state's choice and hint go with a frame from another phase
      await push(page, base({ ...dealt }, { banker: null }));
      await sleep(60);
      await push(page, frame);
      await sleep(250);
      if (act) { await act(page); await sleep(250); }
      const name = `${device}_${pass === "off" ? "" : pass === "on" ? "coach_" : "companions_"}${id}`;
      await rep.check(name, [...await rowAndLint(page), ...(pass === "companions" ? await companionClear(page) : [])], page);
      if (SHOTS && SHOTS.test(name)) await shot(page, name);
      if (id === "deal_ten" && device === "desktop") await rep.check(`${name}_offscreen_option_fails`, await offscreenOptionFails(page), page);
      if (/^(deal|declare)_ten$/.test(id)) await rep.check(`${name}_last_option`, await lastOptionDelivers(page, OPTS10[OPTS10.length - 1]), page);
      if (page.qa.errors.length) await rep.check(`${name}_pageerror`, page.qa.errors.splice(0));
    }
    await page.context().close();
  }
}
// a few devices at a time: each is its own page, and the checks are independent
const lanes = Number(process.env.LANES ?? 3);
await Promise.all(Array.from({ length: lanes }, async () => { for (let d; (d = devices.shift()); ) await runDevice(d); }));
await browser.close();
process.exit(rep.done());
