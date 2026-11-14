// Which seats a join must offer as a deliberate takeover of a dropped
// player's seat, from a peek_room answer.
import type { RoomSeats } from "./protocol";

/** A seat a dropped player left, which a newcomer may take over. */
export interface DroppedSeat { seat: number; name: string }

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
