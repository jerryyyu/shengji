// The real flows against a real server (BASE), driven by taps: two people at
// one table by invite code, chat with the keyboard up, the background and
// back, the network dropping mid-trick, sound through all of it, leaving and
// coming back by code, the round end. What a phone does to the page (keyboard,
// background, dead socket, interrupted audio) is made to happen by inject.js.
//   node e2e/flows.mjs [scenario-regex]
import { BASE, DEVICES, Report, background, contained, dropNetwork, keyboard, launch, lint as lintNow, onShow, open,
  rotate, scenario, settled, shot, sleep, state, textCuts, until, zoomingInputs } from "./lib.mjs";
import { act, playUntil, toTable } from "./drive.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const want = (name) => !only || only.test(name);
const rep = new Report("flows", { partial: !!only });

const browser = await launch();
// a live table is read only once its cards have landed
const lint = async (page) => { await settled(page); return lintNow(page); };
const menu = async (page, open) => {
  const isOpen = (await page.locator(".hud-menu-row").count()) > 0;
  if (isOpen !== open) { await page.click(".hud-more-btn"); await sleep(250); }
};

// ---------------------------------------------------------------- lobby fields
for (const device of ["phone-port", "phone-port-se", "phone-land", "ipad", "desktop"]) {
  if (!want(`lobby-${device}`)) continue;
  const page = await open(browser, device);
  await scenario(rep, `lobby-${device}`, page, async () => {
    await page.waitForSelector(".play-main");
    await sleep(600);
    await rep.check(`lobby-${device}: layout`, [...(await textCuts(page)), ...(await zoomingInputs(page))], page);
    // (a phone held sideways scrolls its lobby: Play need not be on the first screen there)
    if (device !== "phone-land") await rep.check(`lobby-${device}: Play is on the first screen`, await onShow(page, ".play-main", "Play"), page);
    // scrolled as far as it goes, the last controls must clear the floating tab bar
    await page.evaluate(() => { for (const e of document.querySelectorAll(".screen")) e.scrollTop = e.scrollHeight; window.scrollTo(0, 1e6); });
    await sleep(200);
    await rep.check(`lobby-${device}: the code box and the links can be scrolled clear of the tab bar`,
      [await onShow(page, ".room-input", "code box"), await onShow(page, ".howto-link >> nth=-1", "last link")], page);
    await page.evaluate(() => { for (const e of document.querySelectorAll(".screen")) e.scrollTop = 0; window.scrollTo(0, 0); });
    // In mobile Safari the browser itself pans a focused field in the page's flow into view, which
    // this suite cannot imitate: only the app's shrinking WebView is checked here.
    // (a phone held sideways has no lobby design of its own: only the checks above apply to it)
    for (const mode of DEVICES[device].kb && device !== "phone-land" ? ["app"] : []) {
      // the code box
      await page.click(".room-input");
      await keyboard(page, true, mode);
      await page.keyboard.type("ZZZZ");
      await sleep(250);
      await rep.check(`lobby-${device}: code box above the keyboard (${mode})`, [await onShow(page, ".room-input", "code box")], page);
      await shot(page, `lobby_${device}_code_kb_${mode}`);
      await page.keyboard.press("Enter");
      await sleep(900);
      const said = await page.evaluate(() => document.body.innerText.match(/no table|not found|No table|isn.t|wrong|Check the code|doesn.t/i)?.[0] ?? null);
      await rep.check(`lobby-${device}: a bad code says so (${mode})`, said ? null : "no visible answer to a bad code", page);
      await shot(page, `lobby_${device}_badcode_${mode}`);
      await page.fill(".room-input", "");
      await keyboard(page, false, mode);
      // the name
      await page.click(".guest-pill");
      await page.waitForSelector("input[placeholder*='Jerry']");
      await page.click("input[placeholder*='Jerry']");
      await keyboard(page, true, mode);
      await sleep(250);
      await rep.check(`lobby-${device}: name field and Done above the keyboard (${mode})`,
        [await onShow(page, "input[placeholder*='Jerry']", "name field"), await onShow(page, ".btn.secondary:has-text('Done')", "Done")], page);
      await shot(page, `lobby_${device}_name_kb_${mode}`);
      await page.fill("input[placeholder*='Jerry']", "Maximilian Featherst");
      await sleep(200);
      await rep.check(`lobby-${device}: a long name fits its sheet (${mode})`, await textCuts(page), page);
      await page.click(".btn.secondary:has-text('Done')");
      await keyboard(page, false, mode);
      await sleep(400);
      await rep.check(`lobby-${device}: long name on the Play tab (${mode})`, await textCuts(page), page);
      await rep.check(`lobby-${device}: page back in place after the keyboard (${mode})`,
        await page.evaluate(() => (scrollY !== 0 || document.documentElement.scrollTop !== 0 ? `page left scrolled ${scrollY}px` : null)), page);
    }
    await shot(page, `lobby_${device}`);
  });
  await page.context().close();
}

// ---------------------------------------------------------------- two people, one table
if (want("table")) {
  const a = await open(browser, "phone-port", { storage: { "shengji.coach": "off", "shengji.name": "Maximilian Featherst" } });
  let b = null;
  let code = null;
  await scenario(rep, "table: open, invite, chat before the game", a, async () => {
    code = await toTable(a, "casual");
    await rep.check("table: has a code", code ? null : "no code on the waiting table", a);
    await rep.check("table: waiting panel layout", await textCuts(a), a);
    b = await open(browser, "phone-port", { url: `?code=${code}`, storage: { "shengji.coach": "on", "shengji.name": "张伟张伟张伟张伟" } });
    await b.click(".tp-primary");                        // Join, from the invite link
    await until(a, () => (window.__qa.last.queue_state?.table?.seats ?? []).filter(Boolean).length === 2);
    await sleep(400);
    await rep.check("table: two long names at the waiting table", await textCuts(a), a);
    await shot(a, "table_waiting_two");
    // chat at the waiting table, keyboard up
    await a.click(".tp-chat");
    await a.waitForSelector(".chat-input input, .chat-input textarea");
    for (const mode of ["app"]) {
      await a.click(".chat-input input, .chat-input textarea");
      await keyboard(a, true, mode);
      await rep.check(`table: lobby chat field and Send above the keyboard (${mode})`,
        [await onShow(a, ".chat-input input, .chat-input textarea", "chat field"), await onShow(a, ".chat-input .btn", "Send")], a);
      await shot(a, `table_chat_kb_${mode}`);
      await keyboard(a, false, mode);
    }
    await a.fill(".chat-input input, .chat-input textarea", "hello from the waiting table");
    await a.click(".chat-input .btn");
    const got = await until(b, () => document.body.innerText.includes("hello from the waiting table"), { timeout: 5000 });
    await rep.check("table: chat reaches the other person before the game", got ? null : "the other page never showed the message", b);
    await a.keyboard.press("Escape");
    await sleep(300);
    if (await a.locator(".chat-sheet").count()) await a.locator(".q-scrim, .q-link").first().click({ force: true }).catch(() => {});
  });

  await scenario(rep, "game: start, rotate", a, async () => {
    await sleep(300);
    await a.click(".tp-primary");
    await b.click(".tp-primary");
    await until(a, () => window.__qa.state !== null, { timeout: 15000 });
    await rep.check("game: started for both", [(await state(a)) ? null : "host never got a state", (await state(b)) ? null : "joiner never got a state"], a);
    // portrait first: the table is drawn turned
    await sleep(1500);
    await rep.check("game: portrait phone, deal", await textCuts(a), a);
    await shot(a, "game_portrait_deal");
    await rotate(a, "phone-land");
    await rotate(b, "phone-land-se");
  });

  // B plays itself for the rest of the run
  let stopB = false;
  const loopB = (async () => {
    while (!stopB) {
      const did = await act(b).catch(() => null);
      if (!did) await sleep(250);
    }
  })();

  await scenario(rep, "game: declare window", a, async () => {
    await until(a, () => window.__qa.state.phase === "declare" || window.__qa.state.phase === "bury" || window.__qa.state.phase === "play", { timeout: 30000 });
    await sleep(300);
    await rep.check("game: declare window layout", await lint(a), a);
    await shot(a, "game_declare");
    await rep.check("game: declare window layout (small phone, coach on)", await lint(b), b);
    await shot(b, "game_declare_b");
  });

  await scenario(rep, "game: bury with a dropped network", a, async () => {
    // declare if we can, so the bury is ours when the cards allow
    await playUntil(a, () => ["bury", "play"].includes(window.__qa.state.phase), { timeout: 60000, declare: true });
    const s = await state(a);
    if (s.phase === "bury" && s.turn === s.you) {
      await rep.check("bury: layout", await lint(a), a);
      await shot(a, "game_bury");
      // pick half, lose the network, come back, finish
      for (const c of s.hand.slice(0, 4)) await a.locator(`.hand .hand-slot[data-id="${c.id}"] .card`).click({ force: true, position: { x: 8, y: 14 } });
      await dropNetwork(a, 2500);
      const back = await until(a, () => window.__qa.openSockets() === 1 && !document.querySelector(".reconnect-banner"), { timeout: 15000 });
      await rep.check("bury: reconnects mid-bury", back ? null : "no open socket, or the pill stayed, 15 s after the network returned", a);
      const kept = await a.evaluate(() => document.querySelectorAll(".hand .card.selected").length);
      await rep.check("bury: the half-made choice survives the reconnect", kept === 4 ? null : `${kept} of 4 chosen cards still chosen`, a);
      await shot(a, "game_bury_after_reconnect");
      for (const c of s.hand.slice(4, 8)) await a.locator(`.hand .hand-slot[data-id="${c.id}"] .card`).click({ force: true, position: { x: 8, y: 14 } });
      await a.locator(".action-bar .btn", { hasText: /Bury/i }).click({ timeout: 5000 });
      const done = await until(a, () => window.__qa.state.phase === "play", { timeout: 8000 });
      await rep.check("bury: goes through after the reconnect", done ? null : "still in bury 8 s after tapping Bury", a);
    } else {
      console.log("   (not our bury this round: the fixture matrix covers the bury layout)");
      await playUntil(a, () => window.__qa.state.phase === "play", { timeout: 60000 });
    }
  });

  await scenario(rep, "game: sound plays", a, async () => {
    const t = await a.evaluate(() => performance.now());
    await playUntil(a, (t) => window.__qa.soundsSince(t).length > 0, { timeout: 40000, arg: t });
    const starts = await a.evaluate((t) => window.__qa.soundsSince(t), t);
    await rep.check("sound: a clip starts on a running context", starts.some((s) => s.state === "running") ? null : `clips started: ${JSON.stringify(starts.slice(0, 4))}; contexts: ${await a.evaluate(() => window.__qa.audioStates())}`, a);
  });

  await scenario(rep, "game: table layout through a few tricks", a, async () => {
    for (let i = 0; i < 12; i++) {
      await act(a).catch(() => null);
      await sleep(450);
      await rep.check(`game: live table ${i}`, await lint(a), a);
      await rep.check(`game: live table ${i} (small phone, coach on)`, await lint(b), b);
    }
    await shot(a, "game_play");
    await shot(b, "game_play_b");
  });

  await scenario(rep, "chat: in the game, keyboard up", a, async () => {
    await a.click(".chat-launch");
    await a.waitForSelector(".chat-panel");
    await sleep(350);
    await rep.check("chat: panel is one opaque box", (await contained(a, ".chat-panel")).spill, a);
    await shot(a, "chat_open");
    for (const mode of ["safari", "app"]) {
      await a.click(".chat-panel .chat-input input, .chat-panel .chat-input textarea");
      await keyboard(a, true, mode);
      const c = await contained(a, ".chat-panel");
      await rep.check(`chat: opaque with the keyboard up (${mode})`, c.alpha >= 0.99 ? null : `panel background alpha ${c.alpha}`, a);
      await rep.check(`chat: nothing spills out of the panel (${mode})`, c.spill, a);
      await rep.check(`chat: panel, field and Send above the keyboard (${mode})`, [
        await onShow(a, ".chat-panel", "chat panel"),
        await onShow(a, ".chat-panel .chat-input input, .chat-panel .chat-input textarea", "chat field"),
        await onShow(a, ".chat-panel .chat-input .btn", "Send"),
        await onShow(a, ".chat-panel .chat-close", "Close")], a);
      await shot(a, `chat_kb_${mode}`);
      await a.keyboard.type(`typed with the ${mode} keyboard up`);
      await a.click(".chat-panel .chat-input .btn");
      await sleep(300);
      await keyboard(a, false, mode);
    }
    const got = await until(b, () => document.body.innerText.includes("typed with the app keyboard up"), { timeout: 5000 });
    await rep.check("chat: the message reaches the other person", got ? null : "not shown on the other page", b);
    await sleep(200);
    await rep.check("chat: their bubble does not cover the table (small phone)", await lint(b), b);
    await shot(b, "chat_bubble_b");
    await a.click(".chat-panel .chat-close");
    await sleep(300);
    await rep.check("chat: table back in place after the keyboard", [...(await lint(a)), await a.evaluate(() => (scrollY !== 0 ? `page left scrolled ${scrollY}px` : null))], a);
  });

  await scenario(rep, "network: drops mid-trick with cards chosen", a, async () => {
    const mine = await playUntil(a, () => { const s = window.__qa.state; return s.phase === "play" && s.turn === s.you; }, { timeout: 60000 });
    if (!mine) throw new Error("our turn never came");
    const s = await state(a);
    await a.locator(`.hand .hand-slot[data-id="${s.hand[0].id}"] .card`).click({ force: true, position: { x: 8, y: 14 } });
    await a.context().setOffline(true);
    await a.evaluate(() => window.__qa.drop(true));
    const pill = await until(a, () => !!document.querySelector(".reconnect-banner"), { timeout: 6000 });
    await rep.check("network: the Reconnecting pill shows", pill ? null : "no pill within 6 s of the socket dying", a);
    await rep.check("network: the pill covers nothing", await lint(a), a);
    await shot(a, "net_drop_pill");
    await sleep(1500);
    await a.evaluate(() => window.__qa.unblock());
    await a.context().setOffline(false);
    const t0 = Date.now();
    const back = await until(a, () => window.__qa.openSockets() === 1 && !document.querySelector(".reconnect-banner"), { timeout: 15000 });
    console.log(`   back ${((Date.now() - t0) / 1000).toFixed(1)} s after the network returned`);
    await rep.check("network: reconnects and the pill goes", back ? null : "15 s after the network returned: no socket or the pill stayed", a);
    await rep.check("network: back within 5 s of the network returning", Date.now() - t0 <= 5000 ? null : `took ${((Date.now() - t0) / 1000).toFixed(1)} s`, a);
    await sleep(300);
    const did = await act(a);
    await rep.check("network: our play goes through after the reconnect", did === "play" ? null : `act() returned ${did}`, a);
    await shot(a, "net_drop_after");
  });

  await scenario(rep, "background: 4 s away, audio interrupted", a, async () => {
    await playUntil(a, () => { const s = window.__qa.state; return s.phase === "play" && s.turn === s.you; }, { timeout: 60000 });
    await background(a, 4000, { audio: "interrupted", stuck: true });
    const t0 = Date.now();
    const back = await until(a, () => window.__qa.openSockets() === 1 && !document.querySelector(".reconnect-banner"), { timeout: 15000 });
    console.log(`   back ${((Date.now() - t0) / 1000).toFixed(1)} s after returning`);
    await rep.check("background: reconnects on return", back ? null : "15 s after returning: no socket or the pill stayed", a);
    await rep.check("background: live again within 3 s of returning", Date.now() - t0 <= 3000 ? null : `took ${((Date.now() - t0) / 1000).toFixed(1)} s`, a);
    await rep.check("background: no bot holds our seat after 4 s away", await a.evaluate(() => (document.querySelector(".away-pill") ? `pill says "${document.querySelector(".away-pill").innerText.replace(/\s+/g, " ")}"` : null)), a);
    await shot(a, "bg_return");
    const t = await a.evaluate(() => performance.now());
    // the first tap after returning is the gesture that may revive audio
    await playUntil(a, (t) => window.__qa.soundsSince(t).length > 0, { timeout: 45000, arg: t });
    const starts = await a.evaluate((t) => window.__qa.soundsSince(t), t);
    await rep.check("background: sound is back after the first tap", starts.some((s) => s.state === "running") ? null
      : `clips after return: ${JSON.stringify(starts.slice(0, 4))}; contexts: ${await a.evaluate(() => window.__qa.audioStates())}`, a);
    await a.evaluate(() => window.__qa.endInterruption());
  });

  await scenario(rep, "sound: off means silent, on means sound", a, async () => {
    await menu(a, true);
    await a.click(".sound-row");
    await menu(a, false);
    const t = await a.evaluate(() => performance.now());
    for (let i = 0; i < 14; i++) { await act(a).catch(() => null); await sleep(500); }
    const off = await a.evaluate((t) => window.__qa.soundsSince(t).length, t);
    await rep.check("sound: nothing plays while Sound is off", off === 0 ? null : `${off} clips started while muted`, a);
    await menu(a, true);
    await settled(a);
    await rep.check("sound: every row of the menu is on the screen", [await onShow(a, ".sound-row", "Sound"), await onShow(a, ".hud-menu-row.leave", "Leave game")], a);
    await shot(a, "menu_open");
    await a.click(".sound-row");
    await menu(a, false);
    const t2 = await a.evaluate(() => performance.now());
    await playUntil(a, (t) => window.__qa.soundsSince(t).length > 0, { timeout: 45000, arg: t2 });
    const on = await a.evaluate((t) => window.__qa.soundsSince(t), t2);
    await rep.check("sound: plays again once Sound is on", on.some((s) => s.state === "running") ? null : `clips: ${JSON.stringify(on.slice(0, 3))}`, a);
  });

  await scenario(rep, "leave, then back by code", a, async () => {
    await menu(a, true);
    await a.click(".hud-menu-row.leave");
    await a.waitForSelector(".leave-sheet-leave");
    await settled(a);
    await rep.check("leave: the sheet fits a sideways phone", [await onShow(a, ".leave-sheet-leave", "Leave"), await onShow(a, ".leave-sheet-stay", "Stay"), ...(await textCuts(a))], a);
    await shot(a, "leave_sheet");
    const seatBefore = (await state(a))?.you;
    await a.click(".leave-sheet-leave");
    await a.waitForSelector(".room-input", { timeout: 8000 });
    await rotate(a, "phone-port");
    await sleep(500);
    await shot(a, "left_lobby");
    // back under another name: the seat is found by the device, not the name
    await a.click(".guest-pill");
    await a.fill("input[placeholder*='Jerry']", "Maximilian Two");
    await a.click(".btn.secondary:has-text('Done')");
    await sleep(500);
    await a.fill(".room-input", code);
    await a.keyboard.press("Enter");
    await a.waitForSelector(".tp-primary", { timeout: 8000 });
    await sleep(400);
    await rep.check("rejoin: the join panel layout", await textCuts(a), a);
    await shot(a, "rejoin_panel");
    await a.evaluate(() => { window.__qa.state = null; });
    await a.click(".tp-primary");
    const seated = await until(a, () => window.__qa.state !== null && !window.__qa.state.joining_you, { timeout: 90000 });
    await rep.check("rejoin: seated again", seated ? null : "no seat 90 s after tapping Join", a);
    const back = await state(a);
    const mine = back?.players.find((p) => p.seat === back.you);
    await rep.check("rejoin: renamed, back in the seat it left, under the new name",
      back && back.you === seatBefore && mine?.name === "Maximilian Two" ? null
        : `left seat ${seatBefore}; back in seat ${back?.you} as ${JSON.stringify(mine?.name)}; seats ${JSON.stringify(back?.players.map((p) => [p.seat, p.name]))}`, a);
    await rotate(a, "phone-land");
    await shot(a, "rejoin_seated");
  });

  await scenario(rep, "joined by code mid-game, then the network drops", a, async () => {
    const mine = await playUntil(a, () => { const s = window.__qa.state; return s.phase === "play" && s.turn === s.you; }, { timeout: 60000 });
    if (!mine) throw new Error("our turn never came");
    await dropNetwork(a, 2500);
    const back = await until(a, () => window.__qa.openSockets() === 1 && !document.querySelector(".reconnect-banner"), { timeout: 15000 });
    await rep.check("joined mid-game: reconnects", back ? null : "15 s after the network returned: no socket or the pill stayed", a);
    await sleep(500);
    const n = await a.evaluate(() => window.__qa.errors.length);
    const did = await act(a).catch(() => null);
    await sleep(800);
    const refused = await a.evaluate((n) => window.__qa.errors.slice(n).map((e) => e.message), n);
    await rep.check("joined mid-game: still at the table after a reconnect (a play goes through)",
      did === "play" && refused.length === 0 ? null : `act() returned ${did}; the server answered ${JSON.stringify(refused)}`, a);
  });

  await scenario(rep, "back at the table for the round end", a, async () => {
    // Whatever the reconnect above did to our seat, sit down again: a fresh page with the invite link.
    await a.evaluate(() => { window.__qa.state = null; });
    await a.goto(`${BASE}?code=${code}`);
    await sleep(1500);
    if (!(await state(a)) && (await a.locator(".tp-primary").count())) await a.click(".tp-primary");
    const seated = await until(a, () => window.__qa.state !== null && !window.__qa.state.joining_you, { timeout: 90000 });
    if (!seated) throw new Error("could not sit down again");
    await rotate(a, "phone-land");
  });

  await scenario(rep, "round end, with a drop", a, async () => {
    const ended = await playUntil(a, () => window.__qa.state.phase === "round_end", { timeout: 300000 });
    if (!ended) throw new Error("the round did not end in 5 minutes");
    stopB = true;
    await sleep(1800);
    await rep.check("round end: dialog fits", [await onShow(a, "text=Next round", "Next round"), ...(await textCuts(a))], a);
    await shot(a, "round_end");
    await rep.check("round end: dialog fits (small phone)", [await onShow(b, "text=Next round", "Next round"), ...(await textCuts(b))], b);
    await shot(b, "round_end_b");
    await a.click("text=Details");
    await sleep(400);
    await rep.check("round end: Details fits", [await onShow(a, "text=Next round", "Next round"), ...(await textCuts(a))], a);
    await shot(a, "round_end_details");
    await dropNetwork(a, 2500);
    const back = await until(a, () => window.__qa.openSockets() === 1 && !document.querySelector(".reconnect-banner"), { timeout: 15000 });
    await rep.check("round end: reconnects", back ? null : "15 s after the network returned: no socket or the pill stayed", a);
    await rep.check("round end: the result is still up after the reconnect", (await a.locator("text=Next round").count()) ? null : "the round-end dialog is gone", a);
    await shot(a, "round_end_after_reconnect");
    await a.click("text=Next round");
    await b.click("text=Next round").catch(() => {});
    const next = await until(a, () => ["deal", "declare"].includes(window.__qa.state.phase), { timeout: 15000 });
    await rep.check("round end: Next round starts the next deal", next ? null : `phase is ${(await state(a)).phase}`, a);
  });
  stopB = true;
  await loopB.catch(() => {});
  if (!a.isClosed()) {
    const slow = await a.evaluate(() => window.__qa.longTasks.filter((t) => t.ms >= 200));
    await rep.check("smoothness: no main-thread stall of 200 ms or more in the whole game", slow.map((t) => `${t.ms} ms stall at ${Math.round(t.t / 1000)} s`), a);
  }
  await a.context().close();
  if (b) await b.context().close();
}

// ---------------------------------------------------------------- offline, Duo, the other tabs
if (want("offline")) {
  const web = await open(browser, "phone-port");
  await scenario(rep, "offline: a browser's Play tab has no Play offline", web, async () => {
    await web.waitForSelector(".play-main");
    const links = await web.$$eval(".howto-entry button", (bs) => bs.map((b) => b.textContent));
    await rep.check("offline: a browser shows How to play alone", links.join("|") === "How to play" ? null : `links: ${links.join(", ")}`, web);
  });
  await web.context().close();
  const page = await open(browser, "phone-port", { storage: { "shengji.coach": "on" }, native: true });
  await scenario(rep, "offline: Play offline to a dealt table and back", page, async () => {
    await page.click("text=Play offline");
    await page.waitForSelector(".tp-primary");
    await rep.check("offline: table panel layout", await textCuts(page), page);
    await shot(page, "offline_panel");
    await page.click(".tp-primary");
    await page.waitForSelector(".table-screen", { timeout: 15000 });
    await rotate(page, "phone-land");
    await page.waitForSelector(".action-bar .btn", { timeout: 20000 });
    await sleep(500);
    await rep.check("offline: declare window layout", await lint(page), page);
    await shot(page, "offline_declare");
    const pass = page.locator(".action-bar .btn", { hasText: /Pass/ });
    await pass.click({ timeout: 15000 }).catch(() => {});
    for (let i = 0; i < 16; i++) { await sleep(700); await rep.check(`offline: table ${i}`, await lint(page), page); }
    await shot(page, "offline_play");
    await menu(page, true);
    await page.click(".hud-menu-row.leave");
    await page.click(".leave-sheet-leave");
    await page.waitForSelector(".play-main", { timeout: 8000 });
    await rotate(page, "phone-port");
    const online = await until(page, () => window.__qa.openSockets() === 1, { timeout: 10000 });
    await rep.check("offline: leaving returns to the online lobby", online ? null : "no server socket 10 s after leaving the offline table", page);
    await shot(page, "offline_left");
  });
  await page.context().close();
}

if (want("duo")) {
  const page = await open(browser, "phone-port");
  await scenario(rep, "duo: a held seat, then leave", page, async () => {
    await page.waitForSelector(".play-main");
    await page.click(".play-mode-opt:has-text('Casual')");
    await page.click(".play-duo");
    await page.waitForSelector(".tp-primary");
    await sleep(500);
    await rep.check("duo: panel layout", await textCuts(page), page);
    await rep.check("duo: Start and Leave on the first screen", [await onShow(page, ".tp-primary", "Start"), await onShow(page, ".tp-secondary", "Leave")], page);
    await shot(page, "duo_panel");
    await page.click(".tp-secondary");
    await sleep(500);
    await shot(page, "duo_leave");
    const sheet = page.locator(".leave-sheet-leave");
    if (await sheet.count()) await sheet.click();
    const out = await until(page, () => !!document.querySelector(".play-main"), { timeout: 5000 });
    await rep.check("duo: Leave returns to Play", out ? null : "Play did not come back", page);
  });
  await page.context().close();
}

for (const device of ["phone-port", "phone-port-se", "ipad", "desktop"]) {
  if (!want(`tabs-${device}`)) continue;
  const page = await open(browser, device);
  await scenario(rep, `tabs-${device}`, page, async () => {
    await page.waitForSelector(".play-main");
    for (const tab of ["Leaderboard", "Me"]) {
      await page.locator(".tabbar-item, [role=tab], nav button", { hasText: tab }).first().click();
      await sleep(900);
      await rep.check(`tabs-${device}: ${tab} layout`, [...(await textCuts(page)), ...(await zoomingInputs(page))], page);
      await shot(page, `tab_${tab}_${device}`);
    }
    await page.locator(".tabbar-item, [role=tab], nav button", { hasText: "Play" }).first().click();
    await page.click("text=How to play");
    await sleep(900);
    await rep.check(`tabs-${device}: How to play layout`, await textCuts(page), page);
    await shot(page, `howto_${device}`);
    const jumps = await page.evaluate(() => window.__qa.shifts.filter((s) => s.v > 0.05));
    await rep.check(`tabs-${device}: nothing jumps while the pages load`, jumps.map((j) => `layout shift ${j.v.toFixed(2)} at ${Math.round(j.t)} ms: ${j.what.join(", ")}`), page);
  });
  await page.context().close();
}

await browser.close();
process.exit(rep.done());
