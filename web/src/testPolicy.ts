import type { ClientMsg } from "./protocol";

/**
 * Build the create-room wire message for the guarded W32 test controls.
 *
 * The disabled path deliberately returns the historical object shape. A
 * selected policy without a key is refused before any send can occur.
 */
export function createRoomPayload(
  name: string,
  w32Selected: boolean,
  accessKey: string,
): Extract<ClientMsg, { type: "create_room" }> | null {
  if (!w32Selected) return { type: "create_room", name };
  if (!accessKey.trim()) return null;
  return {
    type: "create_room",
    name,
    test_policy: "w32",
    test_access_key: accessKey,
  };
}
