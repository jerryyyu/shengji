import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { AuthUser } from "../auth";
import { Companion, Portrait } from "../companion/Companion";
import type { Pose } from "../companion/Companion";
import { DRAWINGS } from "../companion/kinds";
import type { DrawnColour, DrawnKind } from "../companion/kinds";
import { parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry, UnlockCount } from "../companion/look";
import { guestName } from "../guestName";
import { locale, useT } from "../i18n";
import type { MessageKey } from "../i18n";
import { prefersReducedMotion } from "../motion";
import { STORE_NAMES } from "../companion/characters";
import type { SoldKind, SoonKind } from "../companion/characters";

/** Where a look stands for this viewer, which picks the one button: Use, In
 *  use, the unlock line, Sign in to use, or a store character's price. */
export type Ownership = "owned" | "equipped" | "store" | "locked" | "guest";

const KIND_NAME: Partial<Record<CompanionKind, MessageKey>> = {
  tractor: "home.kindTractor", bun: "home.kindBun", chick: "home.kindChick", sparrow: "home.kindSparrow",
};

/** A companion's name: the free ones' from the messages, a store
 *  character's from its own table (characters.ts). */
export const kindName = (t: ReturnType<typeof useT>, kind: CompanionKind | SoonKind): string => {
  const key = KIND_NAME[kind as CompanionKind];
  if (key) return t(key);
  const name = STORE_NAMES[kind as SoldKind | SoonKind];
  const lang = locale();
  return lang === "zh-Hant" ? name.hant : lang === "zh-Hans" ? name.zh : name.en;
};

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

/** A count's value for `user`. */
const countOf = (user: AuthUser | null, count: UnlockCount): number =>
  count === "rounds" ? user?.rounds_played ?? 0 : count === "ranked_wins" ? user?.ranked_wins ?? 0 : user?.ranked_games ?? 0;

/** A count as the page writes it: 1,000, not 1000. */
const num = (n: number): string => n.toLocaleString("en-US");

/** How far a locked look's count has come, for a signed-in player only. */
export function progressText(t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string {
  if (!entry.needs || !user) return "";
  const { count, of } = entry.needs;
  const n = Math.min(countOf(user, count), of);
  if (count === "rounds") return t("home.lookRounds", { n, of });
  return of === 1 ? t("home.lookRankedWin") : t("home.lookRankedGames", { n: num(n), of: num(of) });
}

/** What unlocks a locked look, as the button says it. */
function unlockLine(t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string {
  const { count, of } = entry.needs ?? { count: "ranked_games" as const, of: 1 };
  const n = Math.min(countOf(user, count), of);
  if (count === "rounds") return t("home.unlockRounds", { of, n });
  return of === 1 ? t("home.unlockRankedWin") : t("home.unlockRankedGames", { of: num(of), n: num(n) });
}

/** What the one button may do for `entry` when `inUse` is worn. */
export function ownershipOf(entry: LookEntry, inUse: string, user: AuthUser | null): Ownership {
  if (entry.product && !entry.unlocked) return "store";
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
 *  marks the one in use, and "New" one newly unlocked (`fresh`). A guest
 *  hears each colour's name alone. */
export function Swatches({ entries, shown, inUse, user, size, className = "", fresh = [], onPick }: {
  entries: readonly LookEntry[]; shown: string; inUse: string; user: AuthUser | null; size: number; className?: string;
  fresh?: readonly string[]; onPick: (entry: LookEntry) => void;
}) {
  const t = useT();
  return (
    <div className={`coll-swatches ${className}`} role="radiogroup" aria-label={t("home.lookColours")}>
      {entries.map((entry) => {
        const { kind, colour } = parseLook(entry.id);
        const name = colourName(kind, colour);
        const progress = entry.unlocked ? "" : progressText(t, entry, user);
        const isNew = entry.unlocked && fresh.includes(entry.id);
        return (
          <button key={entry.id} type="button" role="radio" aria-checked={entry.id === shown}
                  aria-label={progress ? t("home.lookLocked", { name, progress }) : isNew ? `${name} ${t("home.new")}` : name}
                  className={`coll-swatch${entry.id === shown ? " on" : ""}${entry.unlocked ? "" : " locked"}`}
                  onClick={() => onPick(entry)}>
            <Portrait look={entry.id} size={size} />
            {entry.unlocked ? null : <LockBadge />}
            {entry.id === inUse ? <Tick /> : null}
            {isNew ? <span className="coll-new" aria-hidden="true">{t("home.new")}</span> : null}
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
    label = unlockLine(t, entry, user);
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

/** The moves a stage plays by itself, one after another, each for its
 *  time; the signature reaction runs its own length (`reactMs`) and a beat. */
const CYCLE: readonly [Pose, number][] = [["idle", 2200], ["hop", 900], ["idle", 1800], ["cheer", 1500], ["idle", 1800],
  ["react", 0], ["idle", 1800], ["sleep", 2400]];
const REACT_BEAT = 300;
const CHEER_STEP = CYCLE.findIndex(([pose]) => pose === "cheer");

/** A live figure on felt that plays its moves in turn by itself (a tap plays
 *  the next at once), still under Reduce Motion and while the page is hidden. */
export function Stage({ kind, colour, size, label, partner, cheer = 0 }: {
  kind: DrawnKind; colour: DrawnColour; size: number; label: string;
  partner?: { kind: CompanionKind; colour: Colour; size: number } | null;
  /** Each new value plays the cheer at once (a purchase). */
  cheer?: number;
}) {
  const [step, setStep] = useState(0);
  const timer = useRef(0);
  useEffect(() => {
    if (cheer > 0) setStep((s) => s - (s % CYCLE.length) + CYCLE.length + CHEER_STEP);
  }, [cheer]);
  const [pose] = CYCLE[step % CYCLE.length];
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const go = () => {
      window.clearTimeout(timer.current);
      if (document.visibilityState === "hidden") return;
      const [now, ms] = CYCLE[step % CYCLE.length];
      timer.current = window.setTimeout(() => setStep((s) => s + 1), now === "react" ? DRAWINGS[kind].reactMs + REACT_BEAT : ms);
    };
    go();
    document.addEventListener("visibilitychange", go);
    return () => { window.clearTimeout(timer.current); document.removeEventListener("visibilitychange", go); };
  }, [step, kind]);
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
  lamb: { kind: "bun", colour: "plain" }, panda: { kind: "bun", colour: "plain" },
};

/** The one character page, opened from any tile of the Collection's grid:
 *  the live figure on felt, Try on your table, `strip`, the colours, the one
 *  status line (the look shown) and the one button, or for a store character
 *  not owned `price` (Buy, Sign in to buy). A tap on a colour only shows it;
 *  the button puts it in use. "New" marks the colours in `fresh`. */
export default function CharacterPage({ kind, shown, entries, inUse, user, phone, strip, fresh, onShow, onUse, price,
  status = "", cheer = 0 }: {
  kind: CompanionKind; shown: string; entries: readonly LookEntry[]; inUse: string; user: AuthUser | null; phone: boolean;
  strip?: ReactNode; fresh?: readonly string[]; onShow: (entry: LookEntry) => void; onUse: (entry: LookEntry) => void; price?: ReactNode;
  /** Replaces the status line while set (a purchase waiting or refused). */
  status?: string;
  /** Each new value plays the cheer (a purchase granted). */
  cheer?: number;
}) {
  const t = useT();
  const [tryOn, setTryOn] = useState(false);
  const entry = entries.find((e) => e.id === shown) ?? entries[0];
  const { colour } = parseLook(entry.id);
  const partner = tryOn ? { ...TRY_PARTNER[kind], size: phone ? 100 : 118 } : null;
  return (
    <div className="char-page">
      <Stage kind={kind} colour={colour} size={tryOn ? (phone ? 112 : 132) : phone ? 176 : 208} label={lookName(t, entry.id)}
             partner={partner} cheer={cheer} />
      <div className="char-poses">
        <button type="button" className={`char-chip${tryOn ? " on" : ""}`} aria-pressed={tryOn}
                onClick={() => setTryOn((v) => !v)}>
          {t("home.tryOnTable")}
        </button>
      </div>
      {strip}
      <Swatches entries={entries} shown={entry.id} inUse={inUse} user={user} size={56} className="char-swatches" fresh={fresh} onPick={onShow} />
      <p className="coll-status" role="status">{status || lookName(t, entry.id)}</p>
      <UseButton entry={entry} ownership={ownershipOf(entry, inUse, user)} user={user} onUse={() => onUse(entry)} price={price} />
    </div>
  );
}
