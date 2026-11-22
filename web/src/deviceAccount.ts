// The app's device account at the first online Play, Duo or Join: before
// that first table is asked for, sign in with the Keychain's secret, or make
// a new account and keep its secret there, so the table is asked for by the
// account, on a socket that carries it. Anywhere else the action runs at
// once, exactly as it always has.
//
// One tap is one attempt. While it is under way (sign-in, then the socket
// reopening as the account) a further tap does nothing. The attempt is
// bounded as a whole, sign-in included: at INTENT_MS it is abandoned and
// the action goes ahead as things stand. An action whose place is gone by
// then (another tab, another mode, a seat already taken) does not fire.
//
// A failure never blocks play: a server with device accounts off (404), too
// many attempts (429), no connection, a refused secret (401, which also
// clears it) or a Keychain that cannot be read leave the player a guest for
// this action, and an existing secret is never replaced.

import { useEffect, useState } from "react";
import { auth, deleteAccount, deviceAccountsAvailable, deviceAuth, forgetDeviceSecret } from "./auth";
import { keychainGet, keychainSet } from "./keychain";
import { deviceIdiom } from "./native";

/** How long one Play, Duo or Join may wait, sign-in included. */
export const INTENT_MS = 6000;

/** The server has device accounts off: no more asking on this page. */
let off = false;
/** The Keychain refused to keep a new account's secret: no more accounts
 *  are made on this page, since each would be lost with the cookie. */
let unkept = false;
/** The attempt under way, if any. */
let pending: { cancel: () => void } | null = null;
/** True while a deferred action runs, so a join it makes in turn runs at
 *  once instead of starting a second attempt. */
let inAction = false;

/** What the last attempt came to; for tests and the log. */
export type SetupOutcome = "signed_in" | "restored" | "guest" | "off" | "read_failed" | "write_failed" | "timed_out";
let lastOutcome: SetupOutcome | null = null;
export function lastSetupOutcome(): SetupOutcome | null {
  return lastOutcome;
}

/** Keeps a new secret, trying once more on a refusal. */
async function keep(token: string): Promise<boolean> {
  for (let i = 0; i < 2; i += 1) {
    try {
      await keychainSet(token);
      return true;
    } catch {
      /* tried again once */
    }
  }
  return false;
}

/** Signs this device in, as one attempt. */
async function signInDevice(signal: AbortSignal): Promise<SetupOutcome> {
  let token: string | null;
  try {
    token = await keychainGet();
  } catch {
    // an unreadable Keychain may hold a secret: never make a second account over it
    return "read_failed";
  }
  if (signal.aborted) return "timed_out";
  const got = await deviceAuth(token, signal);
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
  if (!got.user) return signal.aborted ? "timed_out" : "guest";
  if (got.token && !(await keep(got.token))) {
    // The new account could live only in the cookie and be lost with it.
    // It is deleted at once (it has nothing yet) and this device stays a
    // guest, shown as one; only if that delete fails is it signed in, so
    // the account is at least visible and can be deleted from Me.
    unkept = true;
    auth.noDeviceAccounts?.();
    try {
      await deleteAccount();
      return "write_failed";
    } catch {
      /* signed in below */
    }
  }
  auth.signedIn(got.user);
  return "signed_in";
}

async function attempt(signal: AbortSignal): Promise<SetupOutcome> {
  // a launch still restoring the account, or a socket reopening as it
  await auth.settled();
  if (signal.aborted) return "timed_out";
  const status = auth.state?.status;
  if (status !== "out" && status !== "off") return status === "in" ? "restored" : "guest";
  if (off || unkept) return "guest";
  const outcome = await signInDevice(signal);
  if (outcome === "signed_in") await auth.settled();
  return outcome;
}

/** Run `action` (an online Play, Duo or Join) as the device's account.
 *  `stillWanted` is asked before a deferred action fires; the action is
 *  also dropped when the page has moved on (its address changed). */
export function beforeOnlineSetup(action: () => void, stillWanted: () => boolean = () => true): void {
  if (inAction || !deviceAccountsAvailable()) {
    action();
    return;
  }
  if (pending) return;
  const status = auth.state?.status;
  const settled = status === "in" || status === "error" || off || unkept;
  if (settled && !auth.isReopening?.()) {
    action();
    return;
  }
  const where = window.location.href;
  const abort = new AbortController();
  let done = false;
  const finish = (outcome: SetupOutcome) => {
    if (done) return;
    done = true;
    window.clearTimeout(timer);
    pending = null;
    lastOutcome = outcome;
    abort.abort();
    if (window.location.href !== where || !stillWanted()) return;
    inAction = true;
    try {
      action();
    } finally {
      inAction = false;
    }
  };
  const timer = window.setTimeout(() => finish("timed_out"), INTENT_MS);
  pending = {
    cancel: () => {
      done = true;
      window.clearTimeout(timer);
      pending = null;
      abort.abort();
    },
  };
  void attempt(abort.signal).catch((): SetupOutcome => "guest").then(finish);
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
  unkept = false;
  pending = null;
  inAction = false;
  lastOutcome = null;
}
