// The app's device account at the first online Play, Duo or Join: before
// that first table is asked for, sign in with the Keychain's secret, or make
// a new account and keep its secret there, so the table is asked for by the
// account. Anywhere else, and whenever an account is already signed in, the
// action runs at once, exactly as it always has.
//
// A failure never blocks play: a server with device accounts off (404), too
// many attempts (429), no connection or a refused secret (401, which also
// clears it) leave the player a guest and the action goes ahead.

import { auth, deviceAccountsAvailable, deviceAuth, forgetDeviceSecret } from "./auth";
import { keychainGet, keychainSet } from "./keychain";
import { conn } from "./ws";
import type { ConnStatus } from "./ws";

/** How long the action waits for the account's socket to open. */
export const OPEN_WAIT_MS = 6000;

/** The server has device accounts off: no more asking on this page. */
let off = false;
let inFlight = false;

function waitForOpen(ms: number): Promise<void> {
  return new Promise((resolve) => {
    let stop: (() => void) | null = null;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      stop?.();
      resolve();
    };
    const timer = window.setTimeout(finish, ms);
    // a test may stand in a partial socket
    stop = conn.subscribeStatus?.((s: ConnStatus) => { if (s === "open") finish(); }) ?? null;
    if (done) stop?.();
  });
}

/** Signs this device in; true when an account now holds the session. */
async function signInDevice(): Promise<boolean> {
  let token: string | null = null;
  try {
    token = await keychainGet();
  } catch {
    token = null;
  }
  const got = await deviceAuth(token);
  if (got.status === 404 || got.status === 403) {
    off = true;
    return false;
  }
  if (got.status === 401) {
    // the account is gone: play as a guest now, a fresh one comes next time
    await forgetDeviceSecret();
    return false;
  }
  if (!got.user) return false;
  if (got.token) {
    try {
      await keychainSet(got.token);
    } catch {
      /* the session cookie still holds the account until it expires */
    }
  }
  auth.signedIn(got.user);
  return true;
}

/** Run `action` (the first online Play, Duo or Join) as the device's
 *  account. A second tap while the first is signing in does nothing. */
export function beforeOnlineSetup(action: () => void): void {
  if (off || !deviceAccountsAvailable()) {
    action();
    return;
  }
  const status = auth.state?.status;
  if (status !== "out" && status !== "off") {
    action();
    return;
  }
  if (inFlight) return;
  inFlight = true;
  void signInDevice()
    .catch(() => false)
    .then((signed) => (signed ? waitForOpen(OPEN_WAIT_MS) : undefined))
    .finally(() => {
      inFlight = false;
      action();
    });
}

/** Test seam: forget what this page learned. */
export function resetDeviceAccountForTests(): void {
  off = false;
  inFlight = false;
}
