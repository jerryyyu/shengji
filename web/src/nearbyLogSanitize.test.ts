// The upload's line sanitizer: every line it returns passes the server's rule,
// and no line's text is lost. The fixture is shared with
// server/tests/test_nearby_logs.py, which runs its output through the
// server's own valid_log_text.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { MAX_LINE, sanitizeLogChunk } from "./nearbyLogUpload";

// Copied from shengji/api/nearby_logs.py: LINE_RE = r"\d+\.\d{3} [a-z]+ .*"
// with re.ASCII and fullmatch, and MAX_LINE = 2000 code points.
const SERVER_LINE_RE = /^[0-9]+\.[0-9]{3} [a-z]+ [^\n]*$/;
const SERVER_MAX_LINE = 2000;
const serverTakesLine = (l: string) => [...l].length <= SERVER_MAX_LINE && SERVER_LINE_RE.test(l);

const fixture = JSON.parse(readFileSync(join(process.cwd(), "src/__fixtures__/nearbyLogSanitize.json"), "utf8")) as {
  input: string; output: string;
};

describe("sanitizeLogChunk", () => {
  it("matches the shared fixture, which the server's rule refuses before and takes after", () => {
    expect(MAX_LINE).toBe(SERVER_MAX_LINE);
    expect(fixture.input.split("\n").filter(Boolean).every(serverTakesLine)).toBe(false);
    expect(sanitizeLogChunk(fixture.input)).toBe(fixture.output);
    for (const l of fixture.output.split("\n")) if (l) expect(serverTakesLine(l), l.slice(0, 80)).toBe(true);
  });

  it("keeps one output line per input line, in order, ending as the input ends", () => {
    const inLines = fixture.input.split("\n");
    const outLines = fixture.output.split("\n");
    expect(outLines).toHaveLength(inLines.length);
    expect(fixture.output.endsWith("\n")).toBe(true);
  });

  it("leaves good lines alone", () => {
    const good = "0.413 host link p1 up\n2.500 join seat 2 name 张伟 José 🀄 ready\n";
    expect(sanitizeLogChunk(good)).toBe(good);
  });

  it("turns a stack trace's continuation lines into raw lines at the previous line's time", () => {
    expect(sanitizeLogChunk("1.020 soak failed: Error: boom\n    at drop (a.js:1:2)\n    at tick (a.js:3:4)\n")).toBe(
      "1.020 soak failed: Error: boom\n1.020 raw     at drop (a.js:1:2)\n1.020 raw     at tick (a.js:3:4)\n");
  });

  it("stamps a shapeless line before any good one 0.000", () => {
    expect(sanitizeLogChunk("--- log file attached ---\n")).toBe("0.000 raw --- log file attached ---\n");
  });

  it("escapes \\r, tab, NUL and other controls", () => {
    expect(sanitizeLogChunk("2.6 x\r\n2.600 native a\rb\tc\u0000d\u007f\n")).toBe(
      "0.000 raw 2.6 x\\r\n2.600 native a\\rb\\tc\\x00d\\x7f\n");
  });

  it("cuts an overlong line to the limit with a marker naming what went", () => {
    const line = "3.000 host " + "x".repeat(5000);
    const out = sanitizeLogChunk(line + "\n").split("\n")[0];
    expect(out.length).toBe(SERVER_MAX_LINE);
    const m = / …\[truncated (\d+)\]$/.exec(out);
    expect(m).not.toBeNull();
    expect(out.length - m![0].length + Number(m![1])).toBe(line.length);
  });

  it("never splits a surrogate pair when it cuts", () => {
    for (let pad = 0; pad < 4; pad++) {
      const out = sanitizeLogChunk("3.000 host " + "a".repeat(pad) + "🀄".repeat(3000));
      expect(out).not.toMatch(/[\ud800-\udbff](?![\udc00-\udfff])/);
      expect(serverTakesLine(out)).toBe(true);
    }
  });
});
