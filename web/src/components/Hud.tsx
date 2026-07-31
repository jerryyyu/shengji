import type { GameState, Phase } from "../protocol";
import { SUIT_SYMBOL } from "./Card";

const PHASE_LABEL: Record<Phase, string> = {
  deal: "Dealing",
  declare: "Declaring trump",
  bury: "Burying the kitty",
  play: "Playing",
  round_end: "Round over",
  game_over: "Game over",
};

function TrumpChip({ state }: { state: GameState }) {
  const trump = state.trump;
  if (!trump) return <span className="chip trump-chip none">No trump yet</span>;
  if (trump.suit === "NT" || trump.suit === null) {
    return (
      <span className="chip trump-chip">
        <span className="trump-suit nt">NT</span>
        <span className="trump-rank">{trump.rank}</span>
      </span>
    );
  }
  const red = trump.suit === "H" || trump.suit === "D";
  return (
    <span className="chip trump-chip">
      <span className={`trump-suit ${red ? "red" : "black"}`}>{SUIT_SYMBOL[trump.suit] ?? trump.suit}</span>
      <span className="trump-rank">{trump.rank}</span>
    </span>
  );
}

export default function Hud({ state }: { state: GameState }) {
  return (
    <div className="hud">
      <div className="hud-bar">
        <div className="hud-group">
          <span className="chip room-chip">{state.room}</span>
          <span className="chip phase-chip">{PHASE_LABEL[state.phase]}</span>
        </div>

        <div className="hud-group">
          <span className="chip level-chip team0" title="Team seats 0 & 2">
            <span className="team-dot t0" />
            Lv {state.levels[0]}
          </span>
          <TrumpChip state={state} />
          <span className="chip level-chip team1" title="Team seats 1 & 3">
            <span className="team-dot t1" />
            Lv {state.levels[1]}
          </span>
        </div>

        <div className="hud-group">
          <span className="chip points-chip" title="Points captured by the attacking team">
            <span className="points-big">{state.attacker_points}</span>
            <span className="points-target">/ 80</span>
          </span>
          <span className="chip kitty-chip" title="Kitty (face-down)">
            <span className="kitty-icon" />
            {state.kitty_count}
          </span>
        </div>
      </div>
      {state.message ? (
        <div className="hud-message" key={state.message}>
          {state.message}
        </div>
      ) : null}
    </div>
  );
}
