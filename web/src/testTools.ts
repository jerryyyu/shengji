// Whether this build may carry the test tools: the nearby soak (Autoplay,
// Chaos, its driver and summary), the log file's rows and upload, the hidden
// switch, the device test's log pane, and the offline autoplay. The page the
// App Store archive bundles is built with VITE_SHENGJI_APP_STORE=1
// (`npm run ios:sync:appstore`), which folds this to false so the bundler
// drops all of them; flavor_guard.sh refuses an App Store archive whose
// bundled page still has their markers. Every other build (the served site,
// the Beta's bundled page) keeps them, and there they still run only where
// the app binary reports them (nearbyGate.ts).
export const TEST_TOOLS: boolean = import.meta.env.VITE_SHENGJI_APP_STORE !== "1";
