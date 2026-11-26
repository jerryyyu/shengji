// What the table panel says, as plain functions of the queue's state.
import { isZh, t } from "../i18n";
import { clock, namesAt, sharedTable, yourReady } from "./store";
import type { OfferView, Presence, QueueView, TableFrame } from "./store";
import type { FirstJoinerMsg, QueueMode } from "./messages";

/** A seat taken this recently reads "Just joined". */
export const JUST_JOINED_MS = 5000;
/** From this long before an offer lapses, its last seconds are announced. */
export const OFFER_CLOCK_MS = 10_000;
/** An offer's full length (matchmaking.py OFFER_SECS): Join's ring starts
 *  full at this many seconds. */
export const OFFER_SECS = 20;
/** Names are cut to this many characters; the full name stays in the label. */
export const NAME_CHARS = 10;

/** The panel's three kinds, and the Play buttons it replaces. */
export type PanelKind = "play" | "join" | "own" | "shared" | "elsewhere";

/** Which kind of panel the queue's state calls for. An offer only reaches
 *  an entry with no table; another device's table is run there. */
export function panelKind(q: QueueView): PanelKind {
  if (!q.queued) return "play";
  if (q.elsewhere) return "elsewhere";
  if (sharedTable(q.frame)) return "shared";
  if (q.offer) return "join";
  return "own";
}

/** A name cut to fit a seat at 320 px. */
export function shortName(name: string): string {
  const n = name.trim();
  return n.length > NAME_CHARS ? `${n.slice(0, NAME_CHARS)}…` : n;
}

/** "Mei", "Mei & Sam", "Mei, Sam & Li" (zh "Mei、Sam 和 Li"). */
export function nameList(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(t("queue.list.comma"))}${t("queue.list.amp")}${names[names.length - 1]}`;
}

/** "Mei and Sam", "Mei, Sam and Li" (zh "Mei、Sam 和 Li"). */
function andList(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(t("queue.list.comma"))}${t("queue.list.and")}${names[names.length - 1]}`;
}

/** A seat label's parts, as a screen reader hears them: "Alice, ready, your team". */
export function labelList(parts: (string | null | false | undefined)[]): string {
  return parts.filter(Boolean).join(isZh() ? "，" : ", ");
}

/** A seat's team, as its label says it. */
export const teamWord = (ours: boolean): string => t(ours ? "queue.seat.yourTeam" : "queue.seat.otherTeam");

/** The seat labels that name the seat's team, one message per team. */
type Sided = "queue.seat.named" | "queue.seat.playing" | "queue.seat.open" | "queue.seat.openSit"
  | "queue.seat.openMove" | "queue.seat.openMoveOther" | "queue.seat.bot" | "queue.seat.botSit"
  | "queue.seat.botN" | "queue.seat.awaySit" | "queue.seat.held" | "queue.seat.openAwaySit";

/** `base`'s label for a seat on your team (`ours`) or the other. */
export function seatLabel(base: Sided, ours: boolean, params: { name?: string; n?: number } = {}): string {
  const key: `${Sided}.ours` | `${Sided}.theirs` = ours ? `${base}.ours` : `${base}.theirs`;
  return t(key, params);
}

/** The people an offer's Join sits you with: those playing and staying.
 *  An away player's seat is open to you, so that player is not named. */
export function offerPeople(o: OfferView): string[] {
  return o.seats.filter((s) => !s.bot && !s.open).map((s) => s.name);
}

export function joinTitle(o: OfferView): string {
  const people = offerPeople(o).map(shortName);
  return people.length ? t("queue.title.join", { name: nameList(people) }) : t("queue.title.joinThis");
}

/** When your own table's bots sit, as a local time: never while you wait
 *  for people or an open table holds your timer still. Its countdown is the
 *  ring on Start with bots. */
export function ownBotsAt(q: QueueView): number | null {
  if (q.waitPlayers || q.botsPaused) return null;
  return q.frame?.timers.bots?.at ?? null;
}

/** Your table holds a seat for a Duo opener's friend. */
function holdsSeat(q: QueueView): boolean {
  return q.frame?.seats.some((s) => s.state === "held") === true;
}

/** Your own table's title: "Your Duo" for a Duo, formed or still holding
 *  the partner seat, else "Your table". The seats name the people. */
export function ownTitle(q: QueueView, partner: string | null): string {
  return t(partner || (q.duo && holdsSeat(q)) ? "queue.title.yourDuo" : "queue.title.yourTable");
}

/** Your own table as the live region names it: "You and Alice" once your
 *  Duo partner sits, else the title. */
function ownSpoken(q: QueueView, partner: string | null): string {
  return partner ? t("queue.title.youAnd", { name: shortName(partner) }) : ownTitle(q, partner);
}

/** A joiner's one status line: the owner starts the table, Ready or not. */
export function waitingLine(owner: string): string {
  return t("queue.status.waitingStart", { name: shortName(owner) });
}

/** The table's owner by name: whoever sits in the opener's seat. */
export function ownerName(f: TableFrame): string {
  return f.seats[f.opener]?.name ?? "";
}

/** The owner's one status line at a shared table: how many joiners are
 *  ready (the owner has no Ready, and its Start never waits for one). The
 *  bots' countdown is the ring on the button, never a line. */
export function sharedStatusLine(f: TableFrame): string {
  const joiners = f.seats.filter((s) => s.state === "taken" && s.seat !== f.opener);
  return t("queue.status.ready", { n: joiners.filter((s) => s.ready).length, count: joiners.length });
}

/** A shared table's title: "Your table", whoever opened it; the seats
 *  name the people. */
export function sharedTitle(_f: TableFrame): string {
  return t("queue.title.yourTable");
}

/** A shared table as the live region names it: "You and Alice", "You,
 *  Alice and Li". */
function sharedSpoken(f: TableFrame): string {
  const others = namesAt(f).map(shortName);
  if (others.length === 0) return t("queue.title.yourTable");
  if (others.length === 1) return t("queue.title.youAnd", { name: others[0] });
  return t("queue.title.youAndMany", { name: andList(others) });
}

/** Where the person at `from` may go: an empty seat that is not held, and
 *  for a Duo both seats of the other team, so the pair moves as one. */
export function moveTargets(seats: ({ pair?: boolean } | null)[], held: number[], from: number): number[] {
  const free = (at: number) => !seats[at] && !held.includes(at);
  if (!seats[from]?.pair) return [0, 1, 2, 3].filter(free);
  return [0, 1, 2, 3].filter((at) => at % 2 !== from % 2 && free(at) && free((at + 2) % 4));
}

/** The opener's one confirm before moving someone: "Move Alice here?",
 *  or a Duo's two names. */
export function moveQuestion(names: string[]): string {
  const who = names.map(shortName);
  return t("queue.move.title", { name: who.length > 1 ? andList(who.slice(0, 2)) : who[0] });
}

/** The one sentence the live region speaks when the panel changes state;
 *  the ticking clocks are not in it. */
export function announcement(q: QueueView): string {
  const kind = panelKind(q);
  if (kind === "join" && q.offer) {
    return t("queue.say.offer", { name: joinTitle(q.offer) });
  }
  if (kind === "own" && q.duoReady !== null && q.partyId && q.frame) {
    const partner = q.party?.members.find((m) => !m.you)?.name ?? "";
    const words = q.leader ? t("queue.btn.startBots")
      : `${waitingLine(partner)}${yourReady(q) ? `${isZh() ? "，" : ", "}${t("queue.seat.ready")}` : ""}`;
    return sentence(ownSpoken(q, partner), words);
  }
  if (kind === "own") {
    const who = t(q.partyId ? "queue.say.duoTable" : q.duo && holdsSeat(q) ? "queue.title.yourDuo" : "queue.title.yourTable");
    return t(q.waitPlayers ? "queue.say.ownNoTimer" : "queue.say.own", { name: who });
  }
  if (kind === "shared" && q.stillHereUntil !== null) {
    return t("queue.say.stillHere");
  }
  if (kind === "shared" && q.frame) {
    const f = q.frame;
    const joiners = f.seats.filter((s) => s.state === "taken" && s.seat !== f.opener);
    const said = t("queue.say.shared", { name: sharedSpoken(f), n: joiners.filter((s) => s.ready).length,
                                         count: joiners.length });
    const words = q.leader && f.opener === f.you ? "" : waitingLine(ownerName(f));
    return words ? `${said}${isZh() ? "" : " "}${words}${isZh() ? "。" : "."}` : said;
  }
  if (kind === "elsewhere") return t("queue.title.elsewhere");
  return "";
}

/** "Name. Words." in the app's language. */
function sentence(name: string, words: string): string {
  return isZh() ? `${name}。${words}。` : `${name}. ${words}.`;
}

/** One piece of the presence line; `hl` marks the selected mode's count. */
export interface PresencePart { text: string; hl?: boolean }

/** The Play tab's line under Play and Duo, first match wins: people
 *  waiting, else open tables (split by mode only when both modes have one)
 *  and people playing. It is global, so it promises no seat; with no counts
 *  from the server, nobody is about. */
export function presenceParts(p: Presence | null, mode: QueueMode = "ranked"): PresencePart[] {
  if (p && p.waiting >= 1) return [{ text: t("queue.presence.waiting", { n: p.waiting }) }];
  if (p && p.tables >= 1) {
    const ranked = p.ranked ?? 0;
    const casual = p.casual ?? 0;
    const playing = { text: t("queue.presence.playing", { n: p.playing }) };
    if (ranked >= 1 && casual >= 1) {
      return [{ text: t("queue.presence.tablesSplit", { n: p.tables }) },
              { text: t("queue.presence.ranked", { n: ranked }), hl: mode === "ranked" },
              { text: t("queue.presence.comma") },
              { text: t("queue.presence.casual", { n: casual }), hl: mode === "casual" }, playing];
    }
    const key = ranked >= 1 ? "queue.presence.tablesRanked" : casual >= 1 ? "queue.presence.tablesCasual"
      : "queue.presence.tables";
    return [{ text: t(key, { n: p.tables }) }, playing];
  }
  return [{ text: t("queue.presence.nobody") }];
}

/** The one toast a game started alone gets when its first newcomer sits. */
export function firstJoinerText(m: Pick<FirstJoinerMsg, "name" | "move_secs" | "round_end">): string {
  if (m.move_secs === null) return t(m.round_end ? "queue.first.joinsNext" : "queue.first.joined", { name: m.name });
  return t(m.round_end ? "queue.first.joinsNextTimed" : "queue.first.joinedTimed",
           { name: m.name, seconds: m.move_secs });
}

/** The idle-seat status, one line: the countdown until the table drops you. */
export function stillHereLine(until: number, now: number): string {
  return t("queue.status.stillHere", { seconds: clock(Math.max(0, until - now), true) });
}
