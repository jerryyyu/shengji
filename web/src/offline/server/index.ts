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
    buryIds(): number[] | null {
      const h = humanSeat();
      if (!h || h.rnd.phase !== "bury" || h.rnd.turn !== h.seat) return null;
      h.room.syncKitty();
      return h.room.idsForCodes(h.seat, h.room.bot.bury(viewFor(h.rnd, h.seat)));
    },
  };
}

if (typeof window !== "undefined") installProbe();
