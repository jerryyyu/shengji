import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GameState } from "../protocol";
import { fetchRound } from "../replay/api";
import type { Fetched } from "../replay/api";
import { buildReplay, frameOfTrick, stepTrick } from "../replay/reducer";
import type { Replay, ReplayFrame, RoundReplayDoc } from "../replay/reducer";
import { navigate } from "../replay/route";
import Card, { SUIT_SYMBOL, shortLabel } from "./Card";
import Hand from "./Hand";
import type { HandRects } from "./Hand";
import TrickArea from "./TrickArea";
import { GamesUnavailable, SignInPrompt } from "./GamesStatus";

const NO_SELECTION = new Set<number>();
const noToggle = () => {};

/** The slice of a live state TrickArea reads (players, `you`, the hand), so
 *  the table's own component draws the replayed trick unchanged. */
function asState(replay: Replay, frame: ReplayFrame): GameState {
  const { setup } = replay;
  return {
    type: "state",
    room: "",
    you: setup.seat,
    phase: frame.kind === "end" ? "round_end" : frame.kind === "play" ? "play" : "declare",
    players: setup.players.map((p) => ({
      seat: p.seat, name: p.name, is_bot: p.is_bot, connected: true,
      team: (p.seat % 2) as 0 | 1, cards_left: frame.cardsLeft[p.seat],
      is_banker: setup.banker === p.seat, takeover_in: null,
      controller: p.is_bot ? "bot" : "human", reserved_for: null, reserved_secs: null,
    })),
    hand: frame.hand,
    levels: setup.levels,
    games_won: [0, 0],
    banker: setup.banker,
    trump: setup.trumpSuit ? { suit: setup.trumpSuit, rank: setup.trumpRank, declarer: null } : null,
    turn: frame.turn,
    declare_options: [],
    current_declaration: null,
    passed: [],
    trick: frame.trick,
    last_trick: null,
    attacker_points: frame.attackerPoints,
    kitty_count: 8,
    round_result: null,
    message: null,
    notice: null,
  };
}

function TrumpLabel({ suit, rank }: { suit: string | null; rank: string }) {
  if (!suit) return <span>{rank}</span>;
  if (suit === "NT") return <span><b>NT</b> {rank}</span>;
  const red = suit === "H" || suit === "D";
  return <span><b className={red ? "replay-red" : undefined}>{SUIT_SYMBOL[suit] ?? suit}</b> {rank}</span>;
}

function cards(list: string[]): string {
  return list.map(shortLabel).join(" ");
}

function caption(replay: Replay, frame: ReplayFrame): string {
  const { setup } = replay;
  const name = (seat: number | null) =>
    seat === null ? "?" : seat === setup.seat ? "You" : setup.players[seat]?.name ?? `Seat ${seat + 1}`;
  if (frame.kind === "deal") {
    if (setup.declarations.length === 0) return "Dealt. Nobody declared; trump was flipped from the kitty.";
    return "Dealt. " + setup.declarations
      .map((d) => `${name(d.seat)} declared ${cards(d.cards)}`).join(", ") + ".";
  }
  if (frame.kind === "start") {
    if (setup.ownBury) return `You buried ${cards(setup.ownBury)}.`;
    return `${name(setup.banker)} buried 8 cards.`;
  }
  if (frame.kind === "end") return "Round over.";
  const play = frame.trick?.plays[frame.playNo];
  const head = `Trick ${frame.trickNo}: ${name(play?.seat ?? null)} ${frame.playNo === 0 ? "led" : "played"} ${cards(play?.cards ?? [])}`;
  if (frame.winner === null) return head + ".";
  const pts = frame.trickPoints ? ` and ${frame.trickPoints} points` : "";
  return `${head}. ${name(frame.winner)} ${frame.winner === setup.seat ? "win" : "wins"} the trick${pts}.`;
}

function ResultPanel({ replay, frame }: { replay: Replay; frame: ReplayFrame }) {
  const r = frame.result;
  if (!r) return null;
  const myTeam = replay.setup.seat % 2;
  const won = r.winner_team === myTeam;
  const kitty = r.kitty ?? replay.setup.kitty;
  return (
    <div className={`replay-result ${won ? "won" : "lost"}`} role="status">
      <div className="replay-result-head">{won ? "Your team won the round" : "Your team lost the round"}</div>
      <div>Attackers scored {r.attacker_points} points{r.kitty_points ? ` (kitty ${r.kitty_points})` : ""}.</div>
      <div>
        {r.level_change > 0 ? `Up ${r.level_change} level${r.level_change === 1 ? "" : "s"}. ` : "No level change. "}
        Levels now: you {r.new_levels[myTeam]}, them {r.new_levels[1 - myTeam]}.
      </div>
      {kitty && kitty.length ? (
        <div className="replay-mini-cards" aria-label="Kitty">
          <span className="replay-mini-label">Kitty</span>
          {kitty.map((c, i) => <Card key={i} code={c} />)}
        </div>
      ) : null}
    </div>
  );
}

export function ReplayBoard({ replay }: { replay: Replay }) {
  const [at, setAt] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const handRects = useRef<HandRects>(new Map());
  const last = replay.frames.length - 1;
  const frame = replay.frames[Math.min(at, last)];
  const state = useMemo(() => asState(replay, frame), [replay, frame]);
  const { setup } = replay;
  const go = useCallback((i: number) => setAt(Math.max(0, Math.min(last, i))), [last]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight") setAt((i) => Math.min(last, i + 1));
      else if (e.key === "ArrowLeft") setAt((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [last]);

  const myTeam = setup.seat % 2;
  const declaration = frame.kind === "deal" && setup.declarations.length
    ? setup.declarations[setup.declarations.length - 1] : null;
  const allKnown = setup.finished && frame.hands.every((h) => h !== null);
  const order = [0, 1, 2, 3].map((k) => (setup.seat + k) % 4);

  return (
    <div className="replay">
      <div className="replay-info">
        <span className="chip">Trump <TrumpLabel suit={setup.trumpSuit} rank={setup.trumpRank} /></span>
        <span className="chip">Levels: you {setup.levels[myTeam]} · them {setup.levels[1 - myTeam]}</span>
        <span className="chip">Attackers {frame.attackerPoints}</span>
      </div>
      <div className="replay-seats">
        {order.map((s) => {
          const p = setup.players[s];
          return (
            <span key={s}
                  className={`replay-seat team${s % 2}${frame.turn === s ? " on-turn" : ""}${s === setup.seat ? " you" : ""}`}>
              {setup.banker === s ? <span className="banker-crown" title="Banker">👑</span> : null}
              <span className="replay-seat-name">{s === setup.seat ? `${p.name} (you)` : p.name}</span>
              <span className="card-count">{frame.cardsLeft[s]}</span>
            </span>
          );
        })}
      </div>
      <div className="replay-felt">
        <TrickArea state={state} trick={frame.kind === "deal" || frame.kind === "start" ? null : frame.trick}
                   winner={frame.winner} declaration={declaration} handRects={handRects} />
      </div>
      <p className="replay-caption" aria-live="polite">{caption(replay, frame)}</p>
      <div className="replay-controls">
        <button className="btn subtle" aria-label="Previous trick" disabled={at === 0}
                onClick={() => go(stepTrick(replay, at, -1))}>⏮</button>
        <button className="btn subtle" aria-label="Previous play" disabled={at === 0}
                onClick={() => go(at - 1)}>◀</button>
        <span className="replay-step">{at + 1}/{last + 1}</span>
        <button className="btn subtle" aria-label="Next play" disabled={at === last}
                onClick={() => go(at + 1)}>▶</button>
        <button className="btn subtle" aria-label="Next trick" disabled={at === last}
                onClick={() => go(stepTrick(replay, at, 1))}>⏭</button>
        {replay.trickCount > 0 ? (
          <select className="replay-jump" aria-label="Jump to trick"
                  value={frame.trickNo > 0 ? String(frame.trickNo) : ""}
                  onChange={(e) => { if (e.target.value) go(frameOfTrick(replay, Number(e.target.value))); }}>
            <option value="">Trick…</option>
            {Array.from({ length: replay.trickCount }, (_, i) => (
              <option key={i + 1} value={String(i + 1)}>Trick {i + 1}</option>
            ))}
          </select>
        ) : null}
      </div>
      <div className="replay-hand">
        <Hand hand={frame.hand} selected={NO_SELECTION} selectable={false} onToggle={noToggle} rects={handRects} />
      </div>
      {frame.kind === "end" ? <ResultPanel replay={replay} frame={frame} /> : null}
      {!replay.complete ? (
        <p className="replay-note">This round did not finish; only the cards played are shown.</p>
      ) : null}
      {allKnown ? (
        <div className="replay-all">
          <button className="btn subtle" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Hide other hands" : "Show other hands"}
          </button>
          {showAll ? order.slice(1).map((s) => (
            <div key={s} className="replay-mini-cards" aria-label={`${setup.players[s].name}'s hand`}>
              <span className="replay-mini-label">{setup.players[s].name}</span>
              {(frame.hands[s] ?? []).map((c) => <Card key={c.id} code={c.code} />)}
            </div>
          )) : null}
        </div>
      ) : null}
    </div>
  );
}

/** One round of a saved game, read-only, from the viewer's seat. */
export default function ReplayView({ id, round }: { id: string; round: number }) {
  const [res, setRes] = useState<Fetched<RoundReplayDoc> | null>(null);
  useEffect(() => {
    let live = true;
    setRes(null);
    fetchRound(id, round).then((r) => { if (live) setRes(r); });
    return () => { live = false; };
  }, [id, round]);
  const replay = useMemo(() => (res && res.ok ? buildReplay(res.data) : null), [res]);

  return (
    <div className="games-panel">
      <div className="games-head">
        <button className="btn subtle" onClick={() => navigate({ page: "game", id })}>‹ Game</button>
        <h2 className="games-title">Round {round}</h2>
      </div>
      {res === null ? <p className="games-empty">Loading…</p>
        : !res.ok ? (res.reason === "signed_out" ? <SignInPrompt />
          : res.reason === "not_found" ? <GamesUnavailable />
          : <p className="lobby-error" role="alert">Could not load the round ({res.status || "no connection"}).</p>)
        : replay && replay.frames.length ? <ReplayBoard replay={replay} />
        : <GamesUnavailable />}
    </div>
  );
}
