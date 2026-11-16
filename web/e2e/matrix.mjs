// Table layout across game states, on every device size: no key element may
// cover another, leave the screen, or cut its text. The states come from a
// scripted socket, so combinations a live game reaches by luck are all here
// (you are banker x it is not your turn x you have played x the trick is wide).
//   node e2e/matrix.mjs [device-regex] [state-regex]
import { Report, launch, lint, open, shot, sleep } from "./lib.mjs";
import { HAND25, LONG_NAMES, base, fakeSocketScript, hand, plays, push } from "./fake.mjs";

const onlyDev = process.argv[2] ? new RegExp(process.argv[2]) : null;
const onlyState = process.argv[3] ? new RegExp(process.argv[3]) : null;
const SHOTS = process.env.SHOTS ? new RegExp(process.env.SHOTS) : null;

const last = (leader, width, winner) => ({ leader, plays: plays(leader, 4, width), winner, points: 10 });

/** [id, frames...]: the last frame is the one checked; earlier ones set it up. */
function states() {
  const out = [];
  for (const banker of [0, 1, 2, 3]) {
    for (const leader of banker >= 2 ? [0, banker === 2 ? 3 : 2] : [0, 1, 2, 3]) {
      for (const n of [0, 1, 2, 3]) {
        for (const width of n === 0 ? [1] : [1, 6]) {
          out.push([`play_b${banker}_l${leader}_n${n}_w${width}`,
            base({ trick: { leader, plays: plays(leader, n, width) }, turn: (leader + n) % 4, last_trick: last(0, 1, 0) }, { banker })]);
        }
      }
    }
    // the trick just filled: it lingers with its WINS tag
    for (const winner of [0, 1, 2, 3]) {
      for (const width of [1, 6]) {
        out.push([`full_b${banker}_win${winner}_w${width}`,
          base({ trick: { leader: 1, plays: plays(1, 3, width) }, turn: 0 }, { banker }),
          base({ trick: { leader: winner, plays: [] }, turn: winner, last_trick: last(1, width, winner) }, { banker })]);
      }
    }
  }
  // long names, every seat
  for (const leader of [0, 1]) for (const n of [1, 3]) {
    out.push([`long_l${leader}_n${n}`, base({ trick: { leader, plays: plays(leader, n, 2) }, turn: (leader + n) % 4 }, { banker: 0, names: LONG_NAMES })]);
  }
  // declare window
  const dealt = { phase: "declare", banker: null, trump: null, turn: null, trick: null, attacker_points: 0, declare_deadline: 12 };
  out.push(["declare_open", base({ ...dealt, declare_options: [[18], [24]] }, { banker: null })]);
  out.push(["declare_none", base({ ...dealt }, { banker: null })]);
  out.push(["declare_passed", base({ ...dealt, passed: [0, 1, 3] }, { banker: null })]);
  for (const seat of [0, 1, 2, 3]) {
    out.push([`declare_by${seat}`, base({ ...dealt, declare_options: [[18]], current_declaration: { seat, cards: ["H2"] }, passed: [1] }, { banker: null })]);
    out.push([`declare_pair_by${seat}_long`, base({ ...dealt, current_declaration: { seat, cards: ["H2", "H2"] } }, { banker: null, names: LONG_NAMES })]);
  }
  // bury
  out.push(["bury_me", base({ phase: "bury", banker: 0, turn: 0, trick: null, attacker_points: 0, hand: hand([...HAND25, "S7", "S10", "H5", "H9", "D3", "DK", "C6", "LJ"]) }, { banker: 0 })]);
  out.push(["bury_other", base({ phase: "bury", banker: 1, turn: 1, trick: null, attacker_points: 0 }, { banker: 1 })]);
  // people away, a bot holding a seat, someone joining
  out.push(["away_partner", (() => { const s = base({ trick: { leader: 1, plays: plays(1, 1, 1) }, turn: 2 }, { banker: 0 }); s.players[2].connected = false; s.players[2].takeover_in = 22; return s; })()]);
  out.push(["bot_holds_partner", (() => { const s = base({ trick: { leader: 1, plays: plays(1, 2, 2) }, turn: 3 }, { banker: 2 }); s.players[2].controller = "bot"; s.players[2].reserved_for = "Alice"; s.players[2].reserved_secs = 90; return s; })()]);
  out.push(["joining", base({ trick: { leader: 1, plays: plays(1, 2, 1) }, turn: 3, joining: [{ seat: 3, name: "Maximilian Featherst", when: "trick" }] }, { banker: 0 })]);
  out.push(["failed_throw", base({ trick: { leader: 0, plays: plays(0, 1, 1) }, turn: 1, notice: { id: 1, kind: "failed_throw", seat: 0, attempted: ["SA", "SK", "S9"], forced: ["S9"] } }, { banker: 0 })]);
  out.push(["ranked_clock", (() => { const s = base({ matched: true, ranked: true, trick: { leader: 1, plays: plays(1, 3, 2) }, turn: 0 }, { banker: 0 }); s.players[0].turn_deadline = 8; return s; })()]);
  out.push(["few_cards", base({ hand: hand(["S3", "HK"]), trick: { leader: 3, plays: plays(3, 1, 2) }, turn: 0 }, { banker: 0 })]);
  // round end
  const result = { attacker_points: 50, kitty_points: 15, kitty_cards: ["S5", "H10", "D3", "D4", "C6", "C7", "S8", "H9"], winner_team: 1, level_change: 1, next_banker: 3, new_levels: ["2", "3"], games_won: [0, 0], point_scored: false, game_over: false };
  out.push(["round_end", base({ phase: "round_end", turn: null, trick: null, attacker_points: 50, hand: [], last_trick: last(0, 1, 0), round_result: result }, { banker: 1 })]);
  out.push(["round_end_long", base({ phase: "round_end", turn: null, trick: null, attacker_points: 50, hand: [], last_trick: last(0, 6, 0), round_result: result }, { banker: 1, names: LONG_NAMES })]);
  return out;
}

const rep = new Report("matrix", { partial: !!(onlyDev || onlyState) });
const browser = await launch();
// A finished trick lingers about 1.5 s and a toast about 4 s, into whatever state comes next.
// A new trick's plays end the linger at once, so the finished tricks run back to back at the
// end, and the toasts after them: nothing has to be waited out.
const rank = ([, ...frames]) => (f_has_toast(frames) ? 2 : frames.length > 1 ? 1 : 0);
const all = states().filter(([id]) => !onlyState || onlyState.test(id)).sort((a, b) => rank(a) - rank(b));
async function runDevice(device) {
  for (const coach of ["off", "on"]) {
    const page = await open(browser, device, { storage: { "shengji.coach": coach, "shengji.muted": "1" }, fakeSocket: fakeSocketScript([all[0][1]]), still: true });
    await page.waitForSelector(".table-screen", { timeout: 10000 });
    for (const [id, ...frames] of all) {
      // the coach changes only the line above the hand: a thinner pass is enough
      if (coach === "on" && !/_b[01]_l[0-3]_n[13]_w[16]|declare|bury|few|full_b0/.test(id)) continue;
      for (const f of frames) { await push(page, f); await sleep(frames.length > 1 ? 120 : 0); }
      await sleep(110);
      const name = `${device}_${coach === "on" ? "coach_" : ""}${id}`;
      await rep.check(name, await lint(page), page);
      if (SHOTS && SHOTS.test(name)) await shot(page, name);
      if (page.qa.errors.length) { await rep.check(`${name}_pageerror`, page.qa.errors.splice(0)); }
    }
    await sleep(4300);   // the last toast and the last finished trick go
    if (!onlyState) {
      // the last trick, opened over a wide trick
      await push(page, base({ trick: { leader: 1, plays: plays(1, 2, 6) }, turn: 3, last_trick: last(0, 6, 2) }, { banker: 0, names: LONG_NAMES }));
      await sleep(1600);
      const btn = page.locator(".last-trick-btn");
      if (await btn.count()) {
        await btn.click(); await sleep(300);
        await rep.check(`${device}_${coach}_last_trick_open`, (await lint(page)).filter((v) => typeof v === "string" || v.cut), page);
        if (SHOTS) await shot(page, `${device}_last_trick_open`);
        await btn.click(); await sleep(200);
      }
    }
    if (id_round_details(all)) {
      await push(page, all.find(([id]) => id === "round_end")[1]); await sleep(200);
      const details = page.locator("text=Details").first();
      if (await details.count()) {
        await details.click(); await sleep(250);
        await rep.check(`${device}_${coach}_round_end_details`, await lint(page), page);
        if (SHOTS) await shot(page, `${device}_round_end_details`);
      }
    }
    await page.context().close();
  }
}
const devices = ["phone-land", "phone-land-app", "phone-land-safari", "phone-land-safari-short", "phone-land-se", "phone-port", "ipad", "desktop"]
  .filter((d) => !onlyDev || onlyDev.test(d));
// a few devices at a time: each is its own page, and the checks are independent
const lanes = Number(process.env.LANES ?? 3);
await Promise.all(Array.from({ length: lanes }, async () => { for (let d; (d = devices.shift()); ) await runDevice(d); }));
function f_has_toast(frames) { const f = frames[frames.length - 1]; return !!f.notice || (f.joining ?? []).length > 0; }
function id_round_details(list) { return list.some(([id]) => id === "round_end"); }
await browser.close();
process.exit(rep.done());
