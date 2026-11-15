/** What the one line between the trick and your hand can say. */
export interface HandLineParts {
  /** Why Play waits: a tapped disabled Play, or a play that does not follow. */
  reason: string | null;
  /** The phase's help: declaring or burying. */
  help: string | null;
  /** The newcomer coach's cue for this turn. */
  coach: string | null;
}

export type HandLinePick = { kind: "reason" | "help" | "coach"; text: string } | null;

/** The one line shown, highest priority first: why Play waits, then the
 *  phase's help, then the coach's cue. */
export function pickHandLine({ reason, help, coach }: HandLineParts): HandLinePick {
  if (reason) return { kind: "reason", text: reason };
  if (help) return { kind: "help", text: help };
  if (coach) return { kind: "coach", text: coach };
  return null;
}
