import type { GameState, LastTrick } from "../protocol";
import { shortLabel } from "./Card";

/** The previous trick, reopened: each play in order with who made it, the
 *  winner and the points it took. It stays until dismissed, so a newcomer can
 *  read why a trick went the way it did. */
export default function LastTrickPanel({ state, trick, onClose }: {
  state: GameState; trick: LastTrick; onClose: () => void;
}) {
  const nameOf = (seat: number) => seat === state.you
    ? "You"
    : state.players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
  return (
    <div className="last-trick-panel" role="dialog" aria-label="Last trick">
      <div className="last-trick-head">
        <b>Last trick</b>
        <span className="last-trick-sum">
          {nameOf(trick.winner)} {trick.winner === state.you ? "win" : "wins"}
          {trick.points > 0 ? ` · ${trick.points} pts` : ""}
        </span>
        <button className="last-trick-close" onClick={onClose} aria-label="Close the last trick">×</button>
      </div>
      <ol className="last-trick-plays">
        {trick.plays.map((play) => (
          <li key={play.seat} className={`last-trick-row team${play.seat % 2}${play.seat === trick.winner ? " winner" : ""}`}>
            <span className="last-trick-who">
              {nameOf(play.seat)}
              {play.seat === trick.leader ? <span className="last-trick-tag">lead</span> : null}
            </span>
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
