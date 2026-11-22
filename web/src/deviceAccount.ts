// The app's device account at the first online Play, Duo or Join: before
// that first table is asked for, sign in with the Keychain's secret, or make
// a new account and keep its secret there, so the table is asked for by the
// account, on a socket that carries it. Anywhere else the action runs at
// once, exactly as it always has.
//
// One tap is one attempt, and identity changes are serialized: one sign-in
// (with its Keychain work and the socket reopening) runs at a time, and a
// launch's restore counts as one. The tap waits at most INTENT_MS for it. Past
// that the tap is given up with nothing sent (the sign-in finishes on its own,
// and the next tap waits for it), so an action never goes out on the socket
// of an identity that is about to change. An action whose place is gone by
// the time it could go (another tab, another mode, a seat already taken)
// does not fire either.
//
// A failure never blocks play: a server with device accounts off (404), too
// many attempts (429), no connection, a refused secret (401, which also
// clears it) or a Keychain that cannot be read leave the player a guest for
// this action, and an existing secret is never replaced. A new account whose
// secret the Keychain will not keep stays signed in on the cookie, with the
// secret held in memory for this session and offered to the Keychain again
// before it is next used; no other account is made meanwhile.

import { useEffect, useState } from "react";
import {
  auth, deviceAccountsAvailable, deviceAuth, deviceSecretOutstanding, forgetDeviceSecret, identityChanging, identityTurn,
  keepDeviceSecret, settleKeychain,
} from "./auth";
import { keychainGet } from "./keychain";
import { deviceIdiom } from "./native";

/** How long a Play, Duo or Join waits for the device's sign-in. */
export const INTENT_MS = 6000;

/** The server has device accounts off: no more asking on this page. */
let off = false;
/** The tap waiting, if any. */
let pending: { cancel: () => void } | null = null;
/** The identity change under way, if any. */
let identityOp: Promise<SetupOutcome> | null = null;
/** True while a deferred action runs, so a join it makes in turn runs at
 *  once instead of starting a second attempt. */
let inAction = false;

/** What the last attempt came to; for tests and the log. */
export type SetupOutcome = "signed_in" | "unsaved" | "restored" | "guest" | "off" | "read_failed" | "timed_out";
let lastOutcome: SetupOutcome | null = null;
export function lastSetupOutcome(): SetupOutcome | null {
  return lastOutcome;
}

/** Signs this device in, inside its identity turn. */
async function signInDevice(): Promise<SetupOutcome> {
  // A removal or a save an earlier attempt could not finish comes first;
  // while either is refused the Keychain is not used, and no account is
  // made over a secret that may be there or is still owed to it.
  if (!(await settleKeychain())) return "read_failed";
  let token: string | null;
  try {
    token = await keychainGet();
  } catch {
    // an unreadable Keychain may hold a secret: never make a second account over it
    return "read_failed";
  }
  const got = await deviceAuth(token);
  if (got.status === 404 || got.status === 403) {
    off = true;
    auth.noDeviceAccounts?.();
    return "off";
  }
  if (got.status === 401) {
    // the account is gone: play as a guest now, a fresh one comes next time
    await forgetDeviceSecret();
    return "guest";
  }
  if (!got.user) return "guest";
  // a secret the Keychain refuses is held for this session; the cookie keeps the account
  const outcome: SetupOutcome = got.token && !(await keepDeviceSecret(got.token)) ? "unsaved" : "signed_in";
  auth.signedIn(got.user);
  return outcome;
}

/** The one identity change at a time: a tap joins the one under way. It
 *  runs in the sign-in turns every path shares, after any launch restore. */
function identity(): Promise<SetupOutcome> {
  if (!identityOp) {
    const op = auth.settled()
      .then(() => identityTurn(async (): Promise<SetupOutcome> => {
        const status = auth.state?.status;
        if (status !== "out" && status !== "off") return status === "in" ? "restored" : "guest";
        if (off) return "guest";
        return signInDevice();
      }))
      .catch((): SetupOutcome => "guest");
    identityOp = op;
    void op.then(() => { if (identityOp === op) identityOp = null; });
  }
  return identityOp;
}

/** Run `action` (an online Play, Duo or Join) as the device's account.
 *  `stillWanted` is asked before a deferred action fires; the action is
 *  also dropped when the page has moved on (its address changed).
 *  `gaveUp` runs when the wait passes INTENT_MS and the tap is dropped. */
export function beforeOnlineSetup(action: () => void, stillWanted: () => boolean = () => true,
                                  gaveUp?: () => void): void {
  if (inAction || !deviceAccountsAvailable()) {
    action();
    return;
  }
  if (pending) return;
  const status = auth.state?.status;
  const settled = status === "in" || status === "error" || off;
  // a sign-in or sign-out under way (a provider switch included) goes first
  if (settled && !identityOp && !identityChanging() && !auth.isReopening?.()) {
    // a secret the Keychain refused earlier this session is offered again
    if (deviceSecretOutstanding()) void settleKeychain();
    action();
    return;
  }
  const where = window.location.href;
  let done = false;
  const end = () => {
    done = true;
    window.clearTimeout(timer);
    pending = null;
  };
  const timer = window.setTimeout(() => {
    if (done) return;
    end();
    lastOutcome = "timed_out";
    gaveUp?.();
  }, INTENT_MS);
  pending = { cancel: end };
  // the action goes once the identity is settled and its socket has reopened
  void identity().then(async (outcome) => { await auth.settled(); return outcome; }).then((outcome) => {
    if (done) return;
    end();
    lastOutcome = outcome;
    if (window.location.href !== where || !stillWanted()) return;
    inAction = true;
    try {
      action();
    } finally {
      inAction = false;
    }
  });
}

/** The one line saying where the app's own account lives, by the device the
 *  shell reports: "On this iPad only" on an iPad, else "On this iPhone only". */
export function useOnThisDeviceLine(): string {
  const [pad, setPad] = useState(false);
  useEffect(() => {
    let live = true;
    void deviceIdiom().then((i) => { if (live) setPad(i === "pad"); });
    return () => { live = false; };
  }, []);
  return `On this ${pad ? "iPad" : "iPhone"} only`;
}

/** Test seam: forget what this page learned. */
export function resetDeviceAccountForTests(): void {
  pending?.cancel();
  off = false;
  pending = null;
  identityOp = null;
  inAction = false;
  lastOutcome = null;
}
