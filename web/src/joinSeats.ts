// What the Join panel shows for a room code, from a peek_room answer: whose
// seats are whose, where a join would sit you, whether the table is full, and
// which seats are a deliberate takeover of a dropped player's seat. A queued
// table's code answers with the table form, drawn as it stands: the server
// seats a code join by its own rules.
import type { RoomSeats, TableSeats } from "./protocol";

/** A seat a dropped player left, which a newcomer may take over. */
export interface DroppedSeat { seat: number; name: string }

type Peek = Pick<RoomSeats, "in_game" | "seats" | "ranked" | "full">;

/** The seats a join must offer as a deliberate takeover: with no bot seat
 *  to take, every claimable seat belongs to a dropped human, and the server
 *  seats nobody there unasked (it answers choose_seat). With a bot seat
 *  free, or before the game an empty one (the peek lists only taken
 *  seats), the server seats you there, and no human's seat is taken. */
export function takeoverSeats(peek: Pick<RoomSeats, "in_game" | "seats">): DroppedSeat[] {
  const { seats } = peek;
  // before the game an empty seat (not listed) seats a joiner at once
  if (!peek.in_game && seats.length < 4) return [];
  if (seats.some((sd) => sd.claimable && sd.is_bot)) return [];
  return seats.filter((sd) => sd.claimable && !sd.is_bot).map((sd) => ({ seat: sd.seat, name: sd.name }));
}

/** The seat a plain Join would get, as the server picks it: before the game
 *  the partner seat of the person the panel names while it is empty, else
 *  the lowest empty seat; in a game (or at a ranked table) the first bot
 *  seat it may take; null when a plain Join gets none. */
export function joinSeat(peek: Peek): number | null {
  if (peek.full) return null;
  if (!peek.in_game && !peek.ranked) {
    const taken = new Set(peek.seats.map((sd) => sd.seat));
    const host = hostSeat(peek);
    if (host !== null && !taken.has((host + 2) % 4)) return (host + 2) % 4;
    const empty = [0, 1, 2, 3].find((at) => !taken.has(at));
    if (empty !== undefined) return empty;
  }
  return peek.seats.find((sd) => sd.claimable && sd.is_bot)?.seat ?? null;
}

/** No seat for a joiner, plain or by takeover. */
export function tableFull(peek: Peek): boolean {
  return joinSeat(peek) === null && takeoverSeats(peek).length === 0;
}

/** The seat of the person the panel's title names: the first person at
 *  the table, by seat, who is connected (else the first person). */
function hostSeat(peek: Pick<RoomSeats, "seats">): number | null {
  const people = [...peek.seats].filter((sd) => !sd.is_bot).sort((a, b) => a.seat - b.seat);
  return (people.find((sd) => sd.connected) ?? people[0])?.seat ?? null;
}

/** Who the panel's title names. */
export function hostName(peek: Pick<RoomSeats, "seats">): string | null {
  const at = hostSeat(peek);
  return peek.seats.find((sd) => sd.seat === at)?.name ?? null;
}

/** The seat a queued table's seats are drawn from: the held seat (a Duo's
 *  code seats its first single there), else the first open seat in the
 *  server's arrival order (partner first), else seat 0. */
export function tableViewSeat(peek: Pick<TableSeats, "seats">): number {
  const at = (state: TableSeats["seats"][number]["state"]) =>
    [0, 2, 1, 3].find((s) => peek.seats.find((sd) => sd.seat === s)?.state === state);
  return at("held") ?? at("open") ?? 0;
}

/** Who a queued table's panel title names: its first taken seat's person. */
export function tableHostName(peek: Pick<TableSeats, "seats">): string | null {
  return [...peek.seats].sort((a, b) => a.seat - b.seat).find((sd) => sd.state === "taken")?.name ?? null;
}
