import type { CapacitorConfig } from "@capacitor/cli";

// The native shell wraps the SAME `dist/` the server serves, built with
// VITE_SERVER_ORIGIN pointing at the game server (`npm run build:ios`). The page
// origin inside the shell is capacitor://localhost, which is why the socket
// URL is configured at build time rather than derived from `location`.
const config: CapacitorConfig = {
  // Reverse-DNS bundle id; it becomes the App Store identity and cannot change
  // after the first upload, so settle it before the first TestFlight build.
  appId: "com.jerryyu.shengji",
  appName: "Sheng Ji",
  webDir: "dist",
  ios: {
    // The layout owns the safe areas via env(safe-area-inset-*); the web view
    // must not add its own content inset on top.
    contentInset: "never",
    // The table is dark; a light scroll bounce would flash white at the edges.
    backgroundColor: "#14171e",
    allowsLinkPreview: false,
  },
};

export default config;
