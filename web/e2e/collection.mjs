// The Collection is one page, measured in a real browser: a tap on a tile
// selects its character into the stage at the top, in place (the address
// stays #/collection, no history entry, the tile ringed); on a phone a tile
// tapped further down scrolls the page back up to the stage; a link to
// #/collection/<kind> selects that character and leaves the plain address;
// the phone's sideways tab swipe still works on the page. Real touch input
// (CDP Input.dispatchTouchEvent) lets the browser's own hit testing pick
// targets.
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
} finally {
  await browser.close();
}
process.exit(rep.done());
