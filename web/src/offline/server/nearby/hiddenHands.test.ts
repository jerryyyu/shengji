// @vitest-environment node
// The hidden-hand property: over seeded nearby games with two to four people,
// some of whom drop out and come back, no frame built for seat s carries a
// card that is not s's own or already public. Each frame is checked twice:
// where the room builds it (server.enqueue, against the true round at that
// moment) and where it crosses the link (every host-to-joiner frame on the
// fake transport must be one the room built for that joiner's seat, or carry
// no card at all).
//
// NEARBY_PROPERTY_ROUNDS sets the number of rounds (default 150 in CI; the
// milestone bar of 1,000 is run with NEARBY_PROPERTY_ROUNDS=1000).
import { describe, expect, it } from "vitest";
import type { Card } from "../../engine/cards";
import type { RoundState } from "../../engine/round";
import type { Seat } from "../server";
import { LIMITS, utf8Bytes } from "./protocol";
import { NearbyTable } from "./testkit";

const ROUNDS = Number(process.env.NEARBY_PROPERTY_ROUNDS ?? 150);
const CARD_RE = /^(?:[SHDC](?:10|[2-9JQKA])|LJ|BJ)$/;

type Json = Record<string, unknown>;

/** Every card code in `v` with its path, e.g. "trick.plays.0.cards.1". */
function cardsIn(v: unknown, path = "", out: [string, string][] = []): [string, string][] {
  if (typeof v === "string") {
    if (CARD_RE.test(v)) out.push([path, v]);
  } else if (Array.isArray(v)) {
    v.forEach((x, i) => cardsIn(x, path ? `${path}.${i}` : String(i), out));
  } else if (v !== null && typeof v === "object") {
    for (const [k, x] of Object.entries(v as Json)) cardsIn(x, path ? `${path}.${k}` : k, out);
  }
  return out;
}

/** Where a state frame may name a card: the seat's own hand, and what the
 *  table has seen (plays, the declaration, and the kitty at the round end). */
const PUBLIC_PATHS = [
  /^hand\.\d+\.code$/,
  /^(trick|last_trick)\.plays\.\d+\.cards\.\d+$/,
  /^current_declaration\.cards\.\d+$/,
  /^round_result\.kitty_cards\.\d+$/,
];

const sorted = (cards: readonly Card[]) => [...cards].sort().join(",");

function checkState(rnd: RoundState, seat: number, f: Json, problems: string[]): void {
  const where = `seat ${seat} phase ${String(f.phase)}`;
  if (f.you !== seat) problems.push(`${where}: frame for seat ${String(f.you)}`);
  const hand = (f.hand as { id: number; code: Card }[]).map((c) => c.code);
  if (sorted(hand) !== sorted(rnd.hands[seat])) problems.push(`${where}: hand is not the seat's own`);
  for (const [path] of cardsIn(f)) {
    if (!PUBLIC_PATHS.some((re) => re.test(path))) problems.push(`${where}: card at ${path}`);
  }
  if (f.round_result !== null && rnd.phase !== "round_end") problems.push(`${where}: round_result before the round end`);
  const ids = new Set((f.hand as { id: number }[]).map((c) => c.id));
  for (const opt of f.declare_options as number[][]) {
    for (const id of opt) if (!ids.has(id)) problems.push(`${where}: declare option id ${id} not in the hand`);
  }
  if (JSON.stringify(f).includes('"deck"')) problems.push(`${where}: deck key`);
}

async function playGame(seed: number, problems: string[], stats: { rounds: number; frames: number; maxBytes: number; drops: number }): Promise<void> {
  const humans = 2 + (seed % 3);
  const rounds = 1 + (seed % 3);
  const t = new NearbyTable(seed, rounds);
  const built = new Map<number, Set<string>>();
  const roundsSeen = new Set<RoundState>();
  const enqueue = t.server.enqueue.bind(t.server);
  t.server.enqueue = (sd: Seat, payload: Json) => {
    const room = t.room;
    if (room && sd.writer) {
      const seat = room.seatIndex(sd);
      const text = JSON.stringify(payload);
      stats.maxBytes = Math.max(stats.maxBytes, utf8Bytes(text));
      if (!built.has(seat)) built.set(seat, new Set());
      built.get(seat)!.add(text);
      if (payload.type === "state") {
        const rnd = room.round!;
        roundsSeen.add(rnd);
        checkState(rnd, seat, payload, problems);
      } else if (cardsIn(payload).length) {
        problems.push(`seat ${seat}: ${String(payload.type)} frame carries a card`);
      }
    }
    enqueue(sd, payload);
  };
  await t.open(true);
  for (let i = 1; i < humans; i++) await t.join(`P${i}`, { drive: true });
  t.send(t.host, { type: "table_start_bots" });
  // a third of the games lose a joiner for 70 s (past the takeover window),
  // who then comes back by token
  if (seed % 3 === 0) {
    const j = t.joiners[0];
    await t.settle(() => (t.room?.round?.history.length ?? 0) >= 2 || j.left, 2_000_000);
    if (!j.left && t.server.rooms.size) {
      stats.drops += 1;
      j.driver = null;
      t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
      await t.advance(70);
      if (t.server.rooms.size) await t.join(j.name, { token: j.token, player: j, drive: true });
    }
  }
  await t.settle(() => t.host.left || t.server.rooms.size === 0, 5_000_000);
  // the link carries only what the room built for that seat
  const seatOfPeer = new Map<string, number>();
  for (const w of t.fake.wire) {
    if (w.from !== "host") continue;
    const f = JSON.parse(w.text) as Json;
    stats.frames += 1;
    if (typeof f.you === "number") seatOfPeer.set(w.to, f.you);
    const seat = seatOfPeer.get(w.to);
    if (f.type === "state" && (seat === undefined || !built.get(seat)?.has(w.text))) {
      problems.push(`seed ${seed}: a state frame to ${w.to} that the room did not build for its seat`);
    }
    if (f.type !== "state" && cardsIn(f).length) problems.push(`seed ${seed}: ${String(f.type)} frame on the link carries a card`);
    if (utf8Bytes(w.text) > LIMITS.frameBytes) problems.push(`seed ${seed}: frame over the link limit`);
  }
  stats.rounds += roundsSeen.size;
}

describe("hidden hands over the nearby link", () => {
  it(`no seat sees another's cards, over ${ROUNDS} seeded rounds`, async () => {
    const problems: string[] = [];
    const stats = { rounds: 0, frames: 0, maxBytes: 0, drops: 0, games: 0 };
    for (let seed = 1; stats.rounds < ROUNDS; seed++) {
      await playGame(seed, problems, stats);
      stats.games += 1;
      if (problems.length > 5) break;
    }
    console.log(JSON.stringify({ nearbyHiddenHands: stats }));
    expect(problems.slice(0, 5)).toEqual([]);
    expect(stats.rounds).toBeGreaterThanOrEqual(ROUNDS);
    expect(stats.drops).toBeGreaterThan(0);
    expect(stats.maxBytes).toBeLessThanOrEqual(LIMITS.frameBytes);
  }, 1_200_000);
});
