import type { GameState, LastTrick } from "../protocol";
import Card from "./Card";
import { displayName, useT } from "../i18n";

/** The round's final trick inside the round-end Details: each play's cards
 *  in play order with the player's name under them, the winner's outlined. */
export default function RoundEndLastTrick({ state, trick }: { state: GameState; trick: LastTrick }) {
  const t = useT();
  const nameOf = (seat: number) => {
    if (seat === state.you) return t("roundend.you");
    const p = state.players.find((x) => x.seat === seat);
    return p === undefined ? t("roundend.seat", { n: seat }) : displayName(p.name, p.is_bot);
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
