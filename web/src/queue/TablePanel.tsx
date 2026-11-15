import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { effectiveName, useAuth } from "../auth";
import { ChatBody } from "../components/ChatPanel";
import { useGuestName } from "../guestName";
import { TimerRing } from "../components/MoveClock";
import LeaveSheet from "../components/LeaveSheet";
import ConfirmSheet from "../components/ConfirmSheet";
import { useAnyTapIsBack } from "../components/seatHeld";
import { COPIED_MS, shareInvite } from "../codes";
import type { ChatMsg, Rank } from "../protocol";
import { RANKS } from "../protocol";
import Sheet from "./Sheet";
import { BOTS_WARN_MS, queue, useNow } from "./store";
import type { QueueView } from "./store";
import { fromQueue, queueSend } from "./tableModel";
import type { MoverSeat, PanelAction, Ring, SeatItem, TableButton, TableModel, TableRows as Rows } from "./tableModel";
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

function SeatBody({ s }: { s: SeatItem }) {
  const mine = useMyInitial();
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
  const className = `tp-seat ${s.look} team${team}${s.picked ? " picked" : ""}`;
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

/** The seats at every width: your team on the left, partner above you,
 *  the other team on the right. */
export function TeamColumns({ seats, you }: { seats: SeatItem[]; you: number }) {
  const ours = [(you + 2) % 4, you].map((at) => seats[at]);
  const theirs = [(you + 1) % 4, (you + 3) % 4].map((at) => seats[at]);
  return (
    <div className="tp-teams">
      <span className="tp-team-label ours" aria-hidden="true">Us</span>
      <span aria-hidden="true" />
      <span className="tp-team-label theirs" aria-hidden="true">Them</span>
      <div className="tp-col">{ours.map((s) => <Seat key={s.at} s={s} team={0} />)}</div>
      <span className="tp-vs" aria-hidden="true">VS</span>
      <div className="tp-col">{theirs.map((s) => <Seat key={s.at} s={s} team={1} />)}</div>
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
export function ModeTag({ tag }: { tag: "Casual" | "Offline" }) {
  return <p className="tp-tag">{tag}</p>;
}

/** A countdown's ring on a button. */
const ringOf = (r: Ring | null | undefined): ReactNode => (r ? <TimerRing left={r.left} total={r.total} /> : null);

/** The leader's switch on your own table: on, your timer never starts a
 *  bot game alone; off, the bot countdown runs. */
function WaitSwitch({ on, disabled, act }: { on: boolean; disabled: boolean; act: (a: PanelAction) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} className="q-wait tp-switch"
            disabled={disabled} onClick={() => act({ type: "wait_players", on: !on })}>
      <span className="q-wait-label">Wait for people</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

/** The panel's frame, the same for every kind: the title, at most one
 *  status line, the seats in team columns, the rows, the buttons, and the leave sheet when it is up. */
function PanelView({ m, guarded, sheet, act }: {
  m: TableModel; guarded: boolean; sheet?: ReactNode; act: (a: PanelAction) => void;
}) {
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
      {m.status ? <p className={`tp-line${m.status.warn ? " warn" : ""}`}>{m.status.text}</p> : null}
      {seats ? <TeamColumns seats={seats} you={m.you} /> : null}
      {m.rows ? <TableRows rows={m.rows} act={act} /> : null}
      {m.waitSwitch ? <WaitSwitch {...m.waitSwitch} act={act} /> : null}
      {m.chat ? <ChatRow messages={m.chat.messages} you={m.chat.you} onSend={(text) => act({ type: "chat", text })} /> : null}
      {m.led ? <p className="tp-led">{ringOf(m.primary?.ring)}{m.led}</p> : (
        <div className="tp-acts">
          {m.primary ? (
            <button ref={primaryRef} type="button"
                    className={`tp-primary${m.primary.searching ? " searching" : ""}${m.primary.waiting ? " waiting" : ""}`}
                    disabled={m.primary.disabled || guarded} onClick={press(m.primary)}>
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
  const kind = panelKind(q);
  const now = useNow(kind !== "play" && kind !== "elsewhere", 250);
  const [asking, setAsking] = useState(false);
  // "still here?": any tap or key on the page answers it, as at a held seat
  useAnyTapIsBack(kind === "shared" && q.stillHereUntil !== null, () => queue.here());
  const mover = useOpenerMove(q.table?.seats ?? null, (from, to, sit) => queueSend({ type: "move_other", from, to, sit }));
  const m = fromQueue(q, { now, picked: mover.picked });
  if (!m) return null;
  const act = (a: PanelAction) => {
    if (a.type === "ask_leave") setAsking(true);
    else if (a.type === "pick_person") mover.pick(a.at);
    else if (a.type === "move_to") mover.to(a.at);
    else queueSend(a);
  };
  const sheet = asking ? (
    <LeaveSheet context={m.leave}
                onStay={() => setAsking(false)}
                onLeave={() => { setAsking(false); queueSend({ type: "leave" }); }} />
  ) : mover.sheet;
  return <PanelView m={m} guarded={guarded} sheet={sheet} act={act} />;
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
  return (
    <ConfirmSheet title={moveQuestion(names)} cancel="Cancel" confirm="Move" confirmClass="tp-move-confirm"
                  onConfirm={onMove} onCancel={onCancel} />
  );
}

/** The table's chat row: the last line and an unread count, and a tap
 *  opens the chat sheet, the shared Sheet. The same log carries into the game, because the
 *  server turns it into the room's scrollback. */
export function ChatRow({ messages, you, onSend }: {
  messages: ChatMsg[]; you: number; onSend: (text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => messages[messages.length - 1]?.id ?? -1);
  const lastId = messages[messages.length - 1]?.id ?? -1;
  useEffect(() => { if (open) setSeen(lastId); }, [open, lastId]);
  const unread = messages.filter((m) => m.id > seen && m.seat !== you && m.seat !== -1).length;
  const last = [...messages].reverse().find((m) => m.seat !== -1);
  return (
    <>
      <button type="button" className="tp-chat" aria-expanded={open} onClick={() => setOpen((o) => !o)}
              aria-label={unread ? `Chat, ${unread} new` : "Chat"}>
        <span className="tp-chat-label" aria-hidden="true">Chat</span>
        <span className="tp-chat-last" aria-hidden="true">{last ? `${shortName(last.name)}: ${last.text}` : ""}</span>
        {unread ? <span className="tp-chat-badge" aria-hidden="true">{unread}</span> : null}
      </button>
      {open ? (
        <Sheet title="Chat" cancel={null} className="chat-sheet" onClose={() => setOpen(false)}>
          <ChatBody messages={messages} you={you} onSend={onSend} />
        </Sheet>
      ) : null}
    </>
  );
}

/** The code with its Invite link: the share sheet, or a copy. */
function CodeRow({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const invite = () => {
    void shareInvite(code).then((didCopy) => {
      if (!didCopy) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MS);
    });
  };
  return (
    <div className="tp-code-row">
      <span className="tp-code" aria-label={`Table code ${code.split("").join(" ")}`}>{code}</span>
      <button type="button" className="tp-invite" onClick={invite}>{copied ? "Link copied" : "Invite link"}</button>
    </div>
  );
}

/** A labelled switch row, label only. */
function SwitchRow({ label, on, onToggle }: { label: string; on: boolean; onToggle: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} className="q-wait tp-switch" onClick={onToggle}>
      <span className="q-wait-label">{label}</span>
      <span className="q-switch" aria-hidden="true" />
    </button>
  );
}

/** Every table's settings rows, labels only: the code with its Invite link,
 *  Starting level on a casual table (the opener picks it, others read it; a
 *  ranked table starts at 2 and has no row), and the opener's Allow joiners
 *  switch when ``joiners`` is set. */
function TableRows({ rows: { code, ranked, opener, level, joiners }, act }: {
  rows: Rows; act: (a: PanelAction) => void;
}) {
  return (
    <>
      {code ? <CodeRow code={code} /> : null}
      {ranked ? null : opener ? (
        <label className="tp-set">
          <span>Starting level</span>
          <select aria-label="Starting level" value={level}
                  onChange={(e) => act({ type: "start_level", level: e.target.value as Rank })}>
            {RANKS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      ) : (
        <div className="tp-set" role="group" aria-label={`Starting level ${level}`}>
          <span aria-hidden="true">Starting level</span>
          <span className="tp-set-val" aria-hidden="true">{level}</span>
        </div>
      )}
      {joiners !== undefined ? (
        <SwitchRow label="Allow joiners" on={joiners} onToggle={() => act({ type: "allow_joiners", on: !joiners })} />
      ) : null}
    </>
  );
}

/** The one polite announcement per change of state, and one when ten
 *  seconds are left; the ticking clocks themselves are not read. */
export function TableAnnouncer({ q }: { q: QueueView }) {
  const kind = panelKind(q);
  const now = useNow(kind === "join" || kind === "own" || kind === "shared", 500);
  const base = announcement(q);
  let soon = "";
  if (kind === "join" && q.offer && q.offer.expiresAt - now <= OFFER_CLOCK_MS) soon = " 10 seconds left to join.";
  const botsAt = kind === "own" && !q.waitPlayers ? q.botsAt : kind === "shared" ? q.table?.timer?.at ?? null : null;
  if (botsAt !== null && botsAt - now <= BOTS_WARN_MS && botsAt > now) soon = " Bots fill the empty seats in 10 seconds.";
  return <div className="sr-only" role="status" aria-live="polite">{base ? base + soon : ""}</div>;
}
