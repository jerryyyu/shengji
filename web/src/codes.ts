// Room codes and pair codes are one space (PROTOCOL.md "Codes"): the same
// four characters, the same link. codeJoin.ts looks a code up and runs the
// room or the pair flow.

export const NO_CODE = "No game or pair has that code.";
export const CODE_LEN = 4;

/** Uppercase letters and digits only, at most four: what the server compares. */
export function normalizeCode(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, CODE_LEN);
}

/** The invite link for a room or a pair: one parameter for either kind. */
export function codeLink(code: string): string {
  return `${window.location.origin}/?code=${code}`;
}
