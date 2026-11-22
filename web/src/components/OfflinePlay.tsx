// The Play tab with no game server: the same page, Casual the only mode, and
// a Play that opens your table with three bots on this device. Ranked, Duo
// and the code box need the server, so they stay in their places, disabled.
// The online Play tab draws these in place of its own controls, both while
// its connection is down and once the page plays offline.
import { useEffect, useRef, useState } from "react";
import type { ConnStatus } from "../ws";
import { clearSavedRoom, conn, getSavedName } from "../ws";
import { effectiveName, useAuth } from "../auth";
import { useOnline } from "../useOnline";
import { ModeSwitch, PlayRow, PresenceLine } from "../queue/Ranked";
import { OfflinePanel } from "../queue/TablePanel";
import type { RoomMsg } from "../protocol";
import type { BotLevel } from "../queue/messages";
import { useNearbyHostView, useNearbyJoinView, useNearbyUi } from "../nearbyGate";
import { useToast } from "../toast";
import { NEARBY_SESSION } from "../offlineMode";
import { offlineGame, useOfflineBotLevel, useOfflineTable } from "./offlineGame";
import { CodeRow } from "./Lobby";
import "./OfflinePlay.css";

interface OfflineControlsProps {
  /** This page plays on the device (offline mode). Without it the page still
   *  belongs to the game server, which cannot be reached, and Play swaps the
   *  socket to the on-device server with the table open. */
  local: boolean;
  status: ConnStatus;
  /** The room Start made, until its deal starts; a nearby table's lobby. */
  room?: RoomMsg | null;
  /** The code box, which takes a nearby table's code where nearby play is offered. */
  code?: string;
  onCode?: (code: string) => void;
  onJoinCode?: () => void;
}

/** The Play tab's controls with no connection, between the name chip and How
 *  to play: the mode switch, then Play, Duo, the presence line and the code
 *  box, or the offline table in their place. The online Play tab shows these
 *  in place of its own, so what surrounds them stays mounted. */
export function OfflineControls({ local, status, room: roomMsg = null, code = "", onCode, onJoinCode }: OfflineControlsProps) {
  const room = roomMsg?.room ?? null;
  const nbUi = useNearbyUi();
  const nb = local ? nbUi : null;
  const host = useNearbyHostView();
  const joinView = useNearbyJoinView();
  const showTable = useOfflineTable(local);
  const bots = useOfflineBotLevel();
  // an error frees Start; the toast says it
  const error = useToast()?.text ?? null;
  const online = useOnline();
  const account = useAuth();
  const signedIn = account.status === "in" && account.user ? account.user : null;
  const [sent, setSent] = useState(false);
  useEffect(() => { if (error) setSent(false); }, [error]);

  // Back here after a game from this table: the table has been left.
  const left = useRef(false);
  useEffect(() => {
    if (!local || !offlineGame.played) return;
    offlineGame.played = false;
    left.current = true;
    offlineGame.setTable(false);
  }, [local]);

  // An offline game stays offline: nothing moves the page online while its
  // table is up or its game is on (this screen is not shown then). Once the
  // table is left, the page goes online again as soon as the device has a
  // network, in place. The app's bundled page loads the live site for it, so
  // at a launch whose live site did not load it waits for the network to
  // return or the table to be left; the shell would only bring it back.
  const inApp = typeof location !== "undefined" && location.protocol === "capacitor:";
  const wasOnline = useRef(online);
  useEffect(() => {
    const cameBack = online && !wasOnline.current;
    wasOnline.current = online;
    // a nearby table is played over the local network: nothing moves it online
    if (!local || showTable || !online || NEARBY_SESSION) return;
    if (cameBack || left.current || !inApp) offlineGame.goOnline();
  }, [local, showTable, online, inApp]);

  const myName = () => (signedIn ? effectiveName(signedIn) : getSavedName()).trim() || "Player";
  const leave = () => {
    if (host.phase !== "off") {
      // the host's Leave ends the nearby table for everyone
      nbUi?.nearbyHost.turnOff();
      left.current = true;
      offlineGame.setTable(false);
      return;
    }
    if (room) conn.send({ type: "table_leave" });
    // a Start whose room has not come back yet: the leave waits for that
    // room on the socket
    else if (sent) conn.leaveToLobby();
    setSent(false);
    offlineGame.played = false;
    left.current = true;
    offlineGame.setTable(false);
  };
  const start = () => {
    if (status !== "open" || sent) return;
    setSent(true);
    offlineGame.played = true;
    clearSavedRoom();
    conn.send({ type: "create_room", name: myName(), start: true, bot_level: bots });
  };
  const toggleNearby = () => {
    if (host.phase === "off") nbUi?.nearbyHost.turnOn(myName(), bots);
    else nbUi?.nearbyHost.turnOff();
  };
  // the host's Bots for the nearby table, kept as the offline table's too
  const pickNearbyBots = (level: BotLevel) => {
    offlineGame.setBotLevel(level);
    conn.send({ type: "table_bot_level", level });
  };
  const ready = (on: boolean) => {
    conn.send(on ? { type: "table_start" } : { type: "table_start", on: false });
  };

  // a nearby table's lobby, for its host and for a joiner
  if (roomMsg?.nearby && nbUi && host.phase !== "starting") {
    return (
      <>
        <ModeSwitch value="casual" disabled={false} rankedOff />
        <nbUi.NearbyRoomPanel room={roomMsg} onReady={ready} onToggle={toggleNearby} onBots={pickNearbyBots}
                              onLeave={host.phase !== "off" ? leave : () => nbUi.nearbyJoin.leave()} />
      </>
    );
  }

  return (
    <>
      <ModeSwitch value="casual" disabled={false} rankedOff />

      {showTable ? (
        <OfflinePanel ready={status === "open" && host.phase === "off"} starting={sent || room !== null}
                      bots={bots} onBots={(b) => offlineGame.setBotLevel(b)}
                      onStart={start} onLeave={leave}
                      nearby={nb ? nb.nearbySwitch({ on: host.phase !== "off", line: host.line }) : null}
                      onToggle={toggleNearby} onSettings={() => nb?.openNearbySettings()} />
      ) : (
        <>
          <PlayRow label="Play" disabled={false} duoDisabled onPlay={() => offlineGame.startFromPlay()} />
          <PresenceLine q={null} online={false} offline />
          <CodeRow disabled code={code} onCode={onCode} onJoin={onJoinCode} nearby={nb}
                   nearbyJoinView={joinView} />
        </>
      )}
    </>
  );
}
