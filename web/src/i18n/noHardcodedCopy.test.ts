// @vitest-environment node
/// <reference types="node" />
// The migrated surfaces draw every visible word from the message table: no
// JSX text, and no aria-label, title, placeholder, alt or label attribute,
// carries an English word of its own, and neither does a copy field of an
// object literal ({ label: "Coach" }). A file joins its area's list in migrated/
// when its strings move into src/i18n/messages; ALLOWED lists the few literals that are the
// same in every language (the brand, a suit letter).
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import ts from "typescript";

const lists = import.meta.glob<{ FILES: string[] }>("./migrated/*.ts", { eager: true });
const MIGRATED = Object.values(lists).flatMap((m) => m.FILES);

const ALLOWED = new Set<string>([
  "Sheng Ji",
]);

const ATTRS = new Set(["aria-label", "title", "placeholder", "alt", "label", "aria-description", "aria-valuetext"]);
/** Object fields that hold copy ({ label: "Coach" }). */
const PROPS = new Set(["label", "title", "line", "text", "sub", "hint", "confirm", "cancel", "body", "heading"]);
const WORD = /[A-Za-z]{2,}/;

function literals(file: string): string[] {
  const path = new URL(`../${file}`, import.meta.url);
  const text = readFileSync(path, "utf8");
  const src = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const flag = (node: ts.Node, value: string) => {
    const v = value.replace(/\s+/g, " ").trim();
    if (!v || !WORD.test(v) || ALLOWED.has(v)) return;
    const { line } = src.getLineAndCharacterOfPosition(node.getStart());
    found.push(`${file}:${line + 1}: ${JSON.stringify(v)}`);
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) flag(node, node.text);
    else if (ts.isJsxExpression(node) && node.expression
      && (ts.isStringLiteral(node.expression) || ts.isNoSubstitutionTemplateLiteral(node.expression))
      && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
      flag(node, node.expression.text);
    } else if (ts.isJsxAttribute(node) && ATTRS.has(node.name.getText(src)) && node.initializer) {
      const init = node.initializer;
      if (ts.isStringLiteral(init)) flag(node, init.text);
      else if (ts.isJsxExpression(init) && init.expression
        && (ts.isStringLiteral(init.expression) || ts.isNoSubstitutionTemplateLiteral(init.expression))) {
        flag(node, init.expression.text);
      }
    }
    else if (ts.isPropertyAssignment(node) && PROPS.has(node.name.getText(src))
      && (ts.isStringLiteral(node.initializer) || ts.isNoSubstitutionTemplateLiteral(node.initializer))) {
      flag(node, node.initializer.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(src);
  return found;
}

describe("migrated surfaces carry no hard-coded English", () => {
  for (const file of MIGRATED) {
    it(file, () => {
      expect(literals(file)).toEqual([]);
    });
  }
});
