// Nearby table codes. A nearby code is longer than an online one, so one
// code names one kind of table, and every character is drawn from the online
// alphabet (no I, O, 0 or 1, which read alike). The code also keys the
// transport's TLS pre-shared key (NearbyPlugin.swift), so it is drawn from
// crypto.getRandomValues, never Math.random.

export const NEARBY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
/** 30 bits: the security audit's floor for a code that keys the link. */
export const NEARBY_CODE_LEN = 6;

const CODE_RE = new RegExp(`^[${NEARBY_ALPHABET}]{${NEARBY_CODE_LEN}}$`);

/** A fresh nearby code. 32 symbols divide 256, so one byte per character
 *  with a mask is uniform; the rejection loop guards a future alphabet that
 *  does not divide it. */
export function newNearbyCode(random: (buf: Uint8Array<ArrayBuffer>) => void = (b) => globalThis.crypto.getRandomValues(b)): string {
  const n = NEARBY_ALPHABET.length;
  const limit = 256 - (256 % n);
  let out = "";
  const buf = new Uint8Array(16);
  while (out.length < NEARBY_CODE_LEN) {
    random(buf);
    for (const b of buf) {
      if (b >= limit) continue;
      out += NEARBY_ALPHABET[b % n];
      if (out.length === NEARBY_CODE_LEN) break;
    }
  }
  return out;
}

/** Whether `raw`, upper-cased and trimmed, is a well-formed nearby code. */
export function isNearbyCode(raw: string): boolean {
  return CODE_RE.test(raw.trim().toUpperCase());
}
