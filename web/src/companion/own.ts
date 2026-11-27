// The viewer's own look: the account's, or for a guest the one its device
// key draws, which is the look the server shows the table for that seat.
import type { AuthUser } from "../auth";
import { deviceKey } from "../deviceKey";
import { guestLookFor } from "./look";

/** The look `user` wears (null for a guest: this device's). */
export function ownLook(user: AuthUser | null): string {
  return user ? user.look ?? "" : guestLookFor(deviceKey());
}
