import type { GameState, HandCard, RoundResult, StatePlayer } from "./protocol";
import { shortLabel } from "./components/Card";

/** Words for the table from the viewer's side: teams are "Us" and "Them",
 *  never a colour, so who gained or who attacks never rests on colour. */

export type Team = 0 | 1;

/** The viewer's team (seat parity). */
export function myTeam(state: GameState): Team {
  return (state.you % 2) as Team;
}

export function teamWord(team: Team, state: GameState): "Us" | "Them" {
  return team === myTeam(state) ? "Us" : "Them";
}

/** The attacking team, the one without the banker; null before a banker is known. */
export function attackingTeam(state: GameState): Team | null {
  return state.banker === null ? null : ((1 - (state.banker % 2)) as Team);
}

/** The banker's crown in words, for screen readers: "You, banker" for your
 *  own seat, "Sam, banker" for anyone else. */
export function bankerText(player: StatePlayer, you: number): string {
  return `${player.seat === you ? "You" : player.name}, banker`;
}

/** "You declared" / "Sam declared", for the tag under a declaration. */
export function declaredBy(seat: number, state: GameState): string {
  if (seat === state.you) return "You declared";
  const name = state.players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
  return `${name} declared`;
}

/** "♥5", "♥5 pair" or "no trump" for declared cards. */
export function declarationWhat(cards: string[]): string {
  const first = cards[0] ?? "";
  if (first === "LJ" || first === "BJ") return "no trump";
  return cards.length === 2 ? `${shortLabel(first)} pair` : shortLabel(first);
}

/** The one-line explanation beside the declare buttons. In the first round
 *  the declarer also becomes banker; later the banker is already fixed. */
export function declareHelp(state: GameState): string {
  return state.banker === null
    ? "Declaring picks trump and makes you banker. A pair outbids a single."
    : "Declaring picks trump for this round. A pair outbids a single.";
}

/** Card points: 5s are worth 5, 10s and kings 10, everything else 0. */
export function cardPoints(code: string): number {
  const rank = code.slice(1);
  if (rank === "5") return 5;
  if (rank === "10" || rank === "K") return 10;
  return 0;
}

export function pointsOf(codes: string[]): number {
  return codes.reduce((sum, code) => sum + cardPoints(code), 0);
}

/** The engine multiplies buried points by 2 x the cards in the final
 *  trick's lead when the attackers win that trick. */
export const BURY_HELP =
  "Pick 8 cards to hide. If the attackers win the last trick, these points count double for them (×4 on a pair lead).";

/** "Burying 15 points" for the cards selected to bury. */
export function buryPointsText(hand: HandCard[], selected: Set<number>): string {
  const pts = pointsOf(hand.filter((c) => selected.has(c.id)).map((c) => c.code));
  return `Burying ${pts} ${pts === 1 ? "point" : "points"}`;
}

/** The seat label's status: "Bot (Alice left)" after a deliberate Leave, a
 *  countdown while a disconnect's grace runs, else null. */
export function seatStatus(player: StatePlayer, takeover: number | null): string | null {
  if (player.is_bot || player.connected) return null;
  if (player.left) return `Bot (${player.name} left)`;
  const parts = seatStatusParts(player, takeover);
  if (parts) return parts.lead + parts.count;
  return player.controller === "bot_cover" ? "bot playing" : "offline";
}

/** The countdown status split so a narrow pill can keep the count whole and
 *  drop the words before it: "offline — bot in " + "28s". Null when the seat
 *  shows no countdown. */
export function seatStatusParts(player: StatePlayer, takeover: number | null): { lead: string; count: string } | null {
  if (player.is_bot || player.connected || player.left) return null;
  if (takeover !== null && takeover > 0) return { lead: "offline — bot in ", count: `${Math.ceil(takeover)}s` };
  return null;
}

/** "You & Sam": the team's players, you first. */
export function teamMembers(team: Team, state: GameState): string {
  return state.players
    .filter((p) => p.team === team)
    .sort((a, b) => Number(b.seat === state.you) - Number(a.seat === state.you) || a.seat - b.seat)
    .map((p) => (p.seat === state.you ? "You" : p.name))
    .join(" & ");
}

/** "Next banker: Bot 1", or "Next banker: you". */
export function nextBankerText(state: GameState, result: RoundResult): string {
  if (result.next_banker === state.you) return "Next banker: you";
  const name = state.players.find((p) => p.seat === result.next_banker)?.name ?? `Seat ${result.next_banker}`;
  return `Next banker: ${name}`;
}
