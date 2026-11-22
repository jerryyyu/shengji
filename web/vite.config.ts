import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// Formats that are compressed already; a second pass only adds bytes.
const COMPRESSED = /\.(png|jpe?g|webp|avif|gif|mp3|mp4|woff2?|br|gz)$/;

/** Writes `<file>.br` and `<file>.gz` beside every file under dist/assets/
 *  that compresses, so the server sends the smallest encoding the browser
 *  accepts without compressing per request (server.py WebFiles). */
function precompressAssets(): Plugin {
  return {
    name: "precompress-assets",
    apply: "build",
    writeBundle(options) {
      const dir = join(options.dir ?? "dist", "assets");
      let names: string[];
      try { names = readdirSync(dir); } catch { return; }
      for (const name of names) {
        if (COMPRESSED.test(name)) continue;
        const raw = readFileSync(join(dir, name));
        const br = brotliCompressSync(raw, { params: {
          [constants.BROTLI_PARAM_QUALITY]: constants.BROTLI_MAX_QUALITY,
          [constants.BROTLI_PARAM_SIZE_HINT]: raw.length,
        } });
        const gz = gzipSync(raw, { level: 9 });
        if (br.length < raw.length) writeFileSync(join(dir, `${name}.br`), br);
        if (gz.length < raw.length) writeFileSync(join(dir, `${name}.gz`), gz);
      }
    },
  };
}

/** Writes the build id into index.html as `<meta name="shengji-build">`: a
 *  hash of every emitted file's name. Hashed assets carry their contents'
 *  hashes, so the id changes whenever the app's code or styles do; a change
 *  only to index.html or an unhashed public file can leave it unchanged. The server
 *  announces the tag it serves, and an older page reloads (reloadGate.ts). */
function buildId(): Plugin {
  return {
    name: "shengji-build-id",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        if (!ctx.bundle) return;
        const names = Object.keys(ctx.bundle).filter((n) => n !== "index.html").sort();
        const id = createHash("sha256").update(names.join("\n")).digest("hex").slice(0, 12);
        return [{ tag: "meta", attrs: { name: "shengji-build", content: id }, injectTo: "head" }];
      },
    },
  };
}

// The nearby M1 transport spike's test page (nearby-spike.html) is built only
// with SHENGJI_NEARBY_SPIKE=1, for the Debug app the spike's xcodebuild makes;
// no served or shipped build contains it.
const NEARBY_SPIKE = process.env.SHENGJI_NEARBY_SPIKE === "1";

// The page the App Store archive bundles is built with VITE_SHENGJI_APP_STORE=1
// (`npm run ios:sync:appstore`): testTools.ts folds TEST_TOOLS to false, and
// nearbyUi.tsx takes nearbyDebugAppStore.ts in place of nearbyDebug.tsx, so
// no soak, log-file, upload or hidden-switch module is in the bundle at all.
// flavor_guard.sh refuses an App Store archive whose bundled page has them.
const APP_STORE = process.env.VITE_SHENGJI_APP_STORE === "1";

function appStoreBundle(): Plugin {
  return {
    name: "shengji-app-store-bundle",
    apply: "build",
    enforce: "pre",
    resolveId(source, importer) {
      if (!APP_STORE || source !== "./nearbyDebug" || !importer) return null;
      if (!/[\\/]src[\\/]nearbyUi\.tsx$/.test(importer)) return null;
      return this.resolve("./nearbyDebugAppStore", importer, { skipSelf: true });
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [appStoreBundle(), react(), precompressAssets(), buildId()],
  ...(NEARBY_SPIKE
    ? { build: { rollupOptions: { input: { main: "index.html", spike: "nearby-spike.html" } } } }
    : {}),
  server: {
    // Same-origin /api in dev: the session cookie is set and read on one
    // host, so no CORS and nothing differs from the served build. The
    // websocket still goes straight to :8000 (ws.ts); cookies are per host,
    // not per port, so it carries the same cookie.
    proxy: { "/api": "http://localhost:8000" },
  },
})
