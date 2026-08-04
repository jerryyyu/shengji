import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GameState, HandCard, LastTrick, StatePlayer } from "../protocol";
import { conn } from "../ws";
import Card, { shortLabel } from "./Card";
import Hand from "./Hand";
import Hud from "./Hud";
import RoundEndModal from "./RoundEndModal";
import TrickArea, { seatPos } from "./TrickArea";
import XrayPanel from "./XrayPanel";
import ChatPanel, { type ChatMsg } from "./ChatPanel";

const LAST_TRICK_MS = 1500;

function declareLabel(ids: number[], hand: HandCard[]): string {
  const codes = ids.map((id) => hand.find((c) => c.id === id)?.code ?? "?");
  const first = codes[0] ?? "?";
  if (first === "LJ" || first === "BJ") return "Declare NT";
  const label = shortLabel(first);
  return codes.length === 2 ? `Declare ${label} pair` : `Declare ${label}`;
}

/** Local countdown: the server sends seconds-remaining with each state, and
 *  states arrive on events, not on a timer. Restart whenever the server's
 *  number changes so we never drift away from it. */
function useCountdown(seconds: number | null): number | null {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    setLeft(seconds);
    if (seconds === null) return;
    const id = window.setInterval(
      () => setLeft((v) => (v === null ? null : Math.max(0, v - 1))), 1000);
    return () => window.clearInterval(id);
  }, [seconds]);
  return left;
}

function OpponentPanel({ player, state }: { player: StatePlayer; state: GameState }) {
  const pos = seatPos(player.seat, state.you);
  const takeover = useCountdown(player.takeover_in ?? null);
  const onTurn = state.turn === player.seat;
  const hasPassed = state.phase === "declare" && state.passed.includes(player.seat);
  const backs = Math.min(player.cards_left, 5);
  return (
    <div className={`opponent pos-${pos} team${player.team}${onTurn ? " on-turn" : ""}${player.connected || player.is_bot ? "" : " disconnected"}`}>
      <div className="opp-name">
        {player.is_banker ? <span className="banker-crown" title="Banker">👑</span> : null}
        <span>{player.name}</span>
        {player.is_bot ? <span className="bot-tag">BOT</span> : null}
        {hasPassed ? <span className="ready-tag">ready</span> : null}
        {!player.connected && !player.is_bot ? (
          <span className="off-tag">
            {takeover !== null && takeover > 0
              ? `offline — bot in ${Math.ceil(takeover)}s`
              : "offline"}
          </span>
        ) : null}
      </div>
      <div className="opp-cards">
        <div className="back-stack">
          {Array.from({ length: backs }, (_, i) => (
            <Card key={i} className="stacked" />
          ))}
        </div>
        <span className="card-count">{player.cards_left}</span>
      </div>
      {onTurn && player.is_bot ? <div className="thinking">thinking…</div> : null}
      {onTurn && !player.is_bot ? <div className="their-turn">their turn</div> : null}
    </div>
  );
}

export default function Table({ state }: { state: GameState }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [shownLastTrick, setShownLastTrick] = useState<LastTrick | null>(null);
  // Hidden debug overlay — only reachable when localStorage["shengji.debug"]
  // holds the server's SHENGJI_DEBUG_TOKEN (set manually via the devtools
  // console); toggled with the "x" key. See XrayPanel.tsx.
  const [xrayOpen, setXrayOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  // Seed from the connection's buffer: scrollback for a joiner arrives before
  // this component exists, so subscribing alone loses it (Codex case 7).
  const [chat, setChat] = useState<ChatMsg[]>(() => conn.chatHistory() as ChatMsg[]);
  const [unread, setUnread] = useState(0);
  useEffect(() => conn.subscribe((m: any) => {
    if (m?.type !== "chat") return;
    setChat(() => conn.chatHistory() as ChatMsg[]);
    setUnread((u) => (chatOpenRef.current ? 0 : u + 1));
  }), []);
  const chatOpenRef = useRef(false);
  useEffect(() => { chatOpenRef.current = chatOpen; if (chatOpen) setUnread(0); }, [chatOpen]);
  const prevStateRef = useRef<GameState | null>(null);
  const lastTrickTimer = useRef<number | null>(null);

  // Prune selection to ids still in hand (clears selection after successful actions).
  useEffect(() => {
    setSelected((prev) => {
      const ids = new Set(state.hand.map((c) => c.id));
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [state.hand]);

  // When the trick resets and last_trick changed, linger on the finished trick briefly.
  useEffect(() => {
    const prev = prevStateRef.current;
    prevStateRef.current = state;
    if (!prev) return;
    const prevPlays = prev.trick?.plays.length ?? 0;
    const nowPlays = state.trick?.plays.length ?? 0;
    const lastChanged = JSON.stringify(prev.last_trick) !== JSON.stringify(state.last_trick);
    if (state.last_trick && lastChanged && nowPlays < prevPlays) {
      setShownLastTrick(state.last_trick);
      if (lastTrickTimer.current !== null) window.clearTimeout(lastTrickTimer.current);
      lastTrickTimer.current = window.setTimeout(() => {
        lastTrickTimer.current = null;
        setShownLastTrick(null);
      }, LAST_TRICK_MS);
    }
  }, [state]);

  useEffect(
    () => () => {
      if (lastTrickTimer.current !== null) window.clearTimeout(lastTrickTimer.current);
    },
    []
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "x" && e.key !== "X") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (!localStorage.getItem("shengji.debug")) return; // hidden unless token set
      setXrayOpen((open) => !open);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const me = state.players.find((p) => p.seat === state.you) ?? null;
  const opponents = state.players.filter((p) => p.seat !== state.you);
  const myTurn = state.turn === state.you;
  const iAmBanker = me?.is_banker ?? false;

  const selectable =
    (state.phase === "bury" && iAmBanker) || state.phase === "play";

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Selected ids in hand (sorted) order.
  const selectedIds = state.hand.filter((c) => selected.has(c.id)).map((c) => c.id);

  const showingLast = shownLastTrick !== null;
  const trickToShow = showingLast
    ? shownLastTrick
    : state.phase === "play" || state.phase === "round_end" || state.phase === "game_over"
      ? state.trick
      : null;
  const declaration =
    state.phase === "deal" || state.phase === "declare" || state.phase === "bury"
      ? state.current_declaration
      : null;

  let actionBar: ReactNode = null;
  if (state.phase === "deal" || state.phase === "declare") {
    // Declaration is a race: options can appear for anyone during dealing and
    // during the short declare window afterwards. No Pass while dealing.
    const canDeclare = state.declare_options.length > 0;
    const iPassed = state.passed.includes(state.you);
    actionBar = (
      <>
        {state.declare_options.map((ids) => (
          <button
            key={ids.join("-")}
            className="btn gold"
            onClick={() => conn.send({ type: "declare", card_ids: ids })}
          >
            {declareLabel(ids, state.hand)}
          </button>
        ))}
        {state.phase === "declare" ? (
          <button
            className="btn"
            disabled={iPassed}
            onClick={() => conn.send({ type: "pass_declare" })}
          >
            {iPassed ? "Passed" : "Pass"}
          </button>
        ) : null}
        {!canDeclare ? (
          <span className="action-hint">
            {state.phase === "deal" ? "Dealing cards…" : "Waiting for declarations…"}
          </span>
        ) : null}
      </>
    );
  } else if (state.phase === "bury" && iAmBanker) {
    actionBar = (
      <button
        className="btn primary"
        disabled={selectedIds.length !== 8}
        onClick={() => conn.send({ type: "bury", card_ids: selectedIds })}
      >
        Bury 8 cards ({selectedIds.length}/8)
      </button>
    );
  } else if (state.phase === "play" && myTurn) {
    actionBar = (
      <>
        <button
          className="btn primary"
          disabled={selectedIds.length === 0}
          onClick={() => conn.send({ type: "play", card_ids: selectedIds })}
        >
          Play {selectedIds.length > 0 ? `(${selectedIds.length})` : ""}
        </button>
        <button
          className="btn subtle"
          disabled={selectedIds.length === 0}
          onClick={() => setSelected(new Set())}
        >
          Clear
        </button>
      </>
    );
  } else if (state.turn !== null && !myTurn) {
    const turnPlayer = state.players.find((p) => p.seat === state.turn);
    actionBar = <span className="action-hint">Waiting for {turnPlayer?.name ?? "…"}</span>;
  }

  return (
    <div className="table-screen">
      <Hud state={state} />
      <div className="felt">
        {opponents.map((p) => (
          <OpponentPanel key={p.seat} player={p} state={state} />
        ))}

        <TrickArea
          state={state}
          trick={trickToShow}
          winner={showingLast && shownLastTrick ? shownLastTrick.winner : null}
          declaration={showingLast ? null : declaration}
        />

        <div className="you-area">
          <div className={`you-tagline team${me?.team ?? 0}${myTurn ? " on-turn" : ""}`}>
            {iAmBanker ? <span className="banker-crown" title="Banker">👑</span> : null}
            <span className="you-name">{me?.name ?? "You"}</span>
            {myTurn ? <span className="your-turn-tag">your turn</span> : null}
            {state.phase === "declare" && state.passed.includes(state.you) ? (
              <span className="ready-tag">ready</span>
            ) : null}
          </div>
          <div className="action-bar">{actionBar}</div>
          <Hand hand={state.hand} selected={selected} selectable={selectable} onToggle={toggle} />
        </div>
      </div>

      {(state.phase === "round_end" || state.phase === "game_over") && state.round_result ? (
        <RoundEndModal state={state} result={state.round_result} />
      ) : null}

      {xrayOpen ? <XrayPanel state={state} onClose={() => setXrayOpen(false)} /> : null}
      {state.players.filter((p) => !p.is_bot).length > 1 && (
        <button className="chat-launch" onClick={() => setChatOpen((o) => !o)}
                aria-label="Chat">
          💬{unread > 0 && <span className="chat-badge">{unread}</span>}
        </button>
      )}
      <ChatPanel messages={chat} you={state.you} open={chatOpen}
                 onClose={() => setChatOpen(false)} />
    </div>
  );
}
