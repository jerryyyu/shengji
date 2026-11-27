// Two people at one table on a real server (BASE, started with
// COLLECTION_ENABLED=1): a tap on A's companion plays its special on B's
// screen, and a tap on A's felt parks A's companion, which B sees walk away
// and stay; a page that comes back (a rejoin, B's or A's own) draws it at the parked spot.
//   COLLECTION_ENABLED=1 server; BASE=<server url> node e2e/companionShare.mjs
import { Report, launch, open, scenario, sleep, until } from "./lib.mjs";
import { toTable } from "./drive.mjs";

const rep = new Report("companionShare");
const browser = await launch();
try {
  const storage = { "shengji.coach": "off", "shengji.muted": "1", "shengji.companions": "individual" };
  const a = await open(browser, "phone-port", { storage: { ...storage, "shengji.name": "Ana" } });
  let b = null;
  await scenario(rep, "two people at one table", a, async () => {
    const code = await toTable(a, "casual");
    b = await open(browser, "phone-port", { url: `?code=${code}`, storage: { ...storage, "shengji.name": "Bo" } });
    await b.click(".tp-primary");
    await until(a, () => (window.__qa.last.queue_state?.table?.seats ?? []).filter(Boolean).length === 2, { timeout: 15000 });
    await sleep(300);
    // the table starts once both are in, or on each person's Start
    for (const p of [a, b]) await p.click(".tp-primary", { timeout: 3000 }).catch(() => {});
    const both = await until(b, () => window.__qa.state !== null && document.querySelectorAll(".tc-seat").length >= 2, { timeout: 30000 });
    await rep.check("both see two companions", both ? null : "no table companions on B", b);
  });
  if (!b) throw new Error("no second page");
  const seatA = await a.evaluate(() => window.__qa.state.you);
  const figure = (seat) => `.tc-seat[data-seat="${seat}"]`;
  // the deal lands before anything is tapped
  await until(a, () => window.__qa.state?.phase !== "deal", { timeout: 60000 });
  await sleep(1500);

  await scenario(rep, "A's special plays on B's screen", b, async () => {
    await a.locator(".tc-mine").click({ force: true });
    const seen = await until(b, (s) => document.querySelector(`${s} svg.cmp`)?.getAttribute("data-pose") === "react", { arg: figure(seatA), timeout: 4000, every: 50 });
    await rep.check("B sees A's companion play its special", seen ? null : "A's figure on B never played react", b);
  });

  await scenario(rep, "A parks its companion and B sees it walk there", b, async () => {
    await sleep(5500);
    const where = (s) => b.evaluate((s) => document.querySelector(`${s} .tc-walk`)?.style.transform ?? "", s);
    const before = await where(figure(seatA));
    const felt = await a.evaluate(() => { const r = document.querySelector(".felt").getBoundingClientRect(); return { x: r.x + r.width * 0.5, y: r.y + r.height * 0.42 }; });
    await a.mouse.click(felt.x, felt.y);
    await sleep(4500);
    const after = await where(figure(seatA));
    // on B, A's figure stands by the same point of the felt (both screens the same size here)
    const near = await b.evaluate((s) => {
      const r = document.querySelector(".felt").getBoundingClientRect();
      const f = document.querySelector(`${s} svg.cmp`).getBoundingClientRect();
      const want = { x: r.x + r.width * 0.5, y: r.y + r.height * 0.42 };
      const d = Math.hypot(f.x + f.width / 2 - want.x, f.y + f.height / 2 - want.y);
      return { d: Math.round(d), w: Math.round(f.width) };
    }, figure(seatA));
    await rep.check("B sees A's companion move to where A parked it",
      after && after !== before && near.d <= 2 * Math.max(near.w, 40) ? null : `${before} -> ${after}, ${near.d}px from the parked point`, b);
    // B comes back: the frame it reads places A's companion where it was parked
    await b.reload();
    const back = await until(b, (s) => document.querySelector(`${s} .tc-walk`)?.style.transform ?? null, { arg: figure(seatA), timeout: 30000 });
    await sleep(1500);
    // at the parked spot again, give or take the small walks a figure takes round its home
    const nearAgain = await b.evaluate((s) => {
      const r = document.querySelector(".felt").getBoundingClientRect();
      const f = document.querySelector(`${s} svg.cmp`).getBoundingClientRect();
      const d = Math.hypot(f.x + f.width / 2 - (r.x + r.width * 0.5), f.y + f.height / 2 - (r.y + r.height * 0.42));
      return { d: Math.round(d), w: Math.round(f.width) };
    }, figure(seatA));
    await rep.check("after a reload B draws A's companion at the parked spot",
      back && nearAgain.d <= 2 * Math.max(nearAgain.w, 40) ? null : `${nearAgain.d}px from the parked point`, b);
    // A, the owner, comes back too: its own companion stands where it parked it
    await a.reload();
    await until(a, () => document.querySelector(".tc-mine") !== null, { timeout: 30000 });
    await sleep(1500);
    const own = await a.evaluate(() => {
      const r = document.querySelector(".felt").getBoundingClientRect();
      const f = document.querySelector(".tc-mine svg.cmp").getBoundingClientRect();
      const d = Math.hypot(f.x + f.width / 2 - (r.x + r.width * 0.5), f.y + f.height / 2 - (r.y + r.height * 0.42));
      return { d: Math.round(d), w: Math.round(f.width) };
    });
    await rep.check("after a reload A draws its own companion at the parked spot",
      own.d <= 2 * Math.max(own.w, 40) ? null : `${own.d}px from the parked point`, a);
  });
} finally {
  await browser.close();
}
process.exit(rep.done());
