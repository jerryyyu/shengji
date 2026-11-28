// The Collection is one page, measured in a real browser: a tap on a tile
// selects its character into the stage at the top, in place (the address
// stays #/collection, no history entry, the tile ringed); on a phone, a tablet
// and a desktop a tile tapped further down scrolls the page back up to the stage; a link to
// #/collection/<kind> selects that character and leaves the plain address;
// the phone's sideways tab swipe still works on the page. The stage's Stage ·
// Table switch sits at its top right, clear of the title and the figure, and
// Table draws the figure on the felt at the size a table seats yours there. Real touch input
// (CDP Input.dispatchTouchEvent) lets the browser's own hit testing pick
// targets. A guest, who cannot buy, sees the store characters as Coming soon.
//   node e2e/collection.mjs [device-regex]
import { webkit } from "playwright-core";
import { BASE, DEVICES as DEVICES_AT, Report, launch, open, scenario, sleep, until } from "./lib.mjs";
import { base, fakeSocketScript, pl } from "./fake.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const rep = new Report("collection", { partial: !!only });
const DEVICES = ["phone-port", "phone-port-se", "ipad11-land"].filter((d) => !only || only.test(d));

/** A guest the server shows the Collection to: the four free companions. */
async function setup(page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: null, device_accounts: false, collection: true } }));
}

const onStage = (page) => page.evaluate(() =>
  [...(document.querySelector(".char-stage svg.cmp")?.classList ?? [])].find((c) => /^cmp-(tractor|bun|chick|sparrow)$/.test(c)) ?? "");

/** One finger, put down at (x, y) and drawn right by `dx` in steps, then lifted. */
async function swipe(cdp, x, y, dx) {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  for (let i = 1; i <= 8; i++) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + (dx * i) / 8, y: y + i * 0.5 }] });
    await sleep(16);
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

/** The stage's move chips, sampled from the browser's own layout and computed style: one row of four,
 *  Big play's apex inside the stage with the figure cheering throughout, a tap on the figure ending it at
 *  once, and under Reduce Motion each chip's still pose inside the stage. `press` is "tap" on a touch
 *  device, "click" with a mouse. */
async function stageBeats(page, device, press = page.qa.d.touch === false ? "click" : "tap") {
  await scenario(rep, `${device} stage chips`, page, async () => {
    await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 0; });
    await page.locator(".coll-yours .coll-tile", { hasText: "Bun" })[press]();
    await sleep(500);
    const chip = (name) => page.locator(".char-poses .char-move", { hasText: name });
    const row = await page.evaluate(() => [...document.querySelectorAll(".char-poses > *")].map((c) => ({
      text: c.textContent, top: Math.round(c.getBoundingClientRect().top) })));
    await rep.check(`${device} the stage has one row of four chips: Hop, Cheer, Big play, the special`,
      JSON.stringify(row.map((c) => c.text)) === JSON.stringify(["Hop", "Cheer", "Big play", "Steamer pop"])
        && new Set(row.map((c) => c.top)).size === 1 ? null : JSON.stringify(row), page);

    await chip("Big play")[press]();
    const apex = await page.evaluate(async () => {
      const stage = document.querySelector(".char-stage").getBoundingClientRect();
      const fig = () => document.querySelector(".char-stage .char-box svg.cmp").getBoundingClientRect();
      let worst = Infinity;
      let rose = 0;
      let cheer = true;
      const start = fig().top;
      const t0 = performance.now();
      while (performance.now() - t0 < 1450) {
        await new Promise((r) => requestAnimationFrame(r));
        const top = fig().top;
        worst = Math.min(worst, top - stage.top);
        rose = Math.max(rose, start - top);
        cheer &&= document.querySelector(".char-stage svg.cmp")?.getAttribute("data-pose") === "cheer";
      }
      return { worst: Math.round(worst), rose: Math.round(rose), cheer };
    });
    await rep.check(`${device} Big play's apex stays inside the stage`, apex.worst >= -1 ? null : `${-apex.worst}px over its top`, page);
    await rep.check(`${device} Big play still jumps`, apex.rose >= 8 ? null : `rose ${apex.rose}px`, page);
    await rep.check(`${device} Big play holds the cheer through the jump`, apex.cheer ? null : "the pose left cheer before 1.45 s", page);

    await sleep(600);
    await chip("Big play")[press]();
    await sleep(300);
    await page.locator(".char-stage .coll-figure")[press]();
    const cut = await page.evaluate(async () => {
      const box = document.querySelector(".char-stage .char-box");
      const seen = [];
      const t0 = performance.now();
      while (performance.now() - t0 < 1700) {
        await new Promise((r) => requestAnimationFrame(r));
        seen.push(box.getAnimations().length + (getComputedStyle(box).transform === "none" ? 0 : 10));
      }
      return { worst: Math.max(...seen) };
    });
    await rep.check(`${device} a tap on the figure ends Big play at once`, cut.worst === 0 ? null : JSON.stringify(cut), page);
  });

  // under Reduce Motion each chip shows one still pose for a second, inside the stage
  await scenario(rep, `${device} stage chips, Reduce Motion`, page, async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    try {
      for (const name of ["Hop", "Cheer", "Big play", "Steamer pop"]) {
        await sleep(1300);
        await page.locator(".char-poses .char-move", { hasText: name })[press]();
        const still = await page.evaluate(async () => {
          const stage = document.querySelector(".char-stage").getBoundingClientRect();
          const box = document.querySelector(".char-stage .char-box");
          let worst = Infinity;
          let moving = 0;
          const t0 = performance.now();
          while (performance.now() - t0 < 900) {
            await new Promise((r) => requestAnimationFrame(r));
            worst = Math.min(worst, document.querySelector(".char-stage .char-box svg.cmp").getBoundingClientRect().top - stage.top);
            moving = Math.max(moving, box.getAnimations().length);
          }
          return { worst: Math.round(worst * 100) / 100, moving };
        });
        await rep.check(`${device} Reduce Motion: ${name}'s still pose stays inside the stage`,
          still.worst >= -1 && still.moving === 0 ? null : JSON.stringify(still), page);
      }
    } finally {
      await page.emulateMedia({ reducedMotion: "no-preference" });
    }
  });
}

const browser = await launch();
try {
  for (const device of DEVICES) {
    const page = await open(browser, device, { url: "#/collection", setup, fakeSocket: fakeSocketScript([]),
      storage: { "shengji.coach": "off", "shengji.muted": "1" } });
    const cdp = await page.context().newCDPSession(page);
    const phone = page.qa.d.w < 700;

    await scenario(rep, `${device} select in place`, page, async () => {
      await until(page, () => document.querySelector(".coll-yours .coll-tile") !== null);
      const entries = await page.evaluate(() => history.length);
      await page.locator(".coll-yours .coll-tile", { hasText: "Bun" }).tap();
      await sleep(300);
      const got = await page.evaluate(() => ({
        hash: location.hash, entries: history.length, title: document.querySelector(".large-title")?.textContent,
        ring: document.querySelector(".coll-tile.selected .coll-tile-name")?.textContent,
      }));
      await rep.check(`${device} a tile selects into the stage`, (await onStage(page)) === "cmp-bun" ? null : `stage ${await onStage(page)}`, page);
      await rep.check(`${device} no page, no history entry`, got.hash === "#/collection" && got.entries === entries && got.title === "Collection"
        ? null : JSON.stringify(got), page);
      await rep.check(`${device} the selected tile is ringed`, got.ring === "Bun" ? null : `ring on ${got.ring}`, page);
    });

    // the stage, its chips, its colours and its button fit above the tab bar on the first view
    await scenario(rep, `${device} fit`, page, async () => {
      await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 0; });
      await page.locator(".coll-yours .coll-tile", { hasText: "Tractor" }).tap();
      await sleep(400);
      const fit = await page.evaluate(() => {
        const use = document.querySelector(".char-page .coll-use").getBoundingClientRect();
        const bar = document.querySelector(".tabbar")?.getBoundingClientRect();
        return { useBottom: Math.round(use.bottom), limit: Math.round(bar ? bar.top : innerHeight) };
      });
      await rep.check(`${device} the one button sits above the tab bar`, fit.useBottom <= fit.limit ? null
        : `the button's foot is ${fit.useBottom - fit.limit}px under it`, page);
    });

    await stageBeats(page, device);

    if (phone) {
      await scenario(rep, `${device} scroll back to the stage`, page, async () => {
        await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 600; });
        await sleep(200);
        await page.locator(".coll-yours .coll-tile", { hasText: "Sparrow" }).tap();
        await sleep(900);
        const top = await page.evaluate(() => {
          const s = document.querySelector(".char-stage").getBoundingClientRect();
          return { scroll: document.querySelector(".coll-page").scrollTop, stageTop: Math.round(s.top), stageBottom: Math.round(s.bottom), h: innerHeight };
        });
        await rep.check(`${device} the stage is in view after a selection`,
          top.stageTop >= 0 && top.stageBottom <= top.h && (await onStage(page)) === "cmp-sparrow" ? null : JSON.stringify(top), page);
      });
    }

    if (phone) {
      // every tap on a lower tile brings the stage back into view: from any depth, while the page is still
      // moving from a fling or from the last tap's own scroll, and on the tile already selected
      await scenario(rep, `${device} every lower tap scrolls up`, page, async () => {
        const stageInView = () => page.evaluate(() => {
          const s = document.querySelector(".char-stage").getBoundingClientRect();
          return { top: Math.round(s.top), scroll: Math.round(document.querySelector(".coll-page").scrollTop) };
        });
        const deep = async (y) => { await page.evaluate((y) => { document.querySelector(".coll-page").scrollTop = y; }, y); await sleep(120); };
        const tile = (sel, n) => page.locator(`${sel} .coll-tile`).nth(n);
        const misses = [];
        const settle = async (label) => {
          await sleep(1000);
          const got = await stageInView();
          if (!(got.top >= 0 && got.scroll <= 1)) misses.push(`${label} ${JSON.stringify(got)}`);
        };
        // repeated taps from the bottom, each before the last scroll has finished
        for (const [n, y] of [[1, 9999], [2, 700], [3, 9999], [0, 500]]) {
          await deep(y);
          await tile(".coll-yours", n).tap();
          await sleep(90);
          await deep(y);
          await tile(".coll-yours", (n + 1) % 4).tap();
          await settle(`tap ${n} then ${(n + 1) % 4} from ${y}`);
        }
        // the tile already selected
        await deep(9999);
        const on = await page.evaluate(() => [...document.querySelectorAll(".coll-yours .coll-tile")].findIndex((t) => t.classList.contains("selected")));
        await tile(".coll-yours", Math.max(on, 0)).tap();
        await settle("the selected tile again");
        // a Coming soon tile
        await deep(9999);
        await tile(".coll-soon", 1).tap();
        await settle("a Coming soon tile");
        // a tap while a fling is still moving the page: a browser may spend that tap on stopping the
        // fling (Chrome and iOS deliver no click for it), so the player taps again on the page
        // where it stopped; the tap that reaches the tile must bring the stage back
        for (const n of [2, 3]) {
          await deep(0);
          // the tile aimed at, by its name: a click the moving page hands a neighbour does not count
          const want = (await tile(".coll-yours", n).locator(".coll-tile-name").textContent()).trim();
          await page.evaluate(() => { window.__tileTaps = []; document.addEventListener("click", (e) => {
            const t = e.target.closest?.(".coll-tile");
            if (t) window.__tileTaps.push(t.querySelector(".coll-tile-name")?.textContent?.trim() ?? ""); }, { capture: true }); });
          const reached = () => page.evaluate((w) => window.__tileTaps.includes(w), want);
          const y = Math.round(page.qa.d.h * 0.8);
          await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: 60, y }] });
          for (let i = 1; i <= 4; i++) {
            await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: 60, y: y - i * 90 }] });
            await sleep(8);
          }
          await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
          await sleep(60);
          await tile(".coll-yours", n).tap({ force: true });
          if (!(await reached())) {
            // the tap went to stopping the fling, or to a neighbour: tap the tile again where it stopped
            await sleep(400);
            await page.locator(".coll-yours .coll-tile", { hasText: want }).tap();
          }
          if (!(await reached())) {
            misses.push(`no tap on ${want} reached it after a fling (clicks: ${JSON.stringify(await page.evaluate(() => window.__tileTaps))})`);
            continue;
          }
          await settle(`a tap on ${want} during or just after a fling`);
          const shows = await onStage(page);
          if (shows !== `cmp-${want.toLowerCase()}`) misses.push(`after the tap on ${want} the stage shows ${shows}`);
        }
        await rep.check(`${device} every lower tap leaves the stage in view at the top`, misses.length ? misses.join("; ") : null, page);
      });
    }

    await scenario(rep, `${device} a link selects`, page, async () => {
      // followed in the open app: the address changes to the character's
      await page.goto(new URL("#/collection/chick", page.url()).href);
      await until(page, () => document.querySelector(".char-stage svg.cmp-chick") !== null, { timeout: 5000 });
      const hash = await page.evaluate(() => location.hash);
      await rep.check(`${device} #/collection/chick selects the Chick and leaves the plain address`,
        (await onStage(page)) === "cmp-chick" && hash === "#/collection" ? null : `${await onStage(page)} ${hash}`, page);
      // and opened fresh, as a shared link or a reload of one
      const fresh = await open(browser, device, { url: "#/collection/sparrow", setup, fakeSocket: fakeSocketScript([]),
        storage: { "shengji.coach": "off", "shengji.muted": "1" } });
      await until(fresh, () => document.querySelector(".char-stage svg.cmp") !== null, { timeout: 5000 });
      const loaded = { stage: await onStage(fresh), hash: await fresh.evaluate(() => location.hash) };
      await rep.check(`${device} a fresh load of #/collection/sparrow selects the Sparrow`,
        loaded.stage === "cmp-sparrow" && loaded.hash === "#/collection" ? null : JSON.stringify(loaded), fresh);
      await fresh.context().close();
    });

    // a guest cannot buy: the store's characters show as Coming soon, no price and no button
    await scenario(rep, `${device} coming soon`, page, async () => {
      await until(page, () => document.querySelector(".coll-soon .coll-tile") !== null, { timeout: 5000 });
      await page.locator(".coll-soon .coll-tile", { hasText: "Jade Rabbit" }).tap();
      await sleep(900);
      const got = await page.evaluate(() => {
        const s = document.querySelector(".char-stage").getBoundingClientRect();
        return {
          tiles: document.querySelectorAll(".coll-soon .coll-tile").length,
          rabbit: document.querySelector(".char-stage svg.cmp-rabbit") !== null,
          status: document.querySelector(".char-page .coll-status")?.textContent,
          button: document.querySelector(".char-page .coll-use") !== null,
          price: /\$|Buy|Shop/.test(document.querySelector(".coll-page").textContent),
          // a phone scrolls back up to the stage; a wide layout does not
          inView: s.top >= 0 && s.bottom <= innerHeight,
        };
      });
      await rep.check(`${device} a Coming soon tile selects its character with the status Coming soon and no button`,
        got.tiles === 7 && got.rabbit && got.status === "Coming soon" && !got.button && !got.price && (got.inView || !phone)
          ? null : JSON.stringify(got), page);
    });

    // a store character's tile wears the foil edge, and the stage shows what it adds with no words:
    // its two canvases, its entrance, and a stroll by itself that leaves its trail under the figure
    await scenario(rep, `${device} a store character's stage`, page, async () => {
      const foil = await page.evaluate(() => ({
        foil: [...document.querySelectorAll(".coll-tile.foil svg.cmp")].map((s) => [...s.classList].find((c) => /^cmp-(lamb|panda)$/.test(c)) ?? "other").sort(),
        plain: document.querySelectorAll(".coll-yours .coll-tile.foil").length,
        edge: getComputedStyle(document.querySelector(".coll-tile.foil")).borderTopWidth,
      }));
      await rep.check(`${device} the store characters' tiles wear the foil edge, and no free one does`,
        foil.foil.join() === "cmp-lamb,cmp-panda" && foil.plain === 0 && foil.edge === "2px" ? null : JSON.stringify(foil), page);
      await page.locator(".coll-soon .coll-tile.foil", { hasText: "Spring Lamb" }).tap();
      await until(page, () => document.querySelector(".char-stage svg.cmp-lamb") !== null, { timeout: 5000 });
      const drawn = await page.evaluate(() => {
        const stage = document.querySelector(".char-stage"), kids = [...stage.children];
        const at = (sel) => kids.findIndex((k) => k.matches(sel));
        return { back: at('canvas.char-flair[data-depth="back"]'), figures: at(".char-figures"), front: at('canvas.char-flair[data-depth="front"]'),
          strings: document.querySelector(".char-page").textContent.replace(/\s+/g, " ").trim() };
      });
      await rep.check(`${device} the Lamb's trail is drawn under the figure and its burst over it`,
        drawn.back === 0 && drawn.figures > drawn.back && drawn.front > drawn.figures ? null : JSON.stringify(drawn), page);
      // the stage watched from the top of the page
      await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 0; });
      // it strolls by itself within a few seconds, and pieces are painted behind it as it goes
      const strolled = await page.evaluate(() => new Promise((done) => {
        const walk = document.querySelector(".char-stage .char-walk"), back = document.querySelector('.char-stage canvas[data-depth="back"]');
        const t0 = performance.now();
        let moved = 0, painted = 0, under = true;
        const tick = () => {
          const dx = new DOMMatrixReadOnly(getComputedStyle(walk).transform).m41;
          moved = Math.max(moved, Math.abs(dx));
          const px = back.getContext("2d").getImageData(0, 0, back.width, back.height).data;
          let n = 0, sum = 0;
          for (let i = 3; i < px.length; i += 4) if (px[i] > 24) { n++; sum += ((i - 3) / 4) % back.width; }
          if (n > 0 && moved > 4) {
            painted = Math.max(painted, n);
            // the pieces' middle is behind the figure's: on the side it came from
            const mid = sum / n / (back.width / back.clientWidth) - back.clientWidth / 2;
            if (Math.sign(mid - dx) === Math.sign(dx) && Math.abs(dx) > 8) under = false;
          }
          if (performance.now() - t0 > 11000 || (painted > 0 && moved > 30)) done({ moved: Math.round(moved), painted, under }); else requestAnimationFrame(tick);
        };
        tick();
      }));
      await rep.check(`${device} the Lamb strolls across the stage by itself and leaves its trail behind it`,
        strolled.moved > 30 && strolled.painted > 0 && strolled.under ? null : JSON.stringify(strolled), page);
      // a tile's tap plays the character's entrance, and its special paints its accent on the stage's felt
      const painted = (ms, depth) => page.evaluate(([span, which]) => new Promise((done) => {
        const cs = [...document.querySelectorAll(".char-stage canvas")].filter((c) => !which || c.dataset.depth === which), t0 = performance.now();
        let most = 0;
        const tick = () => {
          for (const c of cs) { const px = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < px.length; i += 4) if (px[i] > 24) n++; most = Math.max(most, n); }
          if (performance.now() - t0 > span) done(most); else requestAnimationFrame(tick);
        };
        tick();
      }), [ms, depth]);
      await page.locator(".coll-soon .coll-tile.foil", { hasText: "Baby Panda" }).tap();
      await until(page, () => document.querySelector(".char-stage svg.cmp-panda") !== null, { timeout: 5000 });
      await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 0; });
      const entered = await painted(1600, "");
      await rep.check(`${device} a tap on the Panda's tile plays its entrance on the stage`, entered > 0 ? null : "nothing painted in 1.6 s", page);
      await page.locator(".coll-soon .coll-tile.foil", { hasText: "Baby Panda" }).tap();
      await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 0; });
      const again = await painted(1600, "");
      await rep.check(`${device} the selected tile tapped again plays the entrance again`, again > 0 ? null : "nothing painted in 1.6 s", page);
      await sleep(600);
      await page.locator(".char-stage .coll-figure").tap();
      const accent = await painted(2400, "front");
      await rep.check(`${device} the Panda's bamboo bite paints its leaf flecks on the stage`, accent > 0 ? null : "the front canvas stayed empty for 2.4 s", page);
      await page.locator(".coll-yours .coll-tile", { hasText: "Bun" }).tap();
      await until(page, () => document.querySelector(".char-stage svg.cmp-bun") !== null, { timeout: 5000 });
      const free = await page.evaluate(() => document.querySelectorAll(".char-stage canvas").length);
      await rep.check(`${device} a free companion's stage draws no canvas`, free === 0 ? null : `${free} canvases`, page);
    });

    if (phone) {
      await scenario(rep, `${device} tab swipe`, page, async () => {
        const y = Math.round(page.qa.d.h * 0.7);
        await swipe(cdp, 60, y, 240);
        await sleep(700);
        const hash = await page.evaluate(() => location.hash);
        await rep.check(`${device} a sideways drag still pages the tabs`, hash !== "#/collection" ? null : "stayed on Collection", page);
      });
    }
    await page.context().close();
  }
  // a mouse-only wide layout and a short one: the apex has the room the stage really gives it there
  for (const device of ["desktop", "desktop-1280x700"].filter((d) => !only || only.test(d))) {
    const page = await open(browser, device, { url: "#/collection", setup, fakeSocket: fakeSocketScript([]),
      storage: { "shengji.coach": "off", "shengji.muted": "1" } });
    await until(page, () => document.querySelector(".coll-yours .coll-tile") !== null);
    await stageBeats(page, device);
    await page.context().close();
  }
  // the stage's one status line, the colour's name and how it was got, stays one line at 320 px in every
  // language, for every look of every companion owned: a won count, a purchase, a gift, a locked colour
  if (!only || only.test("phone-320")) {
    const LAMB = "com.jerryyu.shengji.companion.lamb", PANDA = "com.jerryyu.shengji.companion.panda";
    const COLOURS = { tractor: ["red", "green", "blue", "yellow", "orange", "jade", "porcelain", "ink"], bun: ["plain", "custard", "taro", "peach"],
      chick: ["yellow", "cream", "cocoa", "ink"], sparrow: ["tree", "java", "snow", "oriole"], lamb: ["newyear", "jade", "ink", "lacquer"],
      panda: ["classic", "russet", "ink", "gilded"] };
    const me = (locked) => ({ name: "J", email: "j@x", picture: null, display_name: null, name_shown: "J", rounds_played: 1200, ranked_wins: locked ? 999 : 2000,
      ranked_games: 300, look: "tractor/red", companions: "individual", products: [LAMB, PANDA], features: { collection: true },
      purchased_on: { [LAMB]: "2025-11-27" }, gifts: [PANDA],
      looks: Object.entries(COLOURS).flatMap(([k, cs]) => cs.map((c, i) => {
        const product = k === "lamb" ? LAMB : k === "panda" ? PANDA : null;
        const earned = k === "tractor" && i > 0;
        return { id: `${k}/${c}`, unlocked: !(earned && locked), needs: earned ? { count: "ranked_wins", of: 1000 } : null, product };
      })) });
    for (const [lang, locked] of [["en", false], ["en", true], ["zh-Hans", false], ["zh-Hans", true], ["zh-Hant", false], ["zh-Hant", true]]) {
      const ctx = await browser.newContext({ viewport: { width: Number(process.env.LINE_W ?? 320), height: 640 }, hasTouch: true, deviceScaleFactor: 2 });
      const page = await ctx.newPage();
      await page.addInitScript((lang) => { try { localStorage.setItem("shengji.coach", "off"); localStorage.setItem("shengji.muted", "1");
        localStorage.setItem("shengji.automated", "1"); localStorage.setItem("shengji.language", lang); } catch {} }, lang);
      await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
      await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: "test.apps", device_accounts: false, collection: true } }));
      await page.route("**/api/me", (r) => r.fulfill({ json: me(locked) }));
      await page.addInitScript(fakeSocketScript([]));
      await page.goto(new URL("#/collection", BASE).href);
      const name = `phone-320 ${lang}${locked ? " locked" : ""}`;
      await scenario(rep, `${name} the stage's status line`, page, async () => {
        await page.waitForSelector(".coll-yours .coll-tile");
        const wrapped = [], lines = new Set();
        for (let i = 0; i < await page.locator(".coll-yours .coll-tile").count(); i++) {
          await page.locator(".coll-yours .coll-tile").nth(i).tap();
          await sleep(250);
          for (let j = 0; j < await page.locator(".char-swatches .coll-swatch").count(); j++) {
            await page.locator(".char-swatches .coll-swatch").nth(j).tap();
            const got = await page.evaluate(() => {
              const p = document.querySelector(".char-page .coll-status"), r = p.getBoundingClientRect(), lh = parseFloat(getComputedStyle(p).fontSize) * 1.6;
              const kids = [...p.children].map((k) => k.getBoundingClientRect());
              return { text: p.textContent, h: r.height, lh, inside: kids.every((k) => k.left >= r.left - 0.5 && k.right <= r.right + 0.5),
                oneRow: kids.every((k) => Math.abs(k.top - (kids[0]?.top ?? k.top)) < 1), fits: p.scrollWidth <= p.clientWidth + 1, onScreen: r.right <= innerWidth,
                shown: kids.map((k) => Math.round(k.width)) };
            });
            lines.add(got.text);
            if (process.env.SHOW_LINES) console.log(`${lang} ${got.text} -> ${got.shown.join("/")} px`);
            if (!(got.h <= got.lh && got.inside && got.oneRow && got.fits && got.onScreen)) wrapped.push(JSON.stringify(got));
          }
        }
        const how = [...lines].filter((l) => l.includes(" · "));
        await rep.check(`${name} the stage's status line is one line at 320 px for every look (${lines.size} lines)`,
          wrapped.length ? wrapped.slice(0, 3).join("; ") : lines.size >= 20 && how.length > 0 ? null : `only ${lines.size} lines read`, page);
      });
      await ctx.close();
    }
  }
  // the Stage · Table switch on a phone each way up, a tablet and a desktop window: at the stage's top right,
  // tappable, clear of the title and of the stage's figure; Table puts the figure wholly on the felt at the
  // size a real table (a scripted socket) seats yours on the same screen, within 1 px
  for (const device of ["phone-port", "phone-land", "ipad11-land", "desktop"].filter((d) => !only || only.test(d))) {
    const page = await open(browser, device, { url: "#/collection", setup, fakeSocket: fakeSocketScript([]),
      storage: { "shengji.coach": "off", "shengji.muted": "1" } });
    await scenario(rep, `${device} Stage · Table`, page, async () => {
      await until(page, () => document.querySelector(".char-view .segmented-btn") !== null);
      const press = (loc) => (page.qa.d.touch === false ? loc.click() : loc.tap());
      const rect = (sel) => page.evaluate((sel) => { const e = document.querySelector(sel); if (!e) return null;
        const b = e.getBoundingClientRect(); return { x: b.left, y: b.top, r: b.right, b: b.bottom }; }, sel);
      const meets = (a, b) => a.x < b.r && b.x < a.r && a.y < b.b && b.y < a.b;
      const sw = await rect(".char-view"), st = await rect(".char-stage"), title = await rect(".large-title"), fig = await rect(".char-figures svg.cmp");
      const top = sw && st && sw.y - st.y <= 12 && st.r - sw.r <= 12 && sw.y >= st.y && sw.r <= st.r;
      await rep.check(`${device} the switch sits at the stage's top right`, top ? null : JSON.stringify({ sw, st }), page);
      await rep.check(`${device} the switch overlaps neither the title nor the figure`,
        sw && (!title || !meets(sw, title)) && fig && !meets(sw, fig) ? null : JSON.stringify({ sw, title, fig }), page);
      const hit = await page.evaluate(() => { const b = [...document.querySelectorAll(".char-view .segmented-btn")][1].getBoundingClientRect();
        return document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2)?.closest(".segmented-btn")?.textContent ?? null; });
      await rep.check(`${device} Table is the topmost thing under its own centre`, hit === "Table" ? null : `hit ${hit}`, page);
      // each segment answers a tap over its full 44 px of height, nothing of it clipped by the stage
      const reach = () => page.evaluate(() => [...document.querySelectorAll(".char-view .segmented-btn")].map((b) => {
        const r = b.getBoundingClientRect(), x = r.left + r.width / 2, mid = r.top + r.height / 2;
        const miss = [];
        for (let dy = -21.5; dy <= 21.5; dy += 1) {
          if (document.elementFromPoint(x, mid + dy)?.closest(".segmented-btn") !== b) miss.push(dy);
        }
        return miss.length ? `${b.textContent}: missed at ${miss.join(",")}` : null;
      }).filter(Boolean));
      const missed = await reach();
      await rep.check(`${device} each segment is hit-testable over 44 px`, missed.length ? missed.join("; ") : null, page);
      await press(page.locator(".char-view .segmented-btn", { hasText: "Table" }));
      await until(page, () => document.querySelector(".char-seat .tc-move svg.cmp") !== null, { timeout: 6000 });
      await sleep(600);
      const missedTable = await reach();
      await rep.check(`${device} in Table each segment is still hit-testable over 44 px`, missedTable.length ? missedTable.join("; ") : null, page);
      const on = await page.evaluate(() => {
        const f = document.querySelector(".char-table").getBoundingClientRect(), s = document.querySelector(".char-seat .tc-move svg.cmp").getBoundingClientRect();
        return { inside: s.left >= f.left && s.right <= f.right && s.top >= f.top && s.bottom <= f.bottom, w: s.width, h: s.height,
          left: s.left - f.left, fromFoot: f.bottom - s.bottom, cards: document.querySelectorAll(".char-table .card, .char-table .opponent").length,
          you: document.querySelector(".char-table .tc-you")?.textContent ?? null };
      });
      await rep.check(`${device} Table puts the figure wholly on the felt, tagged You, by the bottom-left corner`,
        on.inside && on.you === "You" && on.left < on.w && on.fromFoot < on.h && on.cards === 0 ? null : JSON.stringify(on), page);
      const table = await open(browser, device, { setup, fakeSocket: fakeSocketScript([base({ turn: 1, players: [0, 1, 2, 3].map((s) => pl(s, {
        look: s === 0 ? "tractor/red" : null, is_bot: s !== 0, controller: s === 0 ? "human" : "bot" })) })]),
        storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.companions": "individual" } });
      await until(table, () => document.querySelector('.tc-seat[data-pos="bottom"] .tc-move svg.cmp') !== null, { timeout: 8000 });
      const seat = await table.evaluate(() => { const b = document.querySelector('.tc-seat[data-pos="bottom"] .tc-move svg.cmp').getBoundingClientRect();
        return Math.max(b.width, b.height); });
      await table.context().close();
      await rep.check(`${device} the figure is the table's bottom seat's size (${seat} px) within 1 px`,
        Math.abs(Math.max(on.w, on.h) - seat) <= 1 ? null : `stage ${Math.max(on.w, on.h)} vs table ${seat}`, page);
      await press(page.locator(".char-view .segmented-btn", { hasText: "Stage" }));
      await sleep(300);
      await rep.check(`${device} Stage brings the stage back`, (await rect(".char-figures svg.cmp")) && !(await rect(".char-table")) ? null : "still the table", page);
    });
    await page.context().close();
  }
  // the same lower taps in WebKit, the engine of the iOS app: a smooth scroll it is given while the page
  // shrinks under it (a Coming soon stage is shorter) is dropped there, not in Chrome
  const wk = await webkit.launch();
  try {
    for (const [device, w, h] of [["webkit phone-port", 390, 844], ["webkit phone-port-se", 375, 667]].filter(([d]) => !only || only.test(d))) {
      const ctx = await wk.newContext({ viewport: { width: w, height: h }, hasTouch: true, deviceScaleFactor: 2 });
      const page = await ctx.newPage();
      await page.addInitScript(() => { try { localStorage.setItem("shengji.coach", "off"); localStorage.setItem("shengji.muted", "1"); localStorage.setItem("shengji.automated", "1"); } catch {} });
      await setup(page);
      await page.goto(new URL("#/collection", BASE).href);
      await page.waitForSelector(".coll-yours .coll-tile");
      await scenario(rep, `${device} every lower tap scrolls up`, page, async () => {
        const misses = [];
        const tile = (sel, n) => page.locator(`${sel} .coll-tile`).nth(n);
        for (let i = 0; i < 12; i++) {
          await page.evaluate((y) => { document.querySelector(".coll-page").scrollTop = y; }, i % 2 ? 9999 : 600);
          await sleep(100);
          await tile(i % 3 === 0 ? ".coll-soon" : ".coll-yours", i % 4).tap();
          if (i % 4 === 1) { await sleep(80); await tile(".coll-yours", (i + 1) % 4).tap(); }
          if (i % 4 === 2) { await sleep(1000); await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 9999; }); await sleep(100);
            await page.locator(".coll-tile.selected").first().tap(); }
          await sleep(1000);
          const got = await page.evaluate(() => ({ top: Math.round(document.querySelector(".char-stage").getBoundingClientRect().top),
            scroll: Math.round(document.querySelector(".coll-page").scrollTop) }));
          if (!(got.top >= 0 && got.scroll <= 1)) misses.push(`tap ${i}: ${JSON.stringify(got)}`);
        }
        await rep.check(`${device} every lower tap leaves the stage in view at the top`, misses.length ? misses.join("; ") : null, page);
      });
      await ctx.close();
    }
    // a tablet in either orientation and a desktop window, in Chrome and in WebKit: the stage is above the
    // grid there too, so a tap on a lower tile (a Coming soon one, the one already selected) brings it back
    // fully into view
    const WIDE_DEVICES = ["ipad11-land", "ipad11-port", "ipad-mini-land", "ipad-mini-port", "desktop", "desktop-1280x700"];
    for (const [engine, b] of [["chromium", browser], ["webkit", wk]]) {
      for (const device of WIDE_DEVICES.filter((d) => !only || only.test(`${engine} ${d}`))) {
        const d = DEVICES_AT[device];
        const ctx = await b.newContext({ viewport: { width: d.w, height: d.h }, hasTouch: d.touch, deviceScaleFactor: 2 });
        const page = await ctx.newPage();
        await page.addInitScript(() => { try { localStorage.setItem("shengji.coach", "off"); localStorage.setItem("shengji.muted", "1"); localStorage.setItem("shengji.automated", "1"); } catch {} });
        await setup(page);
        await page.goto(new URL("#/collection", BASE).href);
        await page.waitForSelector(".coll-yours .coll-tile");
        const name = `${engine} ${device}`;
        await scenario(rep, `${name} every lower tap scrolls up`, page, async () => {
          const misses = [];
          const press = (loc) => (d.touch ? loc.tap() : loc.click());
          const tile = (sel, n) => page.locator(`${sel} .coll-tile`).nth(n);
          const deep = async (y) => {
            await page.evaluate((y) => { document.querySelector(".coll-page").scrollTop = y; }, y);
            await sleep(120);
            return page.evaluate(() => document.querySelector(".coll-page").scrollTop);
          };
          const inView = async (label) => {
            await sleep(1000);
            const got = await page.evaluate(() => {
              const s = document.querySelector(".char-stage").getBoundingClientRect();
              const bar = document.querySelector(".topbar, .home-topbar")?.getBoundingClientRect();
              return { top: Math.round(s.top), bottom: Math.round(s.bottom), floor: Math.round(bar ? bar.bottom : 0), h: innerHeight,
                scroll: Math.round(document.querySelector(".coll-page").scrollTop) };
            });
            if (!(got.top >= got.floor && got.bottom <= got.h)) misses.push(`${label} ${JSON.stringify(got)}`);
          };
          let scrolled = 0;
          for (const [sel, n, y] of [[".coll-yours", 1, 9999], [".coll-yours", 3, 500], [".coll-soon", 1, 9999], [".coll-yours", 2, 9999]]) {
            scrolled = Math.max(scrolled, await deep(y));
            await press(tile(sel, n));
            await inView(`${sel} ${n} from ${y}`);
          }
          await deep(9999);
          await press(page.locator(".coll-tile.selected").first());
          await inView("the selected tile again");
          if (scrolled <= 0) misses.push("the page never scrolled, so nothing was tested");
          await rep.check(`${name} every lower tap brings the stage fully into view`, misses.length ? misses.join("; ") : null, page);
        });
        await ctx.close();
      }
    }
  } finally {
    await wk.close();
  }
} finally {
  await browser.close();
}
process.exit(rep.done());
