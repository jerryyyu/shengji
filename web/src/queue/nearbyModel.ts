// The nearby panels' models: a nearby table's lobby (`nearbyRoomModel`), a
// nearby code's Join panel (`fromNearbyJoin`) and the offline table's Nearby
// switch (`nearbySwitch`). Part of the nearby UI, loaded only where the app
// binary offers nearby play (nearbyGate.ts).
import { displayName, t } from "../i18n";
import type { NearbyJoin } from "../nearbyJoin";
import { NEARBY_COPY } from "../offline/server/nearby/copy";
import { nearbyChoices, nearbyStartSeat } from "../joinSeats";
import type { RoomMsg } from "../protocol";
import { BOT_FILL_MS } from "./store";
import type { ModelSeat, NearbySwitch, Ring, TableModel } from "./tableModel";
import { labelList, seatLabel, shortName, teamWord, waitingLine } from "./tableText";

/** The offline table's Nearby switch: `on` while the table is open to nearby
 *  phones; `line`, why it fell back off (the denied line links to Settings). */
export function nearbySwitch({ on, line }: { on: boolean; line: "denied" | "wifiOff" | null }): NearbySwitch {
  const status = line === "denied"
    ? { text: NEARBY_COPY.denied, warn: true, link: { label: NEARBY_COPY.openSettings, act: { type: "nearby_settings" } as const } }
    : line === "wifiOff" ? { text: NEARBY_COPY.wifiOff, warn: true } : undefined;
  return { label: NEARBY_COPY.switchLabel, on, status };
}

/** A nearby table's lobby, from its room frame, as a shared online table
 *  draws it: who sits where with their Ready, the code without an Invite
 *  link, the host's Nearby switch (locked once someone has joined). The
 *  host has Start with bots with the bots' ring, never waiting for a
 *  Ready, and "n of m ready" over its guests; a guest has its Ready toggle
 *  and Leave under "Waiting for <host> to start". `botsAt`: the ring's
 *  end, in Date.now() time. */
export function nearbyRoomModel(room: RoomMsg, { now, botsAt }: { now: number; botsAt: number | null }): TableModel {
  const nb = room.nearby ?? { ready: [], bots_in: null, locked: false };
  const ready = new Set(nb.ready ?? []);
  const people = room.players.filter((p) => !p.is_bot);
  const others = people.filter((p) => p.seat !== room.you);
  const host = room.host === room.you;
  const seats = [0, 1, 2, 3].map((at): ModelSeat => {
    const p = room.players.find((x) => x.seat === at);
    const ours = (at - room.you + 4) % 2 === 0;
    if (!p) return { at, look: "open", name: "", sub: "", label: seatLabel("queue.seat.open", ours) };
    const tick = ready.has(at);
    const sub = !p.connected ? t("queue.seat.reconnecting") : "";
    if (at === room.you) {
      return { at, look: "you", name: t("queue.seat.you"), sub: "", tick,
               label: labelList([t("queue.seat.you"), tick && t("queue.seat.ready")]) };
    }
    return { at, look: "person", name: shortName(p.name), sub, tick,
             label: labelList([p.name, tick && t("queue.seat.ready"), sub, teamWord(ours)]) };
  });
  // every table you sit at is "Your table"; the seats name the people
  const title = t("queue.title.yourTable");
  const hostName = room.players.find((p) => p.seat === room.host)?.name ?? "";
  const ring: Ring | null = botsAt !== null && botsAt > now ? { left: (botsAt - now) / 1000, total: BOT_FILL_MS / 1000 } : null;
  return {
    kind: "offline",
    tag: "Offline",
    title,
    status: !host ? { text: waitingLine(hostName) }
      : others.length ? { text: t("queue.status.ready", { n: others.filter((p) => ready.has(p.seat)).length, count: others.length }) }
      : undefined,
    seats,
    you: room.you,
    // the host picks the Bots, as an online casual table's opener does;
    // `ranked` keeps the Starting level row off (it is fixed at Play)
    rows: { code: room.room, invite: false, ranked: true, opener: host, level: room.start_level, joiners: undefined,
            bots: room.bot_level ?? "standard" },
    waitSwitch: null,
    nearbySwitch: host ? { label: NEARBY_COPY.switchLabel, on: true, disabled: nb.locked } : null,
    chat: null,
    primary: host ? { label: t("queue.btn.startBots"), disabled: false, ring, act: { type: "nearby_start" } }
      : { label: t("queue.btn.ready"), disabled: false, ring, pressed: ready.has(room.you), waiting: ready.has(room.you),
          act: { type: "nearby_ready", on: !ready.has(room.you) } },
    secondary: { label: t("queue.btn.leave"), disabled: false, act: { type: "offline_leave" } },
    leave: { kind: "queue", others: [] },
  };
}

/** A nearby code's Join panel: the code alone while it is looked for, then
 *  the table's seats with every open seat a pick, Join and Not now; not
 *  found, Try again. */
export function fromNearbyJoin(j: NearbyJoin): TableModel {
  const peek = j.peek;
  const choices = new Set(peek ? nearbyChoices(peek) : []);
  // the seat this phone holds is a pick too: a tap back to it after another
  if (j.held !== undefined && j.held !== null) choices.add(j.held);
  const seats = peek ? [0, 1, 2, 3].map((at): ModelSeat => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - (j.seat ?? 0) + 4) % 2 === 0;
    if (at === j.seat) return { at, look: "you", picked: true, name: t("queue.seat.you"), sub: "", label: t("queue.seat.youOurs"),
                                ...(choices.has(at) && j.step === "panel" ? { act: { type: "code_pick", seat: at } as const } : {}) };
    if (!sd) {
      return { at, look: "open", name: "", sub: "", label: seatLabel("queue.seat.open", ours),
               ...(choices.has(at) && j.step === "panel" ? { act: { type: "code_pick", seat: at } as const } : {}) };
    }
    const shown = displayName(sd.name, sd.is_bot);
    return { at, look: "person", name: shortName(shown), sub: "", label: seatLabel("queue.seat.named", ours, { name: shown }),
             ...(choices.has(at) && j.step === "panel" ? { act: { type: "code_pick", seat: at } as const } : {}) };
  }) : null;
  const status = j.step === "looking" ? { text: j.linked ? NEARBY_COPY.connecting : NEARBY_COPY.browsing }
    : j.step === "notFound" ? { text: NEARBY_COPY.notFound, warn: true }
    : j.step === "full" ? { text: NEARBY_COPY.full, warn: true }
    : j.step === "version" ? { text: NEARBY_COPY.versionMismatch, warn: true }
    : j.step === "wifiOff" ? { text: NEARBY_COPY.wifiOff, warn: true }
    : undefined;
  const retry = j.step === "notFound" || j.step === "wifiOff";
  return {
    kind: "join-code",
    tag: "Offline",
    title: t("queue.title.join", { name: j.code }),
    status,
    seats,
    you: j.seat ?? 0,
    // the picker stays drawn around the seat it started on: a tap glows
    // where it lands rather than turning the table
    layout: peek ? nearbyStartSeat(peek, j.held ?? null) ?? undefined : undefined,
    rows: null, waitSwitch: null, chat: null,
    primary: retry
      ? { label: NEARBY_COPY.tryAgain, disabled: false, act: { type: "nearby_again" } }
      : { label: t(j.step === "joining" ? "queue.btn.joining" : "queue.btn.join"), disabled: j.step !== "panel" || j.seat === null,
          busy: j.step === "joining" || j.step === "looking", act: { type: "code_join" } },
    secondary: { label: t("queue.btn.notNow"), disabled: false, act: { type: "code_cancel" } },
    leave: { kind: "queue", others: [] },
  };
}
