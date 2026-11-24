import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { GameState, HandCard, LastTrick, ServerMsg, StatePlayer } from "../protocol";
import { conn } from "../ws";
import type { ConnStatus } from "../ws";
import { NEARBY_SESSION, useOffline } from "../offlineMode";
import Card, { shortLabel } from "./Card";
import Hand from "./Hand";
import type { HandRects } from "./Hand";
import { DUR } from "../motion";
import Hud from "./Hud";
import RoundEndModal from "./RoundEndModal";
import TrickArea, { seatPos } from "./TrickArea";
import ChatPanel, { type ChatMsg } from "./ChatPanel";
import ChatBubbles from "./ChatBubbles";
import OpponentActions from "./OpponentActions";
import { syncBlocked } from "../chatBlocks";
import { haptic } from "../native";
import { nameWidthClass } from "../nameWidth";
import Toast from "./Toast";
import HandLine from "./HandLine";
import { leadToFollow } from "../follow";
import { followHint, followsSuit } from "../followRules";
import { TimerRing } from "./MoveClock";
import { LOW_SECS, MOVE_SECS, useMoveClock } from "../useMoveClock";
import { NUDGE_MS, coachFor, coachShows, isNewcomer, playsMade, recordPlay, subscribeCoach, useAccountNewcomer, useCoachSetting } from "../firstTurns";
import { showToast } from "../toast";
import { TurnClock, leadKind, nextTurnNumber, telemetry, useScreen } from "../telemetry";
import { bankerText, buryHelp, buryPointsText, declareHelp, seatStatus, seatStatusParts } from "../tableCopy";
import { t, useT } from "../i18n";
import type { MessageKey } from "../i18n";
import LastTrickPanel from "./LastTrickPanel";
import LeaveSheet from "./LeaveSheet";
import { SeatHeldPill } from "./ConnectionPill";
import { useAnyTapIsBack } from "./seatHeld";

// the debug overlay loads on its first open, so a player's page never carries it
const XrayPanel = lazy(() => import("./XrayPanel"));

/** The declare window's full length, for the countdown ring (server.py DECLARE_GRACE). */
const DECLARE_WINDOW_SECS = 5;

const LAST_TRICK_MS = 1500;
/** At a nearby table, how late a move's answer is before Play says Sending…. */
export const SENDING_AFTER_MS = 1500;
// The sweep ends a little before the finished trick is replaced, so the
// table never waits on it.
const SWEEP_AFTER_MS = LAST_TRICK_MS - DUR.sweep - 40;

/** "Declare ♠2 pair", plus the bare "♠2 pair" that a phone shows after one
 *  "Declare" label for the whole row. */
function declareLabel(ids: number[], hand: HandCard[]): ReactNode {
  const codes = ids.map((id) => hand.find((c) => c.id === id)?.code ?? "?");
  const first = codes[0] ?? "?";
  const code = shortLabel(first);
  const nt = first === "LJ" || first === "BJ";
  const pair = codes.length === 2;
  const full = nt ? t("table.declareNt") : pair ? t("table.declarePair", { code }) : t("table.declareCard", { code });
  const short = nt ? t("table.nt") : pair ? t("table.cardPair", { code }) : code;
  return <><span className="declare-full">{full}</span><span className="declare-short">{short}</span></>;
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

const BOT_BANTER: Record<"bury" | "play", readonly MessageKey[]> = {
  bury: ["table.banterBury1", "table.banterBury2", "table.banterBury3", "table.banterBury4"],
  play: ["table.banterPlay1", "table.banterPlay2", "table.banterPlay3", "table.banterPlay4"],
};

function BotThinking({ phase }: { phase: "bury" | "play" }) {
  const t = useT();
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
      {/* The seat's gold edge shows whose turn it is; this status is for screen readers. */}
      <div className="thinking sr-only" role="status" aria-live="polite">
        {phase === "bury" ? t("table.choosingBury") : t("table.consideringPlay")}
      </div>
      {/* Cosmetic copy only; no card identities, scores, or search reasoning.
          Keep rotation outside the live region so screen readers are not spammed. */}
      <div className="bot-banter">{t(BOT_BANTER[phase][line])}</div>
    </>
  );
}

/** How long a refused Play's hint stays above the hand. */
export const HINT_MS = 2600;

/** How long the full-name popover stays up after a tap or long press. */
const FULL_NAME_MS = 2500;
const LONG_PRESS_MS = 450;

function OpponentPanel({ player, state }: { player: StatePlayer; state: GameState }) {
  const t = useT();
  const pos = seatPos(player.seat, state.you);
  // a tap or long press shows the whole name; only the phone layout draws it
  const [fullName, setFullName] = useState(false);
  // a long press (or a right click) on a person's seat also offers block and
  // report, which are the game server's; a table on a device (offline, or a
  // nearby phone's) never offers them
  const [actions, setActions] = useState(false);
  const offline = useOffline();
  const canAct = !player.is_bot && !offline;
  const pressTimer = useRef<number | null>(null);
  const longPressed = useRef(false);
  const optionsButton = useRef<HTMLButtonElement | null>(null);
  const openedByButton = useRef(false);
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
  // the seat's own move clock, so everyone sees whom the table waits for;
  // only the seat's owner is buzzed
  const moveClock = useMoveClock(player.turn_deadline, state, false);
  const status = seatStatus(player, takeover);
  const countdown = seatStatusParts(player, takeover);
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
             if (canAct) setActions(true);
           }, LONG_PRESS_MS);
         }}
         onContextMenu={(event) => {
           if (!canAct) return;
           event.preventDefault();
           setActions(true);
         }}
         onPointerUp={endPress}
         onPointerLeave={endPress}
         onPointerCancel={endPress}>
      {fullName ? <span className="opp-fullname" role="tooltip">{player.name}</span> : null}
      {/* the long press has no screen-reader or keyboard path, so a person's
          seat also carries an unseen button that opens the same options */}
      {canAct ? (
        <button type="button" className="sr-only opp-options" ref={optionsButton}
                aria-label={t("table.playerOptions", { name: player.name })} aria-haspopup="dialog" aria-expanded={actions}
                onClick={(event) => { event.stopPropagation(); openedByButton.current = true; setActions(true); }} />
      ) : null}
      {actions && canAct ? (
        <OpponentActions room={state.room} seat={player.seat} name={player.name}
                         onClose={() => {
                           setActions(false);
                           // focus goes back to the seat's button only when it opened the options
                           if (openedByButton.current) optionsButton.current?.focus();
                           openedByButton.current = false;
                         }} />
      ) : null}
      <div className="opp-name">
        {/* the phone pill carries the team as a dot and the turn as a gold
            fill ending in "…" */}
        <span className={`seat-dot t${player.team}`} aria-hidden="true" />
        {/* the crown alone marks the banker; its label says so in words */}
        {player.is_banker ? (
          <span className="banker-crown" role="img" aria-label={bankerText(player, state.you)}>👑</span>
        ) : null}
        {/* a seat whose owner left is the bot's now: "Bot (Alice left)" is its name */}
        <span className={`opp-name-text${player.left ? " left-tag" : ""}`}>{player.left ? status : player.name}</span>
        {/* always drawn, so the label's width never changes with the turn */}
        <span className={`turn-dots${onTurn && actionPhase ? " shown" : ""}`} aria-hidden="true">…</span>
        <TimerRing left={moveClock} total={MOVE_SECS} thin />
        {player.is_bot ? <span className="bot-tag">{t("table.botTag")}</span> : null}
        {hasPassed ? <span className="ready-tag">{t("table.readyTag")}</span> : null}
        {player.away && player.connected ? <span className="away-tag">{t("table.awayTag")}</span> : null}
        {/* the phone pill keeps the count whole and drops the words before it
            (they stay for screen readers) */}
        {status !== null && !player.left ? (
          countdown ? (
            <span className="off-tag counting"><span className="off-lead">{countdown.lead}</span>{countdown.count}</span>
          ) : <span className="off-tag">{status}</span>
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
      {onTurn && actionPhase && !botControlled ? <div className="their-turn">{t("table.theirTurn")}</div> : null}
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
 *  round, or the whole game (a heavier pattern of its own). Each fires on the
 *  transition, never on a repeat state; a won trick
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
  const wonGame = wonRound && state.round_result?.point_scored === true;
  const prevResult = useRef(hadResult);
  useEffect(() => {
    if (hadResult && !prevResult.current && wonRound) haptic(wonGame ? "game" : "won");
    prevResult.current = hadResult;
  }, [hadResult, wonRound, wonGame]);
}

/** The joins still outstanding at each room, once told, so a remount of the
 *  table (How to play and back) tells none of them again. A join that is no
 *  longer listed is forgotten, so the same join later is news. */
const toldJoins = new Map<string, Set<string>>();

/** An open-table newcomer is told once, as a toast: "Alice joins next trick"
 *  before the handover, "Alice joins next round" when seated at the round
 *  end. The newcomer itself is not told. */
function useJoinToasts(state: GameState) {
  const lines = (state.joining ?? []).filter((j) => j.seat !== state.you && !state.joining_you);
  const keys = lines.map((j) => `${j.seat}:${j.when}:${j.name}`);
  useEffect(() => {
    const told = toldJoins.get(state.room) ?? new Set<string>();
    toldJoins.set(state.room, new Set(keys));
    lines.forEach((j, i) => {
      if (told.has(keys[i])) return;
      showToast(t(j.when === "round" ? "table.joinsNextRound" : "table.joinsNextTrick", { name: j.name }), { info: true, dot: (j.seat % 2) as 0 | 1 });
    });
    // told on a new key only; the lines are read with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.room, keys.join("|")]);
}

/** The decision whose clock is running, kept across a remount of the
 *  table (opening How to play and coming back is the same decision). */
let openTurn: { key: string; clock: TurnClock; watched: boolean } | null = null;

/** The joining pill's Leave: the seat is not yours until this trick ends,
 *  but leaving still costs what leaving the joined round costs, so it asks
 *  through the leave sheet like every other leave. */
function JoinPillLeave({ ranked, guest }: { ranked: boolean; guest: boolean }) {
  const t = useT();
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button className="btn join-leave" onClick={() => setAsking(true)}>{t("common.leave")}</button>
      {asking ? (
        <LeaveSheet context={{ kind: "game", ranked, guest }}
                    onStay={() => setAsking(false)}
                    onLeave={() => { conn.send({ type: "table_leave" }); setAsking(false); }} />
      ) : null}
    </>
  );
}

export default function Table({ state }: { state: GameState }) {
  const t = useT();
  // The last state without a result, and the socket that brought it. A
  // result that follows it on the same socket arrived live and may
  // celebrate, and the round end reads the levels the round was played at
  // from it. A table opened onto a finished round, or a reconnect onto one
  // (a new socket), draws it settled from the result alone.
  const lastLive = useRef<{ generation: number; levels: [string, string] } | null>(null);
  if (state.round_result === null) lastLive.current = { generation: conn.generation, levels: state.levels };
  const liveHere = lastLive.current !== null && lastLive.current.generation === conn.generation;
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
  // the server marks the seats this viewer blocked, in this game and every later one
  useEffect(() => syncBlocked(state.room, state.players), [state.room, state.players]);
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
  //   it never reached the server, so it goes again once on the new
  //   connection while its cards are still in hand (the server refuses it
  //   if it is no longer legal; a socket it replaced can no longer act); a
  //   second reconnect with it still unanswered clears pending, and the
  //   selection stays for a retry;
  // - an error comes back: pending clears and the selection stays.
  // The socket opening alone settles nothing, and neither does a same-hand
  // broadcast on the connection the play was sent on.
  const [pending, setPending] = useState<{
    kind: "play" | "bury"; cardIds: number[]; handKey: string; turn: number | null;
    generation: number; resent: boolean;
  } | null>(null);
  const handKey = state.hand.map((c) => c.id).join(",");
  // your own plays so far in this browser; the first few get the coach
  const [plays, setPlays] = useState(playsMade);
  useEffect(() => {
    if (!pending) return;
    if (handKey !== pending.handKey || state.turn !== pending.turn) {
      // Only a state on the connection the play went out on proves it was
      // yours: across a reconnect the seat's bot may have moved instead.
      const sameLink = conn.generation === pending.generation;
      if (pending.kind === "play" && sameLink && isNewcomer(plays)) setPlays(recordPlay());
      setPending(null);
      setSelected(new Set());
    } else if (conn.generation !== pending.generation) {
      const inHand = new Set(state.hand.map((c) => c.id));
      const again = !pending.resent && state.turn === state.you && !state.joining_you
        && state.phase === pending.kind && pending.cardIds.every((id) => inHand.has(id))
        && conn.send({ type: pending.kind, card_ids: pending.cardIds });
      setPending(again ? { ...pending, generation: conn.generation, resent: true } : null);
    }
    // settles on each new state, so a re-render of the same state is no answer
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);
  // the turn telemetry reads the send in flight when a turn ends or an error comes
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const turnRef = useRef<TurnClock | null>(null);
  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    if (msg.type !== "error") return;
    if (pendingRef.current !== null && turnRef.current !== null) {
      turnRef.current.refused += 1;
      telemetry.notice("illegal_play", "table");
    }
    setPending(null);
  }), []);
  const [status, setStatus] = useState<ConnStatus>(conn.status);
  useEffect(() => conn.subscribeStatus(setStatus), []);
  const online = status === "open";
  // What Play or Bury says while its send is unanswered: the cards stay put
  // until the server's state moves them, and a dropped connection says so
  // instead of waiting silently.
  // At a nearby table a move's answer can take a moment over the radio: Play
  // says Sending… only once the answer is SENDING_AFTER_MS late, and the
  // link's own state (the pill, the dot) says when it has really stalled.
  const [late, setLate] = useState(false);
  useEffect(() => {
    setLate(false);
    if (pending === null || !NEARBY_SESSION) return;
    const timer = window.setTimeout(() => setLate(true), SENDING_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [pending]);
  const pendingLabel = pending === null ? null : !online ? t("table.reconnecting")
    : NEARBY_SESSION && !late ? null : t("table.sending");
  const sendAction = (msg: { type: "play" | "bury"; card_ids: number[] }) => {
    if (!conn.send(msg)) return;
    setPending({ kind: msg.type, cardIds: msg.card_ids, handKey, turn: state.turn,
                 generation: conn.generation, resent: false });
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
  // a newcomer waiting for the handover watches its seat: the bot plays it
  const watching = state.joining_you === true;
  const myTurn = state.turn === state.you && !watching;
  const iAmBanker = me?.is_banker ?? false;

  const selectable = !watching &&
    ((state.phase === "bury" && iAmBanker) || state.phase === "play");

  const lead = state.phase === "play" ? leadToFollow(state.trick, state.you) : null;

  useTableHaptics(state);
  // your move timer (ranked tables): the ring for the whole decision, red in
  // its last seconds, and a haptic at five
  const clock = useMoveClock(me?.turn_deadline, state);
  // the post-deal declare window: a ring on its buttons, no haptic
  const declareClock = useMoveClock(state.phase === "declare" ? state.declare_deadline : null, state, false);
  const away = me?.away ?? false;
  // a bot holds your seat: one pill, and any tap or key counts as back; while
  // the socket is down the connection pill says Reconnecting in its place
  const held = away && !watching && online;
  const back = useAnyTapIsBack(held, () => conn.send({ type: "im_back" }));


  // The last trick, reopened on request; it stays until dismissed.
  const [lastOpen, setLastOpen] = useState(false);
  useEffect(() => { if (state.phase !== "play") setLastOpen(false); }, [state.phase]);

  // A tap on a Play that cannot go yet says why, once, above the hand.
  const [hint, setHint] = useState<{ text: string; n: number } | null>(null);
  useEffect(() => {
    if (!hint) return;
    const t = window.setTimeout(() => setHint(null), HINT_MS);
    return () => window.clearTimeout(t);
  }, [hint]);
  useEffect(() => { setHint(null); }, [selected, state.turn, state.phase]);

  // A newcomer's turn says what to tap, lights the cards that follow the
  // lead, and after NUDGE_MS with nothing chosen nudges once more.
  // The switch in the menu pins the coach on or off; untouched, it follows
  // the newcomer count and the account's rounds. Flipping it says so in a toast.
  const coachSwitch = useCoachSetting();
  const newAccount = useAccountNewcomer();
  useEffect(() => subscribeCoach((s) => {
    telemetry.tap(s === "on" ? "coach_on" : "coach_off");
    showToast(s === "on" ? t("table.coachOn") : t("table.coachOff"), { info: true });
  }), [t]);
  useJoinToasts(state);
  // One decision for all teaching text at the table: the coach's cues and
  // the declare and bury help. A refused tap's reason is feedback, not
  // teaching, and shows either way.
  const coachOn = coachShows(coachSwitch, plays, newAccount);
  const coach = state.phase === "play" && myTurn && pending === null && coachOn
    ? coachFor(state.hand, lead, state.trump)
    : null;
  const coaching = coach !== null;

  // One of your decisions, from the state that hands it to you to the state
  // that moves past it. The key advances when a play lands or a new trick
  // starts (the trick's leader and size, your hand's size), so a last
  // follower who wins and leads at once closes one decision and opens the
  // next, while a broadcast that changes neither is the same decision. It
  // ends as yours when this socket's own send was in flight, else the bot's
  // (away) or the move timer's. Leaving the table is no transition: the
  // open clock is kept for a remount and never reported as a finished turn.
  useScreen("table");
  const turnActive = !watching &&
    ((state.phase === "bury" && iAmBanker) || (state.phase === "play" && myTurn));
  const decisionKey = turnActive
    ? `${state.room}:${state.phase}:${state.trick?.leader ?? "-"}:${state.trick?.plays.length ?? 0}:${state.hand.length}`
    : null;
  useEffect(() => {
    const open = openTurn;
    if (open !== null && open.key !== decisionKey) {
      openTurn = null;
      turnRef.current = null;
      // seen ending only if this mount watched it: a turn that ended while
      // the table was not shown has no observed outcome and is dropped
      if (open.watched) {
        // the settle effect has not re-rendered yet, so pendingRef still
        // holds the send (if any) that this state answered
        const sent = pendingRef.current;
        const mine = sent !== null && sent.generation === conn.generation;
        telemetry.turnDone(open.clock.finish(mine ? "you" : me?.away ? "bot" : "timer"));
      }
    }
    if (decisionKey === null) return;
    if (openTurn === null) {
      const phase = state.phase === "bury" ? "bury" : "play";
      openTurn = {
        key: decisionKey, watched: true,
        clock: new TurnClock(phase, phase === "bury" ? 8 : lead ? lead.length : 0,
                             lead ? leadKind(lead) : undefined, coaching, nextTurnNumber()),
      };
    }
    openTurn.watched = true;
    turnRef.current = openTurn.clock;
    // the decision is its key; the rest is read when it opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decisionKey]);
  useEffect(() => () => {
    // unmounting: keep the clock for a remount, but this mount no longer sees it end
    if (openTurn !== null) openTurn.watched = false;
    turnRef.current = null;
  }, []);
  const nothingChosen = selected.size === 0;
  const [nudge, setNudge] = useState(false);
  useEffect(() => {
    setNudge(false);
    if (!coaching || !nothingChosen) return;
    const t = window.setTimeout(() => setNudge(true), NUDGE_MS);
    return () => window.clearTimeout(t);
  }, [coaching, nothingChosen, state.turn, handKey]);

  // Stable identity so memoized hand cards skip re-rendering (see Hand).
  const toggle = useCallback((id: number) => {
    haptic("select");
    turnRef.current?.select();
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
    : state.phase === "play" || state.phase === "round_end"
      ? state.trick
      : null;
  const declaration =
    state.phase === "deal" || state.phase === "declare" || state.phase === "bury"
      ? state.current_declaration
      : null;
  // how many cards your own slot of the cross holds, so the phone row's
  // crown can stand clear of them and of their LEAD / WINS tags
  const mySlotCards = trickToShow?.plays.find((p) => p.seat === state.you)?.cards.length
    ?? (declaration?.seat === state.you ? declaration.cards.length : 0);

  let actionBar: ReactNode = null;
  // the hand line's parts that the phase sets: why Play waits, and the
  // phase's help while the coach is on
  let blocked: string | null = null;
  let phaseHelp: string | null = null;
  if (watching) {
    actionBar = null;
  } else if (state.phase === "deal" || state.phase === "declare") {
    // Declaration is a race: options can appear for anyone during dealing and
    // during the short declare window afterwards. No Pass while dealing.
    const canDeclare = state.declare_options.length > 0;
    const iPassed = state.passed.includes(state.you);
    if (canDeclare && coachOn) phaseHelp = declareHelp(state);
    actionBar = (
      <>
        {state.phase === "declare" && !iPassed ? <TimerRing left={declareClock} total={DECLARE_WINDOW_SECS} /> : null}
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
            {iPassed ? t("table.passed") : t("table.pass")}
          </button>
        ) : null}
      </>
    );
  } else if (state.phase === "bury" && iAmBanker) {
    if (coachOn) phaseHelp = buryHelp();
    actionBar = (
      <>
      <TimerRing left={clock} total={MOVE_SECS} />
      {/* drawn at full contrast, its fill the count's share of 8 */}
      <button
        className="btn primary bury-btn"
        style={{ "--bury-fill": `${(Math.min(selectedIds.length, 8) / 8) * 100}%` } as CSSProperties}
        disabled={selectedIds.length !== 8 || pending !== null || !online}
        aria-busy={pending !== null || undefined}
        onClick={() => sendAction({ type: "bury", card_ids: selectedIds })}
      >
        {pendingLabel ?? t("table.bury", { n: selectedIds.length })}
      </button>
      {/* the points are teaching, like the phase's help: shown only with the coach */}
      {coachOn ? <span className="bury-points" role="status">{buryPointsText(state.hand, selected)}</span> : null}
      </>
    );
  } else if (state.phase === "play" && myTurn) {
    const choosing = selectedIds.length === 0 && pending === null;
    // following, a play is exactly as many cards as the lead
    const need = lead ? lead.length : null;
    const countWrong = need !== null && selectedIds.length !== need;
    // the right count but too few of the led suit: Play waits and says why
    const offSuit = lead !== null && !countWrong
      && followsSuit(state.hand, selectedIds, lead, state.trump) === false;
    const playLabel = selectedIds.length === 0
      ? t("table.play")
      : need !== null && need > 1 ? t("table.playOf", { n: selectedIds.length, count: need }) : t("table.playN", { n: selectedIds.length });
    const playDisabled = selectedIds.length === 0 || countWrong || offSuit || pending !== null || !online;
    // a disabled button takes no taps, so its wrapper hears them and explains
    const whyNot = () => {
      if (!playDisabled || pending !== null || !online) return;
      const text = lead ? followHint(lead, state.trump) : t("table.chooseLead");
      if (turnRef.current) turnRef.current.disabledTaps += 1;
      telemetry.notice(lead ? "follow_hint" : "lead_hint", "table");
      setHint((h) => ({ text, n: (h?.n ?? 0) + 1 }));
      haptic("error");
    };
    if (offSuit && lead) blocked = followHint(lead, state.trump);
    actionBar = (
      <>
        <TimerRing left={clock} total={MOVE_SECS} />
        <span className="play-wrap" onClick={whyNot}>
          <button
            className={`btn primary${choosing ? " your-turn" : ""}`}
            disabled={playDisabled}
            aria-busy={pending !== null || undefined}
            onClick={() => sendAction({ type: "play", card_ids: selectedIds })}
          >
            {/* a phone shows "Your turn" on Play until you choose a card */}
            <span className="play-text">{pendingLabel ?? playLabel}</span>
            <span className="your-turn-text">{t("table.yourTurn")}</span>
          </button>
        </span>
        <button
          className="btn subtle"
          disabled={selectedIds.length === 0 || pending !== null}
          onClick={() => setSelected(new Set())}
        >
          {t("table.clear")}
        </button>
      </>
    );
  }

  return (
    <div className={`table-screen phase-${state.phase}${showingLast ? " showing-last" : ""}${isYourTurnCue(state) ? " my-turn" : ""}`}>
      <Hud state={state} />
      <div className="felt">
        {opponents.map((p) => (
          <OpponentPanel key={p.seat} player={p} state={state} />
        ))}

        {state.phase === "play" && state.last_trick ? (
          <button className="btn subtle last-trick-btn" aria-expanded={lastOpen}
                  onClick={() => setLastOpen((o) => !o)}>
            {t("table.lastTrick")}
          </button>
        ) : null}
        {lastOpen && state.last_trick ? (
          <LastTrickPanel state={state} trick={state.last_trick} onClose={() => setLastOpen(false)} />
        ) : null}

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
          <div className="you-row" style={{ "--my-slot-n": mySlotCards } as CSSProperties}>
          <div className={`you-tagline team${me?.team ?? 0}${myTurn ? " on-turn" : ""}`}>
            {iAmBanker && me ? (
              <span className="banker-crown" role="img" aria-label={bankerText(me, state.you)}>👑</span>
            ) : null}
            <span className="you-name">{me?.name ?? t("common.you")}</span>
            {myTurn ? <span className="your-turn-tag">{t("table.yourTurnTag")}</span> : null}
            {state.phase === "declare" && state.passed.includes(state.you) ? (
              <span className="ready-tag">{t("table.readyTag")}</span>
            ) : null}
          </div>
          <div className={`action-bar${clock !== null && clock <= LOW_SECS ? " clock-low" : ""}`}
               data-declare-label={t("table.declarePill")}>{actionBar}</div>
          </div>
          {/* the one line between the trick and your hand */}
          <HandLine parts={{ reason: hint?.text ?? blocked, help: phaseHelp, coach: coach && nothingChosen ? coach.text : null }}
                    tap={hint?.n ?? 0} nudge={nudge} />
          <Hand hand={state.hand} selected={selected} selectable={selectable} onToggle={toggle}
                rects={handRects} lit={coach?.follow ?? null} />
        </div>
      </div>

      {state.phase === "round_end" && state.round_result ? (
        <RoundEndModal state={state} result={state.round_result} clock={clock} live={liveHere}
                       before={liveHere ? lastLive.current!.levels : null} />
      ) : null}

      {xrayOpen ? (
        <Suspense fallback={null}>
          <XrayPanel state={state} onClose={() => setXrayOpen(false)} />
        </Suspense>
      ) : null}
      {state.players.filter((p) => !p.is_bot).length > 1 && (
        <button className="chat-launch" onClick={() => setChatOpen((o) => !o)}
                aria-label={t("table.chat")}>
          💬{unread > 0 && <span className="chat-badge">{unread}</span>}
        </button>
      )}
      <ChatBubbles state={state} open={chatOpen} onOpen={() => setChatOpen(true)} />
      <ChatPanel messages={chat} you={state.you} open={chatOpen}
                 onClose={() => setChatOpen(false)} />
      {watching ? (
        <div className="away-pill join-pill" role="status">
          <span className="away-pill-text">
            <b>{t("table.joiningAfterTrick")}</b>
          </span>
          <JoinPillLeave ranked={!!state.matched} guest={state.guest === true} />
        </div>
      ) : null}
      {held ? <SeatHeldPill onBack={back} /> : null}
      <Toast place="table" />
    </div>
  );
}
