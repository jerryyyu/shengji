// The Collection's character page goes back to the grid on a swipe from the
// screen's left edge, measured with real touch input (CDP
// Input.dispatchTouchEvent, so the browser's own hit testing picks the
// target): a finger put down at x = 2, 6 or 20 returns to the grid, one at
// x = 60 leaves the page as it is, on a phone and on an iPad. A sideways drag
// over the page's title stays on the page (it does not page the tabs), while
// on the grid the phone's tab swipe still works.
//   node e2e/collection.mjs [device-regex]
import { Report, launch, open, scenario, sleep, until } from "./lib.mjs";
import { fakeSocketScript } from "./fake.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const rep = new Report("collection", { partial: !!only });
const DEVICES = ["phone-port", "ipad11-land"].filter((d) => !only || only.test(d));

/** A guest the server shows the Collection to: the four free companions. */
async function setup(page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: null, device_accounts: false, collection: true } }));
}

const title = (page) => page.evaluate(() => document.querySelector(".large-title")?.textContent ?? "");

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
    const y = Math.round(page.qa.d.h * 0.45);
    for (const x of [2, 6, 20, 60]) {
      await scenario(rep, `${device} x=${x}`, page, async () => {
        if ((await title(page)) !== "Collection") await page.goto(new URL("#/collection", page.url()).href);
        await until(page, () => document.querySelector(".coll-yours .coll-tile") !== null);
        await page.locator(".coll-yours .coll-tile", { hasText: "Bun" }).tap();
        await until(page, () => document.querySelector(".large-title")?.textContent === "Bun");
        await swipe(cdp, x, y, 160);
        await sleep(400);
        const now = await title(page);
        const hash = await page.evaluate(() => location.hash);
        const want = x < 24 ? "Collection" : "Bun";
        await rep.check(`${device} drag from x=${x}`, now === want ? null : `expected ${want}, on ${now} (${hash})`, page);
        if (x >= 24) await rep.check(`${device} x=${x} stays on its tab`, hash === "#/collection/bun" ? null : `address ${hash}`, page);
      });
    }
    // a sideways drag over the page's title stays on the page: the page does not
    // page the tabs anywhere on it; on the grid the tab swipe still works
    await scenario(rep, `${device} title swipe`, page, async () => {
      if ((await title(page)) !== "Collection") await page.goto(new URL("#/collection", page.url()).href);
      await until(page, () => document.querySelector(".coll-yours .coll-tile") !== null);
      await page.locator(".coll-yours .coll-tile", { hasText: "Tractor" }).tap();
      await until(page, () => document.querySelector(".large-title")?.textContent === "Tractor");
      const ty = await page.evaluate(() => Math.round(document.querySelector(".large-title").getBoundingClientRect().top + 10));
      await swipe(cdp, 24, ty, 171);
      await sleep(500);
      const on = await page.evaluate(() => [location.hash, document.querySelector(".large-title")?.textContent ?? ""]);
      await rep.check(`${device} drag over the title from x=24`, on[0] === "#/collection/tractor" && on[1] === "Tractor" ? null
        : `left the page: ${on.join(" ")}`, page);
      if (page.qa.d.w >= 700) return;                   // the tab swipe is the phone's
      await page.goto(new URL("#/collection", page.url()).href);
      await until(page, () => document.querySelector(".large-title")?.textContent === "Collection");
      await swipe(cdp, 60, y, 240);
      await sleep(700);
      const grid = await page.evaluate(() => location.hash);
      await rep.check(`${device} the grid still pages the tabs`, grid !== "#/collection" ? null : "a rightward drag on the grid stayed on Collection", page);
    });
    await page.context().close();
  }
} finally {
  await browser.close();
}
process.exit(rep.done());
