// Optional Google sign-in. The server decides whether the feature exists
// (`/api/auth/config` carries the public client id or null); when it is off
// nothing here loads a script, renders a button or sets a cookie, and guest
// play is untouched. The session itself is an HttpOnly cookie the browser
// sends on its own, to `/api/*` and on the `/ws` handshake alike.

import { useEffect, useState } from "react";
import { forgetPrivateSession } from "./home/session";
import { keychainAvailable, keychainGet, keychainRemove, keychainSet } from "./keychain";
import { isNative } from "./native";
import { nativeAppleSignOut, nativeGoogleSignOut } from "./nativeAuth";
import { telemetry } from "./telemetry";
import { conn } from "./ws";
import { t } from "./i18n";

export interface AuthUser {
  /** The profile name: Google's, or the name Apple sent on the first sign-in. */
  name: string;
  email: string;
  picture: string | null;
  /** The name the player chose for this account; null means none chosen. */
  display_name: string | null;
  /** What the player is called: `display_name`, else the Google first name. */
  name_shown: string;
  /** Rounds the account has sat in; null or absent when the server does not say. */
  rounds_played?: number | null;
  /** False for an account with no Google or Apple identity (the iOS app's
   *  own); absent when the server does not say. */
  linked?: boolean;
}

/** The `/api/me` body as the server sends it; older servers lack the two
 *  display-name fields and the round count, so those are filled in here. */
function toUser(body: Partial<AuthUser> & { name: string; email: string }): AuthUser {
  return {
    name: body.name,
    email: body.email,
    picture: body.picture ?? null,
    display_name: body.display_name ?? null,
    name_shown: body.name_shown ?? firstName(body.name),
    rounds_played: typeof body.rounds_played === "number" ? body.rounds_played : null,
    ...(typeof body.linked === "boolean" ? { linked: body.linked } : {}),
  };
}

/** "off": the server has no sign-in configured. "error": the server could
 *  not be asked (no connection, or it answered with a failure), so whether
 *  sign-in exists is unknown and its controls show as unavailable. */
export type AuthStatus = "loading" | "off" | "error" | "out" | "in";

export interface AuthState {
  status: AuthStatus;
  clientId: string | null;
  user: AuthUser | null;
  /** Set only in the iOS app with the Keychain, when the server has device
   *  accounts on: the first online Play makes this device's account. */
  deviceAccounts?: true;
}

const GIS_SRC = "https://accounts.google.com/gsi/client";

/** The slice of Google Identity Services this app uses. */
export interface GoogleAccountsId {
  initialize(cfg: {
    client_id: string;
    callback: (resp: { credential: string }) => void;
    nonce?: string;
    ux_mode?: "popup" | "redirect";
    auto_select?: boolean;
    itp_support?: boolean;
    use_fedcm_for_prompt?: boolean;
  }): void;
  renderButton(parent: HTMLElement, options: Record<string, string | number>): void;
  disableAutoSelect(): void;
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleAccountsId } };
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<{ status: number; body: T | null }> {
  const resp = await fetch(path, { credentials: "same-origin", ...init });
  let body: T | null = null;
  try {
    body = (await resp.json()) as T;
  } catch {
    body = null;
  }
  return { status: resp.status, body };
}

/** Thrown when `/api/auth/config` could not answer: a network failure or a
 *  5xx. A server without the route (404) has no sign-in, which is "off". */
export class AuthConfigUnavailable extends Error {}

export async function fetchAuthConfig(): Promise<{ google_client_id: string | null; device_accounts?: true }> {
  let got: { status: number; body: { google_client_id: string | null; device_accounts?: unknown } | null };
  try {
    got = await api<{ google_client_id: string | null; device_accounts?: unknown }>("/api/auth/config");
  } catch {
    throw new AuthConfigUnavailable("no connection");
  }
  const { status, body } = got;
  if (status >= 500) throw new AuthConfigUnavailable(`status ${status}`);
  if (status !== 200 || !body) return { google_client_id: null };
  return { google_client_id: body.google_client_id ?? null, ...(body.device_accounts === true ? { device_accounts: true as const } : {}) };
}

export async function fetchMe(): Promise<AuthUser | null> {
  const { status, body } = await api<AuthUser>("/api/me");
  return status === 200 && body ? toUser(body) : null;
}

export const DISPLAY_NAME_MAX = 20;

/** The server's refusal codes (`PATCH /api/me` → 400) and what to tell the
 *  player, each read in the current language when it is looked up. */
export const NAME_MESSAGES: Record<string, string> = {
  get empty() { return t("home.nameEmpty"); },
  get too_long() { return t("home.nameTooLong", { n: DISPLAY_NAME_MAX }); },
  get control_chars() { return t("home.nameControl"); },
  get reserved() { return t("home.nameReserved"); },
  get not_allowed() { return t("home.nameNotAllowed"); },
  get not_a_string() { return t("home.nameEmpty"); },
  get taken() { return t("home.nameTaken"); },
};

const RESERVED = new Set(["bot", "system", "admin", "dealer", "moderator", "server"]);
const BOT_LIKE = /^bot\s*\d*$/;
// Control characters (every line break among them), surrogate halves on
// their own, private use, and the line and paragraph separators.
const FORBIDDEN = /[\p{Cc}\p{Co}\p{Zl}\p{Zp}]|\p{Cs}/u;

export type NameCheck = { ok: true; value: string } | { ok: false; reason: string; message: string };

/** The same rules the server applies, so the form can explain a refusal
 *  before the round trip; the server remains the authority. */
export function checkDisplayName(raw: string): NameCheck {
  const fail = (reason: string): NameCheck => ({ ok: false, reason, message: NAME_MESSAGES[reason] });
  if (FORBIDDEN.test(raw)) return fail("control_chars");
  const value = raw.trim().split(/\s+/).filter(Boolean).join(" ");
  if (!value) return fail("empty");
  if (value.length > DISPLAY_NAME_MAX) return fail("too_long");
  const folded = value.toLowerCase();
  if (RESERVED.has(folded) || BOT_LIKE.test(folded)) return fail("reserved");
  return { ok: true, value };
}

export class NameRejected extends Error {
  reason: string;

  constructor(reason: string) {
    super(NAME_MESSAGES[reason] ?? t("home.nameNotSaved", { code: reason }));
    this.reason = reason;
  }
}

/** `PATCH /api/me`: set the display name, or clear it with null. Resolves
 *  with the updated account; rejects with `NameRejected` on a 400. */
export async function updateDisplayName(name: string | null): Promise<AuthUser> {
  const { status, body } = await api<AuthUser & { detail?: string }>("/api/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: name }),
  });
  if (status === 400 && body?.detail) throw new NameRejected(body.detail);
  if (status === 429) throw new Error(t("home.tooManyChanges"));
  if (status !== 200 || !body) throw new Error(t("home.nameNotSavedStatus", { n: status }));
  return toUser(body);
}

/** What a signed-in player is called by default. */
export function effectiveName(user: AuthUser | null | undefined): string {
  if (!user) return "";
  return user.name_shown || firstName(user.name);
}

/** A sign-in from this app's device account whose Apple or Google identity
 *  already has an account (409 `account_exists`): nothing changed, and the
 *  same sign-in repeated with `confirm` gives way to that account. */
export class AccountExists extends Error {
  /** The other account's shown name. */
  holder: string;

  constructor(holder: string) {
    super(t("home.switchTitle", { name: holder }));
    this.holder = holder;
  }
}

type SignInBody = AuthUser & { detail?: unknown; device_token?: string };

/** A provider sign-in's answer: the account, after a merge's new device
 *  credential is in the Keychain; a refusal, the conflict among them, throws. */
async function signInAnswer(status: number, body: SignInBody | null): Promise<AuthUser> {
  const detail = body?.detail as { code?: unknown; name?: unknown } | string | undefined;
  if (status === 409 && typeof detail === "object" && detail?.code === "account_exists") {
    throw new AccountExists(typeof detail.name === "string" && detail.name ? detail.name : t("home.holderFallback"));
  }
  if (status !== 200 || !body) {
    throw new Error(typeof detail === "string" ? detail : t("home.signInFailedStatus", { n: status }));
  }
  if (typeof body.device_token === "string" && body.device_token && deviceAccountsApply()) {
    await keepDeviceSecret(body.device_token);
  }
  return toUser(body);
}

export async function loginWithGoogle(credential: string, nonce: string, confirm = false): Promise<AuthUser> {
  const { status, body } = await api<SignInBody>("/api/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(confirm ? { credential, nonce, confirm } : { credential, nonce }),
  });
  return signInAnswer(status, body);
}

/** What the app posts after Apple's native sheet: the identity token, the raw
 *  nonce whose SHA-256 hex the sheet put into it, the authorization code the
 *  server exchanges (to revoke the grant when the account is deleted), and
 *  the name Apple sends only on the first authorization. */
export interface AppleLogin {
  identityToken: string;
  nonce: string;
  authorizationCode: string | null;
  givenName: string | null;
  familyName: string | null;
}

export async function loginWithApple(login: AppleLogin, confirm = false): Promise<AuthUser> {
  const { status, body } = await api<SignInBody>("/api/auth/apple", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      identity_token: login.identityToken,
      nonce: login.nonce,
      authorization_code: login.authorizationCode,
      given_name: login.givenName,
      family_name: login.familyName,
      ...(confirm ? { confirm } : {}),
    }),
  });
  return signInAnswer(status, body);
}

/** Revoke the session. Resolves only when the server confirmed it; a 5xx or
 *  a network failure throws, because the HttpOnly cookie is then still live
 *  and the page must not claim otherwise. */
export async function logout(deviceToken: string | null = null): Promise<void> {
  let status: number;
  try {
    ({ status } = await api("/api/auth/logout", deviceToken
      ? { method: "POST", headers: { Authorization: `Device ${deviceToken}` } }
      : { method: "POST" }));
  } catch {
    throw new Error(t("home.signOutOffline"));
  }
  if (status !== 200) throw new Error(t("home.signOutStatus", { n: status }));
}

/** `DELETE /api/me`: remove the account for good. Resolves once the server
 *  answered 204 (it also clears the session cookie); throws otherwise, so
 *  the page keeps the account signed in and says why. */
export async function deleteAccount(): Promise<void> {
  let status: number;
  try {
    ({ status } = await api("/api/me", { method: "DELETE" }));
  } catch {
    throw new Error(t("home.deleteOffline"));
  }
  if (status === 429) throw new Error(t("home.tooManyChanges"));
  if (status !== 204) throw new Error(t("home.deleteStatus", { n: status }));
}

/** The display-name default for a signed-in player who typed none. */
export function firstName(name: string | null | undefined): string {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return "";
  return trimmed.split(/\s+/)[0].slice(0, 20);
}

/** A fresh nonce for one sign-in: Google puts it in the token, the server
 *  checks it matches what this page posted, so a token minted for another
 *  page cannot be posted here. */
export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The lowercase SHA-256 hex of a nonce: what Apple's sheet is given, so the
 *  raw nonce stays with the page until it is posted. */
export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Device accounts: in the iOS app only, an account with no provider, made
 *  at the first online Play, Duo or Join and held by a secret in the
 *  Keychain, so a reinstall gets it back. The website never asks for one. */
export function deviceAccountsApply(): boolean {
  if (!isNative()) return false;
  try {
    const cap = (window as unknown as { Capacitor?: { getPlatform?: () => string } }).Capacitor;
    return cap?.getPlatform?.() === "ios";
  } catch {
    return false;
  }
}

/** Whether a device account can be made here: the app on iOS, with a shell
 *  that carries the Keychain plugin (an older build plays as a guest). */
export function deviceAccountsAvailable(): boolean {
  return deviceAccountsApply() && keychainAvailable();
}

/** A signed-in account with no Apple or Google identity: one the app made. */
export function isUnlinkedDevice(user: AuthUser | null | undefined): boolean {
  return !!user && user.linked === false && deviceAccountsApply();
}

/** The app before its first online Play, with device accounts on: the
 *  player is not yet an account, but is about to be one, so neither the
 *  guest line nor a rating shows. */
export function deviceAccountPending(state: AuthState): boolean {
  return state.deviceAccounts === true && (state.status === "out" || state.status === "off");
}

export const CLIENT_HEADER = "X-Shengji-Client";
export const IOS_APP_CLIENT = "ios-app";

/** `POST /api/auth/device`: with a token, sign in as the account holding
 *  it; without, make a new account, whose token comes back this once, asking
 *  for `name` (the guest's chosen name) when given; the server keeps it only
 *  when it passes the display-name checks and is free. `lang`, a Chinese
 *  interface ("zh-Hans", "zh-Hant"), has the server draw a Chinese name
 *  otherwise. Status 0 is no connection. 404 means the server has device
 *  accounts off, and 429 too many attempts: either way the app plays as a
 *  guest. */
export async function deviceAuth(token: string | null, name: string | null = null,
                                 lang: string | null = null): Promise<{ status: number; user: AuthUser | null; token: string | null }> {
  const headers: Record<string, string> = { [CLIENT_HEADER]: IOS_APP_CLIENT };
  if (token) headers.Authorization = `Device ${token}`;
  const init: RequestInit = { method: "POST", headers };
  if (!token && (name || lang)) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify({ ...(name ? { name } : {}), ...(lang ? { lang } : {}) });
  }
  let got: { status: number; body: (Partial<AuthUser> & { user?: AuthUser; token?: string }) | null };
  try {
    got = await api("/api/auth/device", init);
  } catch {
    return { status: 0, user: null, token: null };
  }
  const user = got.status === 200 && got.body?.user ? toUser(got.body.user) : null;
  const issued = got.status === 200 && typeof got.body?.token === "string" ? got.body.token : null;
  return { status: user ? 200 : got.status === 200 ? 0 : got.status, user, token: issued };
}

/** At app launch: sign in with the Keychain's secret. A 401 means the
 *  account is gone (deleted, or purged), so the secret goes too and the
 *  next online Play makes a fresh one; any other failure keeps it for the
 *  next launch. Null when there is no secret or no sign-in. */
export async function reauthFromKeychain(): Promise<AuthUser | null> {
  if (!(await settleKeychain())) return null;
  let token: string | null = null;
  try {
    token = await keychainGet();
  } catch {
    return null;
  }
  if (!token) return null;
  const got = await deviceAuth(token);
  if (got.status === 401) await forgetDeviceSecret();
  telemetry.deviceAccount(got.user ? "restored" : "fell_back_guest");
  return got.user;
}

// Signing in and out, by any path (the device's account, Apple or Google, a
// launch's restore, a sign-out), takes turns: each one's request, the
// session cookie its answer sets, the state here and the socket replaced for
// started for it all finish before the next one starts, so the identity asked for last
// is the one the cookie, this page and the socket all carry.
let identityChain: Promise<unknown> = Promise.resolve();

let turnsPending = 0;

export function identityTurn<T>(op: () => Promise<T>): Promise<T> {
  turnsPending += 1;
  const run = identityChain.then(op, op);
  identityChain = run.catch(() => undefined);
  void identityChain.then(() => { turnsPending -= 1; });
  return run;
}

/** Whether a sign-in or sign-out is under way or waiting its turn: an
 *  online action waits behind it rather than going on the socket it is
 *  about to replace. */
export function identityChanging(): boolean {
  return turnsPending > 0;
}

// Every credential operation (a Keychain write or removal, and a sign-out's
// revocation with its removal) runs on one queue, in the order asked for, so
// a later operation always sees the earlier one finished: a merge's secret
// cannot land after the sign-out that removed it.
let credentials: Promise<unknown> = Promise.resolve();

function onCredentialQueue<T>(op: () => Promise<T>): Promise<T> {
  const run = credentials.then(op, op);
  credentials = run.catch(() => undefined);
  return run;
}

// A secret the Keychain refused, held for this session only (never written
// to the page's storage): its account stays signed in on the cookie, the
// Keychain is asked again before it is next used, and no new device account
// is made while it is outstanding.
let unsaved: string | null = null;

async function setTwice(token: string): Promise<boolean> {
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

async function removeTwice(): Promise<boolean> {
  for (let i = 0; i < 2; i += 1) {
    try {
      await keychainRemove();
      return true;
    } catch {
      /* tried again once */
    }
  }
  return false;
}

/** Keeps a secret the server issued: in the Keychain, or, when it refuses
 *  twice, in memory for this session. True when the Keychain has it. */
export function keepDeviceSecret(token: string): Promise<boolean> {
  return onCredentialQueue(async () => {
    const saved = await setTwice(token);
    unsaved = saved ? null : token;
    return saved;
  });
}

/** Whether a secret is still waiting for the Keychain: while it is, no new
 *  device account is made. */
export function deviceSecretOutstanding(): boolean {
  return unsaved !== null;
}

/** Offers the Keychain a secret it refused earlier this session. False
 *  while it is still refused: the Keychain lacks the secret this session's
 *  account needs, so no sign-in reads it and no other account is made. */
export function settleKeychain(): Promise<boolean> {
  return onCredentialQueue(async () => {
    if (unsaved !== null) {
      if (!(await setTwice(unsaved))) return false;
      unsaved = null;
    }
    return true;
  });
}

/** A sign-out's credential work in the app, on the credential queue. It
 *  reports success only once the secret is confirmed gone from this device
 *  and the server has ended the session; otherwise it throws "Sign-out
 *  failed. Try again.", the account stays signed in, and tapping again
 *  retries. The secret sent is the newest issued: one the Keychain refused
 *  (held in memory) over whatever the Keychain still has. If the server
 *  does not confirm after the removal, the secret goes back to the
 *  Keychain, or, if it refuses, stays in memory for the retry. */
async function revokeHere(): Promise<void> {
  const refused = new Error(t("home.signOutFailed"));
  let device: string | null = unsaved;
  if (device === null) {
    try {
      device = await keychainGet();
    } catch {
      throw refused;
    }
  }
  if (!(await removeTwice())) throw refused;
  try {
    await logout(device);
  } catch {
    if (device) unsaved = (await setTwice(device)) ? null : device;
    throw refused;
  }
  unsaved = null;
}

/** Removes the Keychain's secret; a failure leaves it, and the server then
 *  refuses it on the next launch. */
export function forgetDeviceSecret(): Promise<void> {
  return onCredentialQueue(async () => {
    unsaved = null;
    try {
      await keychainRemove();
    } catch {
      /* refused by the Keychain: the next re-auth's 401 tries again */
    }
  });
}

/** Resolves at the next time the socket opens, not counting its status now. */
function nextOpen(): Promise<void> {
  return new Promise((resolve) => {
    let armed = false;
    const stop = conn.subscribeStatus?.((status) => {
      if (armed && status === "open") {
        stop?.();
        resolve();
      }
    });
    if (!stop) resolve();
    armed = true;
  });
}

let gisLoading: Promise<GoogleAccountsId> | null = null;

/** Load the GIS script once (only ever called when a client id exists). */
export function loadGis(): Promise<GoogleAccountsId> {
  const present = window.google?.accounts?.id;
  if (present) return Promise.resolve(present);
  if (gisLoading) return gisLoading;
  gisLoading = new Promise<GoogleAccountsId>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      const id = window.google?.accounts?.id;
      if (id) resolve(id);
      else reject(new Error(t("home.gisInit")));
    };
    script.onerror = () => {
      gisLoading = null;
      script.remove();
      reject(new Error(t("home.gisLoad")));
    };
    document.head.appendChild(script);
  });
  return gisLoading;
}

type Listener = (state: AuthState) => void;

class AuthStore {
  state: AuthState = { status: "loading", clientId: null, user: null };
  private listeners = new Set<Listener>();
  private initRun: Promise<void> | null = null;
  private reopen: Promise<void> | null = null;

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private set(next: Partial<AuthState>): void {
    this.state = { ...this.state, ...next };
    for (const fn of this.listeners) fn(this.state);
  }

  /** Idempotent: ask the server whether sign-in exists and who we are. A
   *  server without sign-in reads as "off"; a server that could not be
   *  reached reads as "error", so the sign-in controls stay in place,
   *  unavailable, instead of vanishing. */
  init(): Promise<void> {
    if (this.initRun) return this.initRun;
    // in the app a launch's restore is a sign-in like any other: it takes its turn
    this.initRun = deviceAccountsApply() ? identityTurn(() => this.load()) : this.load();
    return this.initRun;
  }

  private async load(): Promise<void> {
    try {
      const cfg = await fetchAuthConfig();
      // the app's device account signs in again at every launch
      const relaunched = deviceAccountsApply() ? await reauthFromKeychain() : null;
      const device = cfg.device_accounts === true && deviceAccountsAvailable() ? { deviceAccounts: true as const } : {};
      if (!cfg.google_client_id) {
        this.set(relaunched ? { status: "in", clientId: null, user: relaunched, ...device }
          : { status: "off", clientId: null, user: null, ...device });
      } else {
        const user = relaunched ?? await fetchMe();
        this.set({ status: user ? "in" : "out", clientId: cfg.google_client_id, user, ...device });
      }
      // a socket opened before the restore carries the guest handshake
      if (relaunched) this.replaceSocket();
    } catch {
      this.set({ status: "error", clientId: null, user: null });
    }
  }

  /** A login the server confirmed (the cookie is set). The open socket
   *  still carries the guest handshake, so it is replaced. */
  signedIn(user: AuthUser): void {
    forgetPrivateSession();
    this.set({ status: "in", user });
    this.replaceSocket();
  }

  /** Replace the socket so its handshake carries the current session. In
   *  the app, `settled` waits for the replacement to open, so a Play is
   *  never sent on the socket of the identity before. */
  private replaceSocket(): void {
    // what was buffered (a sign-in's own steps among it) goes on the socket
    // of the identity it happened under, or nowhere
    telemetry.handover();
    if (deviceAccountsApply()) {
      const next = nextOpen();
      this.reopen = next;
      void next.then(() => { if (this.reopen === next) this.reopen = null; });
    }
    conn.reconnect();
  }

  /** A socket replaced for a sign-in has not opened yet. */
  isReopening(): boolean {
    return this.reopen !== null;
  }

  /** Resolves once sign-in is known and the socket carries it: after
   *  `init`, and after the socket a sign-in replaced has opened. */
  async settled(): Promise<void> {
    if (this.initRun) await this.initRun;
    while (this.reopen) await this.reopen;
  }


  /** The server refused to make a device account (device accounts off):
   *  the app is a guest exactly as on any other day. */
  noDeviceAccounts(): void {
    if (this.state.deviceAccounts) {
      const { deviceAccounts: _gone, ...rest } = this.state;
      this.state = rest;
      for (const fn of this.listeners) fn(this.state);
    }
  }

  /** The account changed (a saved display name): every subscriber follows. */
  updated(user: AuthUser): void {
    if (this.state.status === "in") this.set({ user });
  }

  /** Sign out. Rejects, keeping the signed-in state, when the server did not
   *  confirm the revocation; the caller shows the error and may retry. On
   *  success the socket is replaced so the seat stops carrying the account. */
  async signOut(): Promise<void> {
    if (!deviceAccountsApply()) {
      await logout();
      this.signedOut();
      return;
    }
    await identityTurn(async () => {
      await onCredentialQueue(() => revokeHere());
      this.signedOut();
    });
  }

  private signedOut(): void {
    try {
      window.google?.accounts?.id?.disableAutoSelect();
    } catch {
      /* GIS not loaded */
    }
    void nativeGoogleSignOut();
    void nativeAppleSignOut(false);
    forgetPrivateSession();
    this.set({ status: "out", user: null });
    this.replaceSocket();
  }

  /** The server deleted the account and cleared its cookie: forget it here
   *  the way a confirmed sign-out does. */
  deleted(): void {
    if (deviceAccountsApply()) void forgetDeviceSecret();
    try {
      window.google?.accounts?.id?.disableAutoSelect();
    } catch {
      /* GIS not loaded */
    }
    void nativeGoogleSignOut();
    void nativeAppleSignOut(true);
    forgetPrivateSession();
    this.set({ status: "out", user: null });
    this.replaceSocket();
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    identityChain = Promise.resolve();
    turnsPending = 0;
    credentials = Promise.resolve();
    unsaved = null;
    this.initRun = null;
    this.reopen = null;
    this.state = { status: "loading", clientId: null, user: null };
    gisLoading = null;
  }
}

export const auth = new AuthStore();

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(auth.state);
  useEffect(() => auth.subscribe(setState), []);
  return state;
}
