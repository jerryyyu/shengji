// Where the saved lobby name (`shengji.name` in ws.ts) came from. An
// "account" name was filled in from the signed-in account and should follow
// a later rename; a "typed" name is the player's own choice for the room and
// is left alone. Missing or unreadable reads as "typed", the pre-marker
// behaviour, so an old saved name is never silently replaced.

const SOURCE_KEY = "shengji.nameSource";

export type NameSource = "account" | "typed";

export function getNameSource(): NameSource {
  try {
    return localStorage.getItem(SOURCE_KEY) === "account" ? "account" : "typed";
  } catch {
    return "typed";
  }
}

export function setNameSource(source: NameSource): void {
  try {
    localStorage.setItem(SOURCE_KEY, source);
  } catch {
    /* storage unavailable: the name itself was not saved either */
  }
}
