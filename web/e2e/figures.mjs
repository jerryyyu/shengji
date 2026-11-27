// A companion at the table is the figure the Collection shows, measured in a
// real browser on the real app: for every look, the account wears it, the
// Collection's stage draws it, and a table seats it (a scripted socket); the
// table's figure, with the team's neckwear (every `cmp-team` shape) taken
// out, has the stage's shapes, paints and textures, and drawn at one size
// the two are the same picture. Reduce Motion holds both still in idle.
//   node e2e/figures.mjs [look-regex]
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

/** In the page: the figure `sel`'s shapes, its id taken out and its team shapes left out, and its picture
 *  drawn at 176 px with those shapes removed, as RGBA bytes in base64. */
// Shapes the table repaints in the team's colour rather than adds (the Tractor's waist stripe and its
// rider's neckerchief, which a preview draws in the colourway's own paint), left out of both figures.
const REPAINTED = ["M92 196H228", "M136 178Q158 190 180 178L182 186Q158 200 134 186Z"];
const read = (page, sel) => page.evaluate(async ([sel, repainted]) => {
  const svg = document.querySelector(sel).cloneNode(true);
  for (const el of svg.querySelectorAll(".cmp-team, .cmp-team-lo, .cmp-team-shade, .cmp-team-line")) el.remove();
  for (const el of svg.querySelectorAll("path")) if (repainted.includes(el.getAttribute("d"))) el.remove();
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
  return { shapes, px: btoa(s), n: svg.querySelectorAll("*").length };
}, [sel, REPAINTED]);

const browser = await launch();
try {
  const opts = { setup, storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.companions": "individual" } };
  const coll = await open(browser, "phone-port", { url: "#/collection", fakeSocket: fakeSocketScript([]), ...opts });
  await coll.emulateMedia({ reducedMotion: "reduce" });
  const frame = (look) => base({ players: [0, 1, 2, 3].map((s) => pl(s, { look: s === 0 || s === 2 ? look : null, is_bot: s % 2 === 1,
    controller: s % 2 ? "bot" : "human" })) });
  for (const look of all) {
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
      await rep.check(`${look}: drawn at one size, the two are the same picture`, mean < 0.5 ? null : `mean channel difference ${mean.toFixed(2)}`, table);
      await table.context().close();
    });
  }
} finally {
  await browser.close();
}
process.exit(rep.done());
