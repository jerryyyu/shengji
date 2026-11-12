import { effectiveName, useAuth } from "../auth";
import Sheet from "./Sheet";
import { clock, queue, useNow, useQueue } from "./store";
import type { OfferView } from "./store";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "?";
  const second = parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] ?? "";
  return (first + second).toUpperCase();
}

function BotIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
         strokeLinecap="round" aria-hidden="true">
      <rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 4v4" />
    </svg>
  );
}

/** One seat of the offered table: you (gold), a seat you may take (dashed,
 *  tap to sit there), or a person already playing. `ours` colours it as
 *  your team. */
function OfferSeat({ o, seat, ours, busy, me }: {
  o: OfferView; seat: number; ours: boolean; busy: boolean; me: string;
}) {
  const s = o.seats[seat];
  const team = ours ? "ours" : "theirs";
  if (seat === o.pick) {
    return (
      <button type="button" className={`ot-seat you ${team}`} aria-pressed="true" disabled={busy}>
        <span className="ot-av">{me ? initials(me) : "You"}</span><span className="ot-name">You</span>
      </button>
    );
  }
  if (o.partner && seat === o.partner.seat) {
    // a pair's offer: your partner's seat is fixed and highlighted with yours
    return (
      <div className={`ot-seat you ${team}`} role="group" aria-label={`${o.partner.name}, your partner`}>
        <span className="ot-av">{initials(o.partner.name)}</span><span className="ot-name">{o.partner.name}</span>
      </div>
    );
  }
  if (s.open && o.partner) {
    return (
      <div className={`ot-seat ${team}`} role="group" aria-label="Bot">
        <span className="ot-av"><BotIcon /></span><span className="ot-name">Bot</span>
      </div>
    );
  }
  if (s.open) {
    const label = s.bot ? "Bot" : `${s.name} · away`;
    return (
      <button type="button" className={`ot-seat open ${team}`} aria-pressed="false" disabled={busy}
              aria-label={`Sit here: ${label}, ${ours ? "your team" : "other team"}`}
              onClick={() => queue.offerPick(seat)}>
        <span className="ot-av"><BotIcon /></span><span className="ot-name">{label}</span>
      </button>
    );
  }
  return (
    <div className={`ot-seat ${team}`} role="group" aria-label={s.name}>
      <span className="ot-av">{s.bot ? <BotIcon /> : initials(s.name)}</span>
      <span className="ot-name">{s.bot ? "Bot" : s.name}</span>
    </div>
  );
}

/** An open table offered to a newcomer in the queue: the game's two teams
 *  with you in the seat picked for you (the lone player's partner when that
 *  is free); tap another dashed seat to sit there instead. A pair gets two
 *  partner seats, both highlighted and fixed, and either member's Join takes
 *  both. Join takes the seat after the bot's trick; Wait keeps queuing, and
 *  the bar keeps the table one tap away while it can be joined. */
export default function OpenTableOffer() {
  const q = useQueue();
  const account = useAuth();
  const me = account.status === "in" && account.user ? effectiveName(account.user) : "";
  const o = q.offer;
  const shown = q.queued && q.table === null && o !== null;
  const now = useNow(shown, 250);
  if (!shown || !o) return null;
  const busy = q.pending !== null;
  const yours = [(o.pick + 2) % 4, o.pick];
  const theirs = [(o.pick + 1) % 4, (o.pick + 3) % 4];
  return (
    // Escape, the scrim and a drag down are Wait; none of them while a Join
    // waits for the server's answer
    <Sheet title="Table open" className="ot-sheet" cancel={null} dismissible={!busy}
           onClose={() => queue.offerWait()}>
        <p className="ot-sub">
          {o.roundEnd ? "Joins next round · ranked" : "Game in progress · first round is unranked"}
        </p>
        {o.partner ? <p className="ot-sub ot-pair">Two seats for you and {o.partner.name}</p> : null}
        <div className="ot-teams">
          <div className="ot-col">
            {yours.map((s) => <OfferSeat key={s} o={o} seat={s} ours busy={busy} me={me} />)}
          </div>
          <span className="ot-vs" aria-hidden="true">VS</span>
          <div className="ot-col">
            {theirs.map((s) => <OfferSeat key={s} o={o} seat={s} ours={false} busy={busy} me={me} />)}
          </div>
        </div>
        <button type="button" className="btn ot-join" disabled={busy} onClick={() => queue.offerJoin()}>
          {q.pending === "offer" ? "Joining…" : `Join · ${clock(o.expiresAt - now, true)}`}
        </button>
        <button type="button" className="ot-wait" disabled={busy} onClick={() => queue.offerWait()}>
          Wait
        </button>
    </Sheet>
  );
}
