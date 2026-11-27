// The table's frame time with four seated companions, for a base-vs-head
// measurement: each seat a different look, idle (their own loops and fidgets),
// on a phone held sideways, with the CPU slowed 4x. Prints the median and p90
// frame interval over 10 s and the SVG shapes the four figures draw.
//   BASE=<url> node e2e/figuresTiming.mjs [runs]
import { BASE, launch, open, sleep } from "./lib.mjs";
import { base, fakeSocketScript, pl } from "./fake.mjs";

const RUNS = Number(process.argv[2] ?? 3);
const LOOKS = ["lamb/lacquer", "tractor/red", "panda/gilded", "sparrow/tree"];
const frame = base({ players: [0, 1, 2, 3].map((s) => pl(s, { look: LOOKS[s], is_bot: false, controller: "human" })) }, { humans: [0, 1, 2, 3] });
async function setup(page) {
  await page.route("**/api/**", (r) => r.fulfill({ status: 404, json: { detail: "none" } }));
  await page.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: null, device_accounts: false, collection: true } }));
}
const browser = await launch();
const all = [];
let nodes = 0;
try {
  for (let run = 0; run < RUNS; run++) {
    const page = await open(browser, "phone-land", { setup, fakeSocket: fakeSocketScript([frame]),
      storage: { "shengji.coach": "off", "shengji.muted": "1", "shengji.companions": "individual" } });
    for (let i = 0; i < 100 && (await page.evaluate(() => document.querySelectorAll(".tc-move svg.cmp").length)) < 4; i++) await sleep(100);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await sleep(1500);
    const got = await page.evaluate(async () => {
      const out = [];
      let last = performance.now();
      const t0 = last;
      while (performance.now() - t0 < 10000) {
        await new Promise((r) => requestAnimationFrame(r));
        const t = performance.now(); out.push(t - last); last = t;
      }
      return { dt: out, nodes: [...document.querySelectorAll(".tc-move svg.cmp")].reduce((n, s) => n + s.querySelectorAll("*").length, 0),
               figures: document.querySelectorAll(".tc-move svg.cmp").length };
    });
    all.push(...got.dt.slice(1));
    nodes = got.nodes;
    console.error(`run ${run + 1}: ${got.figures} figures, ${got.nodes} SVG nodes, ${got.dt.length} frames`);
    await page.context().close();
  }
} finally {
  await browser.close();
}
const sorted = [...all].sort((a, b) => a - b);
const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
console.log(JSON.stringify({ base: BASE, frames: sorted.length, median_ms: +q(0.5).toFixed(2), p90_ms: +q(0.9).toFixed(2), p99_ms: +q(0.99).toFixed(2), svg_nodes: nodes }));
