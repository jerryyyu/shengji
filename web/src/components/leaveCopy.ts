// What the leave sheet says: one title and one consequence line for each
// place a player can leave from. The lines restate the server's leave rules;
// they set none of their own.
import { conn } from "../ws";
import type { ServerMsg } from "../protocol";
import { nameList, shortName } from "../queue/tableText";
import { t } from "../i18n";

/** The wait after leaving a round you joined from an open table, as words.
 *  The server's JOIN_COOLDOWN_SECS is 60 and no frame sends it ahead of a
 *  leave, so the copy names it here once. */
export const JOIN_WAIT = "1 minute";

/** Where a leave starts, and what the sheet needs to say about it. */
export type LeaveContext =
  /** The Play tab's table before a game; `others` are the people staying. */
  | { kind: "queue"; others: string[] }
  /** The Play tab's table before a game, in a Duo made there. `partner`
   *  keeps the table; `opener`: you opened it, so its code goes with it. */
  | { kind: "duo"; partner: string; opener: boolean }
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

/** The sheet's title and its one line, or no line when leaving costs
 *  nothing and changes nothing for anyone else. `joined`: the round in play
 *  was joined from an open table. Only a ranked table charges the join wait;
 *  a casual one, and any round end, let you go for free, and a free leave is
 *  not announced as free: a casual round has no line at all. */
export function leaveCopy(ctx: LeaveContext, joined = false): { title: string; line: string | null } {
  if (ctx.kind === "queue") {
    const names = ctx.others.map(shortName);
    return {
      title: t("roundend.leaveTableTitle"),
      line: names.length ? t("roundend.leaveOthers", { names: nameList(names), count: names.length }) : null,
    };
  }
  if (ctx.kind === "duo") {
    const who = shortName(ctx.partner);
    return {
      title: t("roundend.leaveDuoTitle"),
      line: t(ctx.opener ? "roundend.leavePartnerKeepsCode" : "roundend.leavePartnerKeeps", { name: who }),
    };
  }
  const title = t("roundend.leaveGameTitle");
  if (ctx.practice) return { title, line: t("roundend.leavePractice") };
  if (ctx.betweenRounds) return { title, line: t("roundend.leaveBetweenRounds") };
  if (joined && ctx.ranked) return { title, line: t("roundend.leaveJoinWait", { wait: JOIN_WAIT }) };
  if (ctx.ranked && !ctx.guest) return { title, line: t("roundend.leaveAtBestDraw") };
  // a casual round, and a guest's ranked one, cost nothing
  return { title, line: null };
}
