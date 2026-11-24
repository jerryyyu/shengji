// What a phone does to the page, against a scripted socket (no game server
// needed): the keyboard over the in-game chat, audio interrupted by iOS, the
// socket dying with cards chosen. These are the three ways the app broke on a
// real phone while every static screenshot looked fine.
//   node e2e/client.mjs [scenario-regex]
import fs from "node:fs";
import { Report, contained, keyboard, launch, onShow, open, overlaps, scenario, shot, sleep, until } from "./lib.mjs";
import { HAND25, base, fakeSocketScript, hand, plays, push } from "./fake.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const rep = new Report("client", { partial: !!only });

const browser = await launch();
const game = (over = {}, opt = {}) => base({ trick: { leader: 1, plays: plays(1, 1, 1) }, turn: 2, ...over }, { banker: 1, ...opt });
const chatLog = { type: "chat_history", room: "4N5Z", messages: [
  { id: 1, room: "4N5Z", seat: 2, name: "Alice", text: "Hi!", t: Date.now() / 1000 - 30 },
  { id: 2, room: "4N5Z", seat: 2, name: "Alice", text: "A longer line that wraps on a narrow panel so the log has two rows", t: Date.now() / 1000 - 20 }] };

// ---- chat with the keyboard up, both kinds of keyboard, both phones
for (const device of ["phone-land", "phone-land-app", "phone-land-safari", "phone-land-safari-short", "phone-land-se", "phone-port"]) {
  // each device with the keyboard it meets: the app's WebView shrinks, Safari's page does not
  // (the app never turns the table: it locks it sideways, so the turned table meets only Safari's)
  for (const mode of /safari|port/.test(device) ? ["safari"] : /app/.test(device) ? ["app"] : ["safari", "app"]) {
    const name = `chat-${device}-${mode}`;
    if (only && !only.test(name)) continue;
    const page = await open(browser, device, { storage: { "shengji.coach": "off", "shengji.muted": "1" }, fakeSocket: fakeSocketScript([game(), chatLog]) });
    await scenario(rep, name, page, async () => {
      await page.waitForSelector(".chat-launch");
      await page.click(".chat-launch");
      await page.waitForSelector(".chat-panel .chat-input input, .chat-panel .chat-input textarea");
      await sleep(350);
      const before = await contained(page, ".chat-panel");
      await rep.check(`${name}: open panel is one opaque box`, [before.alpha >= 0.99 ? null : `background alpha ${before.alpha}`, ...before.spill], page);
      await page.click(".chat-panel .chat-input input, .chat-panel .chat-input textarea");
      await keyboard(page, true, mode);
      const c = await contained(page, ".chat-panel");
      await rep.check(`${name}: opaque with the keyboard up`, c.alpha >= 0.99 ? null : `background alpha ${c.alpha}`, page);
      await rep.check(`${name}: nothing spills out of the panel`, c.spill, page);
      await rep.check(`${name}: panel, field, Send and Close above the keyboard`, [
        await onShow(page, ".chat-panel", "chat panel"),
        await onShow(page, ".chat-panel .chat-input input, .chat-panel .chat-input textarea", "chat field"),
        await onShow(page, ".chat-panel .chat-input .btn", "Send"),
        await onShow(page, ".chat-panel .chat-close", "Close")], page);
      await shot(page, name);
      await page.keyboard.type("gg");
      await page.click(".chat-panel .chat-input .btn");
      const sent = await page.evaluate(() => window.__fake.sent.some((m) => JSON.stringify(m).includes('"gg"')));
      await rep.check(`${name}: Send sends`, sent ? null : "no chat frame left the page", page);
      await keyboard(page, false, mode);
      await page.click(".chat-panel .chat-close");
      await sleep(300);
      await rep.check(`${name}: table back in place`, [...(await overlaps(page)), await page.evaluate(() => (scrollY !== 0 ? `page left scrolled ${scrollY}px` : null))], page);
    });
    await page.context().close();
  }
}

// ---- audio: iOS interrupts the context; the next tap must bring sound back
for (const [kind, state, stuck] of [["interrupted-stuck", "interrupted", true], ["interrupted", "interrupted", false], ["suspended", "suspended", false]]) {
  const name = `audio-${kind}`;
  if (only && !only.test(name)) continue;
  const page = await open(browser, "phone-land", { storage: { "shengji.coach": "off" }, fakeSocket: fakeSocketScript([game()]) });
  await scenario(rep, name, page, async () => {
    await page.waitForSelector(".table-screen");
    const lead = async (i) => {   // a new trick's lead is announced aloud
      const cards = [["SA"], ["HK"], ["D10"], ["C5"], ["S9"], ["H3"]][i % 6];
      await push(page, game({ trick: { leader: 1, plays: [] }, turn: 1 }));
      await sleep(80);
      await push(page, game({ trick: { leader: 1, plays: [{ seat: 1, cards }] }, turn: 2 }));
    };
    await page.click(".felt", { position: { x: 300, y: 120 } });   // the gesture that unlocks audio
    let t = await page.evaluate(() => performance.now());
    await lead(0);
    let ok = await until(page, (t) => window.__qa.soundsSince(t).some((s) => s.state === "running"), { timeout: 6000, arg: t });
    await rep.check(`${name}: a lead is heard to begin with`, ok ? null : `no clip on a running context; contexts ${await page.evaluate(() => window.__qa.audioStates())}`, page);
    await page.evaluate(([s, k]) => { window.__qa.setHidden(true); window.__qa.interruptAudio(s, k); }, [state, stuck]);
    await sleep(500);
    await page.evaluate(() => window.__qa.setHidden(false));
    await sleep(300);
    await page.click(".felt", { position: { x: 300, y: 120 } });   // the player's first tap after coming back
    await sleep(300);
    t = await page.evaluate(() => performance.now());
    await lead(1);
    ok = await until(page, (t) => window.__qa.soundsSince(t).some((s) => s.state === "running"), { timeout: 6000, arg: t });
    await rep.check(`${name}: sound is back after the first tap`, ok ? null
      : `clips since: ${JSON.stringify(await page.evaluate((t) => window.__qa.soundsSince(t), t))}; contexts ${await page.evaluate(() => window.__qa.audioStates())}`, page);
  });
  await page.context().close();
}

// ---- the socket dies with cards chosen
if (!only || only.test("drop")) {
  const bury = base({ phase: "bury", banker: 0, turn: 0, trick: null, attacker_points: 0, hand: hand([...HAND25, "S7", "S10", "H5", "H9", "D3", "DK", "C6", "LJ"]) }, { banker: 0 });
  const page = await open(browser, "phone-land", { storage: { "shengji.coach": "off", "shengji.muted": "1" }, fakeSocket: fakeSocketScript([bury]) });
  await scenario(rep, "drop-mid-bury", page, async () => {
    await page.waitForSelector(".hand .hand-slot");
    for (const id of [1, 2, 3, 4]) await page.locator(`.hand .hand-slot[data-id="${id}"] .card`).click({ force: true, position: { x: 8, y: 14 } });
    await page.evaluate(() => window.__fake.drop());
    const pill = await until(page, () => !!document.querySelector(".reconnect-banner"), { timeout: 8000 });
    await rep.check("drop-mid-bury: the Reconnecting pill shows", pill ? null : "no pill 8 s after the socket died", page);
    await rep.check("drop-mid-bury: the pill covers nothing", await overlaps(page), page);
    await shot(page, "drop_mid_bury_pill");
    const back = await until(page, () => !document.querySelector(".reconnect-banner") && window.__fake.socks.filter((s) => s.readyState === 1).length === 1, { timeout: 15000 });
    await rep.check("drop-mid-bury: reconnects on its own", back ? null : "still disconnected after 15 s", page);
    await sleep(300);
    const kept = await page.evaluate(() => document.querySelectorAll(".hand .card.selected").length);
    await rep.check("drop-mid-bury: the four chosen cards stay chosen", kept === 4 ? null : `${kept} of 4 still chosen`, page);
    for (const id of [5, 6, 7, 8]) await page.locator(`.hand .hand-slot[data-id="${id}"] .card`).click({ force: true, position: { x: 8, y: 14 } });
    await page.locator(".action-bar .btn", { hasText: /Bury/ }).click();
    const sent = await page.evaluate(() => window.__fake.sent.filter((m) => m.type === "bury").length);
    await rep.check("drop-mid-bury: Bury sends once after the reconnect", sent === 1 ? null : `${sent} bury frames sent`, page);
  });
  await page.context().close();

  const mine = base({ trick: { leader: 1, plays: plays(1, 3, 1) }, turn: 0 }, { banker: 1 });
  const page2 = await open(browser, "phone-land", { storage: { "shengji.coach": "off", "shengji.muted": "1" }, fakeSocket: fakeSocketScript([mine]) });
  await scenario(rep, "drop-play-in-flight", page2, async () => {
    await page2.waitForSelector(".hand .hand-slot");
    await page2.locator(`.hand .hand-slot[data-id="7"] .card`).click({ force: true, position: { x: 8, y: 14 } });
    await page2.locator(".action-bar .btn", { hasText: /^Play/ }).click();
    // frames sent since a cursor, so each reconnect is checked on its own socket's frames
    const cursor = () => page2.evaluate(() => window.__fake.sent.length);
    const since = (n) => page2.evaluate((k) => window.__fake.sent.slice(k).map((m) => ({ type: m.type, ids: m.card_ids ?? null })), n);
    const playOf7 = (f) => f.type === "play" && JSON.stringify(f.ids) === "[7]";
    const first = await since(0);
    await rep.check("drop-play-in-flight: the play goes with card 7",
      first.filter((f) => f.type === "play").length === 1 && first.some(playOf7) ? null : `sent before the drop: ${JSON.stringify(first)}`, page2);
    const c1 = await cursor();
    await page2.evaluate(() => window.__fake.drop());       // the play's answer never comes
    await sleep(400);
    const label = await page2.evaluate(() => document.querySelector(".action-bar")?.innerText.replace(/\\s+/g, " "));
    await rep.check("drop-play-in-flight: the button says it is reconnecting", /Reconnecting/.test(label ?? "") ? null : `action bar reads "${label}"`, page2);
    await shot(page2, "drop_play_in_flight");
    const back = await until(page2, () => !document.querySelector(".reconnect-banner") && window.__fake.socks.filter((s) => s.readyState === 1).length === 1, { timeout: 15000 });
    await rep.check("drop-play-in-flight: reconnects", back ? null : "still disconnected after 15 s", page2);
    await sleep(300);
    // first reconnect: a fresh join, then exactly one identical play after it
    const r1 = await since(c1);
    const j1 = r1.findIndex((f) => f.type === "table_join");
    const plays1 = r1.filter((f) => f.type === "play");
    const chosen = () => page2.evaluate(() => document.querySelectorAll(".hand .card.selected").length);
    await rep.check("drop-play-in-flight: the new socket rejoins, then the same play goes exactly once, card still chosen",
      [j1 >= 0 ? null : `no table_join after the drop: ${JSON.stringify(r1)}`,
       plays1.length === 1 && playOf7(plays1[0]) && r1.indexOf(plays1[0]) > j1 ? null : `after the drop: ${JSON.stringify(r1)}`,
       (await chosen()) === 1 ? null : "the chosen card is no longer chosen"], page2);
    // second reconnect with the resend still unanswered: a fresh join and no play
    const c2 = await cursor();
    await page2.evaluate(() => window.__fake.drop());
    const back2 = await until(page2, () => !document.querySelector(".reconnect-banner") && window.__fake.socks.filter((s) => s.readyState === 1).length === 1, { timeout: 15000 });
    await rep.check("drop-play-in-flight: reconnects a second time", back2 ? null : "still disconnected after 15 s", page2);
    await sleep(300);
    const r2 = await since(c2);
    const play = page2.locator(".action-bar .btn", { hasText: /^Play/ });
    await rep.check("drop-play-in-flight: the second socket rejoins, sends no play, and Play is offered again",
      [r2.some((f) => f.type === "table_join") ? null : `no table_join after the second drop: ${JSON.stringify(r2)}`,
       r2.every((f) => f.type !== "play") ? null : `the play went a third time: ${JSON.stringify(r2)}`,
       (await play.count()) && (await play.isEnabled()) ? null : "Play is not enabled after the second reconnect",
       (await chosen()) === 1 ? null : "the chosen card is no longer chosen"], page2);
  });
  await page2.context().close();
}

// ---- the Play tab in the iOS app, signed in on its device account, at the phones' real safe
// areas: at rest nothing sits under the tab bar (the SE has the least room), Play, Duo, Join and
// the table panel's Start and Leave are one height and one radius, and the links are 44px boxes
const PLAY_SIZES = { "phone-port": { t: 47, b: 34 }, "phone-port-se": { t: 20, b: 0 } };
for (const [device, insets] of Object.entries(PLAY_SIZES)) {
  const name = `playtab-${device}`;
  if (only && !only.test(name)) continue;
  const you = "Swift Crane";
  const user = { name: you, email: "", picture: null, display_name: you, name_shown: you, rounds_played: 14, linked: false };
  const stats = { name: you, rating: 1012, rank: null, rounds: 14, provisional: true, levels_per_round: 0.2, won_pct: 50, history: [1000, 1012], recent_games: [], visible: true };
  const setup = async (page) => {
    await page.addInitScript(`window.Capacitor = { isNativePlatform: () => true, getPlatform: () => "ios", isPluginAvailable: () => true,
      registerPlugin: (n) => new Proxy({}, { get: (_, m) => () => Promise.resolve(n === "ShengjiKeychain" && m === "get" ? { value: "e2e-token" } : undefined) }) };`);
    const json = (body, status = 200) => (r) => r.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    await page.route("**/api/**", json({ detail: "none" }, 404));
    await page.route("**/api/auth/config", json({ google_client_id: "e2e.apps.googleusercontent.com", device_accounts: true }));
    await page.route("**/api/me", json({ detail: "no" }, 401));
    await page.route("**/api/auth/device", json({ user }));
    await page.route("**/api/me/stats", json(stats));
    await page.route("**/accounts.google.com/**", (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
  };
  // the longest presence line: two lines on an SE
  const presence = { type: "presence", tables: 3, playing: 7, waiting: 0, ranked: 2, casual: 1 };
  const page = await open(browser, device, { storage: { "shengji.muted": "1", "shengji.name": you, "shengji.nameChosen": "1" },
    fakeSocket: fakeSocketScript([presence]), insets, setup, still: true });
  await scenario(rep, name, page, async () => {
    await page.waitForSelector(".play-main");
    await sleep(1300);
    const fit = await page.evaluate(() => {
      const bar = document.querySelector(".tabbar").getBoundingClientRect();
      const sc = document.querySelector(".lobby-screen");
      const items = [...document.querySelectorAll(".play-tab button, .play-tab input, .play-tab .play-presence, .play-tab .howto-entry")]
        .filter((e) => e.offsetParent && !e.closest(".tabbar"));
      const under = items.map((e) => [e, e.getBoundingClientRect()]).filter(([, r]) => r.bottom > bar.top + 0.5)
        .map(([e, r]) => `${e.className || e.tagName} ends at ${Math.round(r.bottom)}, the tab bar starts at ${Math.round(bar.top)}`);
      return { under, scroll: sc.scrollHeight - sc.clientHeight, n: items.length };
    });
    await rep.check(`${name}: at rest nothing sits under the tab bar and the page does not scroll`,
      [...fit.under, fit.n >= 8 ? null : `only ${fit.n} controls found`, fit.scroll <= 0 ? null : `the page scrolls ${fit.scroll}px at rest`], page);
    const box = (sel) => page.evaluate((s) => {
      const el = document.querySelector(s); if (!el) return null;
      const r = el.getBoundingClientRect(), x = r.left + r.width / 2; let top = null, bot = null;
      for (let y = Math.floor(r.top) - 30; y <= r.bottom + 30; y++) {
        const e = document.elementFromPoint(x, y); if (e && (e === el || el.contains(e))) { if (top === null) top = y; bot = y; }
      }
      return { h: Math.round(r.height), radius: getComputedStyle(el).borderTopLeftRadius, hit: top === null ? 0 : bot - top + 1 };
    }, sel);
    const one = (rows) => {
      const [first] = Object.values(rows);
      return Object.entries(rows).map(([label, b]) => !b ? `${label}: not in the page`
        : b.h !== first.h || b.radius !== first.radius ? `${label} is ${b.h}px tall with ${b.radius} corners, ${Object.keys(rows)[0]} ${first.h}px with ${first.radius}` : null);
    };
    const lobby = { Play: await box(".play-main"), Duo: await box(".play-duo"), Join: await box(".join-row .btn"), "code box": await box(".room-input") };
    const links = [];
    for (const [i, label] of [[0, "How to play"], [1, "Play offline"]]) {
      const b = await page.evaluate((n) => { const el = document.querySelectorAll(".howto-link")[n]; return el ? Math.round(el.getBoundingClientRect().height) : null; }, i);
      const hit = await box(`.howto-entry > .howto-link:nth-of-type(${i + 1})`);
      links.push(b === null ? `${label}: not in the page` : b < 44 ? `${label} is a ${b}px box` : hit.hit < 44 ? `${label} is tapped over ${hit.hit}px` : null);
    }
    await shot(page, name);
    // Play's table: its Start and Leave
    await page.click(".play-main");
    await sleep(300);
    const frames = JSON.parse(fs.readFileSync(new URL("../src/queue/fixtures/table_frames.json", import.meta.url), "utf8"));
    const f = frames.find((x) => x.queue_state.table === null && !x.queue_state.duo && !x.party);
    const t0 = Date.now() / 1000;
    const fix = (o) => JSON.parse(JSON.stringify(o).replaceAll("<code0>", "4N5Z").replace(/"P\d"/g, `"${you}"`)
      .replaceAll("10060.0", String(t0 + 55)).replaceAll("10030.0", String(t0 + 25)).replaceAll("10000.0", String(t0 - 5)));
    for (const frame of [fix(f.queue_state), fix(f.table)]) await push(page, frame);
    await page.waitForSelector(".tp-primary");
    await sleep(400);
    const table = { Start: await box(".tp-primary"), Leave: await box(".tp-secondary") };
    await rep.check(`${name}: Play, Duo, Join, the code box, Start and Leave share one height and radius; the links are 44px boxes`,
      [...one({ ...lobby, ...table }), lobby.Play?.h >= 52 ? null : `Play is ${lobby.Play?.h}px tall`, ...links], page);
    await shot(page, `${name}_table`);
  });
  await page.context().close();
}

await browser.close();
process.exit(rep.done());
