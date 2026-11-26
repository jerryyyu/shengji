import { useState } from "react";
import type { ReactNode } from "react";
import { Companion, Portrait } from "../companion/Companion";
import type { Pose } from "../companion/Companion";
import { DRAWINGS } from "../companion/kinds";
import type { Colour, CompanionKind } from "../companion/look";
import { isZh, useT } from "../i18n";
import type { MessageKey } from "../i18n";

/** Where a character stands for this viewer, which picks the page's foot:
 *  Equip, Equipped, the unlock line, or (the Shop's, not drawn yet) a price. */
export type Ownership = "owned" | "equipped" | "store" | "locked";

const KIND_NAME: Record<CompanionKind, MessageKey> = {
  tractor: "home.kindTractor", bun: "home.kindBun", chick: "home.kindChick", sparrow: "home.kindSparrow",
};
const REACTION: Record<CompanionKind, MessageKey> = {
  tractor: "home.reactTractor", bun: "home.reactBun", chick: "home.reactChick", sparrow: "home.reactSparrow",
};
const POSES: readonly { pose: Pose; name: MessageKey | null }[] = [
  { pose: "idle", name: "home.poseIdle" }, { pose: "hop", name: "home.poseHop" },
  { pose: "cheer", name: "home.poseCheer" }, { pose: "sleep", name: "home.poseSleep" },
  { pose: "react", name: null },
];

/** The partner a try-on stands the character beside: the Tractor, or for
 *  the Tractor itself the Bun. */
const TRY_PARTNER: Record<CompanionKind, { kind: CompanionKind; colour: Colour }> = {
  tractor: { kind: "bun", colour: "plain" }, bun: { kind: "tractor", colour: "red" },
  chick: { kind: "tractor", colour: "red" }, sparrow: { kind: "tractor", colour: "red" },
};

export const kindName = (t: ReturnType<typeof useT>, kind: CompanionKind): string => t(KIND_NAME[kind]);

/** The spoken name of a companion's colour, in the app's language. */
export function colourName(kind: CompanionKind, colour: Colour): string {
  const name = DRAWINGS[kind].colourName(colour);
  return isZh() ? name.zh : name.en;
}

/** One swatch of the character's colours: its portrait, a lock when not yet earned. */
export interface Swatch { colour: Colour; label: string; locked: boolean }

/** A lock badge on a swatch not yet earned. */
export function LockBadge() {
  return (
    <svg className="coll-lock" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7.5" rx="1.6" />
      <path d="M5.2 7V5.2a2.8 2.8 0 0 1 5.6 0V7" />
    </svg>
  );
}

/** One character's page, opened from the Collection (and from the Shop once
 *  it is built): the live figure on felt, its states, a try-on beside a
 *  partner on your team's pads, its colours, and one foot that `ownership` picks.
 *  The page's one status line names the colour shown, or for a locked one
 *  says how far its count has come (`unlock`). `onEquip` is absent where
 *  there is nothing to store (a guest). */
export default function CharacterPage({ kind, colour, ownership, swatches, phone, onColour, onEquip, price, unlock }: {
  kind: CompanionKind; colour: Colour; ownership: Ownership; swatches: readonly Swatch[];
  phone: boolean; onColour: (colour: Colour) => void; onEquip?: () => void; price?: ReactNode; unlock?: string;
}) {
  const t = useT();
  const partner = TRY_PARTNER[kind];
  const status = ownership === "locked" && unlock ? unlock : colourName(kind, colour);
  const [pose, setPose] = useState<Pose>("idle");
  const [tryOn, setTryOn] = useState(false);
  let foot: ReactNode = null;
  if (ownership === "locked") {
    foot = null;
  } else if (ownership === "store") {
    foot = price ?? null;
  } else if (onEquip) {
    foot = (
      <button type="button" className={`btn big char-foot${ownership === "equipped" ? " done" : " gold"}`}
              disabled={ownership === "equipped"} onClick={onEquip}>
        {ownership === "equipped" ? t("home.equipped") : t("home.equip")}
      </button>
    );
  }
  return (
    <div className="char-page">
      <div className={`coll-felt char-stage${tryOn ? " char-try" : ""}`}>
        <button type="button" className="coll-figure" aria-label={status}
                onClick={() => setPose("hop")}>
          <Companion kind={kind} colour={colour} size={tryOn ? (phone ? 112 : 132) : phone ? 176 : 208} state={pose}
                     team={tryOn ? "us" : undefined} onPoseEnd={() => setPose("idle")} />
        </button>
        {tryOn ? (
          <span className="char-partner" aria-hidden="true">
            <Companion kind={partner.kind} colour={partner.colour} size={phone ? 100 : 118} team="us" />
          </span>
        ) : null}
      </div>
      <div className="char-poses" role="group" aria-label={kindName(t, kind)}>
        {POSES.map(({ pose: p, name }) => (
          <button key={p} type="button" className={`char-chip${p === "react" ? " sig" : ""}${p === pose ? " on" : ""}`}
                  aria-pressed={p === pose} onClick={() => setPose(p)}>
            {name ? t(name) : t(REACTION[kind])}
          </button>
        ))}
        <button type="button" className={`char-chip${tryOn ? " on" : ""}`} aria-pressed={tryOn}
                onClick={() => setTryOn((v) => !v)}>
          {t("home.tryOnTable")}
        </button>
      </div>
      <div className="coll-swatches char-swatches" role="radiogroup" aria-label={t("home.lookColours")}>
        {swatches.map((s) => (
          <button key={s.colour} type="button" role="radio" aria-checked={s.colour === colour} aria-label={s.label}
                  className={`coll-swatch${s.colour === colour ? " on" : ""}${s.locked ? " locked" : ""}`}
                  onClick={() => onColour(s.colour)}>
            <Portrait look={`${kind}/${s.colour}`} size={56} />
            {s.locked ? <LockBadge /> : null}
          </button>
        ))}
      </div>
      <p className="coll-status char-status" role="status">{status}</p>
      {foot ? <div className="char-foot-row">{foot}</div> : null}
    </div>
  );
}
