import { useEffect, useRef, useState } from "react";
import type { GameState, Phase } from "../protocol";
import { conn } from "../ws";
import { SUIT_SYMBOL } from "./Card";
import MuteButton from "./MuteButton";

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

/** Subtle leave control with a confirm step: first tap arms ("Leave game?"),
 * second tap within 3s sends leave_room; otherwise it reverts. */
function LeaveButton() {
  const [armed, setArmed] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    []
  );

  const click = () => {
    if (!armed) {
      setArmed(true);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        setArmed(false);
      }, 3000);
    } else {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      setArmed(false);
      conn.send({ type: "leave_room" });
    }
  };

  return (
    <button
      className={`leave-btn${armed ? " armed" : ""}`}
      onClick={click}
      title="Leave the game (a bot takes over your seat)"
    >
      {armed ? "Leave game?" : "Leave"}
    </button>
  );
}

export default function Hud({ state }: { state: GameState }) {
  // Tapping the room chip mid-game copies a full invite link, so you can
  // pull someone into a game already in progress — they land on a bot's
  // seat (Jerry, 2026-08-03).
  const [copied, setCopied] = useState(false);
  const copyInvite = () => {
    const url = `${window.location.origin}/?room=${state.room}`;
    navigator.clipboard
      .writeText(url)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      })
      .catch(() => {
        /* clipboard blocked (non-https / permissions); leave the chip as-is */
      });
  };

  return (
    <div className="hud">
      <div className="hud-bar">
        <div className="hud-group">
          <button
            className={"chip room-chip" + (copied ? " copied" : "")}
            onClick={copyInvite}
            title="Copy invite link — share this to let someone join this game"
            data-tip="Copy invite link"
          >
            {copied ? "Link copied" : state.room}
          </button>
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
          <MuteButton />
          <LeaveButton />
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
