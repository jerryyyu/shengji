import type { CapacitorConfig } from "@capacitor/cli";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The iOS shell loads the live site rather than the bundled build. WKWebView
// cannot serve bundled assets from an https origin (Capacitor's iosScheme may
// not be http/https), so a bundled page would be cross-origin to the game
// server and its session cookie would be a blocked third-party cookie. Loading
// https://playshengji.com keeps fetch, the WebSocket and cookies same-origin,
// exactly as in a browser. webDir is still required by `cap sync`. Builds up
// to 1.0.1 loaded the Fly host (OriginMove.previousHost), which the server
// still answers; the shell moves an upgraded install's cookies and
// localStorage from that origin once (ios/App/App/OriginMove.swift).
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
const serverUrl = process.env.CAP_SERVER_URL || "https://playshengji.com";

// The lobby's chrome colour (--chrome in src/index.css): the launch screen, the
// splash and the WebView behind the first paint all match the lobby the app
// opens on, so launch shows no black, blank or off-colour frame. The launch
// storyboard and the Splash image asset carry the same colour.
const CHROME = "#14171e";

// The app's version (MARKETING_VERSION, the bundle's CFBundleShortVersionString)
// rides in the WebView's User-Agent as `ShengjiApp/<version>`, so the server
// can stamp it on telemetry (server/shengji/api/telemetry.py, app_version).
// The page itself cannot know it: it is the live site, the same for every
// app version. Capacitor's appendUserAgent is a fixed string in the synced
// capacitor.config.json, so it is read here from the Xcode project at
// `cap sync` time; a version bump needs a sync before the build, as the
// bundled page already does. Every configuration must carry the same
// version, at most four digits a part as the server keeps, or the sync stops.
export const APP_UA_PRODUCT = "ShengjiApp";

export function marketingVersion(pbxproj: string): string {
  const versions = new Set([...pbxproj.matchAll(/^\s*MARKETING_VERSION = "?([^";]+)"?;$/gm)].map((m) => m[1]));
  const [version] = versions;
  if (versions.size !== 1 || !/^\d{1,4}\.\d{1,4}(\.\d{1,4})?$/.test(version)) {
    throw new Error(`capacitor.config.ts: expected one MARKETING_VERSION like 1.0.2, found ${[...versions].join(", ") || "none"}`);
  }
  return version;
}

const here = typeof __dirname === "string" ? __dirname : process.cwd();
const appVersion = marketingVersion(
  readFileSync(join(here, "ios", "App", "App.xcodeproj", "project.pbxproj"), "utf8"));

const config: CapacitorConfig = {
  appId: "com.jerryyu.shengji",
  appName: "Sheng Ji",
  webDir: "dist",
  // Capacitor's bridge logs every plugin call's options and the first 256
  // characters of every result, natively and in the page console, whenever
  // logging is on (Debug builds by default). The Keychain plugin carries the
  // device credential through both, so bridge logging is off in every build.
  loggingBehavior: "none",
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith("http://"),
    errorPath: "index.html",
  },
  ios: {
    appendUserAgent: `${APP_UA_PRODUCT}/${appVersion}`,
    contentInset: "never",
    backgroundColor: CHROME,
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
    // "native" shrinks the WebView to the space above the keyboard, so the
    // focused field stays in view and the page is never shoved up past the top;
    // the tab bar steps aside while the keyboard is up (body.keyboard-open).
    Keyboard: {
      resize: "native",
    },
    SplashScreen: {
      // The page hides the splash on its first paint (src/native.ts); this is
      // the fallback for a page that never does.
      launchShowDuration: 10000,
      launchAutoHide: true,
      launchFadeOutDuration: 200,
      backgroundColor: CHROME,
      showSpinner: false,
    },
  },
};

export default config;
