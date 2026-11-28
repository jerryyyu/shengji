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
import { webkit } from "playwright-core";
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
  // the figure's middle against its strip (px from the felt's middle), less the move box's own sway
  const strip = document.querySelector(".home-cmp")?.getAttribute("data-strip")?.split(",").map(Number);
  const walk = document.querySelector(".home-cmp .char-walk").getBoundingClientRect();
  const mid = walk.left + walk.width / 2 - (f.left + f.width / 2);
  const onStrip = !strip || (mid >= strip[0] - 1 && mid <= strip[1] + 1);
  return { missing: false, inside, onStrip, mid: Math.round(mid * 10) / 10, strip, clash, box: [a.left - f.left, a.top - f.top, a.width].map(Math.round) };
});

/** Sample the home figure every `every` ms for `ms`, while `during` runs: the problems seen, and how many
 *  samples found the figure drawn (`seen`). */
async function sampleHome(page, ms, during = async () => {}, every = 40) {
  const bad = new Set();
  let seen = 0;
  let stop = false;
  const sampling = (async () => {
    const t0 = Date.now();
    while (!stop && Date.now() - t0 < ms) {
      const c = await homeClash(page);
      if (!c.missing) {
        seen++;
        for (const x of c.clash) bad.add(x);
        if (!c.inside) bad.add(`outside the felt at ${c.box}`);
        if (!c.onStrip) bad.add(`middle ${c.mid} off its strip ${c.strip}`);
      }
      await sleep(every);
    }
  })();
  await during();
  await sampling;
  stop = true;
  return Object.assign([...bad], { seen });
}
/** A tap on the felt `share` of the way across and `down` of the way down: at half height it is above the
 *  figure, so it lands on the felt, never on the figure. */
const feltTap = async (page, share, down = 0.5) => {
  const f = await page.locator(".lobby-preview").boundingBox();
  await page.mouse.click(f.x + f.width * share, f.y + f.height * down);
};
/** The way the home figure faces (1 right, -1 left), where its middle stands, and once its special has
 *  started, the signed travel of its lunge's keyframes from there (px; none when no lunge plays). */
const homeFacing = (page) => page.evaluate(() => {
  const face = document.querySelector(".home-cmp .char-face");
  const dir = /scaleX\(-1\)/.test(face?.style.transform ?? "") ? -1 : 1;
  const walk = document.querySelector(".home-cmp .char-walk");
  const at = Number(/translate\((-?[\d.]+)px/.exec(walk?.style.transform ?? "")?.[1] ?? 0);
  return { dir, at };
});
const lungeTravel = (page) => page.evaluate(() => {
  const walk = document.querySelector(".home-cmp .char-walk");
  const xs = walk.getAnimations().flatMap((a) => a.effect.getKeyframes().map((k) => Number(/translate\((-?[\d.]+)px/.exec(k.transform)?.[1])));
  return xs.filter((x) => Number.isFinite(x));
});
const figureSize = (page) => page.evaluate(() => Number(document.querySelector(".home-cmp svg.cmp")?.getAttribute("width") ?? 0));

/** Where the home figure is drawn now: its middle, in px from the felt's middle. */
const drawnAt = (page) => page.evaluate(() => {
  const f = document.querySelector(".home-cmp").getBoundingClientRect(), w = document.querySelector(".home-cmp .char-walk").getBoundingClientRect();
  return w.left + w.width / 2 - (f.left + f.width / 2);
});

/** Touch taps on the felt, as a finger lands them, in Chromium and WebKit at two iPhones and an iPad: a tap
 *  anywhere on the felt (above the cards, beside them, on the figure's own strip) is the felt's, and walks
 *  the figure toward it; a tap on the figure plays its special. */
async function homeTouch(opts, browsers) {
  // left and right in turn, so each tap asks it to walk the other way
  const taps = [["high on the left", 0.08, 0.25], ["high on the right", 0.92, 0.3], ["beside the cards on the left", 0.3, 0.7], ["on its strip at the right", 0.97, 0.94]];
  for (const [engine, b] of browsers) {
    for (const device of ["phone-port", "phone-port-max", "ipad"]) {
      const page = await open(b, device, { fakeSocket: fakeSocketScript([]), ...opts });
      await scenario(rep, `home felt: touch taps walk it (${engine} ${device})`, page, async () => {
        await until(page, () => document.querySelector(".home-cmp svg.cmp") !== null, { timeout: 8000 });
        await sleep(400);
        const f = await page.locator(".lobby-preview").boundingBox();
        const bad = [];
        for (const [where, sx, sy] of taps) {
          const x = f.x + f.width * sx, y = f.y + f.height * sy;
          const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest(".home-cmp") !== null, [x, y]);
          const before = await drawnAt(page);
          await page.touchscreen.tap(x, y);
          await sleep(1700);
          const after = await drawnAt(page);
          const want = Math.sign(x - (f.x + f.width / 2) - before);
          if (!hit || Math.sign(after - before) !== want || Math.abs(after - before) < 8) bad.push(`${where}: felt hit ${hit}, ${Math.round(before)} -> ${Math.round(after)}`);
        }
        await rep.check(`${engine} ${device}: home felt: a touch tap anywhere on the felt walks the figure toward it`, bad.length ? bad.join(" | ") : null, page);
        const fig = await page.locator(".home-cmp .coll-figure").boundingBox();
        await page.touchscreen.tap(fig.x + fig.width / 2, fig.y + fig.height / 2);
        await until(page, () => document.querySelector(".home-cmp svg.cmp")?.getAttribute("data-pose") === "react", { timeout: 3000 }).catch(() => {});
        const pose = await page.evaluate(() => document.querySelector(".home-cmp svg.cmp")?.getAttribute("data-pose"));
        await rep.check(`${engine} ${device}: home felt: a touch tap on the Lamb plays its special`, pose === "react" ? null : `pose ${pose}`, page);
      });
      await page.context().close();
    }
  }
}

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
  // a short phone's felt is wider than its centred card stage: the figure fits beside it, down to 320x600
  const se = await open(browser, "phone-port-se", { fakeSocket: fakeSocketScript([]), ...opts });
  await scenario(rep, "home felt: short phones", se, async () => {
    for (const [w, h] of [[375, 667], [320, 600]]) {
      await se.setViewportSize({ width: w, height: h });
      await until(se, () => document.querySelector(".home-cmp svg.cmp") !== null, { timeout: 4000 }).catch(() => {});
      const px = await figureSize(se);
      const bad = await sampleHome(se, 2500, async () => { await sleep(300); await feltTap(se, 0.5); });
      await rep.check(`${w}x${h}: home felt: the figure fits (${px} px) and covers no card or text`, px >= 24 && !bad.length ? null : `size ${px}; ${bad.slice(0, 3).join(" | ")}`, se);
    }
  });
  await se.context().close();
  // the felt laid out anew mid-walk, and drawn again after a size with no room for it
  const rs = await open(browser, "phone-port", { fakeSocket: fakeSocketScript([]), ...opts });
  await scenario(rep, "home felt: resized", rs, async () => {
    await rs.setViewportSize({ width: 430, height: 940 });
    await until(rs, () => document.querySelector(".home-cmp svg.cmp") !== null, { timeout: 8000 });
    await sleep(500);
    let bad = await sampleHome(rs, 4000, async () => {
      await feltTap(rs, 0.98);
      await sleep(450);
      await rs.setViewportSize({ width: 390, height: 844 });
    });
    await rep.check("home felt: resized from 430x940 to 390x844 mid-walk, it stays on its strip, inside the felt, clear of cards and text", bad.length ? bad.slice(0, 3).join(" | ") : null, rs);
    await rs.setViewportSize({ width: 844, height: 390 });
    await sleep(600);
    const gone = await rs.evaluate(() => document.querySelector(".home-cmp svg.cmp") === null);
    bad = await sampleHome(rs, 3000, async () => { await rs.setViewportSize({ width: 390, height: 844 }); });
    // back upright it must be drawn again: an absent figure is a failure, not a pass
    const back = await rs.evaluate(() => document.querySelector(".home-cmp svg.cmp") !== null);
    await rep.check("home felt: after a size with no felt and back, it is drawn again, on its strip, clear of every card",
      gone && back && bad.seen >= 20 && !bad.length ? null : `gone ${gone}; back ${back}; drawn in ${bad.seen} samples; ${bad.slice(0, 3).join(" | ")}`, rs);
  });
  await rs.context().close();
  // the Lamb's special facing each way, its step back and its lunge sampled: at rest mid-strip facing right
  // (the step back is toward the hand), then mid-strip facing left (the lunge is toward the hand)
  const sp = await open(browser, "phone-port", { fakeSocket: fakeSocketScript([]), ...opts });
  await scenario(rep, "home felt: the Lamb's special both ways", sp, async () => {
    await until(sp, () => document.querySelector(".home-cmp svg.cmp") !== null, { timeout: 8000 });
    await sleep(300);
    // facing right at its spot: the lunge goes right of it, never back past the strip's end
    const special = async (want) => {
      const before = await homeFacing(sp);
      let travel = [];
      const bad = await sampleHome(sp, 1600, async () => {
        await sp.locator(".home-cmp .coll-figure").click();
        await sleep(60);
        travel = await lungeTravel(sp);
      }, 20);
      const out = travel.map((x) => x - before.at);
      const lunged = out.some((d) => Math.sign(d) === want && Math.abs(d) >= 2);
      return { before, out, lunged, bad };
    };
    let r = await special(1);
    await rep.check("home felt: the Lamb's special facing right at its spot lunges right, its step back on its strip, clear of every card",
      r.before.dir === 1 && r.lunged && r.bad.seen >= 15 && !r.bad.length ? null
        : `facing ${r.before.dir}; lunge ${r.out.map(Math.round)}; drawn ${r.bad.seen}; ${r.bad.slice(0, 3).join(" | ")}`, sp);
    // walked to the strip's right end, then back to its middle by a tap on the felt above it: it faces left
    const strip = await sp.evaluate(() => document.querySelector(".home-cmp").getAttribute("data-strip").split(",").map(Number));
    const fw = (await sp.locator(".lobby-preview").boundingBox()).width;
    await feltTap(sp, 0.98);
    await sleep(1700);
    await feltTap(sp, 0.5 + (strip[0] + strip[1]) / 2 / fw);
    await sleep(1700);
    r = await special(-1);
    await rep.check("home felt: the Lamb's special facing left mid-strip lunges left, on its strip, clear of every card",
      r.before.dir === -1 && r.lunged && r.bad.seen >= 15 && !r.bad.length ? null
        : `facing ${r.before.dir}; lunge ${r.out.map(Math.round)}; drawn ${r.bad.seen}; ${r.bad.slice(0, 3).join(" | ")}`, sp);
  });
  await sp.context().close();
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
  if (home) {
    await homeFelt(opts);
    const wk = await webkit.launch();
    try { await homeTouch(opts, [["chromium", browser], ["webkit", wk]]); } finally { await wk.close(); }
  }
} finally {
  await browser.close();
}
process.exit(rep.done());
