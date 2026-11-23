import fs from "node:fs";
import { launch, sleep } from "../lib.mjs";
import { page, snap, OUT } from "./shots.mjs";
import { fakeSocketScript, push } from "../fake.mjs";
import { DECLARE, PLAY, ROUND_END } from "./game.mjs";
const lang = process.argv[2] ?? "en";
const only = process.argv[3] ? new RegExp(process.argv[3]) : null;
const strings = {};
const b = await launch();
const want = (n) => !only || only.test(n);

if (want("home")) {
  const p = await page(b, "phone-port", lang);
  await p.waitForSelector("text=/Play|开始/"); await sleep(2000);
  await snap(p, "01_home", lang, strings);
  await p.context().close();
}
if (want("table")) {
  const p = await page(b, "phone-port", lang);
  await sleep(2000);
  await p.locator(".seg-btn, button", { hasText: /^(Casual|休闲)$/ }).first().click(); await sleep(300);
  await p.locator("button", { hasText: /^(Play|开始)$/ }).first().click(); await sleep(2500);
  await snap(p, "02_yourtable", lang, strings);
  const ts = p.locator("button", { hasText: /Table settings|桌面设置|牌桌设置/ }).first();
  if (await ts.count()) { await ts.click(); await sleep(500); }
  await snap(p, "02b_yourtable_settings", lang, strings);
  await p.context().close();
}
if (want("board")) {
  const p = await page(b, "phone-port", lang, { signedIn: true });
  await sleep(1500);
  await p.locator("button", { hasText: /^(Leaderboard|排行榜)$/ }).last().click(); await sleep(1500);
  await snap(p, "06_leaderboard", lang, strings);
  await p.context().close();
}
if (want("me")) {
  const p = await page(b, "phone-port", lang, { signedIn: true });
  await sleep(1500);
  await p.locator("button", { hasText: /^(Me|我)$/ }).last().click(); await sleep(1500);
  await snap(p, "05_me", lang, strings);
  // The proposed Language row, drawn as a Me row (a mock: the app has none yet).
  await p.evaluate(() => {
    const hap = (document.querySelector(".me-settings .me-haptics") ?? document.querySelector(".me-settings .me-sound")).closest("li");
    const li = document.createElement("li");
    li.innerHTML = '<button type="button" class="grp-row me-language"><span class="grp-label">Language</span><span class="grp-value chev me-language-value">English</span></button>';
    hap.after(li);
  });
  await sleep(300);
  await p.evaluate(() => document.querySelector("#me-settings-head")?.scrollIntoView({ block: "start" })); await sleep(400);
  await snap(p, "05b_me_settings", lang, strings);
  await p.evaluate(() => {
    const li = document.querySelector(".me-language").closest("li");
    const zh = document.documentElement.lang.startsWith("zh");
    const opts = ["Follow system", "English", "中文"];
    const on = zh ? 2 : 1;
    const ul = document.createElement("div");
    ul.className = "grp-inset";
    ul.innerHTML = '<ul class="grp" style="margin:0">' + opts.map((o, i) => '<li><button type="button" class="grp-row"><span class="grp-label">' + o + '</span><span class="grp-value" style="color:var(--accent,#e9b949);font-weight:600">' + (i === on ? "✓" : "") + '</span></button></li>').join("") + '</ul>';
    li.appendChild(ul);
  });
  await sleep(300);
  await snap(p, "05c_me_language", lang, strings);
  await p.context().close();
}
if (want("game")) {
  for (const [name, frame] of [["03a_declare", DECLARE], ["03b_play", PLAY], ["04_roundend", ROUND_END]]) {
    const p = await page(b, "phone-land", lang, { fake: fakeSocketScript([frame]), signedIn: true, storage: { "shengji.coach": "on" } });
    await p.waitForSelector(".table-screen", { timeout: 10000 }); await sleep(1500);
    await snap(p, name, lang, strings);
    if (name === "04_roundend") {
      const d = p.locator("text=/^(Details|详情)$/").first();
      if (await d.count()) { await d.click(); await sleep(500); await snap(p, "04b_roundend_details", lang, strings); }
    }
    await p.context().close();
  }
}
if (want("nearby")) {
  const host = await page(b, "phone-port", lang, { nearby: true });
  const join = await page(b, "phone-port", lang, { nearby: true, storage: { "shengji.name": "Quiet Panda", "shengji.nearbyAllowed": "1" } });
  await host.exposeFunction("__nbRelay", (m) => join.evaluate((m) => window.__nbEmit(m.ev, m.payload), m));
  await join.exposeFunction("__nbRelay", (m) => host.evaluate((m) => window.__nbEmit(m.ev, m.payload), m));
  await sleep(2000);
  await host.locator("button, a", { hasText: /^(Play offline|离线玩)$/ }).first().click(); await sleep(1500);
  await snap(host, "07a_offline_table", lang, strings);
  await host.locator("[role=switch].q-row, [role=switch]", { hasText: /^(Nearby|面对面)$/ }).first().click(); await sleep(1500);
  await snap(host, "07b_nearby_host", lang, strings);
  const code = await host.evaluate(() => document.querySelector("[aria-label^='Table code'], [aria-label^='房间号']").getAttribute("aria-label").replace(/ /g, ""));
  const c5 = code.slice(-5);
  await join.locator("input").first().fill(c5); await sleep(400);
  await snap(join, "07c_nearby_code", lang, strings);
  await join.locator("button", { hasText: /^(Join|加入)$/ }).first().click(); await sleep(2500);
  await snap(join, "07d_nearby_join", lang, strings);
  await join.locator("button", { hasText: /^(Join|加入)$/ }).first().click(); await sleep(2000);
  await snap(host, "07e_nearby_host_joined", lang, strings);
  await host.context().close(); await join.context().close();
}
fs.writeFileSync(`${OUT}strings_${lang}${only ? "_part" : ""}.json`, JSON.stringify(strings, null, 1));
await b.close();
