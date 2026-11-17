// The dependency audit CI runs. Any high or critical advisory in a package the
// app ships (a non-dev dependency) fails. In build and test tools (dev
// dependencies) an advisory fails unless audit-allow.json lists it with a reason
// and an expiry date; an expired entry fails too, so a waiver is reread.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const SEVERE = new Set(["high", "critical"]);

function audit(args) {
  let out;
  try {
    out = execFileSync("npm", ["audit", "--json", ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  } catch (e) {
    out = e.stdout;   // npm audit exits 1 when it finds anything
  }
  return JSON.parse(out).vulnerabilities ?? {};
}

function advisories(vulns) {
  const found = new Map();
  for (const v of Object.values(vulns)) {
    for (const via of v.via) {
      if (typeof via === "object" && SEVERE.has(via.severity)) found.set(via.url, via);
    }
  }
  return found;
}

const allow = JSON.parse(readFileSync(new URL("../audit-allow.json", import.meta.url), "utf8"));
const today = new Date().toISOString().slice(0, 10);
let failed = false;

for (const [url, via] of advisories(audit(["--omit=dev"]))) {
  console.error(`shipped dependency: ${via.name} ${via.severity} ${url}`);
  failed = true;
}
for (const [url, via] of advisories(audit([]))) {
  const entry = allow.find((a) => url.endsWith(a.id));
  if (!entry) {
    console.error(`build tool: ${via.name} ${via.severity} ${url} (not in audit-allow.json)`);
    failed = true;
  } else if (entry.until < today) {
    console.error(`build tool: ${via.name} ${url}: the audit-allow.json entry expired ${entry.until}`);
    failed = true;
  } else {
    console.log(`allowed until ${entry.until}: ${via.name} ${url} (${entry.reason})`);
  }
}
process.exit(failed ? 1 : 0);
