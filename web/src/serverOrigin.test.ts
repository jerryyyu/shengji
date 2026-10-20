/**
 * The server-origin rules. The web build must keep its historical URLs
 * exactly (same-origin in production, :8000 in dev); only an explicit
 * VITE_SERVER_ORIGIN, as the Capacitor build sets, redirects the socket.
 */
import { describe, expect, it } from "vitest";

import { configuredOrigin, httpBase, wsUrl } from "./serverOrigin";

const https = { protocol: "https:", hostname: "shengji.fly.dev", host: "shengji.fly.dev" };
const http = { protocol: "http:", hostname: "192.168.1.9", host: "192.168.1.9:8000" };
const devPage = { protocol: "http:", hostname: "localhost", host: "localhost:5173" };

describe("without VITE_SERVER_ORIGIN (the web build)", () => {
  it("connects same-origin in production, wss behind https", () => {
    expect(wsUrl({ DEV: false }, https)).toBe("wss://shengji.fly.dev/ws");
    expect(wsUrl({ DEV: false }, http)).toBe("ws://192.168.1.9:8000/ws");
    expect(httpBase({ DEV: false }, https)).toBe("");
  });

  it("targets :8000 from the Vite dev server", () => {
    expect(wsUrl({ DEV: true }, devPage)).toBe("ws://localhost:8000/ws");
    expect(httpBase({ DEV: true }, devPage)).toBe("http://localhost:8000");
  });

  it("treats an empty or blank value as unset", () => {
    expect(configuredOrigin({ DEV: false, VITE_SERVER_ORIGIN: "" })).toBeNull();
    expect(configuredOrigin({ DEV: false, VITE_SERVER_ORIGIN: "  " })).toBeNull();
    expect(wsUrl({ DEV: false, VITE_SERVER_ORIGIN: "" }, https)).toBe("wss://shengji.fly.dev/ws");
  });
});

describe("with VITE_SERVER_ORIGIN (the native shell)", () => {
  const capacitor = { protocol: "capacitor:", hostname: "localhost", host: "localhost" };
  const env = { DEV: false, VITE_SERVER_ORIGIN: "https://shengji.fly.dev" };

  it("ignores the page origin and speaks wss to the configured host", () => {
    expect(wsUrl(env, capacitor)).toBe("wss://shengji.fly.dev/ws");
    expect(httpBase(env, capacitor)).toBe("https://shengji.fly.dev");
  });

  it("wins over the dev rule and tolerates a trailing slash", () => {
    const local = { DEV: true, VITE_SERVER_ORIGIN: "http://10.0.0.5:8000/" };
    expect(wsUrl(local, capacitor)).toBe("ws://10.0.0.5:8000/ws");
    expect(httpBase(local, capacitor)).toBe("http://10.0.0.5:8000");
  });

  it("refuses a value that is not a bare http(s) origin", () => {
    expect(() => configuredOrigin({ DEV: false, VITE_SERVER_ORIGIN: "shengji.fly.dev" })).toThrow();
    expect(() => configuredOrigin({ DEV: false, VITE_SERVER_ORIGIN: "https://x.dev/ws" })).toThrow();
  });
});
