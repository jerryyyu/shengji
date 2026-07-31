import type { Declaration, GameState, Trick } from "../protocol";
import Card from "./Card";

export type SidePos = "bottom" | "left" | "top" | "right";

/** Relative position of a seat from your point of view. You are always bottom;
 * (you+1)%4 is left, (you+2)%4 is top, (you+3)%4 is right. */
export function seatPos(seat: number, you: number): SidePos {
  const rel = (seat - you + 4) % 4;
  return (["bottom", "left", "top", "right"] as const)[rel];
}

interface TrickAreaProps {
  state: GameState;
  /** The trick to render (current trick, or the just-finished last trick). */
  trick: Trick | null;
  /** Winner seat when showing a completed trick. */
  winner: number | null;
  declaration: Declaration | null;
}

export default function TrickArea({ state, trick, winner, declaration }: TrickAreaProps) {
  const nameOf = (seat: number) => state.players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;

  return (
    <div className="trick-area">
      {trick?.plays.map((play) => {
        const pos = seatPos(play.seat, state.you);
        const isLeader = play.seat === trick.leader;
        const isWinner = winner !== null && play.seat === winner;
        return (
          <div key={`${play.seat}-${play.cards.join(",")}`} className={`trick-play pos-${pos}${isWinner ? " winner" : ""}`}>
            <div className="trick-cards">
              {play.cards.map((code, i) => (
                <Card key={i} code={code} />
              ))}
            </div>
            <div className="trick-tag">
              {isLeader ? <span className="lead-tag">lead</span> : null}
              {isWinner ? <span className="win-tag">wins</span> : null}
            </div>
          </div>
        );
      })}

      {declaration ? (
        <div className={`trick-play declaration pos-${seatPos(declaration.seat, state.you)}`}>
          <div className="trick-cards">
            {declaration.cards.map((code, i) => (
              <Card key={i} code={code} width={52} />
            ))}
          </div>
          <div className="trick-tag">
            <span className="declare-tag">{nameOf(declaration.seat)} declares</span>
          </div>
        </div>
      ) : null}

      {!trick?.plays.length && !declaration ? <div className="table-emblem">升级</div> : null}
    </div>
  );
}
