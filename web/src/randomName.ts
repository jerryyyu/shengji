// Friendly random lobby names, an adjective and a card or game word
// ("Lucky Spades", "Quiet Tractor"), for a guest who has not picked a name.
// Every combination fits the display-name rules (see randomName.test.ts).

export const NAME_ADJECTIVES = [
  "Lucky", "Bold", "Sly", "Quiet", "Steady", "Clever", "Brave", "Swift", "Calm", "Merry",
  "Witty", "Jolly", "Daring", "Nimble", "Plucky", "Sunny", "Gentle", "Keen", "Patient", "Cheerful",
  "Crafty", "Mighty", "Noble", "Curious", "Dapper", "Breezy", "Humble", "Shrewd", "Spry", "Wise",
] as const;

export const NAME_NOUNS = [
  "Spades", "Hearts", "Diamonds", "Clubs", "Joker", "Tractor", "Ace", "King", "Queen", "Jack",
  "Deuce", "Kitty", "Banker", "Trick", "Pair", "Deck", "Shuffle", "Level", "Throw", "Ten",
] as const;

/** A random "Adjective Noun" name. `avoid` (the name shown now) is never
 *  returned, so a reroll always changes the name. */
export function randomName(avoid = "", rng: () => number = Math.random): string {
  const pick = <T,>(list: readonly T[]) => list[Math.min(list.length - 1, Math.floor(rng() * list.length))];
  for (let tries = 0; tries < 8; tries++) {
    const name = `${pick(NAME_ADJECTIVES)} ${pick(NAME_NOUNS)}`;
    if (name !== avoid.trim()) return name;
  }
  // A stuck random source: fall back to a fixed name other than `avoid`.
  const first = `${NAME_ADJECTIVES[0]} ${NAME_NOUNS[0]}`;
  return first === avoid.trim() ? `${NAME_ADJECTIVES[0]} ${NAME_NOUNS[1]}` : first;
}
