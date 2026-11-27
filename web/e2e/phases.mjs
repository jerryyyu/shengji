// The table keeps its geometry across phases on a phone: one trick-area
// size through the bury, play and round end, the side seats' labels where
// they are, and the hand's cards one size while the banker holds the kitty.
//   node e2e/phases.mjs [device-regex]
import { Report, launch, open, sleep } from "./lib.mjs";
import { HAND25, base, fakeSocketScript, hand, plays, push } from "./fake.mjs";

const only = process.argv[2] ? new RegExp(process.argv[2]) : null;
const DEVICES = ["phone-land", "phone-land-se", "phone-land-app"].filter((d) => !only || only.test(d));

const BURY33 = hand([...HAND25, "S7", "S10", "H5", "H9", "D3", "DK", "C6", "LJ"]);
const result = { attacker_points: 50, kitty_points: 15, kitty_cards: ["S5", "H10", "D3", "D4", "C6", "C7", "S8", "H9"], winner_team: 0,
  level_change: 2, next_banker: 2, new_levels: ["4", "2"], games_won: [0, 0], point_scored: false, game_over: false };
// the declare window keeps its row under the cross; it is measured, not checked
const STATES = [
  ["declare", base({ phase: "declare", banker: null, trump: null, turn: null, trick: null, attacker_points: 0, declare_deadline: 12,
    declare_options: [[18]], current_declaration: { seat: 1, cards: ["H2"] } }, { banker: null })],
  ["bury_me", base({ phase: "bury", banker: 0, turn: 0, trick: null, attacker_points: 0, hand: BURY33 }, { banker: 0 })],
  ["play_me", base({ banker: 0, turn: 0, trick: { leader: 0, plays: [] }, attacker_points: 0 }, { banker: 0 })],
  ["bury_other", base({ phase: "bury", banker: 1, turn: 1, trick: null, attacker_points: 0 }, { banker: 1 })],
  ["play_other", base({ banker: 1, turn: 1, trick: { leader: 1, plays: plays(1, 2, 1) }, attacker_points: 0 }, { banker: 1 })],
  ["round_end", base({ phase: "round_end", turn: null, trick: null, attacker_points: 50, hand: [], round_result: result,
    last_trick: { leader: 0, plays: plays(0, 4, 1), winner: 0, points: 10 } }, { banker: 0 })],
];

const measure = (page) => page.evaluate(() => {
  const r = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
  };
  return { trick: r(".trick-area"), card: r(".hand .hand-slot .card"), oppL: r(".opponent.pos-left"), oppR: r(".opponent.pos-right"),
    phase: [...document.querySelector(".table-screen").classList].find((c) => c.startsWith("phase-")) };
});
const off = (a, b) => (a && b ? Math.max(...a.map((v, i) => Math.abs(v - b[i]))) : 0);

const rep = new Report("phases", { partial: !!only });
const browser = await launch();
for (const device of DEVICES) {
  const page = await open(browser, device, { storage: { "shengji.coach": "off", "shengji.muted": "1" },
    fakeSocket: fakeSocketScript([STATES[0][1]]), still: true });
  await page.waitForSelector(".table-screen", { timeout: 10000 });
  const at = {};
  for (const [id, frame] of STATES) {
    await push(page, frame);
    await sleep(600);
    at[id] = await measure(page);
  }
  console.log(device, JSON.stringify(at));
  const ref = at.play_me;
  for (const id of ["bury_me", "bury_other", "play_other", "round_end"]) {
    const d = off(at[id].trick, ref.trick);
    await rep.check(`${device} ${id}: the trick area is play's`, d <= 1 ? null
      : `${JSON.stringify(at[id].trick)} vs play's ${JSON.stringify(ref.trick)} (${d}px)`, page);
    for (const side of ["oppL", "oppR"]) {
      // its top: a banker's crown may widen the label, never move it
      const s = at[id][side] && ref[side] ? Math.abs(at[id][side][1] - ref[side][1]) : 0;
      await rep.check(`${device} ${id}: the ${side === "oppL" ? "left" : "right"} seat's label stays`, s <= 1 ? null
        : `${JSON.stringify(at[id][side])} vs play's ${JSON.stringify(ref[side])} (${s}px)`, page);
    }
  }
  const c = Math.abs(at.bury_me.card[3] - ref.card[3]);
  await rep.check(`${device} the banker's 33 keep the hand's card size`, c <= 0.5 ? null
    : `a card ${at.bury_me.card[3]}px tall while burying, ${ref.card[3]}px in play`, page);
  if (page.qa.errors.length) await rep.check(`${device} page errors`, page.qa.errors.splice(0));
  await page.context().close();
}
await browser.close();
process.exit(rep.done());
