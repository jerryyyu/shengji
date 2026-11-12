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
//
// Offline: when the live site cannot load (no network), the WebView loads
// `errorPath` from the bundled build at capacitor://localhost instead
// (Capacitor's WebViewDelegationHandler does so on a failed or failed
// provisional navigation, also with a remote server.url). That origin puts
// the client in offline mode: a local game against bots, no server.
const serverUrl = process.env.CAP_SERVER_URL || "https://shengji.fly.dev";

// The felt's edge colour: the launch screen, the splash and the WebView behind
// the first paint all match the lobby, so launch shows no black or blank frame.
const FELT = "#123a26";

const config: CapacitorConfig = {
  appId: "com.jerryyu.shengji",
  appName: "Sheng Ji",
  webDir: "dist",
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith("http://"),
    errorPath: "index.html",
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
    // Google sign-in runs natively in the app because Google refuses its web
    // sign-in inside an embedded WebView. Sign in with Apple uses the system's
    // AuthenticationServices (no SDK) and needs the applesignin entitlement in
    // App.entitlements. The plugin's sync hook drops the other SDKs from its
    // Swift package.
    SocialLogin: {
      providers: { google: true, apple: true, facebook: false, twitter: false },
      logLevel: 1,
    },
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
