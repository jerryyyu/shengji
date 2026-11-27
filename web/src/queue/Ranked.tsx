import { useState } from "react";
import { deviceAccountPending, useAuth } from "../auth";
import { guestName } from "../guestName";
import LeaveSheet from "../components/LeaveSheet";
import type { RoomMsg } from "../protocol";
import type { QueueMode } from "./messages";
import TablePanel, { TableAnnouncer } from "./TablePanel";
import { useKindGuard } from "./useKindGuard";
import { panelKind, presenceParts, shortName } from "./tableText";
import "./playLines.css";
import { clock, queue, useNow, useQueue } from "./store";
import { tx, useT } from "../i18n";
import { telemetry } from "../telemetry";
import { rounds } from "../roundTelemetry";
import { watch } from "../watch/store";
import type { MessageKey } from "../i18n";

/** The ranked mark: a trophy. */
export function TrophyIcon() {
  return (
    <svg className="trophy" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
      <path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 20h6" />
    </svg>
  );
}

/** The line under a guest's Play: they queue like everyone, unrated, and
 *  Sign in opens the identity sheet. Without sign-in on this server the line
 *  says only that they play as a guest. */
function GuestLine({ online }: { online: boolean }) {
  const account = useAuth();
  const t = useT();
  const clientId = account.status === "out" ? account.clientId : null;
  return (
    <p className="play-guest-line">
      {clientId ? tx("home.guestLineSignIn", {
        signIn: (
          <button type="button" className="play-guest-signin" disabled={!online}
                  onClick={() => guestName.open("play_line")}>{t("home.signIn")}</button>
        ),
      }) : t("home.guestLine")}
    </p>
  );
}

/** The counts under Play and Duo: who is about, never a button. When both
 *  modes have tables, the selected mode's count is lit. Until the socket
 *  opens it is Play's connection status: "Connecting…", then, with `offline`
 *  (the offline controls), a grey "Offline". */
export function PresenceLine({ q, online, offline = false }: {
  q: ReturnType<typeof useQueue> | null; online: boolean; offline?: boolean;
}) {
  const t = useT();
  if (offline || !online || !q) {
    return (
      <p className={`play-presence ${offline ? "offline" : "connecting"}`} role="status">
        <span className="play-presence-dot" aria-hidden="true" />
        <span>{offline ? t("home.offline") : t("home.connecting")}</span>
      </p>
    );
  }
  return (
    <p className="play-presence">
      <span className="play-presence-dot" aria-hidden="true" />
      <span>
        {presenceParts(q.presence, q.playMode).map((part, i) => (
          part.watch ? (
            // the way in to watching: one tap lands at a table the server picks
            <span key={i}>
              {/^\s*·\s*/.exec(part.text)?.[0] ?? ""}
              <button type="button" className="play-presence-watch"
                      onClick={() => watch.open(q.playMode)}>
                {part.text.replace(/^\s*·\s*/, "")}<span className="play-presence-chev" aria-hidden="true">›</span>
              </button>
            </span>
          ) : part.hl ? <b key={i} className="play-presence-hl">{part.text}</b> : <span key={i}>{part.text}</span>
        ))}
      </span>
    </p>
  );
}

const MODES: { mode: QueueMode; name: MessageKey }[] = [{ mode: "ranked", name: "home.ranked" }, { mode: "casual", name: "home.casual" }];

/** Ranked / Casual above Play, remembered on this device. At a table it
 *  shows that table's mode and holds still. With `rankedOff` (no game
 *  server) only Ranked is disabled, and a tap changes nothing remembered. */
export function ModeSwitch({ value, disabled, rankedOff = false }: {
  value: QueueMode; disabled: boolean; rankedOff?: boolean;
}) {
  const t = useT();
  return (
    <div className="play-mode" role="group" aria-label={t("home.modeAria")}>
      {MODES.map(({ mode, name }) => (
        <button key={mode} type="button" className={`play-mode-opt${value === mode ? " on" : ""}`}
                aria-pressed={value === mode} disabled={disabled || (rankedOff && mode === "ranked")}
                onClick={rankedOff ? undefined : () => queue.setPlayMode(mode)}>
          {t(name)}
        </button>
      ))}
    </div>
  );
}

/** The gold Play, wide, and Duo beside it. `busy`: a Play on its way. */
export function PlayRow({ label, disabled, busy = false, onPlay, onDuo, duoDisabled }: {
  label: string; disabled: boolean; busy?: boolean; onPlay: () => void; onDuo?: () => void; duoDisabled: boolean;
}) {
  const t = useT();
  return (
    <div className="play-ranked-row">
      <button type="button" className={`btn gold play-main q-find${busy ? " searching" : ""}`}
              disabled={disabled} aria-busy={busy || undefined} onClick={onPlay}>
        {label}
      </button>
      <button type="button" className="btn play-duo" disabled={duoDisabled} onClick={onDuo}>
        {t("home.duo")}
      </button>
    </div>
  );
}

/** The server's two account_in_game sentences, which share one code: each
 *  is read in the player's language; any other text shows as sent. */
const IN_GAME_LINES: Record<string, MessageKey> = {
  "Sign in again to return to your game.": "home.inGameSignIn",
  "You are already in a game on another device.": "home.inGameElsewhere",
};

/** Play refused because this account already plays a ranked game: the
 *  server's words in Play's place, with the way back when there is one. */
function InGameBlock({ message, canReturn, online }: { message: string; canReturn: boolean; online: boolean }) {
  const t = useT();
  const known = IN_GAME_LINES[message];
  return (
    <div className="play-in-game">
      <p className="play-in-game-line" role="status">{known ? t(known) : message}</p>
      <div className="play-ranked-row">
        {canReturn ? (
          <button type="button" className="btn gold play-main" disabled={!online} onClick={() => queue.returnToGame()}>
            {t("home.imBack")}
          </button>
        ) : null}
        <button type="button" className={canReturn ? "btn play-duo" : "btn play-main"}
                onClick={() => queue.dismissInGame()}>
          {t("home.ok")}
        </button>
      </div>
    </div>
  );
}

/** Your Duo on the Play tab between games, or the Duo table you left that
 *  the server still keeps: one plain line naming the partner (when paired),
 *  then the gold button, Rejoin Duo while a Duo seat is kept for you, else
 *  the pair's Play for its leader (the other member has none), and Leave
 *  Duo beside it. Leave Duo goes through the one Leave sheet: a pair's
 *  party_leave ends the pairing; a kept table's table_leave gives it up. */
function DuoBlock({ partner, online, rejoin, play, cooling, busy }: {
  partner: string | null;
  online: boolean;
  /** The kept Duo seat's way back, or null. */
  rejoin: (() => void) | null;
  /** The leader's Play for the pair (its label and whether it may be tapped), or null. */
  play: { label: string; disabled: boolean; onPlay: () => void } | null;
  cooling: boolean;
  busy: boolean;
}) {
  const t = useT();
  const [asking, setAsking] = useState(false);
  const primary = rejoin ? (
    <button type="button" className="btn gold play-main q-find" disabled={!online || busy} onClick={rejoin}>
      {t("home.rejoinDuo")}
    </button>
  ) : play ? (
    <button type="button" className={`btn gold play-main q-find${busy ? " searching" : ""}`}
            disabled={play.disabled} aria-busy={busy || undefined} onClick={play.onPlay}>
      {play.label}
    </button>
  ) : null;
  return (
    <>
      {partner ? <p className="play-pair-label">{t("home.duoWith", { name: shortName(partner) })}</p> : null}
      {cooling ? <p className="play-cool-line">{t("home.coolLine")}</p> : null}
      <div className="play-ranked-row">
        {primary}
        <button type="button" className={primary ? "btn play-duo play-pair-leave" : "btn play-main play-pair-leave"}
                disabled={!online} onClick={() => setAsking(true)}>{t("home.leaveDuo")}</button>
      </div>
      {asking ? (
        <LeaveSheet context={partner ? { kind: "duo", partner, opener: false } : { kind: "queue", others: [] }}
                    onStay={() => setAsking(false)}
                    onLeave={() => {
                      if (partner ? queue.leaveParty() : queue.giveUpBack()) setAsking(false);
                    }} />
      ) : null}
    </>
  );
}

/** Play's block, the same for guests and accounts: the Ranked / Casual
 *  switch, a wide gold Play that joins the queue in that mode (as the pair
 *  when one is formed and you lead it) and Duo, which opens your own table
 *  with the partner seat held; its code is the Duo's invite.
 *  At the queue's table its panel takes the buttons' place on every screen;
 *  in a room whose game is starting, the buttons hold still. A guest sees a
 *  line under the buttons that offers sign-in. While sign-in is still
 *  loading nothing shows. With no connection for a while the Play tab shows
 *  its offline controls in this block's place. */
export function RankedSection({ online, room = null }: {
  /** The socket is open; without it every queue control is disabled. */
  online: boolean;
  /** The room this socket sits in before its game's first state, if any. */
  room?: RoomMsg | null;
}) {
  const t = useT();
  const q = useQueue();
  const account = useAuth();
  const kind = panelKind(q);
  // "I’m back" and Start share the primary place: the guard covers each swap
  const guarded = useKindGuard(kind === "shared" && q.stillHereUntil !== null ? "still_here" : kind);
  const now = useNow(q.cooldownUntil !== null || q.back?.until != null, 500);

  const pair = q.party && q.party.members.length === 2 ? q.party : null;
  // a Duo seat you left that the server still keeps: Play takes you back to it
  const back = queue.backTo(now);
  const joining = q.pending === "join";
  const cooling = q.cooldownUntil !== null && q.cooldownUntil > now;
  let label = t("home.play");
  let disabled = !online || guarded || room !== null;
  if (joining) disabled = true;
  else if (cooling) {
    // a table you joined and left: Play counts the queue cooldown down
    label = t("home.playIn", { time: clock(q.cooldownUntil! - now, true) });
    disabled = true;
  } else if (pair && !pair.you_lead) disabled = true;
  // the switch shows the mode of the table you sit at, else your choice
  const tableMode: QueueMode | null = room ? (room.matched ? "ranked" : "casual")
    : kind !== "play" ? q.queueMode ?? q.playMode : null;
  const modes = <ModeSwitch value={tableMode ?? q.playMode} disabled={tableMode !== null || joining || !!q.inGame} />;
  // first in every branch, so the live region stays mounted as the panel changes kind
  const announcer = <TableAnnouncer q={q} />;
  // while sign-in loads only the connection status shows, once the socket is down
  if (account.status === "loading") return online ? null : <PresenceLine q={q} online={false} />;
  if (account.status === "error") return null;
  const guest = account.status !== "in";
  if (kind !== "play") {
    return (
      <>
        {announcer}
        <div className="play-section play-table">
          {modes}
          <TablePanel q={q} guarded={guarded} />
        </div>
      </>
    );
  }
  // a Duo (paired, or its kept table) has Rejoin Duo or the pair's Play,
  // and Leave Duo, in place of Play and Duo
  const partner = pair ? pair.members.find((m) => !m.you)?.name ?? null : null;
  const onPlay = () => { telemetry.tap("play"); rounds.noteEntry("queue"); queue.join(); };
  const body = q.inGame ? (
    <InGameBlock message={q.inGame.message} canReturn={q.inGame.canReturn} online={online} />
  ) : partner !== null || back ? (
    <>
      <DuoBlock partner={partner} online={online} busy={joining} cooling={!back && cooling && !q.cooldownTold}
                rejoin={back ? () => { telemetry.tap("rejoin_duo"); rounds.noteEntry("friend"); queue.rejoinDuo(); } : null}
                play={pair?.you_lead ? { label, disabled, onPlay } : null} />
      {cooling && !back ? null : <PresenceLine q={q} online={online} />}
    </>
  ) : (
    <>
      {cooling && !q.cooldownTold ? <p className="play-cool-line">{t("home.coolLine")}</p> : null}
      <PlayRow label={label} disabled={disabled} busy={joining} duoDisabled={disabled} onPlay={onPlay}
               onDuo={() => { telemetry.tap("duo"); rounds.noteEntry("friend"); queue.joinDuo(); }} />
      {cooling ? null : <PresenceLine q={q} online={online} />}
    </>
  );
  return (
    <>
      {announcer}
      <section className={`play-section${guest ? " play-guest" : ""}`} aria-label={t("home.playSectionAria")}>
        {modes}
        {body}
        {guest && !deviceAccountPending(account) ? <GuestLine online={online} /> : null}
      </section>
    </>
  );
}
