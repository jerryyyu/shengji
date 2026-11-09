/** Rough drawn width of a name, in narrow-letter units: wide letters, CJK
 *  and emoji take more room. The phone layout steps the name's size down for
 *  long names before it ellipsizes. */
export function nameWidthClass(name: string): "s" | "m" | "l" {
  let units = 0;
  for (const ch of name) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp >= 0x2e80) units += 1.9;          // CJK, emoji and other wide glyphs
    else if (/[WMwm@]/.test(ch)) units += 1.35;
    else if (/[A-Z]/.test(ch)) units += 1.15;
    else units += 1;
  }
  return units > 9.5 ? "l" : units > 8 ? "m" : "s";
}
