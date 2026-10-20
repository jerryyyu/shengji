// Where the game server lives, relative to the page. The web build is served
// by the server itself, so same-origin is the default; the Vite dev server
// targets :8000 directly. A native shell (Capacitor) loads the page from
// capacitor://localhost, where same-origin means nothing, so it is built with
// VITE_SERVER_ORIGIN naming the server, and only then does that origin win.

export interface OriginEnv {
  readonly DEV: boolean;
  readonly VITE_SERVER_ORIGIN?: string;
}

export interface OriginLocation {
  readonly protocol: string;
  readonly hostname: string;
  readonly host: string;
}

/** The configured server origin (`https://host[:port]`, no trailing slash),
 *  or null when the build is same-origin. */
export function configuredOrigin(env: OriginEnv): string | null {
  const raw = env.VITE_SERVER_ORIGIN?.trim();
  if (!raw) return null;
  if (!/^https?:\/\/[^/]+$/.test(raw.replace(/\/+$/, ""))) {
    throw new Error(`VITE_SERVER_ORIGIN must be an http(s) origin, got ${raw}`);
  }
  return raw.replace(/\/+$/, "");
}

/** WebSocket URL for the game socket. */
export function wsUrl(env: OriginEnv, loc: OriginLocation): string {
  const configured = configuredOrigin(env);
  if (configured !== null) {
    return `${configured.replace(/^http/, "ws")}/ws`;
  }
  if (env.DEV) {
    return `ws://${loc.hostname}:8000/ws`;
  }
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${loc.host}/ws`;
}

/** Prefix for HTTP requests to the server: "" when same-origin. Bundled
 *  assets (sounds, icons) never use it; they ship with the page. */
export function httpBase(env: OriginEnv, loc: OriginLocation): string {
  const configured = configuredOrigin(env);
  if (configured !== null) return configured;
  return env.DEV ? `http://${loc.hostname}:8000` : "";
}
