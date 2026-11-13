// The lead a player is following, which fixes how many cards their play must be.

/** The lead you are following, or null when you lead or have already played. */
export function leadToFollow(trick: { plays: { seat: number; cards: string[] }[] } | null, you: number): string[] | null {
  if (!trick || trick.plays.length === 0) return null;
  if (trick.plays.some((p) => p.seat === you)) return null;
  return trick.plays[0].cards;
}
