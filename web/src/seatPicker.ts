import type { RoomSeats } from "./protocol";

/** Whether a join must show the seat picker instead of joining straight
 *  through: more than one seat is open, or the only open seat belongs to a
 *  dropped human (taking someone's seat should always be deliberate).
 *  Not conditioned on in_game: a full pre-game lobby with one dropped player
 *  also needs the picker, or the server answers choose_seat and the client
 *  has nothing to show. */
export function needsSeatPicker(seats: RoomSeats["seats"]): boolean {
  const open = seats.filter((sd) => sd.claimable);
  const bots = seats.filter((sd) => sd.is_bot);
  return open.length > 1 || (open.length === 1 && bots.length === 0);
}
