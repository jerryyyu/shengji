// Test doubles' table frames: the `table` frame the server sends right
// after a queue_state that holds the entry, built from that queue_state
// (a port of server/tests/test_table_frame.py `from_queue_state`, plus the
// seats the server sends while you are alone). `fixtures/table_frames.json`
// holds the server's own pairs, which `testFrames.test.ts` holds this to.
import type { PartyMsg, TableFrameMsg, TableFrameSeatMsg, WaitingTableMsg } from "./messages";

type QueueStateLike = Record<string, unknown>;

function emptySeat(seat: number, state: "open" | "held"): TableFrameSeatMsg {
  return { seat, team: (seat % 2) as 0 | 1, state, name: null, you: false, ready: false, reconnecting: false,
           since: null, sit: null, pair: false, leader: false, left: false };
}

function takenSeat(seat: number, s: Partial<TableFrameSeatMsg> & { name: string }): TableFrameSeatMsg {
  return { ...emptySeat(seat, "open"), state: "taken", you: false, ready: false, reconnecting: false,
           since: null, sit: null, pair: false, leader: false, ...s };
}

/** Whether a queue_state holds the entry here, so a table frame follows it. */
export function holdsEntry(m: unknown): m is QueueStateLike {
  const q = m as QueueStateLike | null;
  return !!q && q.type === "queue_state" && q.queued === true && q.elsewhere !== true;
}

/** The table frame the server sends after `qs`. Alone, `party` names your
 *  Duo partner: you sit at 0 (2 when your partner leads), your partner
 *  across, or the seat held for one; the other seats are open. */
export function tableFrameFor(qs: QueueStateLike, party: PartyMsg | null = null,
                              extra: Partial<TableFrameMsg> = {}): TableFrameMsg {
  const t = (qs.table ?? null) as WaitingTableMsg | null;
  const youReady = t ? t.you_ready : qs.you_ready === true;
  const settings = { allow_joiners: qs.allow_joiners !== false, start_level: (qs.start_level as string) ?? "2" };
  const base = { type: "table" as const, phase: "open" as const, code: (qs.code as string | undefined) ?? t?.code ?? "",
                 mode: (qs.mode as "ranked" | "casual" | undefined) ?? "ranked", settings, your_ready: youReady };
  if (t) {
    const held = t.held_seats ?? (t.held_seat != null ? [t.held_seat] : []);
    const seats = t.seats.map((s, at) => (s ? takenSeat(at, { ...s, sit: s.sit ?? null })
      : emptySeat(at, held.includes(at) ? "held" : "open")));
    // queue_state's own `opener` is what you may set; the frame names the seat
    const opener = qs.opener !== false ? t.you
      : t.opener !== undefined && t.opener !== t.you ? t.opener
      : seats.find((s) => s.state === "taken" && !s.you)?.seat ?? (t.you + 1) % 4;
    return { ...base, you: t.you, opener, seats,
             timers: { bots: t.timer, start_now_at: t.start_now_at ?? null },
             waiting_for: t.waiting_for, chat_log: t.id, ...extra };
  }
  const leads = qs.leader !== false;
  const partner = qs.party_id ? party?.members.find((m) => !m.you) ?? null : null;
  const you = partner && !leads ? 2 : 0;
  const duoReady = (qs.duo_ready as number | null | undefined) ?? null;
  const partnerReady = duoReady !== null && duoReady - (youReady ? 1 : 0) > 0;
  const seats = [0, 1, 2, 3].map((at) => emptySeat(at, "open"));
  seats[you] = takenSeat(you, { name: party?.members.find((m) => m.you)?.name ?? "You", you: true,
                                ready: youReady, pair: !!partner, leader: leads });
  const across = (you + 2) % 4;
  if (partner) {
    seats[across] = takenSeat(across, { name: partner.name, ready: partnerReady, pair: true, leader: !leads });
  } else if (qs.held_seat === across) {
    seats[across] = emptySeat(across, "held");
  }
  const botsAt = (qs.bots_at as number | null | undefined) ?? null;
  return { ...base, you, opener: qs.opener !== false ? you : across, seats,
           timers: { bots: botsAt === null ? null : { at: botsAt, name: seats[leads ? you : across].name ?? "", you: true },
                     start_now_at: null },
           waiting_for: partner && !partnerReady ? [partner.name] : [], chat_log: null, ...extra };
}

/** A test socket's deliveries as the server sends them: a queue_state that
 *  holds the entry, then its table frame. It remembers the socket's last
 *  pair frame, which names a lone Duo's partner; a pair frame that comes
 *  after its queue_state (as the server may send it) is followed by the
 *  table frame again, now with the partner's name. */
export function framer(): (msg: unknown) => unknown[] {
  let party: PartyMsg | null = null;
  let held: QueueStateLike | null = null;
  return (msg) => {
    const m = msg as { type?: string } | null;
    if (holdsEntry(msg)) {
      held = msg;
      return [msg, tableFrameFor(msg, party)];
    }
    if (m?.type === "queue_state" || m?.type === "queue_removed" || m?.type === "match_started") held = null;
    if (m?.type === "party_closed") party = null;
    if (m?.type === "party") {
      party = m as PartyMsg;
      if (held && !held.table && held.party_id === party.party_id) return [msg, tableFrameFor(held, party)];
    }
    return [msg];
  };
}
