// The dependency audit CI runs. Any high or critical advisory in a package the
// app ships (a non-dev dependency) fails. In build and test tools (dev
// dependencies) an advisory fails unless audit-allow.json lists it with its
// package, a reason and an ISO expiry date; an expired or malformed entry fails
// too, so a waiver is reread. The audit itself must complete: an npm error, a
// crash or a report without its vulnerabilities map fails, never passes.
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const SEVERE = new Set(["high", "critical"]);

function audit(args) {
  const run = spawnSync("npm", ["audit", "--json", ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  // npm audit exits 0 when clean and 1 when it finds advisories; anything else
  // (a signal, a spawn failure, another code) means the audit did not run
  if (run.error || run.signal || (run.status !== 0 && run.status !== 1)) {
    throw new Error(`npm audit ${args.join(" ")} did not complete: ${run.error ?? run.signal ?? `exit ${run.status}`}`);
  }
  let report;
  try {
    report = JSON.parse(run.stdout);
  } catch {
    throw new Error(`npm audit ${args.join(" ")} printed no JSON report`);
  }
  if (report === null || typeof report !== "object" || "error" in report) {
    throw new Error(`npm audit ${args.join(" ")} failed: ${JSON.stringify(report?.error ?? report)}`);
  }
  const vulns = report.vulnerabilities;
  if (vulns === null || typeof vulns !== "object" || Array.isArray(vulns)) {
    throw new Error(`npm audit ${args.join(" ")} report has no vulnerabilities map`);
  }
  return vulns;
}

function advisories(vulns) {
  const found = new Map();
  for (const v of Object.values(vulns)) {
    if (!Array.isArray(v?.via)) throw new Error(`npm audit entry without via: ${JSON.stringify(v)}`);
    for (const via of v.via) {
      if (typeof via === "object" && via !== null && SEVERE.has(via.severity)) found.set(via.url, via);
    }
  }
  return found;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** The waiver's problem, or null when it is complete: an advisory id, the
 *  package it names, a reason and a real calendar date. */
function waiverProblem(w) {
  if (w === null || typeof w !== "object") return "not an object";
  if (typeof w.id !== "string" || !/^GHSA(-[0-9a-z]{4}){3}$/.test(w.id)) return "id is not a GHSA identifier";
  if (typeof w.package !== "string" || w.package.trim() === "") return "no package";
  if (typeof w.reason !== "string" || w.reason.trim() === "") return "no reason";
  if (typeof w.until !== "string" || !ISO_DATE.test(w.until)) return "until is not a YYYY-MM-DD date";
  const d = new Date(`${w.until}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== w.until) return "until is not a calendar date";
  return null;
}

function main() {
  const allow = JSON.parse(readFileSync(new URL("../audit-allow.json", import.meta.url), "utf8"));
  if (!Array.isArray(allow)) throw new Error("audit-allow.json is not a list");
  const today = new Date().toISOString().slice(0, 10);
  let failed = false;

  for (const w of allow) {
    const problem = waiverProblem(w);
    if (problem) {
      console.error(`audit-allow.json entry ${JSON.stringify(w)}: ${problem}`);
      failed = true;
    }
  }

  for (const [url, via] of advisories(audit(["--omit=dev"]))) {
    console.error(`shipped dependency: ${via.name} ${via.severity} ${url}`);
    failed = true;
  }
  for (const [url, via] of advisories(audit([]))) {
    const entry = allow.find((a) => waiverProblem(a) === null && url === `https://github.com/advisories/${a.id}`);
    if (!entry) {
      console.error(`build tool: ${via.name} ${via.severity} ${url} (no valid audit-allow.json entry)`);
      failed = true;
    } else if (entry.package !== via.name) {
      console.error(`build tool: ${via.name} ${url}: the audit-allow.json entry names ${entry.package}`);
      failed = true;
    } else if (entry.until < today) {
      console.error(`build tool: ${via.name} ${url}: the audit-allow.json entry expired ${entry.until}`);
      failed = true;
    } else {
      console.log(`allowed until ${entry.until}: ${via.name} ${url} (${entry.reason})`);
    }
  }
  return failed ? 1 : 0;
}

try {
  process.exit(main());
} catch (e) {
  console.error(String(e?.message ?? e));
  process.exit(1);
}
