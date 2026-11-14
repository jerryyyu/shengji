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

/** The points counter's label: "Us" or "Them" once a banker is set. */
export function pointsLabel(state: GameState): string {
  const attack = attackingTeam(state);
  return attack === null ? "Attackers" : teamWord(attack, state);
}

/** "You bank" for your own seat, "Sam banks" for anyone else. */
export function bankerText(player: StatePlayer, you: number): string {
  return player.seat === you ? "You bank" : `${player.name} banks`;
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

/** The ids in the banker's hand that came from the kitty: present now, absent
 *  from the hand held before the bury. Empty without a pre-bury hand. */
export function kittyIds(before: Set<number> | null, hand: HandCard[]): Set<number> {
  if (before === null || before.size === 0) return new Set();
  return new Set(hand.filter((c) => !before.has(c.id)).map((c) => c.id));
}

/** The seat label's status: "Bot (Alice left)" after a deliberate Leave, a
 *  countdown while a disconnect's grace runs, else null. */
export function seatStatus(player: StatePlayer, takeover: number | null): string | null {
  if (player.is_bot || player.connected) return null;
  if (player.left) return `Bot (${player.name} left)`;
  if (takeover !== null && takeover > 0) return `offline — bot in ${Math.ceil(takeover)}s`;
  return player.controller === "bot_cover" ? "bot playing" : "offline";
}

/** "You & Sam": the team's players, you first. */
export function teamMembers(team: Team, state: GameState): string {
  return state.players
    .filter((p) => p.team === team)
    .sort((a, b) => Number(b.seat === state.you) - Number(a.seat === state.you) || a.seat - b.seat)
    .map((p) => (p.seat === state.you ? "You" : p.name))
    .join(" & ");
}

export interface TeamLine {
  team: Team;
  word: "Us" | "Them";
  members: string;
  role: "attacking" | "defending" | null;
  outcome: string;
  won: boolean;
}

/** One line per team for the round end, yours first: its role and what
 *  happened to it, all in words. */
export function roundLines(state: GameState, result: RoundResult): TeamLine[] {
  const attack = attackingTeam(state);
  const levels = (n: number) => `+${n} ${n === 1 ? "level" : "levels"}`;
  const mine = myTeam(state);
  return [mine, (1 - mine) as Team].map((team) => {
    const won = team === result.winner_team;
    const role = attack === null ? null : team === attack ? "attacking" : "defending";
    const parts: string[] = [];
    if (role === "attacking") parts.push(`scored ${result.attacker_points} of 80`);
    if (won) {
      // attackers who reach 80 take the deal even when no level changes
      parts.push(result.point_scored ? "game won"
        : result.level_change > 0 ? levels(result.level_change) : "take the deal · no level change");
    }
    else parts.push("no level change");
    return { team, word: teamWord(team, state), members: teamMembers(team, state), role, outcome: parts.join(" · "), won };
  });
}

/** "Next banker: Bot 1", or "Next banker: you". */
export function nextBankerText(state: GameState, result: RoundResult): string {
  if (result.next_banker === state.you) return "Next banker: you";
  const name = state.players.find((p) => p.seat === result.next_banker)?.name ?? `Seat ${result.next_banker}`;
  return `Next banker: ${name}`;
}
