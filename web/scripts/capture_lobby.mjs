// Phone-size screenshot of the web lobby, for reviewing layout changes.
//
//   npm run capture:lobby -- --out lobby.png [--light] [--width 390 --height 844]
//                            [--scale 3] [--no-google] [--no-servers] [--settle 2500]
//
// By default it starts its own game server (:8000, throwaway data and log
// dirs) and Vite dev server (--web-port, default 5173), waits for both, takes
// a full-page screenshot and stops both process groups, also on error or
// Ctrl-C. The game server must be on :8000 because ws.ts connects there
// directly. --no-servers screenshots servers that are already running.
//
// The Google sign-in button renders only when the server has a client id; it
// is taken from GOOGLE_CLIENT_ID, else from the repo's fly.toml, and
// --no-google leaves it unset.
//
// Chromium: CHROMIUM_PATH, else the newest chromium-* build in the Playwright
// browser cache (playwright-core downloads no browsers). Install one with
// `npx playwright install chromium` if the cache is empty.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { homedir, platform, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(here, "..");
const repoDir = resolve(webDir, "..");

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(`--${name}`);
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : dflt;
};
const out = resolve(process.cwd(), arg("out", "lobby.png"));
const width = Number(arg("width", "390"));
const height = Number(arg("height", "844"));
const scale = Number(arg("scale", "3"));
const settleMs = Number(arg("settle", "2500"));
const webPort = Number(arg("web-port", "5173"));
const colorScheme = flag("light") ? "light" : "dark";
const startServers = !flag("no-servers");
const apiUrl = "http://localhost:8000/";
const webUrl = `http://localhost:${webPort}/`;

function findChromium() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const cache =
    process.env.PLAYWRIGHT_BROWSERS_PATH ||
    (platform() === "darwin"
      ? join(homedir(), "Library/Caches/ms-playwright")
      : platform() === "win32"
        ? join(homedir(), "AppData/Local/ms-playwright")
        : join(homedir(), ".cache/ms-playwright"));
  const builds = existsSync(cache)
    ? readdirSync(cache)
        .filter((d) => /^chromium-\d+$/.test(d))
        .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]))
    : [];
  const candidates = [
    "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    "chrome-linux64/chrome",
    "chrome-linux/chrome",
    "chrome-win64/chrome.exe",
    "chrome-win/chrome.exe",
  ];
  for (const build of builds) {
    for (const rel of candidates) {
      const p = join(cache, build, rel);
      if (existsSync(p)) return p;
    }
  }
  throw new Error(
    `no Chromium found in ${cache}; set CHROMIUM_PATH or run \`npx playwright install chromium\``,
  );
}

function googleClientId() {
  if (flag("no-google")) return "";
  if (process.env.GOOGLE_CLIENT_ID) return process.env.GOOGLE_CLIENT_ID;
  try {
    const toml = readFileSync(join(repoDir, "fly.toml"), "utf8");
    return toml.match(/^\s*GOOGLE_CLIENT_ID\s*=\s*['"]([^'"]+)['"]/m)?.[1] ?? "";
  } catch {
    return "";
  }
}

async function responds(url) {
  try {
    await fetch(url, { signal: AbortSignal.timeout(1000) });
    return true;
  } catch {
    return false;
  }
}

async function waitFor(url, child, label, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${label} exited (code ${child.exitCode}) before answering ${url}`);
    if (await responds(url)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${label} did not answer ${url} within ${timeoutMs / 1000} s`);
}

// Each server runs in its own process group so the uv/npx wrapper and the
// real server process it spawns stop together.
const children = [];
function start(label, cmd, args, cwd, env) {
  const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  const log = [];
  const keep = (chunk) => {
    log.push(chunk.toString());
    if (log.length > 200) log.shift();
  };
  child.stdout.on("data", keep);
  child.stderr.on("data", keep);
  child.label = label;
  child.log = log;
  children.push(child);
  return child;
}
function stopAll() {
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) {
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch {
        // The group already exited.
      }
    }
  }
}
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    stopAll();
    process.exit(130);
  });
}
process.on("exit", stopAll);

let browser;
try {
  if (startServers) {
    for (const url of [apiUrl, webUrl]) {
      if (await responds(url)) throw new Error(`${url} is already in use; stop it or pass --no-servers`);
    }
    const api = start(
      "game server",
      "uv",
      ["run", "uvicorn", "shengji.api.server:app", "--port", "8000"],
      join(repoDir, "server"),
      {
        GOOGLE_CLIENT_ID: googleClientId(),
        SHENGJI_DATA_DIR: mkdtempSync(join(tmpdir(), "capture-lobby-data-")),
        SHENGJI_LOG_DIR: mkdtempSync(join(tmpdir(), "capture-lobby-logs-")),
        SHENGJI_BOT: "smart",
      },
    );
    const web = start("vite", "npx", ["vite", "--port", String(webPort), "--strictPort"], webDir, {});
    await waitFor(apiUrl, api, "game server");
    await waitFor(webUrl, web, "vite");
  }

  browser = await chromium.launch({ executablePath: findChromium() });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale, colorScheme });
  await page.goto(webUrl);
  // The sign-in iframe loads from Google; the lobby is still worth capturing
  // without it (offline, or no client id).
  const signIn = await page
    .waitForSelector("[data-testid=google-signin] iframe", { timeout: 20000 })
    .then(() => true)
    .catch(() => false);
  await page.waitForTimeout(settleMs);
  await page.screenshot({ path: out, fullPage: true });
  console.log(`${out} (${width}x${height} @${scale}x, ${colorScheme}, google sign-in ${signIn ? "rendered" : "absent"})`);
} catch (err) {
  console.error(`capture_lobby: ${err.message}`);
  for (const child of children) {
    if (child.log.length) console.error(`--- ${child.label} output ---\n${child.log.join("").slice(-4000)}`);
  }
  process.exitCode = 1;
} finally {
  await browser?.close();
  stopAll();
}
