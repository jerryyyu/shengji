// The nearby chaos simulator's command line. On demand only, never in CI:
//
//   npx tsx web/scripts/nearby-chaos/nearby-chaos.ts --games 200 --seed 1
//   npx tsx web/scripts/nearby-chaos/nearby-chaos.ts --replay nearby-chaos-1234.json --verbose
//
// --games N      games to run (seeds S, S+1, ...)
// --seed S       first seed (default 1)
// --seconds T    seconds of faults per game (default 240)
// --bound B      seconds a joiner has to be back after a fault clears (default 15;
//                a link broken with no word to the joiner gets 15 s more)
// --bug NAME     re-plant a fixed bug to check the simulator finds it:
//                tried (the look before the path watch: no fresh look on the
//                network's return, the tried set kept, 12 s looks), keepalive
//                (no peer-to-peer keepalive and no kept browse), migrate-stale
//                (a move off peer-to-peer stays spent on a link made with no
//                Wi-Fi network); with --replay, added to the replay's bugs
// --hostile      also duplicate frames inside a link (TCP never does): the
//                safety invariants still hold
// --page MODEL   the joiner page's reconnect: sim (default) or ws (ws.ts's
//                nearby retry waits, no connect timer, and long-lived retry,
//                pageModel.ts)
// --gaps MODE    the app's known gaps (S3: a reconnect under 3 s adds no
//                chat line; S4: a move pending at a rebuild is applied or
//                sent again within 1 s): report (counted as "gap ..." in the
//                totals, never failing) or strict (failing; --gap-only WORD
//                fails only on the gap whose name has WORD, e.g. pending)
// --new-faults   the device test's faults too: stallPhone (every frame of
//                one phone held, on all its links; two phones may overlap)
// --replay FILE  run one game from a replay file, deterministically
// --no-shrink    on a failure, keep the whole fault schedule
// --out DIR      where replay files go (default: the current directory)
// --verbose      print every trace line
//
// replays/ keeps games that once failed; each must replay with no violation:
//
//   for f in web/scripts/nearby-chaos/replays/*.json; do npx tsx web/scripts/nearby-chaos/nearby-chaos.ts --replay $f; done
//
// 581 and 1475 must fail again with --bug migrate-stale.
//
// replays/gaps/ keeps the app's known gaps (--gaps strict): each fails with
// its gap until the app closes it, and then moves up to replays/.
import { writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { runGame, type Fault, type GameOpts, type GameResult } from "./sim";
import type { PageModel } from "./pageModel";

interface Replay {
  seed: number;
  bugs: string[];
  seconds: number;
  bound: number;
  hostile: boolean;
  schedule: Fault[];
  invariant: string;
  page?: PageModel;
  gaps?: "off" | "report" | "strict";
  gapOnly?: string;
}

function args(argv: string[]): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const k = a.slice(2);
    const v = argv[i + 1];
    if (v === undefined || v.startsWith("--")) out[k] = true;
    else {
      out[k] = out[k] && k === "bug" ? `${String(out[k])},${v}` : v;
      i++;
    }
  }
  return out;
}

function fmtFault(f: Fault): string {
  return `t=${f.t.toFixed(1)} ${f.kind} ${f.who}${f.dur ? ` ${f.dur.toFixed(1)}s` : ""}${f.arg ? ` arg=${f.arg}` : ""}`;
}

/** Drops faults one at a time while the same invariant still fails. */
async function shrink(base: GameOpts, res: GameResult): Promise<GameResult> {
  let best = res;
  let schedule = res.schedule;
  for (let i = schedule.length - 1; i >= 0; i--) {
    const trial = schedule.filter((_, k) => k !== i);
    const r = await runGame({ ...base, schedule: trial, verbose: false });
    if (r.violation && r.violation.invariant === res.violation!.invariant) {
      schedule = trial;
      best = r;
    }
  }
  return best;
}

function report(r: GameResult, tail = 60): void {
  const v = r.violation!;
  console.log(`\nFAIL seed ${r.seed} at t=${v.t.toFixed(2)} s: [${v.invariant}] ${v.detail}`);
  console.log(`fault schedule (${r.schedule.length}):`);
  for (const f of r.schedule) console.log(`  ${fmtFault(f)}`);
  console.log(`last ${tail} trace lines:`);
  for (const l of r.trace.slice(-tail)) console.log(`  ${l}`);
}

function pct(xs: number[], q: number): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

async function main(): Promise<void> {
  const a = args(process.argv.slice(2));
  const out = typeof a.out === "string" ? a.out : ".";
  if (typeof a.replay === "string") {
    const rp = JSON.parse(readFileSync(a.replay, "utf8")) as Replay;
    const planted = typeof a.bug === "string" ? a.bug.split(",") : [];
    const r = await runGame({ seed: rp.seed, bugs: [...rp.bugs, ...planted], seconds: rp.seconds, bound: rp.bound, hostile: rp.hostile,
                              schedule: rp.schedule, verbose: a.verbose === true, page: rp.page,
                              gaps: a.gaps === "report" || a.gaps === "strict" ? a.gaps : rp.gaps,
                              gapOnly: typeof a["gap-only"] === "string" ? a["gap-only"] : rp.gapOnly });
    if (r.violation) {
      report(r, a.verbose ? 0 : 200);
      process.exitCode = 1;
    } else console.log(`replay seed ${rp.seed}: no violation (expected [${rp.invariant}])`);
    return;
  }
  const games = Number(a.games ?? 100);
  const seed0 = Number(a.seed ?? 1);
  const base = {
    bugs: typeof a.bug === "string" ? a.bug.split(",") : [],
    seconds: Number(a.seconds ?? 240),
    bound: Number(a.bound ?? 15),
    hostile: a.hostile === true,
    verbose: a.verbose === true,
    newFaults: a["new-faults"] === true,
    page: (a.page === "ws" ? "ws" : "sim") as PageModel,
    gaps: (a.gaps === "report" || a.gaps === "strict" ? a.gaps : "off") as "off" | "report" | "strict",
    gapOnly: typeof a["gap-only"] === "string" ? a["gap-only"] : undefined,
  };
  const totals: Record<string, number> = {};
  const recoveries: number[] = [];
  const freezes: number[] = [];
  const failures: { seed: number; invariant: string; game: number }[] = [];
  const started = Date.now();
  for (let g = 0; g < games; g++) {
    const seed = seed0 + g;
    const opts: GameOpts = { ...base, seed };
    let r = await runGame(opts);
    for (const [k, v] of Object.entries(r.stats)) totals[k] = (totals[k] ?? 0) + v;
    recoveries.push(...r.recoveries);
    freezes.push(...r.freezes);
    if (r.violation) {
      failures.push({ seed, invariant: r.violation.invariant, game: g + 1 });
      if (a["no-shrink"] !== true) r = await shrink(opts, r);
      report(r);
      const rp: Replay = { seed, bugs: base.bugs, seconds: base.seconds, bound: base.bound, hostile: base.hostile,
                           schedule: r.schedule, invariant: r.violation!.invariant, page: base.page, gaps: base.gaps, gapOnly: base.gapOnly };
      const file = join(out, `nearby-chaos-${seed}.json`);
      writeFileSync(file, JSON.stringify(rp, null, 2));
      console.log(`replay: npx tsx web/scripts/nearby-chaos/nearby-chaos.ts --replay ${file}`);
      if (a["keep-going"] !== true) break;
    }
    if ((g + 1) % 50 === 0) console.log(`... ${g + 1} games, ${failures.length} failing, ${((Date.now() - started) / 1000).toFixed(0)} s`);
  }
  const ran = failures.length && a["keep-going"] !== true ? failures[0].game : games;
  console.log(`\n${ran} game(s) from seed ${seed0}${base.bugs.length ? `, planted [${base.bugs.join(",")}]` : ""}: ${failures.length} failing` +
              `${failures.length ? ` (first in game ${failures[0].game}, seed ${failures[0].seed}: ${failures[0].invariant})` : ""}`);
  console.log(`totals: ${Object.entries(totals).map(([k, v]) => `${k} ${v}`).join(", ")}`);
  const spread = (xs: number[]) => `n=${xs.length} p50 ${pct(xs, 0.5).toFixed(1)} s p95 ${pct(xs, 0.95).toFixed(1)} s max ${pct(xs, 1).toFixed(1)} s`;
  console.log(`recovery after a fault: ${spread(recoveries)}`);
  console.log(`freeze, last frame heard to back: ${spread(freezes)}`);
  console.log(`wall ${((Date.now() - started) / 1000).toFixed(0)} s`);
  if (failures.length) process.exitCode = 1;
}

void main();
