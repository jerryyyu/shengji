// A companion at the table is the figure the Collection shows, measured in a
// real browser on the real app: for every look, the account wears it, the
// Collection's stage draws it, and a table seats it (a scripted socket); the
// table's figure has the stage's shapes, paints and textures, every one and
// no other (no figure wears a team's colour), and drawn at one size the two
// are the same picture. Reduce Motion holds both still in idle. On the home
// felt your own figure stands inside the felt, and through the felt's whole
// loop, and after a tap aimed at the middle cards, it touches no card and no
// text, on a phone, an iPad and a desktop.
//   node e2e/figures.mjs [look-regex]   ("home" runs the home felt alone)
import { Report, launch, open, scenario, sleep, until } from "./lib.mjs";
import { base, fakeSocketScript, pl } from "./fake.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const rep = new Report("figures", { partial: !!only });
const LAMB = "com.jerryyu.shengji.companion.lamb", PANDA = "com.jerryyu.shengji.companion.panda";
const LOOKS = {
  tractor: ["red", "green", "blue", "yellow", "orange", "jade", "porcelain", "ink"],
  bun: ["plain", "custard", "taro", "peach"], chick: ["yellow", "cream", "cocoa", "ink"],
  sparrow: ["tree", "java", "snow", "oriole"], lamb: ["newyear", "jade", "ink", "lacquer"],
  panda: ["classic", "russet", "ink", "gilded"],
};
const home = !only || only.test("home");
const all = Object.entries(LOOKS).flatMap(([k, cs]) => cs.map((c) => `${k}/${c}`)).filter((l) => !only || only.test(l));
const product = (look) => ({ lamb: LAMB, panda: PANDA })[look.split("/")[0]] ?? null;
const user = (look) => ({
  name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry", rounds_played: 40,
  ranked_wins: 2000, ranked_games: 300, look, companions: "individual", products: [LAMB, PANDA], features: { collection: true },
  looks: all.concat(Object.entries(LOOKS).flatMap(([k, cs]) => cs.map((c) => `${k}/${c}`))).filter((v, i, a) => a.indexOf(v) === i)
    .map((id) => ({ id, unlocked: true, needs: null, product: product(id) })),
});
let wearing = all[0];
async function setup(page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: "test.apps", device_accounts: false, collection: true } }));
  await page.route("**/api/me", (r) => r.fulfill({ json: user(wearing) }));
}

/** In the page: the figure `sel`'s shapes, its id taken out, whether anything of a team is on it, and its
 *  picture drawn at 176 px, as RGBA bytes in base64. */
const read = (page, sel) => page.evaluate(async ([sel]) => {
  const live = document.querySelector(sel);
  const team = /cmp-(us|them)/.test(live.getAttribute("class") ?? "") || live.querySelector('[class*="cmp-team"]') !== null;
  const svg = live.cloneNode(true);
  const id = /url\(#[a-z]+-([A-Za-z0-9]+)\)/.exec(svg.innerHTML)?.[1] ?? "";
  const norm = svg.innerHTML.split(id).join("ID");
  const doc = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${norm}</svg>`, "image/svg+xml");
  const shapes = [...doc.documentElement.querySelectorAll("*")].map((el) =>
    `${el.tagName} ${[...el.attributes].map((a) => `${a.name}=${a.value}`).sort().join(" ")}`);
  svg.setAttribute("width", "176"); svg.setAttribute("height", "176");
  svg.removeAttribute("class"); svg.removeAttribute("style");
  svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const img = new Image();
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg.outerHTML);
  await img.decode();
  const c = document.createElement("canvas"); c.width = 176; c.height = 176;
  const g = c.getContext("2d"); g.drawImage(img, 0, 0, 176, 176);
  const px = g.getImageData(0, 0, 176, 176).data;
  let s = ""; for (let i = 0; i < px.length; i += 8192) s += String.fromCharCode(...px.subarray(i, i + 8192));
  return { shapes, px: btoa(s), n: svg.querySelectorAll("*").length, team };
}, [sel]);

/** In the page: the home figure's box, and every card and text box it overlaps (a card or tag drawn at
 *  all), or that it is not wholly inside the felt. */
const homeClash = (page) => page.evaluate(() => {
  const r = (el) => el.getBoundingClientRect();
  const fig = document.querySelector(".home-cmp svg.cmp");
  const felt = document.querySelector(".lobby-preview");
  if (!fig || !felt) return { missing: true, clash: [] };
  const a = r(fig), f = r(felt);
  const shown = (el) => { for (let e = el; e && e !== felt; e = e.parentElement) if (Number(getComputedStyle(e).opacity) < 0.02) return false; return true; };
  const cards = [...felt.querySelectorAll(".lp-fan .card, .lp-flip .card")].filter(shown).map((el) => ["card", el]);
  const text = [...document.querySelectorAll(".win-tag, .game-title, .account-pill")].filter(shown).map((el) => ["text", el]);
  const clash = [];
  for (const [what, el] of cards.concat(text)) {
    const b = r(el);
    if (b.width && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) clash.push(`${what} ${el.className} ${el.getAttribute("title") ?? el.textContent?.slice(0, 12)}`);
  }
  const inside = a.left >= f.left && a.right <= f.right && a.top >= f.top && a.bottom <= f.bottom;
  return { missing: false, inside, clash, box: [a.left - f.left, a.top - f.top, a.width].map(Math.round) };
});

/** The home felt's own figure at three sizes: on the felt, and clear of cards and text all loop long. */
async function homeFelt(opts) {
  wearing = "lamb/newyear";
  for (const device of ["phone-port", "ipad", "desktop"]) {
    const page = await open(browser, device, { fakeSocket: fakeSocketScript([]), ...opts });
    await scenario(rep, `home felt: your companion on the felt (${device})`, page, async () => {
      await until(page, () => document.querySelector(".home-cmp svg.cmp-lamb") !== null, { timeout: 8000 });
      const first = await homeClash(page);
      await rep.check(`${device}: home felt: your own figure stands wholly inside the felt`, first.inside ? null : `figure at ${first.box}`, page);
      // the felt's loop (three tricks and the empty table) is under 12 s; every 120 ms, a tap at the middle cards half way
      const seen = new Set();
      let outside = 0;
      const t0 = Date.now();
      let tapped = false;
      while (Date.now() - t0 < 13000) {
        if (!tapped && Date.now() - t0 > 6000) {
          tapped = true;
          const f = await page.locator(".lobby-preview").boundingBox();
          await page.mouse.click(f.x + f.width / 2, f.y + f.height * 0.5);
        }
        const c = await homeClash(page);
        if (c.missing || !c.inside) outside++;
        for (const x of c.clash) seen.add(x);
        await sleep(120);
      }
      await rep.check(`${device}: home felt: through the loop and a tap at the middle cards it covers no card and no text`,
        seen.size ? [...seen].slice(0, 4).join(" | ") : null, page);
      await rep.check(`${device}: home felt: it never leaves the felt`, outside ? `${outside} samples outside` : null, page);
      // a store character's tap on the figure is its special
      await page.locator(".home-cmp .coll-figure").click();
      await until(page, () => document.querySelector(".home-cmp svg.cmp")?.getAttribute("data-pose") === "react", { timeout: 3000 }).catch(() => {});
      const pose = await page.evaluate(() => document.querySelector(".home-cmp svg.cmp")?.getAttribute("data-pose"));
      await rep.check(`${device}: home felt: a tap on the Lamb plays its special`, pose === "react" ? null : `pose ${pose}`, page);
      if (process.env.HOME_SHOTS) await page.screenshot({ path: `${process.env.HOME_SHOTS}/home-${device}.png` });
    });
    await page.context().close();
  }
}

const browser = await launch();
try {
  const opts = { setup, storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.companions": "individual" } };
  const coll = await open(browser, "phone-port", { url: "#/collection", fakeSocket: fakeSocketScript([]), ...opts });
  await coll.emulateMedia({ reducedMotion: "reduce" });
  const frame = (look) => base({ players: [0, 1, 2, 3].map((s) => pl(s, { look: s === 0 || s === 2 ? look : null, is_bot: s % 2 === 1,
    controller: s % 2 ? "bot" : "human" })) });
  for (const look of home && only ? [] : all) {
    wearing = look;
    await scenario(rep, `${look} at the table and on the stage`, coll, async () => {
      await coll.reload();
      await until(coll, (k) => document.querySelector(`.char-stage svg.cmp-${k}`) !== null, { arg: look.split("/")[0], timeout: 8000 });
      await sleep(300);
      const stage = await read(coll, ".char-stage svg.cmp");
      const table = await open(browser, "phone-land", { fakeSocket: fakeSocketScript([frame(look)]), ...opts });
      await table.emulateMedia({ reducedMotion: "reduce" });
      await until(table, (k) => document.querySelector(`.tc-move svg.cmp-${k}`) !== null, { arg: look.split("/")[0], timeout: 8000 });
      await sleep(300);
      const seat = await read(table, ".tc-move svg.cmp");
      const missing = stage.shapes.filter((s) => !seat.shapes.includes(s)), extra = seat.shapes.filter((s) => !stage.shapes.includes(s));
      await rep.check(`${look}: the table figure has the stage figure's shapes, paints and textures`,
        missing.length || extra.length ? `missing ${missing.length} (${missing.slice(0, 2).join(" | ")}), extra ${extra.length} (${extra.slice(0, 2).join(" | ")})` : null, table);
      const a = Buffer.from(stage.px, "base64"), b = Buffer.from(seat.px, "base64");
      let diff = 0; for (let i = 0; i < a.length; i++) diff += Math.abs(a[i] - b[i]);
      const mean = diff / a.length;
      await rep.check(`${look}: nothing of a team is drawn on the table's figure or the stage's`, !seat.team && !stage.team ? null : `team marks: table ${seat.team}, stage ${stage.team}`, table);
      await rep.check(`${look}: drawn at one size, the two are the same picture`, mean < 0.5 ? null : `mean channel difference ${mean.toFixed(2)}`, table);
      await table.context().close();
    });
  }
  if (home) await homeFelt(opts);
} finally {
  await browser.close();
}
process.exit(rep.done());
