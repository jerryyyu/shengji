// The nearby UI, one module that nearbyGate.ts imports only once the app
// binary offers nearby play. Components outside it reach nearby play only
// through what this exports, so the main bundle holds none of its code or
// copy, and nothing here runs on the web or in an App Store binary.
import { useEffect, useState, useSyncExternalStore } from "react";
import type { GameState } from "./protocol";
import { conn, type ConnStatus } from "./ws";
import { nearbyGate } from "./nearbyGate";
import { nearbyJoin } from "./nearbyJoin";
import type { NearbyJoin } from "./nearbyJoin";
import { nearbyAllowedBefore, openNearbySettings } from "./nearbySession";
import { NEARBY_LINK_LABEL, nearbyLinkState } from "./nearbyLink";
import { isNearbyCode } from "./offline/server/nearby/codes";
import { NEARBY_COPY } from "./offline/server/nearby/copy";
import {
  clearNearbyLogFile, copyNearbyLog, nearbySoakSwitchTap, uploadNearbyLogNow, useNearbyDebug, useNearbyKeepalive,
  useNearbyLogFile, useNearbySoak, useNearbySoakSwitch,
} from "./nearbyDebug";
import { tapHandlers } from "./tap";
import { NearbyJoinPanel as JoinPanel, NearbyRoomPanel as RoomPanel } from "./queue/TablePanel";
import { fromNearbyJoin, nearbyRoomModel } from "./queue/nearbyModel";
import type { ComponentProps } from "react";

export { default as NearbyDebugPane, startNearbyLogFile } from "./nearbyDebug";
export { nearbyJoin } from "./nearbyJoin";
export { nearbyHost, openNearbySettings } from "./nearbySession";
export { isNearbyCode, NEARBY_CODE_LEN } from "./offline/server/nearby/codes";
export { NEARBY_COPY } from "./offline/server/nearby/copy";
export { nearbySwitch } from "./queue/nearbyModel";

/** A nearby table's lobby, in the one table panel. */
export function NearbyRoomPanel(props: Omit<ComponentProps<typeof RoomPanel>, "model">) {
  return <RoomPanel {...props} model={nearbyRoomModel} />;
}

/** A nearby code's Join panel, in the one table panel. */
export function NearbyJoinPanel(props: Omit<ComponentProps<typeof JoinPanel>, "model">) {
  return <JoinPanel {...props} model={fromNearbyJoin} />;
}

/** The one line under the code box, for a nearby code only: what Join will
 *  ask (until iOS has been asked once), or why the last Join could not look
 *  (with the link to Settings). The copy rule lists it as its one exception
 *  (FLOWS.md "Play nearby"). */
export function NearbyCodeLine({ code, join }: { code: string; join: NearbyJoin | null }) {
  if (join?.step === "denied" && join.code === code) {
    return (
      <p className="join-line">
        {NEARBY_COPY.denied}{" "}
        <button type="button" className="howto-link join-line-link" onClick={() => openNearbySettings()}>
          {NEARBY_COPY.openSettings}
        </button>
      </p>
    );
  }
  if (isNearbyCode(code) && !nearbyAllowedBefore()) return <p className="join-line">{NEARBY_COPY.explain}</p>;
  return null;
}

/** A nearby table's link: a dot, green while linked, amber and pulsing
 *  while a link is being made again, grey once the table is lost. No text;
 *  its name is the connection pill's words. */
export function NearbyLinkDot({ state }: { state: GameState }) {
  const [status, setStatus] = useState<ConnStatus>(conn.status);
  useEffect(() => conn.subscribeStatus(setStatus), []);
  const hostLeft = useSyncExternalStore(nearbyJoin.subscribe, () => nearbyJoin.hostLeft, () => nearbyJoin.hostLeft);
  const link = nearbyLinkState({ host: !nearbyJoin.seated, status, hostLeft, players: state.players });
  return <span className={`nearby-link-dot ${link}`} role="img" aria-label={NEARBY_LINK_LABEL[link]} />;
}

/** A tap on the ⋯ menu's table code: the hidden switch's counter, where the
 *  plugin reports `chaos` (nearbyDebug.tsx); a no-op anywhere else. */
export function nearbyMenuTitleTap(): void {
  nearbySoakSwitchTap(nearbyGate().chaos);
}

/** The ⋯ menu's soak rows at a nearby table. With the log file
 *  (`logFile`: the device test and the Beta): Copy log, Clear log file and
 *  Upload log now. In a Debug build for the device test (`debug`): the
 *  peer-to-peer keepalive, and the soak's Autoplay, Chaos and summary; in
 *  the Beta (`chaos`) those three only while the hidden switch is on. A
 *  reviewed App Store binary reports none and draws none of them. */
export function NearbyMenuRows({ close }: { close: () => void }) {
  const gate = nearbyGate();
  const debug = useNearbyDebug(gate.debug);
  const logFile = useNearbyLogFile(gate.logFile);
  const hidden = useNearbySoakSwitch();
  const keepalive = useNearbyKeepalive(debug);
  const soak = useNearbySoak(gate.logFile && (debug || (gate.chaos && hidden)));
  return (
    <>
      {debug || logFile ? (
        <button className="hud-menu-row" role="menuitem" {...tapHandlers(() => { void copyNearbyLog(); close(); })}>
          <span>Copy log</span>
        </button>
      ) : null}
      {logFile ? (
        <button className="hud-menu-row" role="menuitem" {...tapHandlers(() => { void clearNearbyLogFile(); close(); })}>
          <span>Clear log file</span>
        </button>
      ) : null}
      {logFile ? (
        <button className="hud-menu-row" role="menuitem" {...tapHandlers(() => { void uploadNearbyLogNow(); close(); })}>
          <span>Upload log now</span>
        </button>
      ) : null}
      {debug && keepalive ? (
        <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={keepalive.on}
                {...tapHandlers(keepalive.toggle)}>
          <span>AWDL keepalive</span><span className={`ios-switch${keepalive.on ? " on" : ""}`} aria-hidden="true" />
        </button>
      ) : null}
      {soak ? (
        <>
          <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={soak.autoplay}
                  {...tapHandlers(soak.toggleAutoplay)}>
            <span>Autoplay</span><span className={`ios-switch${soak.autoplay ? " on" : ""}`} aria-hidden="true" />
          </button>
          <button className="hud-menu-row joiners-row" role="menuitemcheckbox" aria-checked={soak.chaos}
                  {...tapHandlers(soak.toggleChaos)}>
            <span>Chaos</span><span className={`ios-switch${soak.chaos ? " on" : ""}`} aria-hidden="true" />
          </button>
          <button className="hud-menu-row" role="menuitem" {...tapHandlers(() => { void soak.copy(); close(); })}>
            <span>Copy soak summary</span>
          </button>
        </>
      ) : null}
    </>
  );
}
