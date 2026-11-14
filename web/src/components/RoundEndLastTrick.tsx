import type { GameState, LastTrick } from "../protocol";
import Card from "./Card";

/** The round's final trick inside the round-end Details: each play's cards
 *  in play order with the player's name under them, the winner's outlined. */
export default function RoundEndLastTrick({ state, trick }: { state: GameState; trick: LastTrick }) {
  const nameOf = (seat: number) => seat === state.you
    ? "You"
    : state.players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
  return (
    <div className="round-end-col round-end-last-trick">
      <div className="round-end-col-label">
        Last trick · {nameOf(trick.winner)}{trick.points > 0 ? `, ${trick.points} points` : ""}
      </div>
      <ol className="round-end-plays">
        {trick.plays.map((play) => (
          <li key={play.seat} className={`round-end-play${play.seat === trick.winner ? " winner" : ""}`}>
            <span className="round-end-play-cards">
              {play.cards.map((code, i) => <Card key={i} code={code} />)}
            </span>
            <span className="round-end-play-who">{nameOf(play.seat)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
