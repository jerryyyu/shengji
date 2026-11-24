import type { StatePlayer } from "./protocol";
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

/** The chat's system lines (joins, leaves, seat claims) as the server and
 *  the offline server word them, each in the current language with any bot
 *  named as the table names it. A line of another form passes through. */
const SYSTEM_LINES: [RegExp, MessageKey][] = [
  [/^bot is playing for (.+) \(disconnected\)$/, "table.sysBotPlaying"],
  [/^(.+?) reconnected — taking over from the bot$/, "table.sysReconnectedFromBot"],
  [/^(.+?) reconnected$/, "table.sysReconnected"],
  [/^(.+?) took over for (.+) \(offline\)$/, "table.sysTookOver"],
  [/^(.+?) took (.+)'s seat$/, "table.sysTookSeat"],
  [/^(.+?) joined$/, "table.sysJoined"],
  [/^(.+?) left$/, "table.sysLeft"],
  [/^(.+?) disconnected$/, "table.sysDisconnected"],
];

export function formatSystemLine(text: string): string {
  for (const [re, key] of SYSTEM_LINES) {
    const m = re.exec(text);
    if (m) return t(key, { name: displayName(m[1]), took: m[2] === undefined ? "" : displayName(m[2]) });
  }
  return text;
}
