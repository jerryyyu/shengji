// @vitest-environment node
/// <reference types="node" />
// Guards how names fit in index.css, which jsdom cannot lay out: a table
// panel seat's words stay on one line and end in an ellipsis, the panel keeps
// the phone's single column at every width (no side column that squeezes the
// seats until each name breaks inside a word), a CJK name in the panel's
// title moves to the next line whole, and Edit name on Me keeps its label on
// one line beside an ellipsized name, as does the large name heading. A chat
// sender, a leaderboard row and each name under the round end's last trick
// are one ellipsized line too.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./index.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Every rule as [selector, declarations], at any nesting depth. */
function rules(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = re.exec(css); m; m = re.exec(css)) {
    out.push([m[1].replace(/@media[^{]*$/, "").trim().replace(/\s+/g, " "), m[2]]);
  }
  return out;
}

/** The merged declarations of every rule whose selector list includes `selector`. */
function decls(selector: string): string {
  const found = rules().filter(([sel]) => sel.split(",").map((s) => s.trim()).includes(selector)).map(([, d]) => d);
  if (!found.length) throw new Error(`no rule ${selector}`);
  return found.join(";");
}

describe("names in the table panel", () => {
  it("keeps a seat's name and its second line on one line, ellipsized", () => {
    for (const sel of [".tp-seat-name", ".tp-seat-sub"]) {
      const d = decls(sel);
      expect(d).toContain("white-space: nowrap");
      expect(d).toContain("overflow: hidden");
      expect(d).toContain("text-overflow: ellipsis");
      expect(d).not.toMatch(/overflow-wrap: anywhere|word-break: break-(all|word)/);
    }
  });

  it("never sets the seats in a side column beside the words and buttons", () => {
    const side = rules().filter(([sel, d]) => /\.tp\b/.test(sel) && /grid-column|grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\)/.test(d)
      && !/\.tp-teams|\.seat-clock/.test(sel));
    expect(side.map(([sel]) => sel)).toEqual([]);
  });

  it("keeps the action row in reach on a sideways phone, as on a phone", () => {
    expect(decls(".phone-landscape .play-table-up .tp-acts")).toContain("position: sticky");
  });

  it("moves a CJK name in the title to the next line whole", () => {
    expect(decls(".tp-title")).toContain("word-break: keep-all");
  });
});

describe("names on Me", () => {
  it("keeps Edit name's label on one line and ellipsizes the name", () => {
    expect(decls(".me-edit .grp-label")).toContain("white-space: nowrap");
    const value = decls(".me-edit .grp-value");
    expect(value).toContain("text-overflow: ellipsis");
    expect(value).toContain("white-space: nowrap");
  });

  it("keeps the large name heading on one line, ellipsized", () => {
    const d = decls(".me-name");
    expect(d).toContain("white-space: nowrap");
    expect(d).toContain("text-overflow: ellipsis");
    expect(d).not.toMatch(/overflow-wrap: anywhere/);
  });

  it("is one column at every width", () => {
    expect(rules().filter(([sel]) => /\.me-cols?\b/.test(sel)).map(([, d]) => d.trim())).toEqual(["display: contents;"]);
  });
});

describe("names in chat, the leaderboard and the round end", () => {
  const oneLine = (sel: string) => {
    const d = decls(sel);
    expect(d).toContain("white-space: nowrap");
    expect(d).toContain("overflow: hidden");
    expect(d).toContain("text-overflow: ellipsis");
    expect(d).not.toMatch(/overflow-wrap: anywhere|word-break: break-(all|word)/);
  };

  it("keeps a chat sender's name on one line, ellipsized", () => {
    oneLine(".chat-msg .chat-name");
    expect(decls(".chat-msg .chat-name")).toContain("display: inline-block");
  });

  it("keeps each name under the last trick on one line, ellipsized and narrow", () => {
    oneLine(".round-end-play-who");
    expect(decls(".round-end-play-who")).toMatch(/max-width: \d+px/);
  });

  it("moves a CJK name in a round-end Details label to the next line whole", () => {
    expect(decls(".round-end-col-label")).toContain("word-break: keep-all");
  });

  it("lets a four-digit rating take the width it needs", () => {
    const d = decls(".lb-rating");
    expect(d).toContain("min-width: 46px");
    expect(d).not.toMatch(/(^|[^-])width: 46px/);
  });

  it("keeps a leaderboard name and a saved game's title on one line, ellipsized", () => {
    oneLine(".lb-name-text");
    oneLine(".games-row-title");
  });
});
