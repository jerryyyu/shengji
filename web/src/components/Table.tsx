import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { GameState, HandCard, LastTrick, ServerMsg, StatePlayer } from "../protocol";
import { conn } from "../ws";
import type { ConnStatus } from "../ws";
import Card, { shortLabel } from "./Card";
import Hand from "./Hand";
import type { HandRects } from "./Hand";
import { DUR } from "../motion";
import Hud from "./Hud";
import RoundEndModal from "./RoundEndModal";
import TrickArea, { seatPos } from "./TrickArea";
import XrayPanel from "./XrayPanel";
import ChatPanel, { type ChatMsg } from "./ChatPanel";
import { haptic } from "../native";
import { nameWidthClass } from "../nameWidth";
import type { Toast } from "../toast";
import ToastView from "./ToastView";
import MatchedNote from "../queue/MatchedNote";
import { leadToFollow } from "../follow";
import { followHint, playableIds } from "../followRules";
import { STALL_MS } from "./Lobby";

const LAST_TRICK_MS = 1500;
// The sweep ends a little before the finished trick is replaced, so the
// table never waits on it.
const SWEEP_AFTER_MS = LAST_TRICK_MS - DUR.sweep - 40;

/** "Declare ♠2 pair", plus the bare "♠2 pair" that a phone shows after one
 *  "Declare" label for the whole row. */
function declareLabel(ids: number[], hand: HandCard[]): ReactNode {
  const codes = ids.map((id) => hand.find((c) => c.id === id)?.code ?? "?");
  const first = codes[0] ?? "?";
  const what = first === "LJ" || first === "BJ"
    ? "NT"
    : codes.length === 2 ? `${shortLabel(first)} pair` : shortLabel(first);
  return <><span className="declare-full">{`Declare ${what}`}</span><span className="declare-short">{what}</span></>;
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

const BOT_BANTER = {
  bury: ["Eight cards have to go…", "A little mystery for the kitty.", "Parting with cards is hard.", "New round, new possibilities."],
  play: ["Hmm… decisions, decisions.", "One trick at a time.", "Trying to keep a trick up my sleeve.", "Jokers aren’t the only surprises."],
} as const;

function BotThinking({ phase }: { phase: "bury" | "play" }) {
  const [line, setLine] = useState(() => Math.floor(Math.random() * BOT_BANTER[phase].length));
  useEffect(() => {
    const timer = window.setInterval(() => {
      // Pick another cosmetic phrase; never repeat the currently visible line.
      const offset = 1 + Math.floor(Math.random() * (BOT_BANTER[phase].length - 1));
      setLine((n) => (n + offset) % BOT_BANTER[phase].length);
    }, 3200);
    return () => window.clearInterval(timer);
  }, [phase]);
  return (
    <>
      <div className="thinking" role="status" aria-live="polite">
        {phase === "bury" ? "Choosing 8 cards to bury…" : "Considering the next play…"}
      </div>
      <div className="bot-progress" role="progressbar"
        title="Working — completion percentage is not available."
        aria-label={phase === "bury" ? "Bot choosing cards to bury" : "Bot considering its play"}>
        <span />
      </div>
      {/* Cosmetic copy only; no card identities, scores, or search reasoning.
          Keep rotation outside the live region so screen readers are not spammed. */}
      <div className="bot-banter" title="Playful flavor, not model reasoning.">
        <span className="bot-banter-label">Bot banter: </span>{BOT_BANTER[phase][line]}
      </div>
    </>
  );
}

/** How long a refused Play's hint stays above the hand. */
export const HINT_MS = 2600;

/** Whether the connection has stayed short of "open" for the lobby's
 *  STALL_MS, and a retry that reconnects at once and starts the wait over;
 *  the same wait and retry the lobby offers. */
function useStalled(status: ConnStatus): [boolean, () => void] {
  const [stalled, setStalled] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const open = status === "open";
  useEffect(() => {
    setStalled(false);
    if (open) return;
    const t = window.setTimeout(() => setStalled(true), STALL_MS);
    return () => window.clearTimeout(t);
  }, [open, attempt]);
  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
    conn.reconnect();
  }, []);
  return [stalled && !open, retry];
}

/** How long the full-name popover stays up after a tap or long press. */
const FULL_NAME_MS = 2500;
const LONG_PRESS_MS = 450;

function OpponentPanel({ player, state }: { player: StatePlayer; state: GameState }) {
  const pos = seatPos(player.seat, state.you);
  // a tap or long press shows the whole name; only the phone layout draws it
  const [fullName, setFullName] = useState(false);
  const pressTimer = useRef<number | null>(null);
  const longPressed = useRef(false);
  useEffect(() => {
    if (!fullName) return;
    const t = window.setTimeout(() => setFullName(false), FULL_NAME_MS);
    return () => window.clearTimeout(t);
  }, [fullName]);
  useEffect(() => () => { if (pressTimer.current !== null) window.clearTimeout(pressTimer.current); }, []);
  const endPress = () => {
    if (pressTimer.current !== null) { window.clearTimeout(pressTimer.current); pressTimer.current = null; }
  };
  const takeover = useCountdown(player.takeover_in ?? null);
  const onTurn = state.turn === player.seat;
  const actionPhase = state.phase === "bury" || state.phase === "play";
  const botControlled = player.is_bot || player.controller === "bot_cover";
  const hasPassed = state.phase === "declare" && state.passed.includes(player.seat);
  const backs = Math.min(player.cards_left, 5);
  return (
    <div className={`opponent pos-${pos} team${player.team}${onTurn ? " on-turn" : ""}${player.connected || player.is_bot ? "" : " disconnected"}`}
         data-name-len={nameWidthClass(player.name)}
         onClick={() => {
           if (longPressed.current) { longPressed.current = false; return; }
           setFullName((v) => !v);
         }}
         onPointerDown={() => {
           endPress();
           longPressed.current = false;
           pressTimer.current = window.setTimeout(() => {
             pressTimer.current = null; longPressed.current = true; setFullName(true);
           }, LONG_PRESS_MS);
         }}
         onPointerUp={endPress}
         onPointerLeave={endPress}
         onPointerCancel={endPress}>
      {fullName ? <span className="opp-fullname" role="tooltip">{player.name}</span> : null}
      <div className="opp-name">
        {/* the phone pill carries the team as a dot and the turn as a gold
            fill ending in "…" */}
        <span className={`seat-dot t${player.team}`} aria-hidden="true" />
        {player.is_banker ? <span className="banker-crown" title="Banker">👑</span> : null}
        <span className="opp-name-text">{player.name}</span>
        {/* always drawn, so the label's width never changes with the turn */}
        <span className={`turn-dots${onTurn && actionPhase ? " shown" : ""}`} aria-hidden="true">…</span>
        {player.is_bot ? <span className="bot-tag">BOT</span> : null}
        {hasPassed ? <span className="ready-tag">ready</span> : null}
        {!player.connected && !player.is_bot ? (
          <span className="off-tag">
            {takeover !== null && takeover > 0
              ? `offline — bot in ${Math.ceil(takeover)}s`
              : player.controller === "bot_cover"
                ? "bot playing"
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
      {onTurn && actionPhase && botControlled ? (
        <BotThinking key={`${state.room}:${state.phase}:${player.cards_left}`} phase={state.phase as "bury" | "play"} />
      ) : null}
      {onTurn && actionPhase && !botControlled ? <div className="their-turn">their turn</div> : null}
    </div>
  );
}

/** Whether the table is waiting on you: your play, or your bury as banker. */
function isYourTurnCue(state: GameState): boolean {
  if (state.turn !== state.you) return false;
  if (state.phase === "play") return true;
  return state.phase === "bury" && (state.players.find((p) => p.seat === state.you)?.is_banker ?? false);
}

/** Haptic ticks on the moments that matter (no-ops outside the iOS app):
 *  your turn arriving, a declare option appearing and your team taking the
 *  round. Each fires on the transition, never on a repeat state; a won trick
 *  is shown, not felt, since it comes about 25 times a round. */
function useTableHaptics(state: GameState) {
  const turn = isYourTurnCue(state);
  const canDeclare = (state.phase === "deal" || state.phase === "declare") && state.declare_options.length > 0;
  const myTeam = state.players.find((p) => p.seat === state.you)?.team ?? null;
  const prev = useRef({ turn, canDeclare });
  useEffect(() => {
    if (turn && !prev.current.turn) haptic("turn");
    if (canDeclare && !prev.current.canDeclare) haptic("declare");
    prev.current = { turn, canDeclare };
  }, [turn, canDeclare]);
  // every server state is a fresh object, so the round's arrival is the
  // transition from no result to one, not a change of identity
  const wonRound = state.round_result !== null && myTeam !== null && state.round_result.winner_team === myTeam;
  const hadResult = state.round_result !== null;
  const prevResult = useRef(hadResult);
  useEffect(() => {
    if (hadResult && !prevResult.current && wonRound) haptic("won");
    prevResult.current = hadResult;
  }, [hadResult, wonRound]);
}

export default function Table({ state, toast = null }: { state: GameState; toast?: Toast | null }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [shownLastTrick, setShownLastTrick] = useState<LastTrick | null>(null);
  // Hidden debug overlay — only reachable when localStorage["shengji.debug"]
  // holds the server's SHENGJI_DEBUG_TOKEN (set manually via the devtools
  // console); toggled with the "x" key. See XrayPanel.tsx.
  const [xrayOpen, setXrayOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  // Seed from the connection's buffer: scrollback for a joiner arrives before
  // this component exists, so subscribing alone loses it.
  const [chat, setChat] = useState<ChatMsg[]>(() => conn.chatHistory() as ChatMsg[]);
  const [unread, setUnread] = useState(0);
  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    // chat and chat_history both mutate the log; read it back from the
    // connection rather than reconstructing it here.
    if (msg.type !== "chat" && msg.type !== "chat_history") return;
    setChat(() => conn.chatHistory() as ChatMsg[]);
    setUnread((u) => (chatOpenRef.current ? 0 : u + 1));
  }), []);
  const chatOpenRef = useRef(false);
  useEffect(() => { chatOpenRef.current = chatOpen; if (chatOpen) setUnread(0); }, [chatOpen]);
  const [prevState, setPrevState] = useState(state);
  const handRects = useRef<HandRects>(new Map());

  // Prune selection to ids still in hand (clears selection after successful actions).
  useEffect(() => {
    setSelected((prev) => {
      const ids = new Set(state.hand.map((c) => c.id));
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [state.hand]);

  // A play or bury you sent is in flight until the server answers, and Play,
  // Bury and Clear wait meanwhile. Pending belongs to the connection it was
  // sent on, and only a state settles it:
  // - your hand changed or the turn moved on: it committed, so the whole
  //   selection clears, including cards a failed throw handed back;
  // - the first state after a reconnect still shows the same hand and turn:
  //   it never committed (or its answer was lost), so pending clears and the
  //   selection stays for a retry;
  // - an error comes back: pending clears and the selection stays.
  // The socket opening alone settles nothing, and neither does a same-hand
  // broadcast on the connection the play was sent on.
  const [pending, setPending] = useState<{ handKey: string; turn: number | null; generation: number } | null>(null);
  const handKey = state.hand.map((c) => c.id).join(",");
  useEffect(() => {
    if (!pending) return;
    if (handKey !== pending.handKey || state.turn !== pending.turn) {
      setPending(null);
      setSelected(new Set());
    } else if (conn.generation !== pending.generation) {
      setPending(null);
    }
    // settles on each new state, so a re-render of the same state is no answer
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);
  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    if (msg.type === "error") setPending(null);
  }), []);
  const [status, setStatus] = useState<ConnStatus>(conn.status);
  useEffect(() => conn.subscribeStatus(setStatus), []);
  const online = status === "open";
  const [stalled, retry] = useStalled(status);
  // What Play or Bury says while its send is unanswered: the cards stay put
  // until the server's state moves them, and a dropped connection says so
  // instead of waiting silently.
  const pendingLabel = pending === null ? null : online ? "Sending…" : "Reconnecting…";
  const sendAction = (msg: { type: "play" | "bury"; card_ids: number[] }) => {
    if (!conn.send(msg)) return;
    setPending({ handKey, turn: state.turn, generation: conn.generation });
  };

  // When the trick resets and last_trick changed, linger on the finished trick
  // briefly. Derived during render, so the frame that delivers the reset
  // already shows the finished trick instead of an empty table.
  if (prevState !== state) {
    setPrevState(state);
    const prevPlays = prevState.trick?.plays.length ?? 0;
    const nowPlays = state.trick?.plays.length ?? 0;
    const lastChanged = JSON.stringify(prevState.last_trick) !== JSON.stringify(state.last_trick);
    if (state.last_trick && lastChanged && nowPlays < prevPlays) {
      setShownLastTrick(state.last_trick);
    }
  }

  useEffect(() => {
    if (shownLastTrick === null) return;
    const timer = window.setTimeout(() => setShownLastTrick(null), LAST_TRICK_MS);
    return () => window.clearTimeout(timer);
  }, [shownLastTrick]);

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

  const lead = state.phase === "play" ? leadToFollow(state.trick, state.you) : null;

  useTableHaptics(state);

  // Following, the cards no legal play can use are dimmed. Only your hand,
  // the lead and the trump go in: nothing another player holds.
  const following = state.phase === "play" && myTurn && lead !== null;
  const playable = useMemo(
    () => (following && lead ? playableIds(state.hand, lead, state.trump) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [following, state.hand, JSON.stringify(lead), state.trump?.suit, state.trump?.rank]);

  // A tap on a Play that cannot go yet says why, once, above the hand.
  const [hint, setHint] = useState<{ text: string; n: number } | null>(null);
  useEffect(() => {
    if (!hint) return;
    const t = window.setTimeout(() => setHint(null), HINT_MS);
    return () => window.clearTimeout(t);
  }, [hint]);
  useEffect(() => { setHint(null); }, [selected, state.turn, state.phase]);

  // Stable identity so memoized hand cards skip re-rendering (see Hand).
  const toggle = useCallback((id: number) => {
    haptic("select");
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

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
        disabled={selectedIds.length !== 8 || pending !== null || !online}
        aria-busy={pending !== null || undefined}
        onClick={() => sendAction({ type: "bury", card_ids: selectedIds })}
      >
        {pendingLabel ?? `Bury 8 cards (${selectedIds.length}/8)`}
      </button>
    );
  } else if (state.phase === "play" && myTurn) {
    const choosing = selectedIds.length === 0 && pending === null;
    // following, a play is exactly as many cards as the lead
    const need = lead ? lead.length : null;
    const countWrong = need !== null && selectedIds.length !== need;
    const playLabel = selectedIds.length === 0
      ? "Play"
      : need !== null && need > 1 ? `Play (${selectedIds.length}/${need})` : `Play (${selectedIds.length})`;
    const playDisabled = selectedIds.length === 0 || countWrong || pending !== null || !online;
    // a disabled button takes no taps, so its wrapper hears them and explains
    const whyNot = () => {
      if (!playDisabled || pending !== null || !online) return;
      const text = lead ? followHint(lead, state.trump) : "Choose the cards to lead";
      setHint((h) => ({ text, n: (h?.n ?? 0) + 1 }));
      haptic("error");
    };
    actionBar = (
      <>
        <span className="play-wrap" onClick={whyNot}>
          <button
            className={`btn primary${choosing ? " your-turn" : ""}`}
            disabled={playDisabled}
            aria-busy={pending !== null || undefined}
            onClick={() => sendAction({ type: "play", card_ids: selectedIds })}
          >
            {/* a phone shows "Your turn" on Play until you choose a card */}
            <span className="play-text">{pendingLabel ?? playLabel}</span>
            <span className="your-turn-text">Your turn</span>
          </button>
        </span>
        <button
          className="btn subtle"
          disabled={selectedIds.length === 0 || pending !== null}
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
    <div className={`table-screen phase-${state.phase}${showingLast ? " showing-last" : ""}${isYourTurnCue(state) ? " my-turn" : ""}`}>
      <Hud state={state} />
      {state.matched ? <MatchedNote /> : null}
      <div className="felt">
        {opponents.map((p) => (
          <OpponentPanel key={p.seat} player={p} state={state} />
        ))}

        <TrickArea
          state={state}
          trick={trickToShow}
          winner={showingLast && shownLastTrick ? shownLastTrick.winner : null}
          declaration={showingLast ? null : declaration}
          handRects={handRects}
          sweepAfterMs={showingLast ? SWEEP_AFTER_MS : null}
        />

        <div className="you-area">
          {/* your name and your controls; a phone centres them as one row */}
          <div className="you-row">
          <div className={`you-tagline team${me?.team ?? 0}${myTurn ? " on-turn" : ""}`}>
            {iAmBanker ? <span className="banker-crown" title="Banker">👑</span> : null}
            <span className="you-name">{me?.name ?? "You"}</span>
            {myTurn ? <span className="your-turn-tag">your turn</span> : null}
            {state.phase === "declare" && state.passed.includes(state.you) ? (
              <span className="ready-tag">ready</span>
            ) : null}
          </div>
          <div className="action-bar">{actionBar}</div>
          </div>
          {hint ? (
            <div className="follow-hint" role="status" key={hint.n}>{hint.text}</div>
          ) : null}
          <Hand hand={state.hand} selected={selected} selectable={selectable} onToggle={toggle}
                rects={handRects} playable={playable} />
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
      {stalled ? (
        <div className="table-stalled" role="status">
          <span>Can’t reach the server.</span>
          <button className="btn conn-retry" onClick={retry}>Retry</button>
        </div>
      ) : null}
      {toast ? <ToastView key={toast.id} toast={toast} /> : null}
    </div>
  );
}
