import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { effectiveName, useAuth } from "../auth";
import { ChatBody } from "../components/ChatPanel";
import { useGuestName } from "../guestName";
import { TimerRing } from "../components/MoveClock";
import LeaveSheet from "../components/LeaveSheet";
import ConfirmSheet from "../components/ConfirmSheet";
import { useAnyTapIsBack } from "../components/seatHeld";
import { COPIED_MS, inviteAskOf, shareInvite, type InviteAsk } from "../codes";
import type { CodeJoin } from "../codeJoin";
import { takeoverSeats } from "../joinSeats";
import type { DroppedSeat } from "../joinSeats";
import type { ChatMsg, Rank, RoomMsg } from "../protocol";
import type { NearbyJoin } from "../nearbyJoin";
import { RANKS } from "../protocol";
import { isZh, t, useT } from "../i18n";
import Sheet from "./Sheet";
import { BOTS_WARN_MS, queue, useNow } from "./store";
import type { QueueView } from "./store";
import { fromCode, fromQueue, offlineModel, queueSend } from "./tableModel";
import type { MoverSeat, NearbySwitch, PanelAction, Ring, SeatItem, TableButton, TableModel, TableRows as Rows } from "./tableModel";
import { BOT_LEVELS } from "./messages";
import type { BotLevel } from "./messages";
import { OFFER_CLOCK_MS, announcement, moveQuestion, panelKind, shortName } from "./tableText";
import "./tablePanel.css";

export type { SeatItem } from "./tableModel";

/** The initial of the name you play under: the account's, or a guest's own. */
function useMyInitial(): string {
  const account = useAuth();
  const guest = useGuestName();
  const name = account.status === "in" && account.user ? effectiveName(account.user) : guest.name.trim();
  return name.slice(0, 1).toUpperCase();
}

/** A seat's avatar and words; an open seat with no name is its "+" alone,
 *  and its `label` says what it is. */
function SeatBody({ s }: { s: SeatItem }) {
  const mine = useMyInitial();
  if (s.look === "open" && !s.name) return <span className="tp-av" aria-hidden="true">+</span>;
  const av = s.look === "open" ? "+" : s.look === "bot" || s.look === "held" ? "·"
    : s.look === "you" ? mine || "·" : s.name.slice(0, 2).toUpperCase();
  return (
    <>
      <span className="tp-av" aria-hidden="true">{av}</span>
      <span className="tp-seat-text" aria-hidden="true">
        <span className="tp-seat-name">{s.name}{s.tick ? <span className="tp-tick"> ✓</span> : null}</span>
        {s.sub ? <span className="tp-seat-sub">{s.sub}</span> : null}
      </span>
    </>
  );
}

function Seat({ s, team }: { s: SeatItem; team: 0 | 1 }) {
  const className = `tp-seat ${s.look}${s.look === "open" && !s.name ? " bare" : ""} team${team}${s.picked ? " picked" : ""}`;
  if (s.pick) {
    return (
      <button type="button" className={className} aria-label={s.label} aria-pressed={s.picked}
              disabled={s.busy} onClick={s.pick}>
        <SeatBody s={s} />
      </button>
    );
  }
  return <div className={className} role="group" aria-label={s.label}><SeatBody s={s} /></div>;
}

/** The seats at every width, drawn around `layout` (else `you`): its team
 *  on the left with its partner above it, the other team on the right; the
 *  gap between the columns divides them. Us and the team colours follow
 *  `you`, so a seat picker's tap on the right column makes that column Us
 *  while every seat stays where it was. */
function TeamColumns({ seats, you, layout = you }: { seats: SeatItem[]; you: number; layout?: number }) {
  const left = [(layout + 2) % 4, layout].map((at) => seats[at]);
  const right = [(layout + 1) % 4, (layout + 3) % 4].map((at) => seats[at]);
  const t = useT();
  const usLeft = (you - layout + 4) % 2 === 0;
  const label = (us: boolean) => (
    <span className={`tp-team-label ${us ? "ours" : "theirs"}`} aria-hidden="true">{t(us ? "queue.us" : "queue.them")}</span>
  );
  return (
    <div className="tp-teams">
      {label(usLeft)}
      {label(!usLeft)}
      <div className="tp-col">{left.map((s) => <Seat key={s.at} s={s} team={usLeft ? 0 : 1} />)}</div>
      <div className="tp-col">{right.map((s) => <Seat key={s.at} s={s} team={usLeft ? 1 : 0} />)}</div>
    </div>
  );
}

/** Enter presses the primary button while focus is on nothing else that
 *  takes it (a button, a field, an open sheet). Escape does nothing: the
 *  panel is part of the page, and leaving is only ever Leave. */
function useEnterIsPrimary(primary: RefObject<HTMLButtonElement | null>, box: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.defaultPrevented || e.repeat) return;
      if (document.querySelector("[aria-modal='true']")) return;
      const at = document.activeElement;
      const free = !at || at === document.body || at === box.current
        || (box.current?.contains(at) && !at.matches("button, input, textarea, select, a, [role='switch']"));
      const btn = primary.current;
      if (!free || !btn || btn.disabled) return;
      e.preventDefault();
      btn.click();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [primary, box]);
}

/** The small mode tag above a panel's title, set in capitals by CSS. */
function ModeTag({ tag }: { tag: "Casual" | "Offline" }) {
  const t = useT();
  return <p className="tp-tag">{t(tag === "Casual" ? "queue.tag.casual" : "queue.tag.offline")}</p>;
}

/** A countdown's ring on a button. */
const ringOf = (r: Ring | null | undefined): ReactNode => (r ? <TimerRing left={r.left} total={r.total} /> : null);

/** The leader's switch on your own table: on, your timer never starts a
 *  bot game alone; off, the bot countdown runs. */
function WaitSwitch({ on, disabled, act }: { on: boolean; disabled: boolean; act: (a: PanelAction) => void }) {
  const t = useT();
  return (
    <button type="button" role="switch" aria-checked={on} className="q-wait tp-switch"
            disabled={disabled} onClick={() => act({ type: "wait_players", on: !on })}>
      <span className="q-wait-label">{t("queue.waitPeople")}</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

/** The panel's frame, the same for every kind: the title, at most one
 *  status line, the seats in team columns, the rows, the buttons, and the leave sheet when it is up. */
function PanelView({ m, guarded, sheet, act }: {
  m: TableModel; guarded: boolean; sheet?: ReactNode; act: (a: PanelAction) => void;
}) {
  const t = useT();
  const titleId = useId();
  const primaryRef = useRef<HTMLButtonElement | null>(null);
  const box = useRef<HTMLElement | null>(null);
  useEnterIsPrimary(primaryRef, box);
  const seats = m.seats?.map(({ act: a, ...s }): SeatItem => (a ? { ...s, pick: () => act(a) } : s)) ?? null;
  const press = (b: TableButton) => () => { if (b.act) act(b.act); };
  return (
    <section ref={box} className={`tp tp-${m.kind}`} aria-labelledby={titleId}>
      {m.tag ? <ModeTag tag={m.tag} /> : null}
      <h2 className="tp-title" id={titleId}>{m.title}</h2>
      {m.status ? (
        <p className={`tp-line${m.status.warn ? " warn" : ""}`}>
          {m.status.text}
          {m.status.link ? (
            <>
              {" "}
              <button type="button" className="howto-link tp-line-link" onClick={() => act(m.status!.link!.act)}>
                {m.status.link.label}
              </button>
            </>
          ) : null}
        </p>
      ) : null}
      {seats ? <TeamColumns seats={seats} you={m.you} layout={m.layout} /> : null}
      {m.rows ? <TableRows rows={m.rows} wait={m.waitSwitch ?? undefined} act={act}
                           ask={seats ? inviteAskOf(seats, m.you) : undefined} /> : null}
      {m.waitSwitch && !m.rows ? <WaitSwitch {...m.waitSwitch} act={act} /> : null}
      {m.nearbySwitch ? (
        <SwitchRow label={m.nearbySwitch.label} on={m.nearbySwitch.on} disabled={m.nearbySwitch.disabled}
                   onToggle={() => act({ type: "nearby_toggle" })} />
      ) : null}
      {m.chat && "disabled" in m.chat ? (
        <button type="button" className="tp-chat" disabled aria-label={t("queue.chat.offline")}>
          <span className="tp-chat-label" aria-hidden="true">{t("queue.chat")}</span>
        </button>
      ) : m.chat ? <ChatRow messages={m.chat.messages} you={m.chat.you} onSend={(text) => act({ type: "chat", text })} /> : null}
      {m.led ? <p className="tp-led">{ringOf(m.primary?.ring)}{m.led}</p> : (
        <div className="tp-acts">
          {m.primary ? (
            <button ref={primaryRef} type="button"
                    className={`tp-primary${m.primary.waiting ? " waiting" : ""}`}
                    disabled={m.primary.disabled || guarded} aria-busy={m.primary.busy || undefined}
                    onClick={press(m.primary)}>
              {ringOf(m.primary.ring)}
              {m.primary.label}
            </button>
          ) : null}
          {m.secondary ? (
            <button type="button" className="tp-secondary" disabled={m.secondary.disabled}
                    onClick={press(m.secondary)}>
              {m.secondary.label}
            </button>
          ) : null}
        </div>
      )}
      {sheet}
    </section>
  );
}

/** The table you are at, in Play's place: the queue's Join (a game in
 *  progress has a seat), your own table (alone, drawn by the app) or a
 *  shared table (two or three people waiting). Inline and non-modal on
 *  every screen. Leave asks through the leave sheet. */
export default function TablePanel({ q, guarded }: { q: QueueView; guarded: boolean }) {
  useT(); // the model's words follow the language
  const kind = panelKind(q);
  const now = useNow(kind !== "play" && kind !== "elsewhere", 250);
  const [asking, setAsking] = useState(false);
  // "still here?": any tap or key on the page answers it, as at a held seat
  useAnyTapIsBack(kind === "shared" && q.stillHereUntil !== null, () => queue.here());
  const people = kind === "shared" && q.frame
    ? q.frame.seats.map((s) => (s.state === "taken" ? { name: s.name ?? "", sit: s.sit, pair: s.pair } : null)) : null;
  const mover = useOpenerMove(people, (from, to, sit) => queueSend({ type: "move_other", from, to, sit }));
  const m = fromQueue(q, { now, picked: mover.picked });
  if (!m) return null;
  const act = (a: PanelAction) => {
    if (a.type === "ask_leave") setAsking(true);
    else if (a.type === "pick_person") mover.pick(a.at);
    else if (a.type === "move_to") mover.to(a.at);
    else if (a.type !== "code_pick" && a.type !== "code_join" && a.type !== "code_cancel"
             && a.type !== "offline_start" && a.type !== "offline_leave" && a.type !== "nearby_toggle"
             && a.type !== "nearby_settings" && a.type !== "nearby_start" && a.type !== "nearby_again") queueSend(a);
  };
  const sheet = asking ? (
    <LeaveSheet context={m.leave}
                onStay={() => setAsking(false)}
                onLeave={() => { setAsking(false); queueSend({ type: "leave" }); }} />
  ) : mover.sheet;
  return <PanelView m={m} guarded={guarded} sheet={sheet} act={act} />;
}

/** The one code path's panel, in Play's place: a code from the Play box or
 *  a link shows its table (`fromCode`). A dropped player's seat is taken
 *  only after confirming. */
export function JoinCodePanel({ join, busy, onJoin, onCancel, onPick }: {
  join: CodeJoin; busy: boolean; onJoin: () => void; onCancel: () => void; onPick: (seat: number) => void;
}) {
  useT();
  const [asking, setAsking] = useState<DroppedSeat | null>(null);
  const m = fromCode(join, busy);
  const act = (a: PanelAction) => {
    if (a.type === "code_pick") onPick(a.seat);
    else if (a.type === "code_cancel") onCancel();
    else if (a.type === "code_join") {
      const room = join.peek && !join.peek.table ? join.peek : null;
      const dropped = room ? takeoverSeats(room).find((d) => d.seat === join.seat) : undefined;
      if (dropped) setAsking(dropped);
      else onJoin();
    }
  };
  const sheet = asking ? (
    <TakeoverConfirm name={asking.name}
                     onCancel={() => setAsking(null)}
                     onTake={() => { setAsking(null); onJoin(); }} />
  ) : null;
  return <PanelView m={m} guarded={false} sheet={sheet} act={act} />;
}

/** What the offline and nearby panels answer, beyond Start and Leave. */
export interface NearbyActs {
  onToggle?: () => void;
  onSettings?: () => void;
  /** A nearby lobby host's Start. */
  onHostStart?: () => void;
  /** The Bots row's pick (the offline table's, or a nearby lobby's host). */
  onBots?: (level: BotLevel) => void;
}

function offlineAct({ onStart, onLeave, onBots, onToggle, onSettings, onHostStart }: NearbyActs & {
  onStart?: () => void; onLeave: () => void;
}) {
  return (a: PanelAction) => {
    if (a.type === "offline_start") onStart?.();
    else if (a.type === "offline_leave") onLeave();
    else if (a.type === "bot_level") onBots?.(a.level);
    else if (a.type === "nearby_toggle") onToggle?.();
    else if (a.type === "nearby_settings") onSettings?.();
    else if (a.type === "nearby_start") onHostStart?.();
  };
}

/** Your offline table in Play's place (`offlineModel`), with its Bots
 *  row until Start. Leave asks nothing: no one else sits at it. `nearby`:
 *  the Nearby switch row. */
export function OfflinePanel({ ready, starting, bots, onBots, onStart, onLeave, nearby = null, ...acts }: {
  ready: boolean; starting: boolean; bots: BotLevel; onBots: (level: BotLevel) => void;
  onStart: () => void; onLeave: () => void;
  nearby?: NearbySwitch | null;
} & NearbyActs) {
  useT();
  return <PanelView m={offlineModel({ ready, starting, bots, nearby })} guarded={false}
                    act={offlineAct({ onStart, onLeave, onBots, ...acts })} />;
}

/** A nearby table's lobby in Play's place, for its host and each joiner:
 *  the host's Start with the bots' ring, a joiner's wait. `model` is nearbyModel.ts's
 *  `nearbyRoomModel`, passed in by the nearby UI (nearbyUi.tsx), so this
 *  file carries none of nearby play's copy. */
export function NearbyRoomPanel({ room, model, onLeave, ...acts }: {
  room: RoomMsg; onLeave: () => void;
  model: (room: RoomMsg, at: { now: number; botsAt: number | null }) => TableModel;
} & NearbyActs) {
  useT();
  // the ring's end, from when this frame arrived: each frame restamps it
  const botsAt = useMemo(() => {
    const botsIn = room.nearby?.bots_in ?? null;
    return botsIn === null ? null : Date.now() + botsIn * 1000;
  }, [room]);
  const now = useNow(botsAt !== null, 250);
  return <PanelView m={model(room, { now, botsAt })} guarded={false} act={offlineAct({ onLeave, ...acts })} />;
}

/** A nearby code's Join panel: looking, the seat picker, Join and Not now,
 *  or Try again. `model` is nearbyModel.ts's `fromNearbyJoin`. */
export function NearbyJoinPanel({ join, model, onJoin, onCancel, onPick, onAgain }: {
  join: NearbyJoin; model: (join: NearbyJoin) => TableModel;
  onJoin: () => void; onCancel: () => void; onPick: (seat: number) => void; onAgain: () => void;
}) {
  useT();
  const act = (a: PanelAction) => {
    if (a.type === "code_pick") onPick(a.seat);
    else if (a.type === "code_cancel") onCancel();
    else if (a.type === "code_join") onJoin();
    else if (a.type === "nearby_again") onAgain();
  };
  return <PanelView m={model(join)} guarded={false} act={act} />;
}

/** The confirm before taking a dropped player's seat: one question, then
 *  Cancel and Take seat, on the one confirm sheet. */
function TakeoverConfirm({ name, onTake, onCancel }: { name: string; onTake: () => void; onCancel: () => void }) {
  const t = useT();
  return (
    <ConfirmSheet title={t("queue.takeover.title", { name: shortName(name) })} cancel={t("queue.cancel")}
                  confirm={t("queue.takeover.confirm")}
                  confirmClass="seat-take-confirm" onConfirm={onTake} onCancel={onCancel} />
  );
}

/** The opener's move of someone else, for a table's seats: the
 *  person tapped, then the seat, then one confirm, which `send`s it with
 *  the sitting picked. A picked seat that empties or changes hands drops
 *  the pick and its confirm. */
function useOpenerMove(seats: MoverSeat[] | null, send: (from: number, to: number, sit: string | null) => void) {
  const [picked, setPicked] = useState<{ at: number; name: string; sit: string | null } | null>(null);
  const [ask, setAsk] = useState<{ from: number; to: number; names: string[]; sit: string | null } | null>(null);
  const now = picked !== null ? seats?.[picked.at] : null;
  const still = !!now && now.name === picked!.name && (now.sit ?? null) === picked!.sit;
  useEffect(() => { if (picked && !still) { setPicked(null); setAsk(null); } }, [picked, still]);
  const pick = (at: number) => setPicked((was) => (was?.at === at || !seats?.[at] ? null
                                                   : { at, name: seats[at]!.name, sit: seats[at]!.sit ?? null }));
  const to = (dest: number) => {
    if (!picked || !seats) return;
    const s = seats[picked.at];
    const mate = s?.pair ? seats[(picked.at + 2) % 4] : null;
    setAsk({ from: picked.at, to: dest, names: [picked.name, ...(mate ? [mate.name] : [])], sit: picked.sit });
  };
  const sheet = ask ? (
    <MoveConfirm names={ask.names}
                 onMove={() => { send(ask.from, ask.to, ask.sit); setAsk(null); setPicked(null); }}
                 onCancel={() => setAsk(null)} />
  ) : null;
  return { picked: still ? picked!.at : null, pick, to, sheet };
}

/** The one confirm before the opener moves someone: "Move Alice here?",
 *  then Cancel and Move, in the panel's gold: moving is not a way out. */
function MoveConfirm({ names, onMove, onCancel }: { names: string[]; onMove: () => void; onCancel: () => void }) {
  const t = useT();
  return (
    <ConfirmSheet title={moveQuestion(names)} cancel={t("queue.cancel")} confirm={t("queue.move.confirm")}
                  confirmClass="tp-move-confirm"
                  onConfirm={onMove} onCancel={onCancel} />
  );
}

/** The table's chat row: the last line and an unread count, and a tap
 *  opens the chat sheet, the shared Sheet. The same log carries into the game, because the
 *  server turns it into the room's scrollback. */
export function ChatRow({ messages, you, onSend }: {
  messages: ChatMsg[]; you: number; onSend: (text: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => messages[messages.length - 1]?.id ?? -1);
  const lastId = messages[messages.length - 1]?.id ?? -1;
  useEffect(() => { if (open) setSeen(lastId); }, [open, lastId]);
  const unread = messages.filter((m) => m.id > seen && m.seat !== you && m.seat !== -1).length;
  const last = [...messages].reverse().find((m) => m.seat !== -1);
  return (
    <>
      <button type="button" className="tp-chat" aria-expanded={open} onClick={() => setOpen((o) => !o)}
              aria-label={unread ? t("queue.chat.unread", { n: unread }) : t("queue.chat")}>
        <span className="tp-chat-label" aria-hidden="true">{t("queue.chat")}</span>
        <span className="tp-chat-last" aria-hidden="true">{last ? `${shortName(last.name)}: ${last.text}` : ""}</span>
        {unread ? <span className="tp-chat-badge" aria-hidden="true">{unread}</span> : null}
        <Chevron />
      </button>
      {open ? (
        <Sheet title={t("queue.chat")} cancel={null} className="chat-sheet" onClose={() => setOpen(false)}>
          <ChatBody messages={messages} you={you} onSend={onSend} />
        </Sheet>
      ) : null}
    </>
  );
}

/** The share mark beside Invite: a box with an arrow up, in the text's colour. */
function ShareIcon() {
  return (
    <svg className="tp-share" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M8 10H6a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1h-2"
            fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The code and its Invite as one control: a tap opens the share sheet, or
 *  copies the link. A nearby table's code is the code alone (there is no
 *  URL offline). */
function CodeRow({ code, invite: withInvite = true, ask = "three" }: { code: string; invite?: boolean; ask?: InviteAsk }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const spelled = code.split("").join(" ");
  const invite = () => {
    void shareInvite(code, ask).then((didCopy) => {
      if (!didCopy) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MS);
    });
  };
  if (!withInvite) {
    return (
      <div className="tp-code-row">
        <span className="tp-code" aria-label={t("queue.code", { code: spelled })}>{code}</span>
      </div>
    );
  }
  const word = t(copied ? "queue.invite.copied" : "queue.invite");
  return (
    <button type="button" className="tp-code-row tp-invite" onClick={invite}
            aria-label={t(copied ? "queue.invite.copiedLabel" : "queue.invite.label", { code: spelled })}>
      <span className="tp-code" aria-hidden="true">{code}</span>
      <span className="tp-invite-word" aria-hidden="true"><ShareIcon />{word}</span>
    </button>
  );
}

/** A labelled switch row, label only. */
function SwitchRow({ label, on, onToggle, disabled = false }: {
  label: string; on: boolean; onToggle: () => void; disabled?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={on} className="q-wait tp-switch" disabled={disabled}
            onClick={onToggle}>
      <span className="q-wait-label">{label}</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

const BOT_LEVEL_NAMES = { beginner: "queue.set.beginner", standard: "queue.set.standard", advanced: "queue.set.advanced" } as const;
const botLevelName = (b: BotLevel): string => t(BOT_LEVEL_NAMES[b]);

/** A setting row: the opener's select, or the value read-only for everyone else. */
function SetRow<V extends string>({ label, value, values, names, opener, onPick }: {
  label: string; value: V; values: readonly V[]; names: (v: V) => string; opener: boolean; onPick: (v: V) => void;
}) {
  return opener ? (
    <label className="tp-set">
      <span>{label}</span>
      <select aria-label={label} value={value} onChange={(e) => onPick(e.target.value as V)}>
        {values.map((v) => <option key={v} value={v}>{names(v)}</option>)}
      </select>
    </label>
  ) : (
    <div className="tp-set" role="group" aria-label={`${label}${isZh() ? "：" : " "}${names(value)}`}>
      <span aria-hidden="true">{label}</span>
      <span className="tp-set-val" aria-hidden="true">{names(value)}</span>
    </div>
  );
}

/** The chevron at a disclosure row's end; it turns down while the row is open. */
function Chevron() {
  return (
    <svg className="tp-chev" viewBox="0 0 24 24" aria-hidden="true">
      <path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Every table's rows, labels only: the code with its Invite, then the
 *  settings. Starting level and Bots on a casual table (the opener picks
 *  them, others read them; a ranked table starts at 2 with Advanced bots and
 *  has neither row), the opener's Allow joiners switch when ``joiners`` is
 *  set, and the leader's Wait for people when ``wait`` is set. Two or more
 *  settings fold into one Table settings row, closed until tapped, its
 *  values beside the label as a select shows its value; one setting (Bots
 *  offline and at a nearby table) is its own row. A nearby table's code has
 *  no Invite (``invite`` false). */
function TableRows({ rows: { code, invite, ranked, opener, level, joiners, bots }, wait, ask, act }: {
  rows: Rows; wait?: { on: boolean; disabled: boolean }; ask?: InviteAsk; act: (a: PanelAction) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const hasLevel = !ranked && level !== null;
  const settings: ReactNode[] = [];
  if (hasLevel) {
    settings.push(<SetRow key="level" label={t("queue.set.level")} value={level as Rank} values={RANKS} names={(r) => r}
                          opener={opener} onPick={(r) => act({ type: "start_level", level: r })} />);
  }
  if (bots !== undefined) {
    settings.push(<SetRow key="bots" label={t("queue.set.bots")} value={bots} values={BOT_LEVELS} names={botLevelName}
                          opener={opener} onPick={(b) => act({ type: "bot_level", level: b })} />);
  }
  if (joiners !== undefined) {
    settings.push(<SwitchRow key="joiners" label={t("queue.set.joiners")} on={joiners}
                             onToggle={() => act({ type: "allow_joiners", on: !joiners })} />);
  }
  if (wait) settings.push(<WaitSwitch key="wait" {...wait} act={act} />);
  const values = [hasLevel ? t("queue.set.levelValue", { level: level as string }) : null,
                  bots !== undefined ? botLevelName(bots) : null]
    .filter((v): v is string => v !== null);
  return (
    <>
      {code ? <CodeRow code={code} invite={invite !== false} ask={ask} /> : null}
      {settings.length > 1 ? (
        <>
          <button type="button" className="tp-set tp-settings" aria-expanded={open}
                  aria-controls={open ? bodyId : undefined} aria-label={[t("queue.settings"), ...values].join(isZh() ? "，" : ", ")}
                  onClick={() => setOpen((o) => !o)}>
            <span className="tp-settings-label" aria-hidden="true">{t("queue.settings")}</span>
            <span className="tp-set-val" aria-hidden="true">{values.join(" · ")}</span>
            <Chevron />
          </button>
          {open ? <div className="tp-settings-body" id={bodyId}>{settings}</div> : null}
        </>
      ) : settings}
    </>
  );
}

/** The one polite announcement per change of state, and one when ten
 *  seconds are left; the ticking clocks themselves are not read. */
export function TableAnnouncer({ q }: { q: QueueView }) {
  const t = useT();
  const kind = panelKind(q);
  const now = useNow(kind === "join" || kind === "own" || kind === "shared", 500);
  const base = announcement(q);
  let soon = "";
  if (kind === "join" && q.offer && q.offer.expiresAt - now <= OFFER_CLOCK_MS) soon = t("queue.say.offerSoon");
  const botsAt = kind === "shared" || (kind === "own" && !q.waitPlayers) ? q.frame?.timers.bots?.at ?? null : null;
  if (botsAt !== null && botsAt - now <= BOTS_WARN_MS && botsAt > now) soon = t("queue.say.botsSoon");
  return <div className="sr-only" role="status" aria-live="polite">{base ? base + soon : ""}</div>;
}
