import type { GameState, LastTrick } from "../protocol";
import Card from "./Card";
import { t, useT } from "../i18n";

/** A seat's name as the round end shows it: a bot seat's "Bot 2" in the
 *  current language, any other name as it is. */
export function seatName(name: string): string {
  const bot = /^Bot (\d+)$/.exec(name);
  return bot ? t("roundend.bot", { n: bot[1] }) : name;
}

/** The round's final trick inside the round-end Details: each play's cards
 *  in play order with the player's name under them, the winner's outlined. */
export default function RoundEndLastTrick({ state, trick }: { state: GameState; trick: LastTrick }) {
  const t = useT();
  const nameOf = (seat: number) => {
    if (seat === state.you) return t("roundend.you");
    const name = state.players.find((p) => p.seat === seat)?.name;
    return name === undefined ? t("roundend.seat", { n: seat }) : seatName(name);
  };
  return (
    <div className="round-end-col round-end-last-trick">
      <div className="round-end-col-label">
        {trick.points > 0
          ? t("roundend.lastTrickPoints", { name: nameOf(trick.winner), points: trick.points })
          : t("roundend.lastTrick", { name: nameOf(trick.winner) })}
      </div>
      <ol className="round-end-plays">
        {trick.plays.map((play) => (
          <li key={play.seat} className={`round-end-play${play.seat === trick.winner ? " winner" : ""}`}>
            <span className="round-end-play-cards">
              {play.cards.map((code, i) => <Card key={i} code={code} />)}
            </span>
            <span className="round-end-play-who" title={nameOf(play.seat)}>{nameOf(play.seat)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
