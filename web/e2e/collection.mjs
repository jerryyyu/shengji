// The Collection is one page, measured in a real browser: a tap on a tile
// selects its character into the stage at the top, in place (the address
// stays #/collection, no history entry, the tile ringed); on a phone a tile
// tapped further down scrolls the page back up to the stage; a link to
// #/collection/<kind> selects that character and leaves the plain address;
// the phone's sideways tab swipe still works on the page. Real touch input
// (CDP Input.dispatchTouchEvent) lets the browser's own hit testing pick
// targets. A guest, who cannot buy, sees the store characters as Coming soon.
//   node e2e/collection.mjs [device-regex]
import { Report, launch, open, scenario, sleep, until } from "./lib.mjs";
import { fakeSocketScript } from "./fake.mjs";

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

/** The table's moves on the stage, sampled from the browser's own computed style: Ready keeps its larger
 *  size between its bobs, a tap on the figure ends a beat at once, and Big play's apex stays inside the
 *  stage. `press` is "tap" on a touch device, "click" with a mouse. */
async function stageBeats(page, device, press = page.qa.d.touch === false ? "click" : "tap") {
  await scenario(rep, `${device} stage beats`, page, async () => {
      await page.evaluate(() => { document.querySelector(".coll-page").scrollTop = 0; });
      await page.locator(".coll-yours .coll-tile", { hasText: "Bun" })[press]();
      await sleep(500);
      const chip = (name) => page.locator(".char-poses .char-move", { hasText: name });
      const scaleAt = (times) => page.evaluate(async (ts) => {
        const box = document.querySelector(".char-stage .char-box");
        const t0 = performance.now();
        const out = [];
        for (const t of ts) {
          while (performance.now() - t0 < t) await new Promise((r) => requestAnimationFrame(r));
          const m = getComputedStyle(box).transform;
          out.push(m === "none" ? 1 : new DOMMatrix(m).a);
        }
        return out;
      }, times);
      await chip("Ready")[press]();
      // in the gaps between the jump and the bobs, and between the bobs (bobs start at 520, 1620, 2720 ms)
      const gaps = await scaleAt([1150, 2250, 3350]);
      await rep.check(`${device} Ready holds its larger size between its bobs`,
        gaps.every((a) => a > 1.12) ? null : `scale in the gaps ${gaps.map((a) => a.toFixed(2)).join(", ")}`, page);
      await sleep(1200);
      const after = await scaleAt([0]);
      await rep.check(`${device} Ready ends at the figure's own size`, Math.abs(after[0] - 1) < 0.01 ? null : `scale ${after[0]}`, page);

      await chip("Ready")[press]();
      await sleep(600);
      await page.locator(".char-stage .coll-figure")[press]();
      const cut = await page.evaluate(async () => {
        const box = document.querySelector(".char-stage .char-box");
        const seen = [];
        const t0 = performance.now();
        while (performance.now() - t0 < 3500) {
          await new Promise((r) => requestAnimationFrame(r));
          seen.push(box.getAnimations().length + (getComputedStyle(box).transform === "none" ? 0 : 10));
        }
        return { worst: Math.max(...seen), pose: document.querySelector(".char-stage svg.cmp")?.getAttribute("data-pose") };
      });
      await rep.check(`${device} a tap on the figure ends Ready at once`, cut.worst === 0 ? null : JSON.stringify(cut), page);

      await sleep(1500);
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

    // the stage, its colours and its button fit above the tab bar on the first view,
    // and Try on your table does not move the controls under the stage
    await scenario(rep, `${device} fit and try-on`, page, async () => {
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
      const where = () => page.evaluate(() => Math.round(document.querySelector(".char-swatches").getBoundingClientRect().top));
      const before = await where();
      await page.locator(".char-chip").tap();
      await sleep(300);
      const after = await where();
      await page.locator(".char-chip").tap();
      await sleep(300);
      await rep.check(`${device} Try on your table keeps the controls in place`, Math.abs(after - before) <= 1 ? null
        : `the swatches moved ${after - before}px`, page);
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
} finally {
  await browser.close();
}
process.exit(rep.done());
