// The audit gate runs against a stand-in npm on PATH, so each case is the real
// CLI deciding on a known report: only a complete report with nothing unwaived passes.
// @vitest-environment node
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, writeFileSync, chmodSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";

const SCRIPT = new URL("../scripts/audit.mjs", import.meta.url).pathname;
const dir = mkdtempSync(join(tmpdir(), "audit-gate-"));
mkdirSync(join(dir, "scripts"));
copyFileSync(SCRIPT, join(dir, "scripts", "audit.mjs"));
const npm = join(dir, "npm");
writeFileSync(npm, [
  "#!/usr/bin/env node",
  "const full = !process.argv.includes('--omit=dev');",
  "process.stdout.write(process.env[full ? 'FULL' : 'PROD']);",
  "process.exit(Number(process.env.RC));",
].join("\n"));
chmodSync(npm, 0o755);
afterAll(() => rmSync(dir, { recursive: true, force: true }));

const PICO = { name: "picomatch", severity: "high", url: "https://github.com/advisories/GHSA-fc5q-39xc-vjpf" };
const FOUND = { vulnerabilities: { picomatch: { via: [PICO] } } };
const CLEAN = { vulnerabilities: {} };
const WAIVER = { id: "GHSA-fc5q-39xc-vjpf", package: "picomatch", reason: "build tools only", until: "2999-01-01" };

function gate(prod: unknown, full: unknown, rc: number, allow: unknown): number | null {
  writeFileSync(join(dir, "audit-allow.json"), JSON.stringify(allow));
  const env = { ...process.env, PATH: `${dir}:${process.env.PATH}`, PROD: JSON.stringify(prod), FULL: JSON.stringify(full), RC: String(rc) };
  return spawnSync("node", [join(dir, "scripts", "audit.mjs")], { env, encoding: "utf8" }).status;
}

describe("the audit gate", () => {
  it("passes a clean audit and a dev advisory with a valid waiver", () => {
    expect(gate(CLEAN, CLEAN, 0, [WAIVER])).toBe(0);
    expect(gate(CLEAN, FOUND, 1, [WAIVER])).toBe(0);
  });

  it("fails a shipped advisory even when it is waived", () => {
    expect(gate(FOUND, FOUND, 1, [WAIVER])).toBe(1);
  });

  it("fails a dev advisory without a waiver, or with an expired one", () => {
    expect(gate(CLEAN, FOUND, 1, [])).toBe(1);
    expect(gate(CLEAN, FOUND, 1, [{ ...WAIVER, until: "2000-01-01" }])).toBe(1);
  });

  it("fails when the audit itself did not complete", () => {
    expect(gate({ error: { code: "E503", summary: "registry unavailable" } }, { error: { code: "E503" } }, 1, [WAIVER])).toBe(1);
    expect(gate({}, {}, 0, [WAIVER])).toBe(1);
    expect(gate(CLEAN, "not json", 1, [WAIVER])).toBe(1);
    expect(gate(CLEAN, CLEAN, 2, [WAIVER])).toBe(1);
  });

  it("fails a waiver missing a field, with a bad date, or naming another package", () => {
    const { until: _u, ...noUntil } = WAIVER;
    const { reason: _r, ...noReason } = WAIVER;
    expect(gate(CLEAN, FOUND, 1, [noUntil])).toBe(1);
    expect(gate(CLEAN, FOUND, 1, [noReason])).toBe(1);
    expect(gate(CLEAN, FOUND, 1, [{ ...WAIVER, until: "never" }])).toBe(1);
    expect(gate(CLEAN, FOUND, 1, [{ ...WAIVER, until: "2999-02-30" }])).toBe(1);
    expect(gate(CLEAN, FOUND, 1, [{ ...WAIVER, package: "minimatch" }])).toBe(1);
  });

  it("fails any malformed waiver even when no advisory needs it", () => {
    expect(gate(CLEAN, CLEAN, 0, [{ ...WAIVER, reason: "" }])).toBe(1);
  });
});
