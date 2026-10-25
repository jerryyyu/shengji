// Optional Google sign-in. The server decides whether the feature exists
// (`/api/auth/config` carries the public client id or null); when it is off
// nothing here loads a script, renders a button or sets a cookie, and guest
// play is untouched. The session itself is an HttpOnly cookie the browser
// sends on its own, to `/api/*` and on the `/ws` handshake alike.

import { useEffect, useState } from "react";
import { conn } from "./ws";

export interface AuthUser {
  /** The Google profile name. */
  name: string;
  email: string;
  picture: string | null;
  /** The name the player chose for this account; null means none chosen. */
  display_name: string | null;
  /** What the player is called: `display_name`, else the Google first name. */
  name_shown: string;
}

/** The `/api/me` body as the server sends it; older servers lack the two
 *  display-name fields, so both are filled in here. */
function toUser(body: Partial<AuthUser> & { name: string; email: string }): AuthUser {
  return {
    name: body.name,
    email: body.email,
    picture: body.picture ?? null,
    display_name: body.display_name ?? null,
    name_shown: body.name_shown ?? firstName(body.name),
  };
}

export type AuthStatus = "loading" | "off" | "out" | "in";

export interface AuthState {
  status: AuthStatus;
  clientId: string | null;
  user: AuthUser | null;
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

export async function fetchAuthConfig(): Promise<{ google_client_id: string | null }> {
  const { status, body } = await api<{ google_client_id: string | null }>("/api/auth/config");
  if (status !== 200 || !body) return { google_client_id: null };
  return { google_client_id: body.google_client_id ?? null };
}

export async function fetchMe(): Promise<AuthUser | null> {
  const { status, body } = await api<AuthUser>("/api/me");
  return status === 200 && body ? toUser(body) : null;
}

export const DISPLAY_NAME_MAX = 20;

/** The server's refusal codes (`PATCH /api/me` → 400) and what to tell the player. */
export const NAME_MESSAGES: Record<string, string> = {
  empty: "Enter a name.",
  too_long: `Up to ${DISPLAY_NAME_MAX} characters.`,
  control_chars: "No line breaks or control characters.",
  reserved: "That name is reserved for bots and the system.",
  not_allowed: "That name is not allowed.",
  not_a_string: "Enter a name.",
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
    super(NAME_MESSAGES[reason] ?? `Could not save the name (${reason}).`);
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
  if (status === 429) throw new Error("Too many changes; try again in a minute.");
  if (status !== 200 || !body) throw new Error(`Could not save the name (${status})`);
  return toUser(body);
}

/** What a signed-in player is called by default. */
export function effectiveName(user: AuthUser | null | undefined): string {
  if (!user) return "";
  return user.name_shown || firstName(user.name);
}

export async function loginWithGoogle(credential: string, nonce: string): Promise<AuthUser> {
  const { status, body } = await api<AuthUser & { detail?: string }>("/api/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential, nonce }),
  });
  if (status !== 200 || !body) {
    throw new Error(body?.detail ?? `Sign-in failed (${status})`);
  }
  return toUser(body);
}

/** Revoke the session. Resolves only when the server confirmed it; a 5xx or
 *  a network failure throws, because the HttpOnly cookie is then still live
 *  and the page must not claim otherwise. */
export async function logout(): Promise<void> {
  let status: number;
  try {
    ({ status } = await api("/api/auth/logout", { method: "POST" }));
  } catch {
    throw new Error("Sign-out failed: no connection. Try again.");
  }
  if (status !== 200) throw new Error(`Sign-out failed (${status}). Try again.`);
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
      else reject(new Error("Google Identity Services did not initialise"));
    };
    script.onerror = () => {
      gisLoading = null;
      script.remove();
      reject(new Error("Could not load Google sign-in"));
    };
    document.head.appendChild(script);
  });
  return gisLoading;
}

type Listener = (state: AuthState) => void;

class AuthStore {
  state: AuthState = { status: "loading", clientId: null, user: null };
  private listeners = new Set<Listener>();
  private started = false;

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
   *  network failure reads as "off": the lobby then looks exactly like a
   *  deployment without the feature. */
  async init(): Promise<void> {
    if (this.started) return;
    this.started = true;
    try {
      const cfg = await fetchAuthConfig();
      if (!cfg.google_client_id) {
        this.set({ status: "off", clientId: null, user: null });
        return;
      }
      const user = await fetchMe();
      this.set({ status: user ? "in" : "out", clientId: cfg.google_client_id, user });
    } catch {
      this.set({ status: "off", clientId: null, user: null });
    }
  }

  /** A login the server confirmed (the cookie is set). The open socket
   *  still carries the guest handshake, so it is replaced. */
  signedIn(user: AuthUser): void {
    this.set({ status: "in", user });
    conn.reconnect();
  }

  /** The account changed (a saved display name): every subscriber follows. */
  updated(user: AuthUser): void {
    if (this.state.status === "in") this.set({ user });
  }

  /** Sign out. Rejects, keeping the signed-in state, when the server did not
   *  confirm the revocation; the caller shows the error and may retry. On
   *  success the socket is replaced so the seat stops carrying the account. */
  async signOut(): Promise<void> {
    await logout();
    try {
      window.google?.accounts?.id?.disableAutoSelect();
    } catch {
      /* GIS not loaded */
    }
    this.set({ status: "out", user: null });
    conn.reconnect();
  }

  /** Test seam: forget everything, as a fresh page would. */
  reset(): void {
    this.started = false;
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
