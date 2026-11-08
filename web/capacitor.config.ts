import type { CapacitorConfig } from "@capacitor/cli";

// The iOS shell loads the live site rather than the bundled build. WKWebView
// cannot serve bundled assets from an https origin (Capacitor's iosScheme may
// not be http/https), so a bundled page would be cross-origin to the game
// server and its session cookie would be a blocked third-party cookie. Loading
// https://shengji.fly.dev keeps fetch, the WebSocket and cookies same-origin,
// exactly as in a browser. webDir is still required by `cap sync`.
const config: CapacitorConfig = {
  appId: "org.shengji.app",
  appName: "Sheng Ji",
  webDir: "dist",
  server: {
    url: "https://shengji.fly.dev",
    cleartext: false,
  },
  ios: {
    contentInset: "never",
    backgroundColor: "#14171e",
    limitsNavigationsToAppBoundDomains: false,
  },
};

export default config;
