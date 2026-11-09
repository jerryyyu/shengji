import type { CapacitorConfig } from "@capacitor/cli";

// The iOS shell loads the live site rather than the bundled build. WKWebView
// cannot serve bundled assets from an https origin (Capacitor's iosScheme may
// not be http/https), so a bundled page would be cross-origin to the game
// server and its session cookie would be a blocked third-party cookie. Loading
// https://shengji.fly.dev keeps fetch, the WebSocket and cookies same-origin,
// exactly as in a browser. webDir is still required by `cap sync`.
//
// CAP_SERVER_URL points a local build at a test server instead, for example
// `CAP_SERVER_URL=http://192.168.1.20:8765 npx cap sync ios`. Cleartext is
// allowed only for such an http override; the committed default never changes.
const serverUrl = process.env.CAP_SERVER_URL || "https://shengji.fly.dev";

// The felt's edge colour: the launch screen, the splash and the WebView behind
// the first paint all match the lobby, so launch shows no black or blank frame.
const FELT = "#123a26";

const config: CapacitorConfig = {
  appId: "org.shengji.app",
  appName: "Sheng Ji",
  webDir: "dist",
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith("http://"),
  },
  ios: {
    contentInset: "never",
    backgroundColor: FELT,
    limitsNavigationsToAppBoundDomains: false,
    // no outer scroll view behind the page, and no link previews on a long press
    scrollEnabled: false,
    allowsLinkPreview: false,
  },
  plugins: {
    SplashScreen: {
      // The page hides the splash on its first paint (src/native.ts); this is
      // the fallback for a page that never does.
      launchShowDuration: 10000,
      launchAutoHide: true,
      launchFadeOutDuration: 200,
      backgroundColor: FELT,
      showSpinner: false,
    },
  },
};

export default config;
