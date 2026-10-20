# iOS shell (Capacitor) and the installable web app

The same `web/` client ships three ways:

| how | page origin | server |
|---|---|---|
| browser at https://shengji.fly.dev | same-origin | same-origin (`/ws`) |
| Add to Home Screen (PWA) | same-origin, standalone window | same-origin |
| Capacitor iOS app (`web/ios/`) | `capacitor://localhost`, bundled `dist/` | `VITE_SERVER_ORIGIN` baked in at build time |

Nothing is cached by a service worker: the game is live state over one
WebSocket and a stale shell would be worse than a reload. There is no offline
page either; the lobby already shows the connection status.

## What is in the tree

- `src/serverOrigin.ts`: the one place that decides the socket URL and the
  HTTP base. Unset `VITE_SERVER_ORIGIN` keeps the historical rules (same-origin
  in production, `:8000` under `npm run dev`); set, it wins. Tests cover both.
- `public/manifest.webmanifest`, `public/icons/`: the PWA manifest and icons
  (`icon.svg` is the source; the PNGs are `qlmanage -t -s <size>` renders of it).
- `index.html`: manifest link, `apple-touch-icon`, `apple-mobile-web-app-*`,
  `theme-color`. The layout already pads every pinned edge with
  `env(safe-area-inset-*)`, which standalone mode and the shell both need.
- `capacitor.config.ts`: `appId` **`com.jerryyu.shengji`** (a placeholder:
  change it before the first upload, it is permanent afterwards), `appName`
  "Sheng Ji", `webDir` `dist`.
- `ios/`: the Xcode project `npx cap add ios` generated (Capacitor 8, Swift
  Package Manager, no CocoaPods). The app icon and launch image in
  `ios/App/App/Assets.xcassets` are flattened renders of `public/icons/icon.svg`
  and `ios-art/splash.svg`.
- `src/haptics.ts`: one tap when the turn arrives, native only; a browser
  never loads the plugin.
- `server/shengji/api/server.py`: a GET-only CORS allowlist for
  `capacitor://localhost` and `http://localhost`. The WebSocket endpoint checks
  no Origin, so play needs nothing from this; the allowlist only lets the shell
  read `/healthz` and the token-gated `/debug/xray`.

Build for the shell from `web/`:

```sh
npm run build:ios      # VITE_SERVER_ORIGIN=https://shengji.fly.dev npm run build && cap sync ios
npx cap open ios       # needs Xcode
```

`cap sync ios` copies `dist/` into `ios/App/App/public` (git-ignored) and
regenerates `ios/App/CapApp-SPM/Package.swift` from the installed plugins. Both
`cap add ios` and `cap sync ios` ran on the Mini with only the Command Line
Tools installed; nothing below has been compiled or launched yet.

## Remaining steps (need an Apple account and Xcode)

1. **Apple Developer Program**, developer.apple.com/programs, USD 99/year.
   *Individual* enrolls in minutes with an Apple ID and shows "Jerry Yu" as the
   seller; *Organization* needs a D-U-N-S number and a legal entity and shows
   the company name. Individual is the fit unless a company should own the app.
   Free Apple IDs can run on a cable-connected device for 7 days at a time but
   cannot use TestFlight or submit.

2. **Xcode** (App Store, ~12 GB download, ~35 GB with the iOS platform and one
   simulator). The Mini has about 35 GB free and runs training; install on the
   Air instead. The Air needs the repo checked out, `cd web && npm ci`, and no
   CocoaPods (the project uses SPM). Open Xcode once so it installs the
   components it asks for, then `xcode-select -s /Applications/Xcode.app`.

3. **Build and open**: `npm run build:ios && npx cap open ios`. In Xcode,
   target *App* → *Signing & Capabilities* → tick *Automatically manage
   signing* and pick the team from step 1. Change the bundle identifier there
   or in `capacitor.config.ts` if `com.jerryyu.shengji` is not the final one
   (keep the two equal; `cap sync` does not rewrite the Xcode project's id).

4. **Run on a device**: plug in the phone, trust the Mac on it, select it as
   the run destination, press Run. First launch of a development build asks to
   trust the developer under *Settings → General → VPN & Device Management*.
   Check: the lobby connects (status chip), a room with three bots deals,
   the Mandarin clips play (they ship inside the app, no network), the phone
   taps once on the first "your turn", and rotating to landscape keeps the hand
   inside the safe area.

5. **TestFlight**: in App Store Connect create the app (name "Sheng Ji", the
   bundle id, primary language, SKU). In Xcode *Product → Archive*, then
   *Distribute App → TestFlight & App Store*. Internal testers (up to 100,
   any App Store Connect user) get the build with no review; external testers
   (up to 10,000, by link) after a one-time beta review. Bump
   `CFBundleShortVersionString` / build number in Xcode for each upload.

6. **App Store review**. Known risks, in order:
   - *Guideline 4.2 minimum functionality*: a web page in a wrapper is the
     classic rejection. The app must feel native: no browser chrome, a real
     icon and launch screen (present), safe areas respected (present), and
     ideally something the website cannot do: haptics on your turn (present),
     and push notifications for "your turn" / "a friend joined" are the usual
     argument winner. Say in the review notes that the game logic, bots and
     multiplayer run on the server and that the app is the only way to play
     with native notifications and haptics.
   - *Privacy policy URL* is mandatory. Nothing identifying is collected: a
     display name in `localStorage`, a per-room seat token, and the server's
     room logs (plays and chat, kept for bot training). A one-page policy
     saying exactly that, hosted on the Fly site (for example `/privacy`,
     a static file in `web/public/`), is enough. Fill the *App Privacy*
     questionnaire to match (data collected: "Other user content" — chat;
     "Gameplay content"; not linked to identity, not used for tracking).
   - *Sign in with Apple* is required only if the app offers another
     third-party login (Google, Facebook). There is no login today, so it
     does not apply; it becomes mandatory the day a social login is added.
   - *Age rating*: the questionnaire gives 4+ (cards, no gambling with real
     money, no user-generated content moderation needed beyond chat). Chat
     between players counts as user-generated content: Apple expects a way to
     report or block, so either keep chat room-scoped among invited players
     (say so in the notes) or add a report button before submission.
   - *Demo account*: not needed, there is no login; give the reviewer a room
     code flow in the notes ("tap Create, add three bots, Start").
   - *Export compliance*: the app uses only HTTPS/WSS, answer "uses standard
     encryption, exempt".

7. **Server capacity**. Production is one Fly machine (`fly.toml`:
   `shared-cpu-1x`, 512 MB, `min_machines_running = 1`) and rooms live in
   process memory: a deploy or restart drops every live game, and the bot's
   search budget is sized for a handful of concurrent tables. An App Store
   listing can bring more. Before promoting the app widely: watch
   `/healthz` (`rooms`, `activity`), consider a second size (shared-cpu-2x or
   1 GB) and a rolling-restart-friendly room store. Any change there is a
   deploy, which stays Jerry's call.

## Local device testing without the Fly server

Point the shell at a LAN dev server instead of production:

```sh
VITE_SERVER_ORIGIN=http://192.168.1.9:8000 npm run build && npx cap sync ios
```

iOS blocks plain `http://` and `ws://` by default (App Transport Security).
For a LAN test add `NSAllowsLocalNetworking` (or a
`NSExceptionDomains` entry for that host) under `NSAppTransportSecurity` in
`ios/App/App/Info.plist`, and remove it before an App Store build.

## Keeping the web build unchanged

`npm run build` with no `VITE_SERVER_ORIGIN` is byte-for-byte what the
Dockerfile ships: `serverOrigin.test.ts` pins the same-origin and `:8000`
rules, and the Capacitor packages are only reached through a dynamic import
that the web never executes.
