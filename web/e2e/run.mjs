// Runs the interaction suites end to end.
//   node e2e/run.mjs ci     the scripted-socket suites (matrix, phases, client, watch, collection): needs only web/dist
//   node e2e/run.mjs full   those, then the live flows against a game server it starts
//   node e2e/run.mjs flows  the live flows alone
// `full` needs a Python with the server's dependencies: PY=/path/to/python
// (default server/.venv/bin/python). BASE=<url> skips starting anything.
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.dirname(HERE);
const mode = process.argv[2] ?? "ci";
const kids = [];
const stop = () => { for (const k of kids) { try { process.kill(-k.pid, "SIGTERM"); } catch { /* gone */ } } };
process.on("exit", stop);
process.on("SIGINT", () => process.exit(130));

const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
async function up(url, ms = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if ((await fetch(url)).ok) return true; } catch { /* not yet */ }
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}
function run(file, env) {
  const r = spawnSync(process.execPath, [path.join(HERE, file)], { stdio: "inherit", env: { ...process.env, ...env } });
  return r.status ?? 1;
}

// the move picker is the offline engine's rules, bundled for node
const built = spawnSync(path.join(WEB, "node_modules/.bin/rolldown"), [path.join(HERE, "pick.ts"), "--file", path.join(HERE, ".build/pick.mjs"), "--format", "esm"], { stdio: ["ignore", "ignore", "inherit"] });
if (built.status !== 0) process.exit(built.status ?? 1);
if (!fs.existsSync(path.join(WEB, "dist/index.html"))) { console.error("web/dist is missing: run `npm run build` first"); process.exit(2); }

let rc = 0;
if (mode !== "flows") {
  let base = process.env.BASE;
  if (!base) {
    const port = await freePort();
    const k = spawn(path.join(WEB, "node_modules/.bin/vite"), ["preview", "--port", String(port), "--strictPort", "--host", "127.0.0.1"], { cwd: WEB, stdio: "ignore", detached: true });
    kids.push(k);
    base = `http://127.0.0.1:${port}/`;
    if (!(await up(base))) { console.error("the static server did not start"); process.exit(2); }
  }
  rc |= run("matrix.mjs", { BASE: base });
  rc |= run("phases.mjs", { BASE: base });
  rc |= run("client.mjs", { BASE: base });
  rc |= run("watch.mjs", { BASE: base });
  rc |= run("collection.mjs", { BASE: base });
}
if (mode === "full" || mode === "flows") {
  let base = process.env.BASE;
  if (!base) {
    const py = process.env.PY ?? path.join(WEB, "../server/.venv/bin/python");
    if (!fs.existsSync(py)) { console.error(`no Python at ${py}: set PY`); process.exit(2); }
    const port = await freePort();
    // its own empty server: other people's open tables would seat the suite elsewhere
    const data = fs.mkdtempSync(path.join(os.tmpdir(), "shengji-e2e-"));
    const k = spawn(py, ["-m", "uvicorn", "shengji.api.server:app", "--host", "127.0.0.1", "--port", String(port)], {
      cwd: path.join(WEB, "../server"), stdio: "ignore", detached: true,
      env: { ...process.env, PYTHONPATH: path.join(WEB, "../server"), SHENGJI_DATA_DIR: data, SHENGJI_LOG_DIR: path.join(data, "logs") },
    });
    kids.push(k);
    base = `http://127.0.0.1:${port}/`;
    if (!(await up(base + "healthz", 60000))) { console.error("the game server did not start"); process.exit(2); }
  }
  rc |= run("flows.mjs", { BASE: base });
}
stop();
process.exit(rc);
