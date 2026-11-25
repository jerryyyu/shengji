import type { ChatMsg, StatePlayer } from "./protocol";
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

/** The chat's one-person system lines (joins, leaves, reconnects) as the
 *  server and the offline server word them, in the current language. The
 *  name is everything before the line's fixed ending, so it is unambiguous,
 *  and a person's: it shows as typed. */
const SYSTEM_LINES: [RegExp, MessageKey][] = [
  [/^bot is playing for (.+) \(disconnected\)$/, "table.sysBotPlaying"],
  [/^(.+) reconnected — taking over from the bot$/, "table.sysReconnectedFromBot"],
  [/^(.+) reconnected$/, "table.sysReconnected"],
  [/^(.+) joined$/, "table.sysJoined"],
  [/^(.+) left$/, "table.sysLeft"],
  [/^(.+) disconnected$/, "table.sysDisconnected"],
];

/** A system line in the current language. A seat claim is worded from its
 *  participants (`actor` a person, `target` named as the table names bots
 *  when `target_is_bot`), never from its text; one without them, from an
 *  older server, keeps its text as sent. A line of another form passes
 *  through. */
export function formatSystemLine(m: Pick<ChatMsg, "text" | "event" | "actor" | "target" | "target_is_bot">): string {
  if (m.event && m.actor !== undefined && m.target !== undefined) {
    const took = m.target_is_bot === true ? displayName(m.target, true) : m.target;
    return t(m.event === "took_over" ? "table.sysTookOver" : "table.sysTookSeat", { name: m.actor, took });
  }
  if (/^.+ took .+'s seat$/.test(m.text) || /^.+ took over for .+ \(offline\)$/.test(m.text)) return m.text;
  for (const [re, key] of SYSTEM_LINES) {
    const match = re.exec(m.text);
    if (match) return t(key, { name: match[1] });
  }
  return m.text;
}
