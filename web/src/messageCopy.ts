import type { ChatMsg, StatePlayer, SystemEventKind } from "./protocol";
import { SUIT_SYMBOL } from "./components/Card";
import { displayName, t } from "./i18n";
import type { MessageKey } from "./i18n";

/** Readable copy for the engine's table messages. The engine words them in
 *  its own notation ("Seat 1 declared H2 (pair)", "... flipped from the
 *  kitty: S"); this maps seats to names and suit letters to symbols. Any other
 *  message passes through unchanged. */
const DECLARED = /^Seat (\d+) declared (NT|[SHDC])(\S*)( \(pair\))?$/;

/** Whether a table message announces a declaration, which the table already
 *  shows as a tag under the declared cards. */
export function isDeclareMessage(message: string): boolean {
  return DECLARED.test(message);
}

export function formatTableMessage(message: string, players: StatePlayer[], you: number): string {
  const declared = DECLARED.exec(message);
  if (declared) {
    const seat = Number(declared[1]);
    const p = players.find((x) => x.seat === seat);
    const name = seat === you ? t("common.you") : p ? displayName(p.name, p.is_bot) : t("table.seatN", { n: seat });
    const pair = declared[4] !== undefined;
    if (declared[2] === "NT") return t(pair ? "table.declaredNtPair" : "table.declaredNt", { name });
    const code = `${SUIT_SYMBOL[declared[2]]}${declared[3]}`;
    return t(pair ? "table.declaredPair" : "table.declaredCard", { name, code });
  }
  const flipped = /^No declaration — trump flipped from the kitty: (NT|[SHDC])$/.exec(message);
  if (flipped) {
    return flipped[1] === "NT" ? t("table.flippedNt") : t("table.flipped", { suit: SUIT_SYMBOL[flipped[1]] });
  }
  if (message === "No declaration — played without trump: NT") return t("table.playedNt");
  return message;
}

/** Each system line kind's sentence; `{name}` is the actor, `{took}` a seat
 *  claim's target. */
const SYSTEM_LINE: Record<SystemEventKind, MessageKey> = {
  joined: "table.sysJoined",
  left: "table.sysLeft",
  disconnected: "table.sysDisconnected",
  reconnected: "table.sysReconnected",
  reconnected_from_bot: "table.sysReconnectedFromBot",
  bot_playing_for: "table.sysBotPlaying",
  took_seat: "table.sysTookSeat",
  took_over: "table.sysTookOver",
};

/** A system line in the current language, worded from its kind and
 *  participants alone: the actor is a person and shows as typed; a seat
 *  claim's target is named as the table names bots only when
 *  `target_is_bot`. A line without them, from an older server, or of a kind
 *  this client does not know, is shown exactly as sent. Names are never
 *  read out of `text`. */
export function formatSystemLine(m: Pick<ChatMsg, "text" | "event" | "actor" | "target" | "target_is_bot">): string {
  const key = m.event === undefined ? undefined : SYSTEM_LINE[m.event];
  if (key === undefined || m.actor === undefined) return m.text;
  const twoPerson = m.event === "took_seat" || m.event === "took_over";
  if (twoPerson && m.target === undefined) return m.text;
  const target = m.target ?? "";
  return t(key, { name: m.actor, took: m.target_is_bot === true ? displayName(target, true) : target });
}
