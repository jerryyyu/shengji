import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { AuthUser } from "../auth";
import { Companion, Portrait } from "../companion/Companion";
import type { Pose } from "../companion/Companion";
import { DRAWINGS } from "../companion/kinds";
import { parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry } from "../companion/look";
import { guestName } from "../guestName";
import { locale, useT } from "../i18n";
import type { MessageKey } from "../i18n";
import { prefersReducedMotion } from "../motion";

/** Where a look stands for this viewer, which picks the one button: Use, In
 *  use, the unlock line, Sign in to use, or (the Shop's, not drawn yet) a price. */
export type Ownership = "owned" | "equipped" | "store" | "locked" | "guest";

const KIND_NAME: Record<CompanionKind, MessageKey> = {
  tractor: "home.kindTractor", bun: "home.kindBun", chick: "home.kindChick", sparrow: "home.kindSparrow",
};

export const kindName = (t: ReturnType<typeof useT>, kind: CompanionKind): string => t(KIND_NAME[kind]);

/** The spoken name of a companion's colour, in the app's language. */
export function colourName(kind: CompanionKind, colour: Colour): string {
  const name = DRAWINGS[kind].colourName(colour);
  const lang = locale();
  return lang === "zh-Hant" ? name.hant : lang === "zh-Hans" ? name.zh : name.en;
}

/** A look's one status line: its companion and its colour. */
export const lookName = (t: ReturnType<typeof useT>, id: string): string => {
  const { kind, colour } = parseLook(id);
  return t("home.lookShown", { kind: kindName(t, kind), colour: colourName(kind, colour) });
};

/** How far a locked look's count has come, for a signed-in player only. */
export function progressText(t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string {
  if (!entry.needs || !user) return "";
  if (entry.needs.count === "ranked_wins") return t("home.lookRankedWin");
  const n = Math.min(user.rounds_played ?? 0, entry.needs.of);
  return t("home.lookRounds", { n, of: entry.needs.of });
}

/** What the one button may do for `entry` when `inUse` is worn. */
export function ownershipOf(entry: LookEntry, inUse: string, user: AuthUser | null): Ownership {
  if (!user) return "guest";
  if (!entry.unlocked) return "locked";
  return entry.id === inUse ? "equipped" : "owned";
}

/** A lock badge on a colour not yet earned. */
export function LockBadge() {
  return (
    <svg className="coll-lock" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7.5" rx="1.6" />
      <path d="M5.2 7V5.2a2.8 2.8 0 0 1 5.6 0V7" />
    </svg>
  );
}

/** The tick on what is in use. */
export function Tick() {
  return (
    <svg className="coll-tick" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="8" />
      <path d="M4.5 8.2l2.3 2.3 4.7-4.9" />
    </svg>
  );
}

/** A companion's colours. A tap only shows one (the gold ring); the tick
 *  marks the one in use. A guest hears each colour's name alone. */
export function Swatches({ entries, shown, inUse, user, size, className = "", onPick }: {
  entries: readonly LookEntry[]; shown: string; inUse: string; user: AuthUser | null; size: number; className?: string;
  onPick: (entry: LookEntry) => void;
}) {
  const t = useT();
  return (
    <div className={`coll-swatches ${className}`} role="radiogroup" aria-label={t("home.lookColours")}>
      {entries.map((entry) => {
        const { kind, colour } = parseLook(entry.id);
        const name = colourName(kind, colour);
        const progress = entry.unlocked ? "" : progressText(t, entry, user);
        return (
          <button key={entry.id} type="button" role="radio" aria-checked={entry.id === shown}
                  aria-label={progress ? t("home.lookLocked", { name, progress }) : name}
                  className={`coll-swatch${entry.id === shown ? " on" : ""}${entry.unlocked ? "" : " locked"}`}
                  onClick={() => onPick(entry)}>
            <Portrait look={entry.id} size={size} />
            {entry.unlocked ? null : <LockBadge />}
            {entry.id === inUse ? <Tick /> : null}
          </button>
        );
      })}
    </div>
  );
}

/** The one button: Use, In use (inert), the locked look's unlock line
 *  (inert), or for a guest Sign in to use. */
export function UseButton({ entry, ownership, user, onUse, price }: {
  entry: LookEntry; ownership: Ownership; user: AuthUser | null; onUse: () => void; price?: ReactNode;
}) {
  const t = useT();
  if (ownership === "store") return price ? <>{price}</> : null;
  let label: string;
  let act: (() => void) | null = null;
  if (ownership === "guest") {
    label = t("home.signInToUse");
    act = () => guestName.open("collection");
  } else if (ownership === "locked") {
    label = entry.needs?.count === "ranked_wins" ? t("home.unlockRankedWin")
      : t("home.unlockRounds", { of: entry.needs?.of ?? 0, n: Math.min(user?.rounds_played ?? 0, entry.needs?.of ?? 0) });
  } else if (ownership === "equipped") {
    label = t("home.inUse");
  } else {
    label = t("home.use");
    act = onUse;
  }
  return (
    <div className="coll-use-row">
      <button type="button" className={`btn big coll-use${act ? " gold" : " done"}`} disabled={!act} onClick={act ?? undefined}>
        {label}
      </button>
    </div>
  );
}

/** The moves a stage plays by itself, one after another, each for its time. */
const CYCLE: readonly [Pose, number][] = [["idle", 2200], ["hop", 900], ["idle", 1800], ["cheer", 1500], ["idle", 1800],
  ["react", 1800], ["idle", 1800], ["sleep", 2400]];

/** A live figure on felt that plays its moves in turn by itself (a tap plays
 *  the next at once), still under Reduce Motion and while the page is hidden. */
export function Stage({ kind, colour, size, label, partner }: {
  kind: CompanionKind; colour: Colour; size: number; label: string;
  partner?: { kind: CompanionKind; colour: Colour; size: number } | null;
}) {
  const [step, setStep] = useState(0);
  const timer = useRef(0);
  const [pose] = CYCLE[step % CYCLE.length];
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const go = () => {
      window.clearTimeout(timer.current);
      if (document.visibilityState === "hidden") return;
      timer.current = window.setTimeout(() => setStep((s) => s + 1), CYCLE[step % CYCLE.length][1]);
    };
    go();
    document.addEventListener("visibilitychange", go);
    return () => { window.clearTimeout(timer.current); document.removeEventListener("visibilitychange", go); };
  }, [step]);
  const next = () => setStep((s) => s + 1);
  return (
    <div className={`coll-felt char-stage${partner ? " char-try" : ""}`}>
      <button type="button" className="coll-figure" aria-label={label} onClick={next}>
        <Companion kind={kind} colour={colour} size={size} state={pose} team={partner ? "us" : undefined} />
      </button>
      {partner ? (
        <span className="char-partner" aria-hidden="true">
          <Companion kind={partner.kind} colour={partner.colour} size={partner.size} team="us" />
        </span>
      ) : null}
    </div>
  );
}

/** The partner a try-on stands the character beside: the Tractor, or for
 *  the Tractor itself the Bun. */
const TRY_PARTNER: Record<CompanionKind, { kind: CompanionKind; colour: Colour }> = {
  tractor: { kind: "bun", colour: "plain" }, bun: { kind: "tractor", colour: "red" },
  chick: { kind: "tractor", colour: "red" }, sparrow: { kind: "tractor", colour: "red" },
};

/** The one character page, the Collection's body (and the Shop's, with a
 *  price for its button, once it is built): the live figure on felt, Try on
 *  your table, `strip` (the Collection's companions), the colours, the one
 *  status line (the look shown) and the one button. A tap on a colour only
 *  shows it; the button puts it in use. */
export default function CharacterPage({ kind, shown, entries, inUse, user, phone, strip, onShow, onUse, price }: {
  kind: CompanionKind; shown: string; entries: readonly LookEntry[]; inUse: string; user: AuthUser | null; phone: boolean;
  strip?: ReactNode; onShow: (entry: LookEntry) => void; onUse: (entry: LookEntry) => void; price?: ReactNode;
}) {
  const t = useT();
  const [tryOn, setTryOn] = useState(false);
  const entry = entries.find((e) => e.id === shown) ?? entries[0];
  const { colour } = parseLook(entry.id);
  const partner = tryOn ? { ...TRY_PARTNER[kind], size: phone ? 100 : 118 } : null;
  return (
    <div className="char-page">
      <Stage kind={kind} colour={colour} size={tryOn ? (phone ? 112 : 132) : phone ? 176 : 208} label={lookName(t, entry.id)}
             partner={partner} />
      <div className="char-poses">
        <button type="button" className={`char-chip${tryOn ? " on" : ""}`} aria-pressed={tryOn}
                onClick={() => setTryOn((v) => !v)}>
          {t("home.tryOnTable")}
        </button>
      </div>
      {strip}
      <Swatches entries={entries} shown={entry.id} inUse={inUse} user={user} size={56} className="char-swatches" onPick={onShow} />
      <p className="coll-status" role="status">{lookName(t, entry.id)}</p>
      <UseButton entry={entry} ownership={ownershipOf(entry, inUse, user)} user={user} onUse={() => onUse(entry)} price={price} />
    </div>
  );
}
