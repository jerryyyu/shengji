import { launch, open, sleep } from "../lib.mjs";
const OUT = "/Users/jerryyu/.claude/jobs/d0498cda/tmp/zh_mocks/raw/";
const b = await launch();
const page = await open(b, "phone-port", { base: "http://127.0.0.1:8000/", native: process.env.NATIVE === "1", storage: { "shengji.muted": "1" } });
await sleep(2500);
await page.screenshot({ path: OUT + "explore_home.png" });
console.log(await page.evaluate(() => document.body.innerText));
console.log(await page.evaluate(() => [...document.querySelectorAll("button,a,[role=tab]")].map(e => e.tagName + ":" + (e.getAttribute("aria-label")||"") + ":" + e.textContent.trim().slice(0,40)).join("\n")));
await b.close();
