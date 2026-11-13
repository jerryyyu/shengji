// What the table panel says, as plain functions of the queue's state.
import { clock } from "./store";
import type { OfferView, QueueView, TableView } from "./store";

/** A seat taken this recently reads "Just joined". */
export const JUST_JOINED_MS = 5000;
/** The offer's clock shows on Join only in its last ten seconds. */
export const OFFER_CLOCK_MS = 10_000;
/** Names are cut to this many characters; the full name stays in the label. */
export const NAME_CHARS = 10;

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

/** The Join button: the offer's clock only in its last ten seconds. */
export function joinLabel(o: OfferView, now: number): string {
  const base = o.partner ? "Join together" : "Join";
  const left = o.expiresAt - now;
  return left <= OFFER_CLOCK_MS ? `${base} · ${clock(Math.max(0, left), true)}` : base;
}

/** The lines under the Join title. `guest`: never rated, so no round is
 *  called ranked. Leaving the round you joined costs a 5-minute wait;
 *  joining between rounds does not. */
export function joinLines(o: OfferView, guest: boolean): { text: string; warn?: boolean }[] {
  const lines: { text: string; warn?: boolean }[] = [];
  if (o.partner) lines.push({ text: `Two seats for you and ${shortName(o.partner.name)}, as partners.` });
  if (o.roundEnd) {
    if (!o.partner) lines.push({ text: "Between rounds. You play from the next round." });
    if (!guest) lines.push({ text: "Ranked." });
    return lines;
  }
  if (!o.partner) lines.push({ text: "Round in progress. You sit after this trick." });
  if (!guest) lines.push({ text: "Ranked from the next round." });
  lines.push({ text: "Stay until this round ends, or wait 5 minutes to play again.", warn: true });
  return lines;
}

/** Your own table's bot line: the countdown, none while you wait for
 *  people, and nothing while an open table holds your timer still. */
export function ownTimerLine(q: QueueView, now: number): string | null {
  if (q.waitPlayers) return "No timer. Starts when someone joins you.";
  if (q.botsPaused || q.botsAt === null) return null;
  const left = q.botsAt - now;
  if (left <= 0) return "Adding bots…";
  return `Bots fill the empty seats in ${clock(left, true)}.`;
}

/** A shared table's bot line. Whose timer it is does not matter to anyone
 *  at the table, so it is not said. */
export function sharedTimerLine(t: TableView, now: number): string {
  if (!t.timer) return "No timer. Starts when the table is full or everyone taps Start.";
  const left = t.timer.at - now;
  if (left <= 0) return "Adding bots…";
  return `Bots fill the empty seats in ${clock(left, true)}.`;
}

/** "You and Alice", "You, Alice and Li". */
export function sharedTitle(t: TableView): string {
  const others = t.seats.filter((s) => s && !s.you).map((s) => shortName(s!.name));
  if (others.length === 0) return "Your table";
  if (others.length === 1) return `You and ${others[0]}`;
  return `You, ${others.slice(0, -1).join(", ")} and ${others[others.length - 1]}`;
}

/** The Start button's words: Start now until you tap it, then who the
 *  table is waiting for. */
export function startLabel(t: TableView): string {
  if (!t.youReady) return "Start now";
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
export function announcement(q: QueueView, guest: boolean): string {
  const kind = panelKind(q);
  if (kind === "join" && q.offer) {
    const lines = joinLines(q.offer, guest).map((l) => l.text).join(" ");
    return `Table with people. ${joinTitle(q.offer)}. ${lines}`;
  }
  if (kind === "own") {
    const who = q.partyId ? "Your Duo's table" : "Your table";
    return `${who}. Waiting for players.${q.waitPlayers ? " No timer." : ""}`;
  }
  if (kind === "shared" && q.table) {
    const t = q.table;
    const after = t.youReady ? ` ${startLabel(t)}.` : "";
    return `Table. ${sharedTitle(t)}. ${t.ready} of ${t.of} ready.${after}`;
  }
  if (kind === "elsewhere") return "Your table is open on another device.";
  return "";
}
