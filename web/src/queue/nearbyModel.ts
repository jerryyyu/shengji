// The nearby panels' models: a nearby table's lobby (`nearbyRoomModel`), a
// nearby code's Join panel (`fromNearbyJoin`) and the offline table's Nearby
// switch (`nearbySwitch`). Part of the nearby UI, loaded only where the app
// binary offers nearby play (nearbyGate.ts).
import type { NearbyJoin } from "../nearbyJoin";
import { NEARBY_COPY } from "../offline/server/nearby/copy";
import { nearbyChoices } from "../joinSeats";
import type { RoomMsg } from "../protocol";
import { BOT_FILL_MS } from "./store";
import { teamWord } from "./tableModel";
import type { ModelSeat, NearbySwitch, Ring, TableModel } from "./tableModel";
import { shortName } from "./tableText";

/** The offline table's Nearby switch: `on` while the table is open to nearby
 *  phones; `line`, why it fell back off (the denied line links to Settings). */
export function nearbySwitch({ on, line }: { on: boolean; line: "denied" | "wifiOff" | null }): NearbySwitch {
  const status = line === "denied"
    ? { text: NEARBY_COPY.denied, warn: true, link: { label: NEARBY_COPY.openSettings, act: { type: "nearby_settings" } as const } }
    : line === "wifiOff" ? { text: NEARBY_COPY.wifiOff, warn: true } : undefined;
  return { label: NEARBY_COPY.switchLabel, on, status };
}

/** A nearby table's lobby, from its room frame, as a shared online table
 *  draws it: who sits where with their Start, "n of m ready", the code
 *  without an Invite link, the host's Nearby switch (locked once someone
 *  has joined), and Start with the bots' ring. `botsAt`: the ring's end,
 *  in Date.now() time. */
export function nearbyRoomModel(room: RoomMsg, { now, botsAt }: { now: number; botsAt: number | null }): TableModel {
  const nb = room.nearby ?? { ready: [], bots_in: null, locked: false };
  const ready = new Set(nb.ready);
  const people = room.players.filter((p) => !p.is_bot);
  const others = people.filter((p) => p.seat !== room.you);
  const host = room.host === room.you;
  const youReady = ready.has(room.you);
  const seats = [0, 1, 2, 3].map((at): ModelSeat => {
    const p = room.players.find((x) => x.seat === at);
    const ours = (at - room.you + 4) % 2 === 0;
    if (!p) return { at, look: "open", name: "", sub: "", label: `Open seat, ${teamWord(ours)}` };
    const tick = ready.has(at);
    const sub = !p.connected ? "Reconnecting" : "";
    if (at === room.you) {
      return { at, look: "you", name: "You", sub: "", tick,
               label: ["You", tick ? "ready" : null].filter(Boolean).join(", ") };
    }
    return { at, look: "person", name: shortName(p.name), sub, tick,
             label: [p.name, tick ? "ready" : null, sub || null, teamWord(ours)].filter(Boolean).join(", ") };
  });
  const names = others.map((p) => shortName(p.name));
  const title = names.length === 0 ? "Your table"
    : names.length === 1 ? `You and ${names[0]}`
    : `You, ${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  const waitingFor = people.filter((p) => p.connected && !ready.has(p.seat)).map((p) => shortName(p.name));
  const label = !youReady ? "Start"
    : waitingFor.length === 0 ? "Starting…"
    : waitingFor.length === 1 ? `Waiting for ${waitingFor[0]}`
    : `Waiting for ${waitingFor.length} players`;
  const ring: Ring | null = botsAt !== null && botsAt > now ? { left: (botsAt - now) / 1000, total: BOT_FILL_MS / 1000 } : null;
  return {
    kind: "offline",
    tag: "Offline",
    title,
    status: others.length ? { text: `${people.filter((p) => ready.has(p.seat)).length} of ${people.length} ready` } : undefined,
    seats,
    you: room.you,
    // the host picks the Bots, as an online casual table's opener does;
    // `ranked` keeps the Starting level row off (it is fixed at Play)
    rows: { code: room.room, invite: false, ranked: true, opener: host, level: room.start_level, joiners: undefined,
            bots: room.bot_level ?? "standard" },
    waitSwitch: null,
    nearbySwitch: host ? { label: NEARBY_COPY.switchLabel, on: true, disabled: nb.locked } : null,
    chat: null,
    primary: { label, disabled: youReady && waitingFor.length === 0, ring,
               act: { type: "nearby_ready", on: !youReady }, waiting: youReady },
    secondary: { label: "Leave", disabled: false, act: { type: "offline_leave" } },
    leave: { kind: "queue", others: [] },
  };
}

/** A nearby code's Join panel: the code alone while it is looked for, then
 *  the table's seats with every open seat a pick, Join and Not now; not
 *  found, Try again. */
export function fromNearbyJoin(j: NearbyJoin): TableModel {
  const peek = j.peek;
  const choices = new Set(peek ? nearbyChoices(peek) : []);
  const seats = peek ? [0, 1, 2, 3].map((at): ModelSeat => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - (j.seat ?? 0) + 4) % 2 === 0;
    if (at === j.seat) return { at, look: "you", picked: true, name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (!sd) {
      return { at, look: "open", name: "", sub: "", label: `Open seat, ${teamWord(ours)}`,
               ...(choices.has(at) && j.step === "panel" ? { act: { type: "code_pick", seat: at } as const } : {}) };
    }
    return { at, look: "person", name: shortName(sd.name), sub: "", label: `${sd.name}, ${teamWord(ours)}` };
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
    title: `Join ${j.code}`,
    status,
    seats,
    you: j.seat ?? 0,
    rows: null, waitSwitch: null, chat: null,
    primary: retry
      ? { label: NEARBY_COPY.tryAgain, disabled: false, act: { type: "nearby_again" } }
      : { label: j.step === "joining" ? "Joining…" : "Join", disabled: j.step !== "panel" || j.seat === null,
          busy: j.step === "joining" || j.step === "looking", act: { type: "code_join" } },
    secondary: { label: "Not now", disabled: false, act: { type: "code_cancel" } },
    leave: { kind: "queue", others: [] },
  };
}
