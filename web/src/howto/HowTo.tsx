import { useLayoutEffect, useRef } from "react";
import type { ReactNode, TouchEvent } from "react";
import type { GameState, Trick } from "../protocol";
import Card from "../components/Card";
import TrickArea from "../components/TrickArea";
import { closeHowto, openHowto } from "./route";
import type { HowtoRoute } from "./route";
import Picture from "./Picture";
import type { Frame } from "./useTimeline";

const RANK_LADDER = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];

/** A row of real table cards. `glow` marks cards by index with the winner ring. */
function Cards({ codes, size = "md", tight = false, glow = [], lift = [], hide, faceDown = false }: {
  codes: string[]; size?: "sm" | "md" | "lg"; tight?: boolean; glow?: number[]; lift?: number[];
  /** Cards not dealt in yet (their space is kept); the others pop in. */
  hide?: number[]; faceDown?: boolean;
}) {
  return (
    <div className={`howto-cards ${size}${tight ? " tight" : ""}`}>
      {codes.map((c, i) => (
        <Card key={i} code={faceDown ? undefined : c}
              className={[glow.includes(i) ? "glow" : "", lift.includes(i) ? "lifted" : "",
                         hide ? (hide.includes(i) ? "howto-out" : "howto-in") : ""].filter(Boolean).join(" ")} />
      ))}
    </div>
  );
}

function Group({ label, children, note, className }: {
  label?: ReactNode; children: ReactNode; note?: ReactNode; className?: string;
}) {
  return (
    <div className={`howto-group${className ? ` ${className}` : ""}`}>
      {children}
      {label ? <span className="howto-cap">{label}</span> : null}
      {note ? <span className="howto-note">{note}</span> : null}
    </div>
  );
}

function Trump({ suit, rank }: { suit: string | null; rank: string }) {
  const sym: Record<string, string> = { S: "♠", H: "♥", D: "♦", C: "♣" };
  const red = suit === "H" || suit === "D";
  return (
    <span className="chip trump-chip">
      {suit ? <span className={`trump-suit ${red ? "red" : "black"}`}>{sym[suit]}</span>
        : <span className="trump-suit nt">NT</span>}
      <span className="trump-rank">{rank}</span>
    </span>
  );
}

function Level({ team, level, star }: { team: 0 | 1; level: string; star?: number }) {
  return (
    <span className={`chip level-chip team${team}`}>
      <span className={`team-dot t${team}`} />
      Lv <span className="level-value">{level}</span>
      {star ? <span className="games-won">★{star}</span> : null}
    </span>
  );
}

/** Class for a part of a picture that appears partway through its timeline:
 *  hidden (keeping its space) until `shown`, then it pops in. */
const at = (shown: boolean, extra = "") => [shown ? "howto-in" : "howto-out", extra].filter(Boolean).join(" ");

/* Climb from 2 to Ace: the four seats take their places by team, then the
   two teams' markers climb the level ladder from 2. */
interface GoalFrame { seats: number; lv0: string; lv1: string }
const GOAL_SEATS = [
  { cls: "team0 you pos-bottom", name: "You" },
  { cls: "team0 pos-top", name: "Bea · partner" },
  { cls: "team1 pos-left", name: "Ana" },
  { cls: "team1 pos-right", name: "Cal" },
];
const GOAL_FRAMES: Frame<GoalFrame>[] = [
  { at: 0, state: { seats: 0, lv0: "2", lv1: "2" } },
  { at: 300, state: { seats: 2, lv0: "2", lv1: "2" } },
  { at: 900, state: { seats: 4, lv0: "2", lv1: "2" } },
  { at: 1700, state: { seats: 4, lv0: "3", lv1: "2" } },
  { at: 2300, state: { seats: 4, lv0: "3", lv1: "3" } },
  { at: 2900, state: { seats: 4, lv0: "4", lv1: "3" } },
  { at: 3500, state: { seats: 4, lv0: "5", lv1: "3" } },
];

function GoalPicture({ f }: { f: GoalFrame }) {
  return (
    <>
      <div className="howto-seats">
        {GOAL_SEATS.map((s, k) => (
          <span key={s.name} className={`replay-seat ${s.cls} ${at(k < f.seats)}`}>
            <span className="replay-seat-name">{s.name}</span>
          </span>
        ))}
        <span className="howto-seats-mark" aria-hidden="true">升级</span>
      </div>
      <div className="howto-ladder" aria-label="Levels 2 to Ace">
        {RANK_LADDER.map((r) => (
          <span key={r} className={`howto-rung${r === "A" ? " finish" : ""}`}>
            {r}
            {r === f.lv0 ? <span className="team-dot t0" /> : null}
            {r === f.lv1 ? <span className="team-dot t1" /> : null}
          </span>
        ))}
      </div>
      <div className="howto-row center">
        <Level key={`0-${f.lv0}`} team={0} level={f.lv0} />
        <Level key={`1-${f.lv1}`} team={1} level={f.lv1} />
      </div>
    </>
  );
}

/* Trump beats everything: the order builds up from the strongest trump. */
interface CountFrame { shown: number }
const count = (times: number[]): Frame<CountFrame>[] =>
  [{ at: 0, state: { shown: 0 } }, ...times.map((t, k) => ({ at: t, state: { shown: k + 1 } }))];

const TRUMP_FRAMES = count([300, 900, 1500, 2100, 2900]);

function TrumpPicture({ f }: { f: CountFrame }) {
  return (
    <>
      <div className="howto-row center"><span className="howto-label">Example</span><Trump suit="H" rank="7" /></div>
      <div className="howto-order">
        <Group className={at(f.shown >= 1)} label={<><b>1</b> Big Joker</>}><Cards codes={["BJ"]} /></Group>
        <Group className={at(f.shown >= 2)} label={<><b>2</b> Little Joker</>}><Cards codes={["LJ"]} /></Group>
        <Group className={at(f.shown >= 3)} label={<><b>3</b> ♥7</>}><Cards codes={["H7"]} /></Group>
        <Group className={at(f.shown >= 4)} label={<><b>4</b> other 7s, equal</>}><Cards codes={["S7", "C7", "D7"]} tight /></Group>
      </div>
      <Group className={at(f.shown >= 5)} label={<><b>5</b> then the rest of ♥, Ace down to 2</>}>
        <Cards codes={["HA", "HK", "HQ", "HJ", "H10", "H9", "H8", "H6", "H5", "H4", "H3", "H2"]} size="sm" tight />
      </Group>
    </>
  );
}

/* Declare to pick trump: one 7 is declared, then each stronger show
   replaces it (the gold outline marks the declaration standing). */
interface DeclareFrame { shown: number; standing: number | null }
const DECLARE_ROWS: { cards: string[]; what: string; trump: ReactNode }[] = [
  { cards: ["BJ", "BJ"], what: "Pair of Big Jokers", trump: <Trump suit={null} rank="7" /> },
  { cards: ["LJ", "LJ"], what: "Pair of Little Jokers", trump: <Trump suit={null} rank="7" /> },
  { cards: ["H7", "H7"], what: "Pair of 7s", trump: <Trump suit="H" rank="7" /> },
  { cards: ["S7"], what: "One 7", trump: <Trump suit="S" rank="7" /> },
];
const DECLARE_FRAMES: Frame<DeclareFrame>[] = [
  { at: 0, state: { shown: 0, standing: null } },
  { at: 300, state: { shown: 1, standing: 3 } },
  { at: 1200, state: { shown: 2, standing: 2 } },
  { at: 2100, state: { shown: 3, standing: 1 } },
  { at: 3000, state: { shown: 4, standing: 0 } },
  { at: 3900, state: { shown: 4, standing: null } },
];

function DeclarePicture({ f }: { f: DeclareFrame }) {
  const n = DECLARE_ROWS.length;
  return (
    <div className="howto-stack">
      <span className="howto-arrow-up" aria-hidden="true">stronger ↑</span>
      {DECLARE_ROWS.map((r, k) => (
        <div key={r.what} className={`howto-declare-row ${at(k >= n - f.shown)}${f.standing === k ? " standing" : ""}`}>
          <Cards codes={r.cards} size="sm" />
          <span className="howto-declare-what">{r.what}</span>
          {r.trump}
        </div>
      ))}
    </div>
  );
}

/* Banker and kitty: the kitty slides into the banker's hand, the banker
   marks 8 cards, and they go back down as the new kitty. */
interface KittyFrame { kitty: "down" | "taken"; lifted: number; teams: boolean }
const KITTY_HAND = ["S3", "S4", "S6", "C2", "C6", "C8", "D3", "D9", "HK", "HA", "S7", "BJ"];
const KITTY_FRAMES: Frame<KittyFrame>[] = [
  { at: 0, state: { kitty: "down", lifted: 0, teams: false } },
  { at: 500, state: { kitty: "taken", lifted: 0, teams: false } },
  ...Array.from({ length: 8 }, (_, k) => ({ at: 1300 + k * 140, state: { kitty: "taken" as const, lifted: k + 1, teams: false } })),
  { at: 2700, state: { kitty: "down", lifted: 8, teams: false } },
  { at: 3400, state: { kitty: "down", lifted: 8, teams: true } },
];

function KittyPicture({ f }: { f: KittyFrame }) {
  return (
    <>
      <Group label="The kitty: 8 cards, face down">
        <div className={`howto-kitty-cards ${f.kitty}`}><Cards codes={Array(8).fill("")} faceDown size="sm" tight /></div>
      </Group>
      <span className="howto-arrow" aria-hidden="true">↓ the banker picks it up</span>
      <Group label="…then picks 8 of their 33 cards to bury">
        <Cards codes={KITTY_HAND} size="sm" lift={Array.from({ length: f.lifted }, (_, k) => k)} />
      </Group>
      <div className={`howto-row center ${at(f.teams)}`}>
        <span className="howto-pill def">Banker's team defends</span>
        <span className="howto-pill att">Other team attacks</span>
      </div>
    </>
  );
}

/* Play a trick: in seat order Ana leads, Bea, Cal and you follow, and the
   picture holds on the finished trick with Cal winning. */
const TRICK_STATE = {
  you: 0,
  hand: [],
  players: [
    { seat: 0, name: "You" }, { seat: 1, name: "Ana" }, { seat: 2, name: "Bea" }, { seat: 3, name: "Cal" },
  ],
} as unknown as GameState;

const TRICK_PLAYS = [
  { seat: 1, cards: ["SK"] },
  { seat: 2, cards: ["SA"] },
  { seat: 3, cards: ["H4"] },
  { seat: 0, cards: ["S2"] },
];

interface TrickFrame {
  plays: number;          // how many of TRICK_PLAYS are on the table
  leading: number | null; // seat winning so far (soft glow)
  winner: number | null;  // trick complete: WINS tag
}
const TRICK_FRAMES: Frame<TrickFrame>[] = [
  { at: 0, state: { plays: 0, leading: null, winner: null } },
  { at: 300, state: { plays: 1, leading: 1, winner: null } },
  { at: 1000, state: { plays: 2, leading: 2, winner: null } },
  { at: 1800, state: { plays: 3, leading: 3, winner: null } },
  { at: 2500, state: { plays: 4, leading: 3, winner: null } },
  { at: 3100, state: { plays: 4, leading: null, winner: 3 } },
];

function TrickPicture({ f }: { f: TrickFrame }) {
  const trick = { leader: 1, plays: TRICK_PLAYS.slice(0, f.plays) } as unknown as Trick;
  return (
    <>
      <div className="howto-row center"><span className="howto-label">Trump</span><Trump suit="H" rank="7" /></div>
      <div className="replay-felt howto-felt" data-leading={f.leading ?? undefined}>
        <TrickArea state={TRICK_STATE} trick={f.plays ? trick : null} winner={f.winner} declaration={null} />
        <span className="howto-seat-name pos-left">Ana</span>
        <span className="howto-seat-name pos-top">Bea</span>
        <span className="howto-seat-name pos-right">Cal</span>
        <span className="howto-seat-name pos-bottom">You</span>
        {/* Where TrickArea's flights start from. */}
        <span className="opponent pos-left howto-anchor" aria-hidden="true" />
        <span className="opponent pos-top howto-anchor" aria-hidden="true" />
        <span className="opponent pos-right howto-anchor" aria-hidden="true" />
        <span className="you-tagline howto-anchor" aria-hidden="true" />
      </div>
    </>
  );
}

/* Pairs and tractors: a pair, a tractor forming from two pairs, the tractor
   that skips the level rank, then a pair led and the pair you must answer. */
const PAIRS_FRAMES = count([300, 900, 1400, 2000, 2700, 3300, 3900]);

function PairsPicture({ f }: { f: CountFrame }) {
  const s = f.shown;
  return (
    <>
      <div className="howto-order">
        <Group className={at(s >= 1)} label="Pair"><Cards codes={["S9", "S9"]} tight /></Group>
        <Group className={at(s >= 2)} label="Tractor">
          <Cards codes={["S9", "S9", "S10", "S10"]} tight hide={s >= 3 ? [] : [2, 3]} />
        </Group>
        <Group className={at(s >= 4)} label="Tractor at level 7" note="the 7 is trump, so 6 and 8 touch">
          <Cards codes={["S6", "S6", "S8", "S8"]} tight />
        </Group>
      </div>
      <div className="howto-follow">
        <Group className={at(s >= 5)} label="Led"><Cards codes={["DQ", "DQ"]} size="sm" tight /></Group>
        <span className={at(s >= 6, "howto-arrow side")} aria-hidden="true">→</span>
        <Group className={at(s >= 6)} label="Your diamonds" note="you must play the pair">
          <Cards codes={["D5", "D5", "D9", "DJ"]} size="sm" tight glow={s >= 7 ? [0, 1] : []} />
        </Group>
      </div>
    </>
  );
}

/* Throws: the same throw first stands (nobody can beat a part), then fails
   against ♣K♣K and only the beatable pair is played. */
const THROW_FRAMES = count([200, 700, 1300, 2400, 3000, 3600]);

function ThrowPicture({ f }: { f: CountFrame }) {
  const s = f.shown;
  const fails = s >= 4;
  return (
    <>
      <div className="howto-follow">
        <Group className={at(s >= 1)} label="You throw ♣A and ♣Q♣Q"><Cards codes={["CA", "CQ", "CQ"]} tight /></Group>
        <span className={at(s >= 2, "howto-arrow side")} aria-hidden="true">vs</span>
        {fails
          ? <Group key="fails" className="howto-in" label="Someone holds ♣K♣K"><Cards codes={["CK", "CK"]} tight /></Group>
          : <Group key="stands" className={at(s >= 2)} label="Nobody holds a pair above ♣Q"><Cards codes={["CK", "CJ"]} tight /></Group>}
      </div>
      {fails ? (
        <>
          <span key="fails-arrow" className={at(s >= 5, "howto-arrow")} aria-hidden="true">↓ the throw fails</span>
          <Group key="fails-play" className={at(s >= 6)} label="You must play only the part that can be beaten">
            <Cards codes={["CQ", "CQ"]} tight glow={[0, 1]} />
          </Group>
        </>
      ) : (
        <>
          <span key="stands-arrow" className={at(s >= 3, "howto-arrow")} aria-hidden="true">↓ the throw stands</span>
          <Group key="stands-play" className={at(s >= 3)} label="All three cards are played together">
            <Cards codes={["CA", "CQ", "CQ"]} tight glow={[0, 1, 2]} />
          </Group>
        </>
      )}
    </>
  );
}

/* Points: the attackers' tricks bring in a 5, a 10 and a King, and their
   count climbs from 40 to 65; then the last-trick bonus. Scoring a round
   finishes this same hand. */
const POINT_CARDS = [{ code: "H5", pts: 5 }, { code: "S10", pts: 10 }, { code: "DK", pts: 10 }];
const POINTS_BEFORE = 40;
interface PointsFrame { shown: number; bonus: boolean }
const POINTS_FRAMES: Frame<PointsFrame>[] = [
  { at: 0, state: { shown: 0, bonus: false } },
  { at: 400, state: { shown: 1, bonus: false } },
  { at: 1100, state: { shown: 2, bonus: false } },
  { at: 1800, state: { shown: 3, bonus: false } },
  { at: 2700, state: { shown: 3, bonus: true } },
];

function PointsPicture({ f }: { f: PointsFrame }) {
  const points = POINT_CARDS.slice(0, f.shown).reduce((n, c) => n + c.pts, POINTS_BEFORE);
  return (
    <>
      <div className="howto-order">
        {POINT_CARDS.map((c, k) => (
          <Group key={c.code} className={at(k < f.shown)} label={<span className="win-tag">{c.pts}</span>}>
            <Cards codes={[c.code]} size="lg" glow={[0]} />
          </Group>
        ))}
      </div>
      <div className="howto-row center">
        <span className="howto-label">Attackers</span>
        <span className="chip points-chip">
          <span className="points-big howto-count-up" key={points}>{points}</span>
          <span className="points-target">/ 80</span>
        </span>
      </div>
      <div className={`howto-kitty ${at(f.bonus)}`}>
        <span className="howto-kitty-head">Last trick bonus</span>
        <span>If attackers win the last trick, they also score the kitty's points, multiplied by twice the cards led:</span>
        <span className="howto-kitty-mult"><b>×2</b> single · <b>×4</b> pair · <b>×8</b> tractor of 2 pairs</span>
      </div>
    </>
  );
}

/* Scoring a round: the same hand as Points. The attackers' earlier 40, then
   the 5, 10 and King fly into their count; 65 is short of 80, so the
   defenders go up one level. */
const BANDS: { from: number; to: number; text: string; side: "def" | "att" }[] = [
  { from: 0, to: 5, text: "0", side: "def" },
  { from: 5, to: 40, text: "5–35", side: "def" },
  { from: 40, to: 80, text: "40–75", side: "def" },
  { from: 80, to: 120, text: "80–115", side: "att" },
  { from: 120, to: 160, text: "120–155", side: "att" },
  { from: 160, to: 200, text: "160–195", side: "att" },
];
const OUTCOME = ["Defenders +3", "Defenders +2", "Defenders +1",
  "Attackers take the deal", "Attackers +1", "Attackers +2"];

const cardPoints = (c: string) => (c.slice(1) === "5" ? 5 : c.slice(1) === "10" || c.slice(1) === "K" ? 10 : 0);
/** The attackers' point cards, trick by trick: the earlier tricks (40), then
 *  Points' 5, 10 and King, 65 in all. */
const HAULS = [["SK", "C10", "H10", "CK"], ...POINT_CARDS.map((c) => [c.code])];

interface ScoreFrame { haul: number | null; points: number; result: boolean }
const SCORE_FRAMES: Frame<ScoreFrame>[] = (() => {
  const frames: Frame<ScoreFrame>[] = [{ at: 0, state: { haul: null, points: 0, result: false } }];
  let points = 0;
  HAULS.forEach((cards, k) => {
    const start = 300 + k * 640;
    frames.push({ at: start, state: { haul: k, points, result: false } });
    points += cards.reduce((n, c) => n + cardPoints(c), 0);
    frames.push({ at: start + 440, state: { haul: k, points, result: false } });
  });
  frames.push({ at: 300 + HAULS.length * 640 + 250, state: { haul: null, points, result: true } });
  return frames;
})();

function ScoringPicture({ f }: { f: ScoreFrame }) {
  const haulRef = useRef<HTMLDivElement>(null);
  const counterRef = useRef<HTMLSpanElement>(null);
  // Aim each haul's flight at the counter.
  useLayoutEffect(() => {
    const h = haulRef.current, c = counterRef.current;
    if (!h || !c) return;
    const hb = h.getBoundingClientRect(), cb = c.getBoundingClientRect();
    h.style.setProperty("--fx", `${cb.left + cb.width / 2 - (hb.left + hb.width / 2)}px`);
    h.style.setProperty("--fy", `${cb.top + cb.height / 2 - (hb.top + hb.height / 2)}px`);
  }, [f.haul]);
  const band = BANDS.findIndex((b) => f.points >= b.from && f.points < b.to);
  const won = band >= 3;
  return (
    <>
      <div className="howto-score">
        <div className="howto-haul-slot">
          {f.haul !== null
            ? <div className="howto-haul" ref={haulRef} key={f.haul}><Cards codes={HAULS[f.haul]} size="sm" tight /></div>
            : null}
          {f.result ? <span className={`howto-pill ${won ? "att" : "def"} howto-result`}>{OUTCOME[band]}</span> : null}
        </div>
        <div className="howto-group">
          <span className="howto-label">Attackers</span>
          <span className="chip points-chip" ref={counterRef}>
            <span className="points-big howto-count-up" key={f.points}>{f.points}</span>
            <span className="points-target">/ 80</span>
          </span>
        </div>
        <div aria-hidden="true" />
      </div>
      <div className="howto-scale" aria-hidden="true">
        {BANDS.map((b) => (
          <span key={b.text} className={`howto-band ${b.side}`} style={{ flexGrow: b.to - b.from }} />
        ))}
        <span className="howto-scale-fill" style={{ width: `${Math.min(f.points, 200) / 2}%` }} />
        <span className={`howto-scale-line${f.points >= 80 ? " crossed" : ""}`} style={{ left: "40%" }}><span>80</span></span>
      </div>
      <div className="howto-ticks" aria-hidden="true">
        {[0, 40, 80, 120, 160, 200].map((t) => <span key={t} style={{ left: `${t / 2}%` }}>{t}</span>)}
      </div>
      <ul className="howto-bands">
        {BANDS.map((b, i) => (
          <li key={b.text} className={`${b.side}${i === band && (f.haul !== null || f.result) ? " on" : ""}${i === band && f.result ? " final" : ""}`}>
            <span className="howto-band-pts">{b.text}</span>
            <span>{OUTCOME[i]}</span>
          </li>
        ))}
        <li className="att"><span className="howto-band-pts">200+</span><span>Attackers +3, and +1 per 40 more</span></li>
      </ul>
    </>
  );
}

/* Win a game: defending at Ace wins the game (a star), then both teams
   start again from 2. */
const WIN_FRAMES = count([300, 1100, 2000, 2700]);

function WinPicture({ f }: { f: CountFrame }) {
  const s = f.shown;
  return (
    <>
      <div className="howto-follow">
        <Group className={at(s >= 1)} label="Your team defends at Ace…"><Level team={0} level="A" /></Group>
        <span className={at(s >= 2, "howto-arrow side")} aria-hidden="true">→</span>
        <Group className={at(s >= 2)} label="…and wins a game"><Level team={0} level="A" star={1} /></Group>
      </div>
      <span className={at(s >= 3, "howto-arrow")} aria-hidden="true">↓ both teams start again</span>
      <div className={`howto-row center ${at(s >= 4)}`}>
        <Level team={0} level="2" star={1} />
        <Level team={1} level="2" />
      </div>
    </>
  );
}

/** The last frame of a timeline: each picture's still image. */
const lastState = <S,>(frames: Frame<S>[]): S => frames[frames.length - 1].state;
const picture = <S,>(frames: Frame<S>[], render: (f: S) => ReactNode) =>
  <Picture frames={frames} still={lastState(frames)} render={render} />;

/** One step: a headline, a line or two of rules, a picture and an optional
 *  caption under it. The text here is the guide's copy. */
interface Step { title: string; body: ReactNode; visual: ReactNode; caption?: ReactNode }

const STEPS: Step[] = [
  {
    title: "Climb from 2 to Ace",
    body: <>Four players in two teams: you and the partner across from you. Win rounds to climb levels from 2 up to Ace.</>,
    visual: picture(GOAL_FRAMES, (f) => <GoalPicture f={f} />),
  },
  {
    title: "Trump beats everything",
    body: <>The level card's rank and the jokers are always trump. One suit is trump too. Highest trump first:</>,
    visual: picture(TRUMP_FRAMES, (f) => <TrumpPicture f={f} />),
  },
  {
    title: "Declare to pick trump",
    body: <>While the cards are dealt, show a card of the level's rank to make its suit trump. A stronger show replaces it; a joker pair means no trump suit.</>,
    visual: picture(DECLARE_FRAMES, (f) => <DeclarePicture f={f} />),
  },
  {
    title: "Banker and kitty",
    body: <>The banker picks up the 8 leftover cards, then buries any 8 face down. The banker leads the first trick.</>,
    visual: picture(KITTY_FRAMES, (f) => <KittyPicture f={f} />),
  },
  {
    title: "Play a trick",
    body: <>Follow the led suit if you can. The highest card of that suit wins, unless someone out of it plays trump. The winner leads next.</>,
    visual: picture(TRICK_FRAMES, (f) => <TrickPicture f={f} />),
    caption: <>Ana leads ♠K. Bea plays ♠A, but Cal has no spades and plays ♥4: trump wins.</>,
  },
  {
    title: "Pairs and tractors",
    body: <>Two identical cards are a pair; pairs next to each other are a tractor. When a pair is led, you must answer with a pair of that suit if you have one.</>,
    visual: picture(PAIRS_FRAMES, (f) => <PairsPicture f={f} />),
  },
  {
    title: "Throws",
    body: <>You may lead several cards of one suit at once. If another player could beat any part of it, the throw fails.</>,
    visual: picture(THROW_FRAMES, (f) => <ThrowPicture f={f} />),
  },
  {
    title: "Points",
    body: <>Only 5s, 10s and Kings score: 200 points in all. Attackers keep the points in the tricks they win.</>,
    visual: picture(POINTS_FRAMES, (f) => <PointsPicture f={f} />),
  },
  {
    title: "Scoring a round",
    body: <>Attackers need 80 to win the round. Every 40 points either way moves a level.</>,
    visual: picture(SCORE_FRAMES, (f) => <ScoringPicture f={f} />),
  },
  {
    title: "Win a game",
    body: <>Reach Ace, then defend it as the banker's team. Winning as attackers at Ace only takes the deal.</>,
    visual: picture(WIN_FRAMES, (f) => <WinPicture f={f} />),
    caption: <>The ★ on your level chip counts games won. The table keeps playing.</>,
  },
];

function Head({ count }: { count: ReactNode }) {
  return (
    <header className="howto-head">
      <button className="btn subtle games-back" onClick={closeHowto}>‹ Back</button>
      <h1 className="howto-page">How to play</h1>
      <span className="howto-count">{count}</span>
    </header>
  );
}

function Stepper({ step }: { step: number }) {
  const n = STEPS.length;
  const i = Math.min(Math.max(step, 1), n) - 1;
  const s = STEPS[i];
  const go = (to: number) => openHowto(Math.min(Math.max(to, 1), n));
  return (
    <div className="panel games-panel howto-panel">
      <Head count={`${i + 1} of ${n}`} />
      {/* Keyed by step, so a slide's picture starts afresh each time it is entered. */}
      <section key={i} className="howto-step" aria-roledescription="slide">
        <h2 className="howto-title">{s.title}</h2>
        <p className="howto-body">{s.body}</p>
        {s.visual}
        <p className="howto-caption">{s.caption}</p>
      </section>
      <nav className="howto-nav" aria-label="Steps">
        {/* Where you are, not a control: ten taps would be under 30px wide on
            a small phone, and Next and the swipe already move a step.
            The header's "n of 10" says the same for a screen reader. */}
        <div className="howto-dots" aria-hidden="true">
          {STEPS.map((_, k) => (
            <span key={k} className={`howto-dot${k === i ? " on" : ""}`} />
          ))}
        </div>
        {/* One way forward: a step back is a swipe or the browser's own back,
            and the header's ‹ Back is the one way out. */}
        <div className="howto-buttons">
          {i < n - 1
            ? <button className="btn primary big" onClick={() => go(i + 2)}>Next</button>
            : <button className="btn gold big" onClick={closeHowto}>Start playing</button>}
        </div>
      </nav>
    </div>
  );
}

/** A swipe turns the page wherever it starts on the screen: only a mostly
 *  horizontal single-finger move past the threshold counts, so vertical
 *  scrolling and taps pass through. A touch that starts at the left edge
 *  belongs to the system's back gesture. */
const SWIPE_MIN_PX = 50;
const EDGE_PX = 20;

function useSwipe(step: number) {
  const n = STEPS.length;
  const i = Math.min(Math.max(step, 1), n);
  const touch = useRef<{ x: number; y: number } | null>(null);
  return {
    onTouchStart: (e: TouchEvent) => {
      const t = e.touches[0];
      touch.current = e.touches.length === 1 && t.clientX > EDGE_PX
        ? { x: t.clientX, y: t.clientY } : null;
    },
    onTouchMove: (e: TouchEvent) => { if (e.touches.length !== 1) touch.current = null; },
    onTouchCancel: () => { touch.current = null; },
    onTouchEnd: (e: TouchEvent) => {
      const start = touch.current; touch.current = null;
      if (start === null || e.changedTouches.length !== 1) return;
      const dx = e.changedTouches[0].clientX - start.x;
      const dy = e.changedTouches[0].clientY - start.y;
      if (Math.abs(dx) > SWIPE_MIN_PX && Math.abs(dx) > Math.abs(dy)) {
        openHowto(Math.min(Math.max(i + (dx < 0 ? 1 : -1), 1), n));
      }
    },
  };
}

export default function HowTo({ route }: { route: HowtoRoute }) {
  const swipe = useSwipe(route.step);
  return (
    <div className="screen lobby-screen howto-screen" {...swipe}>
      <Stepper step={route.step} />
    </div>
  );
}
