// Offline play: the in-page game server and the socket ws.ts opens to it.
// Loaded on demand (ws.ts imports it only in offline mode), so the online
// bundle carries none of the engine or the bots.
import { legalPlays } from "../engine/round";
import { viewFor } from "../bot";
import { LocalSocket, localServer } from "./socket";

export { LocalSocket, localServer };

/** Read-only probes for the browser end-to-end test: the human seat's legal
 *  plays and a bury, as card ids of the current state. Offline games only. */
function installProbe(): void {
  const humanSeat = () => {
    const room = [...localServer().rooms.values()][0];
    if (!room) return null;
    const seat = room.seats.findIndex((s) => !s.isBot);
    const rnd = room.round;
    return rnd && seat >= 0 ? { room, seat, rnd } : null;
  };
  (globalThis as Record<string, unknown>).__shengjiOffline = {
    legalPlayIds(): number[][] | null {
      const h = humanSeat();
      if (!h) return null;
      const plays = legalPlays(h.rnd, h.seat);
      return plays ? plays.map((p) => h.room.idsForCodes(h.seat, p)) : null;
    },
    /** The release bot's counters: decisions asked, answered, and why SmartBot took the others. */
    botStats(): unknown {
      return localServer().remote?.stats ?? null;
    },
    buryIds(): number[] | null {
      const h = humanSeat();
      if (!h || h.rnd.phase !== "bury" || h.rnd.turn !== h.seat) return null;
      h.room.syncKitty();
      return h.room.idsForCodes(h.seat, h.room.bot.bury(viewFor(h.rnd, h.seat)));
    },
  };
}

if (typeof window !== "undefined") installProbe();

// Nearby play: the host page's NearbyHost on its room, and the joiner's link.
import { NearbyHost, type NearbyHostEvents } from "./nearby/host";
import { nativeTransport } from "./nearby/native";
import { NearbySocket } from "./nearby/socket";
import { NearbyError, type LinkState, type NearbyTransport } from "./nearby/transport";

let nearbyTransport: NearbyTransport | null = null;
let activeHost: NearbyHost | null = null;
/** A host whose Leave is telling its joiners; it stops on its own, or at
 *  once when the next table starts (the plugin runs one session). */
let endingHost: NearbyHost | null = null;

/** Tests: the transport nearby play uses in place of the native plugin. */
export function setNearbyTransportForTests(t: NearbyTransport | null): void {
  nearbyTransport = t;
}

function transport(): NearbyTransport {
  const t = nearbyTransport ?? nativeTransport();
  if (!t) throw new NearbyError("failed", "no nearby transport in this app");
  return t;
}

/** Advertise this page's nearby room `code` on the local network. */
export async function hostNearby(code: string, events: NearbyHostEvents): Promise<void> {
  stopNearbyHost();
  endingHost?.stop();
  endingHost = null;
  const server = localServer();
  const room = server.rooms.get(code);
  if (!room || !room.nearby) throw new NearbyError("failed", "no such nearby room");
  const host = new NearbyHost(server, room, events);
  activeHost = host;
  try {
    await host.start(transport());
  } catch (e) {
    if (activeHost === host) activeHost = null;
    host.stop();
    throw e;
  }
}

export function stopNearbyHost(): void {
  activeHost?.stop();
  activeHost = null;
}

/** The host's Leave: its room tells every joiner the table is over before
 *  the links stop (NearbyHost.stopWhenClosed). */
export function endNearbyHost(): void {
  const host = activeHost;
  activeHost = null;
  if (!host) return;
  endingHost = host;
  host.stopWhenClosed();
}

/** The joiner's socket to the nearby table `code`, for ws.ts's Connection. */
export function nearbyJoinSocket(code: string, onState: (state: LinkState, detail?: string) => void): NearbySocket {
  endingHost?.stop();
  endingHost = null;
  return new NearbySocket(transport(), code, onState);
}
