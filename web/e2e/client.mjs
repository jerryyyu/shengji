// What a phone does to the page, against a scripted socket (no game server
// needed): the keyboard over the in-game chat, audio interrupted by iOS, the
// socket dying with cards chosen. These are the three ways the app broke on a
// real phone while every static screenshot looked fine.
//   node e2e/client.mjs [scenario-regex]
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
    await page2.evaluate(() => window.__fake.drop());       // the play's answer never comes
    await sleep(400);
    const label = await page2.evaluate(() => document.querySelector(".action-bar")?.innerText.replace(/\\s+/g, " "));
    await rep.check("drop-play-in-flight: the button says it is reconnecting", /Reconnecting/.test(label ?? "") ? null : `action bar reads "${label}"`, page2);
    await shot(page2, "drop_play_in_flight");
    const back = await until(page2, () => !document.querySelector(".reconnect-banner") && window.__fake.socks.filter((s) => s.readyState === 1).length === 1, { timeout: 15000 });
    await rep.check("drop-play-in-flight: reconnects", back ? null : "still disconnected after 15 s", page2);
    await sleep(300);
    // the first state on the new socket shows the same hand and turn, so the play goes once more there
    const after = () => page2.evaluate(() => {
      const sent = window.__fake.sent.map((m) => m.type);
      return { plays: sent.filter((t) => t === "play").length, resentAfterJoin: sent.lastIndexOf("play") > sent.lastIndexOf("table_join") };
    });
    const once = await after();
    const chosen = () => page2.evaluate(() => document.querySelectorAll(".hand .card.selected").length);
    await rep.check("drop-play-in-flight: the play goes once more on the new socket, card still chosen",
      [once.plays === 2 && once.resentAfterJoin ? null : `${once.plays} play frames; resent after the rejoin: ${once.resentAfterJoin}`,
       (await chosen()) === 1 ? null : "the chosen card is no longer chosen"], page2);
    // a second drop with the resend still unanswered: nothing goes a third time and Play is offered again
    await page2.evaluate(() => window.__fake.drop());
    const back2 = await until(page2, () => !document.querySelector(".reconnect-banner") && window.__fake.socks.filter((s) => s.readyState === 1).length === 1, { timeout: 15000 });
    await rep.check("drop-play-in-flight: reconnects a second time", back2 ? null : "still disconnected after 15 s", page2);
    await sleep(300);
    const play = page2.locator(".action-bar .btn", { hasText: /^Play/ });
    await rep.check("drop-play-in-flight: Play is offered again, card still chosen",
      [(await play.count()) && (await play.isEnabled()) ? null : "Play is not enabled after the second reconnect",
       (await after()).plays === 2 ? null : "the play went a third time",
       (await chosen()) === 1 ? null : "the chosen card is no longer chosen"], page2);
  });
  await page2.context().close();
}

await browser.close();
process.exit(rep.done());
