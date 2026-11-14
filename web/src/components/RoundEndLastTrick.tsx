import type { GameState, LastTrick } from "../protocol";
import { shortLabel } from "./Card";

/** The round's final trick inside the round-end Details: who played what,
 *  and who took it with how many points. */
export default function RoundEndLastTrick({ state, trick }: { state: GameState; trick: LastTrick }) {
  const nameOf = (seat: number) => seat === state.you
    ? "You"
    : state.players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
  return (
    <div className="round-end-last-trick">
      <div className="kitty-reveal-label">
        Last trick · {nameOf(trick.winner)} {trick.winner === state.you ? "win" : "wins"}
        {trick.points > 0 ? ` · ${trick.points} pts` : ""}
      </div>
      <ol className="last-trick-plays">
        {trick.plays.map((play) => (
          <li key={play.seat} className={`last-trick-row team${play.seat % 2}${play.seat === trick.winner ? " winner" : ""}`}>
            <span className="last-trick-who">{nameOf(play.seat)}</span>
            <span className="last-trick-cards">
              {play.cards.map((code, i) => (
                <span key={i} className={`last-trick-card${/^[HD]/.test(code) || code === "BJ" ? " red" : ""}`}>
                  {shortLabel(code)}
                </span>
              ))}
            </span>
            {play.seat === trick.winner ? <span className="last-trick-tag win">wins</span> : <span />}
          </li>
        ))}
      </ol>
    </div>
  );
}
