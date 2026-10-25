// Optional Google sign-in. The server decides whether the feature exists
// (`/api/auth/config` carries the public client id or null); when it is off
// nothing here loads a script, renders a button or sets a cookie, and guest
// play is untouched. The session itself is an HttpOnly cookie the browser
// sends on its own, to `/api/*` and on the `/ws` handshake alike.

import { useEffect, useState } from "react";

export interface AuthUser {
  name: string;
  email: string;
  picture: string | null;
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
  return status === 200 && body ? body : null;
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
  return { name: body.name, email: body.email, picture: body.picture ?? null };
}

export async function logout(): Promise<void> {
  await api("/api/auth/logout", { method: "POST" });
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

  signedIn(user: AuthUser): void {
    this.set({ status: "in", user });
  }

  async signOut(): Promise<void> {
    try {
      await logout();
    } finally {
      try {
        window.google?.accounts?.id?.disableAutoSelect();
      } catch {
        /* GIS not loaded */
      }
      this.set({ status: "out", user: null });
    }
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
