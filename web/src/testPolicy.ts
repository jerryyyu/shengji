import type { ClientMsg, Rank } from "./protocol";
import { RANKS } from "./protocol";

/** The level a room starts at unless the creator picks another. */
export const DEFAULT_START_LEVEL: Rank = RANKS[0];

/**
 * Build the create-room wire message for the guarded W32 test controls.
 *
 * The disabled path deliberately returns the historical object shape. A
 * selected policy without a key is refused before any send can occur.
 *
 * `start_level` is omitted at the default, so an ordinary game puts exactly
 * the historical bytes on the wire and an older server keeps working.
 */
export function createRoomPayload(
  name: string,
  w32Selected: boolean,
  accessKey: string,
  startLevel: Rank = DEFAULT_START_LEVEL,
): Extract<ClientMsg, { type: "create_room" }> | null {
  const level =
    startLevel === DEFAULT_START_LEVEL ? {} : { start_level: startLevel };
  if (!w32Selected) return { type: "create_room", name, ...level };
  if (!accessKey.trim()) return null;
  return {
    type: "create_room",
    name,
    ...level,
    test_policy: "w32",
    test_access_key: accessKey,
  };
}
