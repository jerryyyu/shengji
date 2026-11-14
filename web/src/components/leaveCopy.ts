// What the leave sheet says: one title and one consequence line for each
// place a player can leave from. The lines restate the server's leave rules;
// they set none of their own.
import { conn } from "../ws";
import type { ServerMsg } from "../protocol";
import { nameList, shortName } from "../queue/tableText";

/** The wait after leaving a round you joined from an open table, as words.
 *  The server's JOIN_COOLDOWN_SECS is 60 and no frame sends it ahead of a
 *  leave, so the copy names it here once. */
export const JOIN_WAIT = "1 minute";

/** Where a leave starts, and what the sheet needs to say about it. */
export type LeaveContext =
  /** The Play tab's table before a game; `others` are the people staying. */
  | { kind: "queue"; others: string[] }
  /** A created room's lobby. `others` are the people staying, in seat order;
   *  `host`: you hold the opener's controls, which pass to the first of them. */
  | { kind: "room"; others: string[]; host: boolean }
  /** A game at the table. `ranked`: the table is ranked; `guest`: the viewer
   *  is never rated, so no line speaks of ranking; `practice`: an offline
   *  game on this device, which ends; `betweenRounds`: opened from the round end. */
  | { kind: "game"; ranked: boolean; guest?: boolean; practice?: boolean; betweenRounds?: boolean };

/** This socket's seat was taken mid-round from an open table and that round
 *  is still in play: leaving it costs the join wait. A state frame's
 *  `joined_round` says so when the server sends it; otherwise an open-table
 *  join counts from its match_started until that room reaches a round end
 *  (a seat claimed at a round end never counts). */
let joinedRoom: string | null = null;
// The connection the joined round was seen on: a state on a later connection
// that does not repeat the flag means the round may have ended while away.
let joinedGeneration = -1;

function trackJoin(m: ServerMsg): void {
  if (m.type === "match_started") {
    joinedRoom = m.joining ? m.room : null;
    joinedGeneration = conn.generation;
    return;
  }
  if (m.type === "left") {
    joinedRoom = null;
    return;
  }
  if (m.type !== "state") return;
  const flag = (m as { joined_round?: boolean }).joined_round;
  if (typeof flag === "boolean") {
    joinedRoom = flag ? m.room : null;
    joinedGeneration = conn.generation;
  } else if (joinedRoom !== null && (m.room !== joinedRoom || m.phase === "round_end"
                                     || conn.generation !== joinedGeneration)) {
    joinedRoom = null;
  }
}
conn.subscribe?.(trackJoin);

/** Whether leaving now leaves a round joined from an open table. */
export function inJoinedRound(): boolean {
  return joinedRoom !== null;
}

const stays = (names: string[]) => (names.length === 1 ? "stays" : "stay");

/** The sheet's title and its one line, or no line when leaving costs
 *  nothing and changes nothing for anyone else. `joined`: the round in play
 *  was joined from an open table. Only a ranked table charges the join wait;
 *  a casual one, and any round end, let you go for free, and a free leave is
 *  not announced as free. */
export function leaveCopy(ctx: LeaveContext, joined = false): { title: string; line: string | null } {
  if (ctx.kind === "queue") {
    const names = ctx.others.map(shortName);
    return { title: "Leave the table?", line: names.length ? `${nameList(names)} ${stays(names)} at the table.` : null };
  }
  if (ctx.kind === "room") {
    if (ctx.others.length === 0) return { title: "Leave the room?", line: "The room closes." };
    const line = ctx.host
      ? `The table stays open; ${shortName(ctx.others[0])} can start it.`
      : "The table stays open.";
    return { title: "Leave the room?", line };
  }
  if (ctx.practice) return { title: "Leave the game?", line: "This offline game ends." };
  if (ctx.betweenRounds) return { title: "Leave the game?", line: "This round's result is kept." };
  if (joined && ctx.ranked) return { title: "Leave the game?", line: `You'll wait ${JOIN_WAIT} to play again.` };
  if (ctx.ranked && !ctx.guest) {
    return { title: "Leave the game?", line: "A bot takes your seat. This round counts as at best a draw for you." };
  }
  return { title: "Leave the game?", line: "A bot takes your seat and the others keep playing." };
}
