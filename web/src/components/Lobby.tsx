import type { RoomMsg } from "../protocol";
import { openHowto } from "../howto/route";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { effectiveName, useAuth } from "../auth";
import { randomName } from "../randomName";
import AccountChip from "./AccountChip";
import GuestChip from "./GuestChip";
import LobbyPreview from "./LobbyPreview";
import { RankedSection, TrophyIcon } from "../queue/Ranked";
import { JoinCodePanel } from "../queue/TablePanel";
import { useQueue } from "../queue/store";
import { guestName, useGuestName } from "../guestName";
import { OfflineControls } from "./OfflinePlay";
import { useOffline } from "../offlineMode";
import { codes, panelShown, useCodes } from "../codeJoin";
import type { NearbyJoin } from "../nearbyJoin";
import { useNearbyJoinView, useNearbyUi, type NearbyUi } from "../nearbyGate";
import { normalizeCode } from "../codes";
import { WIDE } from "../home/route";
import { useMediaQuery } from "../phoneLayout";
import { offlineGame, offlineOffered, useOfflineTable } from "./offlineGame";
import { isNative } from "../native";
import { telemetry } from "../telemetry";
import { APP_STORE_BADGE, APP_STORE_URL } from "../appStore";
import { isZh, useT } from "../i18n";

/** Apple's zh-cn badge, beside the English one under public/badges/. */
const APP_STORE_BADGE_ZH = "/badges/app-store-zh.svg";

interface LobbyProps {
  status: ConnStatus;
  /** The room this socket sits in before its game's first state. */
  room?: RoomMsg | null;
}

/** After this long without a connection the Play tab shows its offline state. */
export const STALL_MS = 4000;

/** Whether `status` has stayed short of "open" for STALL_MS. */
function useStalled(status: ConnStatus): boolean {
  const [stalled, setStalled] = useState(false);
  const open = status === "open";
  useEffect(() => {
    setStalled(false);
    if (open) return;
    const t = window.setTimeout(() => setStalled(true), STALL_MS);
    return () => window.clearTimeout(t);
  }, [open]);
  return stalled && !open;
}

/** The Ranked block while the server cannot say whether sign-in exists:
 *  Play and Duo in their places, unavailable. */
function RankedUnavailable() {
  const t = useT();
  const labelId = useId();
  return (
    <section className="play-section" aria-labelledby={labelId} data-testid="ranked-unavailable">
      <h2 className="play-label ranked" id={labelId}><TrophyIcon />{t("home.ranked")}</h2>
      <div className="play-ranked-row">
        <button type="button" className="btn gold play-main q-find" disabled>{t("home.play")}</button>
        <button type="button" className="btn play-duo" disabled>{t("home.duo")}</button>
      </div>
    </section>
  );
}

/** Play's code box: a table's four-letter code, and Join, which opens its
 *  panel. `looking`: the code's seats are on their way. Disabled, it holds
 *  its place with no connection to look a code up on. `nearby`, the nearby
 *  UI where the app binary offers nearby play: it also takes a nearby
 *  table's five characters (and only those when `disabled`, with no
 *  connection), followed by the one nearby line. */
export function CodeRow({ disabled, code = "", looking = false, onCode, onJoin, nearby = null, nearbyJoinView = null }: {
  disabled: boolean; code?: string; looking?: boolean; onCode?: (code: string) => void; onJoin?: () => void;
  nearby?: NearbyUi | null; nearbyJoinView?: NearbyJoin | null;
}) {
  const t = useT();
  const trimmed = code.trim();
  const joinable = nearby?.isNearbyCode(trimmed) ? true : !disabled && trimmed.length === 4;
  return (
    <>
    <div className={`join-row${nearby ? " nearby" : ""}`}>
      <input
        className="room-input"
        value={code}
        maxLength={nearby ? nearby.NEARBY_CODE_LEN : 4}
        placeholder={t("home.codePlaceholder")}
        aria-label={t("home.codeAria")}
        disabled={disabled && !nearby}
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="go"
        onChange={(e) => onCode?.(e.target.value.toUpperCase())}
        onKeyDown={(e) => {
          if (e.key === "Enter") onJoin?.();
        }}
      />
      <button
        className="btn"
        disabled={looking || !joinable}
        onClick={onJoin}
        aria-busy={looking || undefined}
      >
        {looking ? t("home.joining") : t("home.join")}
      </button>
    </div>
    {nearby ? <nearby.NearbyCodeLine code={trimmed.toUpperCase()} join={nearbyJoinView} /> : null}
    </>
  );
}

export default function Lobby({ status, room = null }: LobbyProps) {
  const t = useT();
  const stalled = useStalled(status);
  // Offline, the socket talks to the on-device server: Play's controls are
  // the offline ones, and links, peeks and the Join panel wait for the game server.
  const offline = useOffline();
  const offlineTable = useOfflineTable(offline);
  const { name } = useGuestName();
  const account = useAuth();
  const signedIn = account.status === "in" && account.user ? account.user : null;
  const accountName = effectiveName(signedIn);
  // A signed-in player plays under their account name, the one the account
  // pill shows and its Edit name changes. It is sent explicitly because the
  // socket's own default is read once at its handshake and would miss a
  // rename made since.
  // A guest's chip sits in the same place and opens their name editor: the
  // name starts as the one they used last time, saved on Play, Join
  // or the editor's Done, or else a random one.
  const playerName = signedIn ? accountName : name.trim();
  // The random fill happens once, as soon as the page knows the visitor is
  // not signed in; a field the guest has typed into, or cleared afterwards,
  // is left alone. The store is the one name the chip shows and Join sends:
  // storage written since it loaded (another tab) does not stand in for it.
  const autoFilled = useRef(false);
  useEffect(() => {
    if (autoFilled.current || (account.status !== "out" && account.status !== "off" && account.status !== "error")) return;
    autoFilled.current = true;
    if (!guestName.name.trim()) guestName.fill(randomName());
  }, [account.status]);
  // Only a guest's own name is remembered; an account name lives on the account.
  const rememberName = useCallback((trimmed: string) => {
    if (!signedIn && trimmed) guestName.keep(trimmed);
  }, [signedIn]);
  // A ?code= link prefills the box (an older ?room= link reads as one).
  const [roomCode, setRoomCode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return normalizeCode(params.get("code") ?? params.get("room") ?? "");
  });
  // The one code path (codeJoin.ts): a code from this box or a ?code= link
  // opens the Join panel in Play's place, with you glowing in the seat Join
  // takes. Join is the player's tap; a full table shows the same panel with
  // Join disabled. This screen tells the store where it stands.
  const codeView = useCodes();
  const { queued, frame, pending: queuePending } = useQueue();
  const seated = room !== null || queued;
  const seatedAt = seated ? (room?.room ?? frame?.code ?? "") : null;
  const ready = status === "open";
  useEffect(() => {
    codes.setPlace({ ready: status === "open" && !offline, seatedAt });
  }, [status, offline, seatedAt, codeView?.step]);
  // A code typed in the box waits for its seats before the panel opens.
  const looking = codeView?.step === "peek" && !panelShown(codeView);
  // An empty name never blocks a start: the panel's Join fills the field
  // with a random name and goes, the same as the dice.
  const nameOrRandom = () => {
    if (playerName) return playerName;
    const picked = randomName();
    guestName.fill(picked);
    return picked;
  };

  // The box takes a room or table code: its peek opens the panel. Five
  // characters name a nearby table, looked for on the local network.
  const nb = useNearbyUi();
  const nearbyView = useNearbyJoinView();
  const join = () => {
    if (nb?.isNearbyCode(roomCode)) {
      const as = nameOrRandom();
      rememberName(as);
      nb.nearbyJoin.open(roomCode.trim().toUpperCase(), as);
      return;
    }
    if (!ready || looking || normalizeCode(roomCode).length !== 4) return;
    codes.open(roomCode);
  };
  const typeCode = (c: string) => {
    // a changed code drops the last nearby answer about the old one
    if (nearbyView && nearbyView.step === "denied") nb?.nearbyJoin.cancel();
    setRoomCode(c);
  };
  const nearbyPanel = nearbyView !== null && nearbyView.step !== "denied" ? nearbyView : null;

  // Not now: the panel goes and the link with it; Play is back.
  const closeJoin = () => {
    codes.cancel();
    setRoomCode("");
  };

  // The panel's Join, under the name the chip shows (a guest's random one
  // until they edit it).
  const joinFromPanel = () => {
    const as = nameOrRandom();
    rememberName(as);
    codes.join(as);
  };

  // only the app plays on the device: a browser's Play tab with no
  // connection keeps its own controls, disabled, until the server is back
  const offlineUp = stalled && offlineOffered();
  const wide = useMediaQuery(WIDE);
  const screenRef = useRef<HTMLDivElement | null>(null);
  // a panel that opens puts the page back at its top, where the panel is
  const joinUp = panelShown(codeView) && !seated && !offline;
  const panelUp = nearbyPanel !== null || (offline ? offlineTable || !!room?.nearby : (queued || joinUp) && !offlineUp);
  useEffect(() => {
    if (panelUp && screenRef.current) screenRef.current.scrollTop = 0;
  }, [panelUp]);

  // A phone's panel sits right under the chip and the mode switch, with the
  // art gone, so its buttons are on screen; wide screens keep the art beside it.
  const showArt = wide || !panelUp;
  const ranked = account.status === "error" && !room
    ? <RankedUnavailable /> : <RankedSection online={status === "open"} room={room} />;

  return (
    <div ref={screenRef} className={`screen lobby-screen play-tab${offlineUp || offline ? " play-offline" : ""}${panelUp ? " play-table-up" : ""}`}>
      <div className="panel lobby-panel">
        {/* one column at every width: the art, then the controls or the
            table panel */}
        <div className="play-art">
          <h1 className="game-title">
            {isZh() ? "升级" : <>升级 <span className="game-title-en">Sheng Ji</span></>}
          </h1>
          {showArt ? <LobbyPreview /> : null}
        </div>
        <div className="play-side">
        {signedIn ? <AccountChip user={signedIn} /> : <GuestChip />}

        {/* With no connection the app's Play plays on this device, and what
            needs the server waits; the chip, How to play and an open sheet
            stay put. */}
        {nearbyPanel && nb ? (
          <nb.NearbyJoinPanel join={nearbyPanel} onJoin={() => nb.nearbyJoin.join()}
                              onCancel={() => nb.nearbyJoin.cancel()} onPick={(at) => nb.nearbyJoin.pick(at)}
                              onAgain={() => nb.nearbyJoin.again()} />
        ) : offline ? (
          <OfflineControls local status={status} room={room}
                           code={roomCode} onCode={typeCode} onJoinCode={join} />
        ) : offlineUp && !room ? <OfflineControls local={false} status={status} /> : (
          <>
            {joinUp ? (
              <JoinCodePanel join={codeView}
                             busy={codeView.step === "joining" || (codeView.step === "peek" && codeView.peek !== null)
                                   || queuePending === "join"}
                             onJoin={joinFromPanel} onCancel={closeJoin} onPick={(at) => codes.pick(at)} />
            ) : ranked}

            {/* at a table the panel is the page: no code box until you leave it */}
            {seated || joinUp ? null : (
              <CodeRow disabled={!ready} code={roomCode} looking={looking} onCode={typeCode} onJoin={join}
                       nearby={nb} nearbyJoinView={nearbyView} />
            )}
          </>
        )}

        <p className="howto-entry">
          <button className="howto-link" onClick={() => openHowto()}>{t("home.howto")}</button>
          {/* the bots on this device, on purpose: a game started here stays
              offline when the network comes back */}
          {stalled || offline || seated || joinUp || !offlineOffered() ? null : (
            <>
              <span className="howto-sep" aria-hidden="true">·</span>
              <button className="howto-link" onClick={() => offlineGame.startFromPlay()}>{t("home.playOffline")}</button>
            </>
          )}
        </p>
        {/* the website's way to the iOS app: Apple's badge as Apple draws it,
            under the controls and gone while a table panel is the page */}
        {isNative() || panelUp ? null : <AppStoreBadge />}
        </div>
      </div>
    </div>
  );
}

function AppStoreBadge() {
  const t = useT();
  const tapped = () => {
    telemetry.tap("app_store_badge");
    telemetry.flush();
  };
  return (
    <a className="app-store-badge" href={APP_STORE_URL} onClick={tapped}>
      <img src={isZh() ? APP_STORE_BADGE_ZH : APP_STORE_BADGE} alt={t("home.appStoreAlt")} width={120} height={40} />
    </a>
  );
}
