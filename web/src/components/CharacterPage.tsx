import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { AuthUser } from "../auth";
import { Companion, Portrait } from "../companion/Companion";
import { DRAWINGS } from "../companion/kinds";
import type { DrawnColour, DrawnKind } from "../companion/kinds";
import { PAGE_CYCLE, useLivePose } from "../companion/livePose";
import { playStageBeat, stageBeatMs, STAGE_BEATS } from "../companion/stageBeats";
import type { StageBeat } from "../companion/stageBeats";
import { parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry, UnlockCount } from "../companion/look";
import { guestName } from "../guestName";
import { locale, useT } from "../i18n";
import type { MessageKey } from "../i18n";
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

/** Each character's special, as its move chip names it. */
const SPECIAL_NAME: Record<DrawnKind, MessageKey> = {
  tractor: "home.specialTractor", bun: "home.specialBun", chick: "home.specialChick", sparrow: "home.specialSparrow",
  lamb: "home.specialLamb", panda: "home.specialPanda", rabbit: "home.specialRabbit", cat: "home.specialCat",
  fox: "home.specialFox", lion: "home.specialLion", dragon: "home.specialDragon",
};

/** The stage's move chips, in order: Hop, Cheer, Big play (the table's
 *  two-bounce jump), then the character's special. */
const MOVES: readonly { pose: "hop" | "cheer"; name: MessageKey }[] = [
  { pose: "hop", name: "home.moveHop" }, { pose: "cheer", name: "home.moveCheer" },
];

/** The spoken name of a companion's colour, in the app's language. */
export function colourName(kind: CompanionKind, colour: Colour): string {
  const name = DRAWINGS[kind].colourName(colour);
  const lang = locale();
  return lang === "zh-Hant" ? name.hant : lang === "zh-Hans" ? name.zh : name.en;
}

/** A look's one status line: its companion and its colour. */
export const lookName = (t: ReturnType<typeof useT>, id: string): string => {
  const { kind, colour } = parseLook(id);
  const name = kindName(t, kind), shade = colourName(kind, colour);
  // a colour named as its companion (the Sparrow's 麻雀) is said once
  return shade === name ? name : t("home.lookShown", { kind: name, colour: shade });
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
  return of === 1 ? t("home.lookRankedWin") : t("home.lookRankedRounds", { n: num(n), of: num(of) });
}

/** What unlocks a locked look, as the button says it. */
function unlockLine(t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string {
  const { count, of } = entry.needs ?? { count: "ranked_wins" as const, of: 1 };
  const n = Math.min(countOf(user, count), of);
  if (count === "rounds") return t("home.unlockRounds", { of, n });
  return of === 1 ? t("home.unlockRankedWin") : t("home.unlockRankedRounds", { of: num(of), n: num(n) });
}

const DATE_LOCALE = { en: undefined, "zh-Hans": "zh-CN", "zh-Hant": "zh-TW" } as const;

/** How `user` got an owned look, for the one status line: the date its
 *  companion was bought, or the count that unlocked its colour. "" for a look
 *  free from the start, and for one kept in use from before its count was
 *  reached: the line then names the look. */
export function provenanceLine(t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string {
  if (!user || !entry.unlocked) return "";
  const bought = entry.product ? user.purchased_on?.[entry.product] : undefined;
  if (bought) {
    const [y, m, d] = bought.split("-").map(Number);
    const date = new Date(y, m - 1, d).toLocaleDateString(DATE_LOCALE[locale()], { day: "numeric", month: "short", year: "numeric" });
    return t("home.purchasedOn", { date });
  }
  if (!entry.needs || countOf(user, entry.needs.count) < entry.needs.of) return "";
  const { count, of } = entry.needs;
  if (count === "rounds") return t("home.unlockedRounds", { of: num(of) });
  return of === 1 ? t("home.unlockedRankedWin") : t("home.unlockedRankedRounds", { of: num(of) });
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

/** The one button, one size whatever it says: Use, In use (inert), Use
 *  inert for a locked look (what unlocks it is the status line's), or for a
 *  guest Sign in to use. */
export function UseButton({ ownership, onUse, price }: {
  ownership: Ownership; onUse: () => void; price?: ReactNode;
}) {
  const t = useT();
  if (ownership === "store") return price ? <>{price}</> : null;
  let label: string;
  let act: (() => void) | null = null;
  if (ownership === "guest") {
    label = t("home.signInToUse");
    act = () => guestName.open("collection");
  } else if (ownership === "locked") {
    // what unlocks it is the status line's; the button keeps its one label and size
    label = t("home.use");
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

/** A live figure on felt that cycles through its moves by itself (idle,
 *  hop, cheer, its special, a short sleep: `PAGE_CYCLE`), each once-move for
 *  its own animation's length, while it is on screen; off screen its figure
 *  is paused. Every tap plays its special from the start. With `moves`, one
 *  row of chips under it plays Hop, Cheer, Big play or the special once,
 *  then the cycle resumes. Under Reduce Motion it stands still, and a tap or
 *  a chip shows that pose drawn still. */
export function Stage({ kind, colour, size, label, cheer = 0, moves = false }: {
  kind: DrawnKind; colour: DrawnColour; size: number; label: string;
  /** The row of move chips under the felt, each playing its move once before the cycle resumes. */
  moves?: boolean;
  /** Each new value plays the cheer at once (a purchase). */
  cheer?: number;
}) {
  const t = useT();
  const felt = useRef<HTMLDivElement>(null);
  const moveBox = useRef<HTMLSpanElement>(null);
  const beat = useRef<{ stop: () => void } | null>(null);
  const live = useLivePose(kind, PAGE_CYCLE, felt);
  const { play } = live;
  useEffect(() => () => beat.current?.stop(), []);
  // the table's big play: the box jumps while the figure holds the cheer
  const playBeat = (b: StageBeat) => {
    beat.current?.stop();
    // the figure keeps the beat's pose for the whole beat
    play(STAGE_BEATS[b].pose, stageBeatMs(b));
    const top = felt.current?.getBoundingClientRect().top ?? 0;
    const at = moveBox.current?.getBoundingClientRect().top ?? top;
    beat.current = playStageBeat(moveBox.current, b, { px: size, up: Math.max(0, at - top) });
  };
  const playPose = (p: "hop" | "cheer" | "react") => {
    beat.current?.stop();
    beat.current = null;
    if (p === "react") live.tap();
    else play(p);
  };
  useEffect(() => {
    if (cheer > 0) play("cheer");
  }, [cheer, play]);
  const stage = (
    <div ref={felt} className={`coll-felt char-stage${live.paused ? " live-paused" : ""}`}>
      <div className="char-figures" style={{ height: size }}>
        <button type="button" className="coll-figure" aria-label={label} onClick={() => playPose("react")}>
          <span className="char-box" ref={moveBox}>
            <Companion key={live.key} kind={kind} colour={colour} size={size} state={live.pose}
                       onPoseEnd={live.onPoseEnd} />
          </span>
        </button>
      </div>
    </div>
  );
  if (!moves) return stage;
  // the special's chip is the figure's own tap
  return (
    <>
      {stage}
      <div className="char-poses" role="group" aria-label={label}>
        {MOVES.map((m) => (
          <button key={m.pose} type="button" className="char-move" onClick={() => playPose(m.pose)}>{t(m.name)}</button>
        ))}
        <button type="button" className="char-move" onClick={() => playBeat("big")}>{t("home.moveBigPlay")}</button>
        <button type="button" className="char-move" onClick={() => playPose("react")}>{t(SPECIAL_NAME[kind])}</button>
      </div>
    </>
  );
}

/** A screen this short or shorter draws a smaller stage, so the stage, its
 *  colours and its one button fit above a phone's tab bar on the first view
 *  (375x667, an iPhone SE, is the smallest supported). */
export const SHORT_SCREEN = "(max-height: 700px)";

/** The stage's figure size: a phone's, a short phone's, or a wide layout's. */
export function stageSize(phone: boolean, short: boolean): number {
  return phone ? (short ? 132 : 176) : 208;
}

/** The selected character at the top of the Collection's one page (a tile
 *  selects it): the live figure on felt and its move chips, `strip`, the
 *  colours, the one status line (how an owned look was got, what unlocks a
 *  locked one, else the look shown) and the one button, or for a
 *  store character not owned `price` (Buy, Sign in to buy). A tap on a colour
 *  only shows it; the button puts it in use. "New" marks the colours in `fresh`. */
export default function CharacterPage({ kind, shown, entries, inUse, user, phone, short = false, strip, fresh, onShow, onUse, price,
  status = "", cheer = 0 }: {
  kind: CompanionKind; shown: string; entries: readonly LookEntry[]; inUse: string; user: AuthUser | null; phone: boolean;
  /** A short screen (`SHORT_SCREEN`): a smaller stage, so its colours and button fit above the tab bar. */
  short?: boolean;
  strip?: ReactNode; fresh?: readonly string[]; onShow: (entry: LookEntry) => void; onUse: (entry: LookEntry) => void; price?: ReactNode;
  /** Replaces the status line while set (a purchase waiting or refused). */
  status?: string;
  /** Each new value plays the cheer (a purchase granted). */
  cheer?: number;
}) {
  const t = useT();
  const entry = entries.find((e) => e.id === shown) ?? entries[0];
  const { colour } = parseLook(entry.id);
  return (
    <div className="char-page">
      <Stage kind={kind} colour={colour} size={stageSize(phone, short)} label={lookName(t, entry.id)} cheer={cheer} moves />
      {strip}
      <Swatches entries={entries} shown={entry.id} inUse={inUse} user={user} size={56} className="char-swatches" fresh={fresh} onPick={onShow} />
      <p className="coll-status" role="status">
        {status || (ownershipOf(entry, inUse, user) === "locked" ? unlockLine(t, entry, user)
          : provenanceLine(t, entry, user) || lookName(t, entry.id))}
      </p>
      <UseButton ownership={ownershipOf(entry, inUse, user)} onUse={() => onUse(entry)} price={price} />
    </div>
  );
}
