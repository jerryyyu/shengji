// What the table panel says, as plain functions of the queue's state.
import { clock } from "./store";
import type { OfferView, Presence, QueueView, TableView } from "./store";
import type { FirstJoinerMsg, QueueMode } from "./messages";
import type { RoomMsg, RoomPlayer } from "../protocol";

/** A seat taken this recently reads "Just joined". */
export const JUST_JOINED_MS = 5000;
/** From this long before an offer lapses, its last seconds are announced. */
export const OFFER_CLOCK_MS = 10_000;
/** An offer's full length (matchmaking.py OFFER_SECS): Join's ring starts
 *  full at this many seconds. */
export const OFFER_SECS = 20;
/** Names are cut to this many characters; the full name stays in the label. */
export const NAME_CHARS = 10;

/** The opener's Start now unlocks this long after the latest arrival
 *  (server START_NOW_SECS); `start_now_in` from the server wins. */
export const START_NOW_SECS = 30;

/** The panel's three kinds, and the Play buttons it replaces. */
export type PanelKind = "play" | "join" | "own" | "shared" | "elsewhere";

/** Which kind of panel the queue's state calls for. An offer only reaches
 *  an entry with no table; another device's table is run there. */
export function panelKind(q: QueueView): PanelKind {
  if (!q.queued) return "play";
  if (q.elsewhere) return "elsewhere";
  if (q.table) return "shared";
  if (q.offer) return "join";
  return "own";
}

/** A name cut to fit a seat at 320 px. */
export function shortName(name: string): string {
  const n = name.trim();
  return n.length > NAME_CHARS ? `${n.slice(0, NAME_CHARS)}…` : n;
}

/** "Mei", "Mei & Sam", "Mei, Sam & Li". */
export function nameList(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}`;
}

/** The people an offer's Join sits you with: those playing and staying.
 *  An away player's seat is open to you, so that player is not named. */
export function offerPeople(o: OfferView): string[] {
  return o.seats.filter((s) => !s.bot && !s.open).map((s) => s.name);
}

export function joinTitle(o: OfferView): string {
  const people = offerPeople(o).map(shortName);
  return people.length ? `Join ${nameList(people)}` : "Join this table";
}

/** The Join button's words; the offer's clock is the ring beside them. */
export function joinLabel(o: OfferView): string {
  return o.partner ? "Join together" : "Join";
}

/** When your own table's bots sit, as a local time: never while you wait
 *  for people or an open table holds your timer still. Its countdown is the
 *  ring on Start with bots. */
export function ownBotsAt(q: QueueView): number | null {
  if (q.waitPlayers || q.botsPaused) return null;
  return q.botsAt;
}

/** A shared table's one status line: who is ready. The bots' countdown is
 *  the ring on the Start button, never a line. */
export function sharedStatusLine(t: TableView): string {
  return `${t.ready} of ${t.of} ready`;
}

/** "You and Alice", "You, Alice and Li". */
export function sharedTitle(t: TableView): string {
  const others = t.seats.filter((s) => s && !s.you).map((s) => shortName(s!.name));
  if (others.length === 0) return "Your table";
  if (others.length === 1) return `You and ${others[0]}`;
  return `You, ${others.slice(0, -1).join(", ")} and ${others[others.length - 1]}`;
}

/** The people at a room other than you, by name. */
function roomOthers(room: RoomMsg): RoomPlayer[] {
  return room.players.filter((pl) => !pl.is_bot && pl.seat !== room.you);
}

/** A room's title: "Your table", "You and Alice", "You, Alice and Li". */
export function roomTitle(room: RoomMsg): string {
  const others = roomOthers(room).map((pl) => shortName(pl.name));
  if (others.length === 0) return "Your table";
  if (others.length === 1) return `You and ${others[0]}`;
  return `You, ${others.slice(0, -1).join(", ")} and ${others[others.length - 1]}`;
}

/** "1 of 2 ready" once someone else sits: the people connected, and how
 *  many of them tapped Start. Alone there is nothing to wait for. */
export function roomReadyLine(room: RoomMsg): string | null {
  if (roomOthers(room).length === 0) return null;
  const here = room.players.filter((pl) => !pl.is_bot && (pl.connected || pl.seat === room.you));
  const ready = new Set(room.ready ?? []);
  return `${here.filter((pl) => ready.has(pl.seat)).length} of ${here.length} ready`;
}

/** Your Start is in: who the room still waits for. */
export function roomWaitingLabel(room: RoomMsg): string {
  const ready = new Set(room.ready ?? []);
  const w = roomOthers(room).filter((pl) => pl.connected && !ready.has(pl.seat)).map((pl) => pl.name);
  if (w.length === 0) return "Starting…";
  if (w.length === 1) return `Waiting for ${shortName(w[0])}`;
  return `Waiting for ${w.length} players`;
}

/** The Start button's words: Start until you tap it, then who the table is
 *  waiting for. */
export function startLabel(t: TableView): string {
  if (!t.youReady) return "Start";
  const w = t.waitingFor;
  if (w.length === 0) return "Starting…";
  if (w.length === 1) return `Waiting for ${shortName(w[0])}`;
  return `Waiting for ${w.length} players`;
}

/** The strip and pill on other tabs: what the table is, in a few words. */
export function stripLabel(q: QueueView): string {
  return q.offer && !q.table && !q.elsewhere ? "Table with a seat" : "Your table";
}

/** The one sentence the live region speaks when the panel changes state;
 *  the ticking clocks are not in it. */
export function announcement(q: QueueView): string {
  const kind = panelKind(q);
  if (kind === "join" && q.offer) {
    return `Table with people. ${joinTitle(q.offer)}.`;
  }
  if (kind === "own") {
    const who = q.partyId ? "Your Duo's table" : "Your table";
    return `${who}. Waiting for players.${q.waitPlayers ? " No timer." : ""}`;
  }
  if (kind === "shared" && q.table && q.stillHereUntil !== null) {
    return "Still here? Tap I'm here to stay at the table.";
  }
  if (kind === "shared" && q.table) {
    const t = q.table;
    const after = t.youReady ? ` ${startLabel(t)}.` : "";
    return `Table. ${sharedTitle(t)}. ${t.ready} of ${t.of} ready.${after}`;
  }
  if (kind === "elsewhere") return "Your table is open on another device.";
  return "";
}

/** One piece of the presence line; `hl` marks the selected mode's count. */
export interface PresencePart { text: string; hl?: boolean }

/** The Play tab's line under Play and Duo, first match wins: people
 *  waiting, else open tables (split by mode only when both modes have one)
 *  and people playing. It is global, so it promises no seat; with no counts
 *  from the server, nobody is about. */
export function presenceParts(p: Presence | null, mode: QueueMode = "ranked"): PresencePart[] {
  const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;
  if (p && p.waiting >= 1) return [{ text: `${n(p.waiting, "person is", "people are")} waiting for a game` }];
  if (p && p.tables >= 1) {
    const ranked = p.ranked ?? 0;
    const casual = p.casual ?? 0;
    const playing = { text: ` · ${n(p.playing, "person", "people")} playing` };
    if (ranked >= 1 && casual >= 1) {
      return [{ text: `${n(p.tables, "table has", "tables have")} a seat · ` },
              { text: `${ranked} ranked`, hl: mode === "ranked" }, { text: ", " },
              { text: `${casual} casual`, hl: mode === "casual" }, playing];
    }
    const kind = ranked >= 1 ? "ranked " : casual >= 1 ? "casual " : "";
    return [{ text: `${p.tables} ${kind}${p.tables === 1 ? "table has" : "tables have"} a seat` }, playing];
  }
  return [{ text: "Nobody is playing right now" }];
}

/** The presence line as one string, for a reader and for tests. */
export function presenceLine(p: Presence | null, mode: QueueMode = "ranked"): string {
  return presenceParts(p, mode).map((x) => x.text).join("");
}

/** The one toast a game started alone gets when its first newcomer sits. */
export function firstJoinerText(m: Pick<FirstJoinerMsg, "name" | "move_secs" | "round_end">): string {
  const who = m.round_end ? `${m.name} joins your table from next round.` : `${m.name} joined your table.`;
  if (m.move_secs === null) return who;
  return m.round_end ? `${who} Moves are timed from next round, ${m.move_secs} s each.`
    : `${who} Moves are now timed, ${m.move_secs} s each.`;
}

/** The "still here?" status: the question and its countdown, one line. */
export function stillHereLine(until: number, now: number): string {
  return `Still here? You leave the table in ${clock(Math.max(0, until - now), true)}.`;
}
