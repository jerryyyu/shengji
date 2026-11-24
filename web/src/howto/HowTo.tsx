import { useLayoutEffect, useRef } from "react";
import type { ReactNode, TouchEvent } from "react";
import type { GameState, Trick } from "../protocol";
import Card from "../components/Card";
import TrickArea from "../components/TrickArea";
import { closeHowto, openHowto } from "./route";
import type { HowtoRoute } from "./route";
import Picture from "./Picture";
import type { Frame } from "./useTimeline";
import { useScreen } from "../telemetry";
import { t, tx, useT } from "../i18n";
import type { MessageKey } from "../i18n";

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
  const t = useT();
  const sym: Record<string, string> = { S: "♠", H: "♥", D: "♦", C: "♣" };
  const red = suit === "H" || suit === "D";
  return (
    <span className="chip trump-chip">
      {suit ? <span className={`trump-suit ${red ? "red" : "black"}`}>{sym[suit]}</span>
        : <span className="trump-suit nt">{t("howto.chip.nt")}</span>}
      <span className="trump-rank">{rank}</span>
    </span>
  );
}

function Level({ team, level }: { team: 0 | 1; level: string }) {
  useT();
  return (
    <span className={`chip level-chip team${team}`}>
      <span className={`team-dot t${team}`} />
      {tx("howto.chip.level", { level: <span className="level-value">{level}</span> })}
    </span>
  );
}

/** The top bar's games score, as the table shows it. */
function Games({ us, them }: { us: number; them: number }) {
  const t = useT();
  return <span className="chip games-chip">{t("howto.chip.games", { n: us, count: them })}</span>;
}

/** Class for a part of a picture that appears partway through its timeline:
 *  hidden (keeping its space) until `shown`, then it pops in. */
const at = (shown: boolean, extra = "") => [shown ? "howto-in" : "howto-out", extra].filter(Boolean).join(" ");

/* Climb from 2 to Ace: the four seats take their places by team, then the
   two teams' markers climb the level ladder from 2. */
interface GoalFrame { seats: number; lv0: string; lv1: string }
const goalSeats = () => [
  { cls: "team0 you pos-bottom", name: t("howto.goal.you") },
  { cls: "team0 pos-top", name: t("howto.goal.partner", { name: "Bea" }) },
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
  const t = useT();
  return (
    <>
      <div className="howto-seats">
        {goalSeats().map((s, k) => (
          <span key={s.name} className={`replay-seat ${s.cls} ${at(k < f.seats)}`}>
            <span className="replay-seat-name">{s.name}</span>
          </span>
        ))}
        <span className="howto-seats-mark" aria-hidden="true">升级</span>
      </div>
      <div className="howto-ladder" aria-label={t("howto.goal.ladder")}>
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
  const t = useT();
  return (
    <>
      <div className="howto-row center"><span className="howto-label">{t("howto.trump.example")}</span><Trump suit="H" rank="7" /></div>
      <div className="howto-order">
        <Group className={at(f.shown >= 1)} label={tx("howto.trump.bigJoker", { n: <b>1</b> })}><Cards codes={["BJ"]} /></Group>
        <Group className={at(f.shown >= 2)} label={tx("howto.trump.littleJoker", { n: <b>2</b> })}><Cards codes={["LJ"]} /></Group>
        <Group className={at(f.shown >= 3)} label={<><b>3</b> ♥7</>}><Cards codes={["H7"]} /></Group>
        <Group className={at(f.shown >= 4)} label={tx("howto.trump.otherLevel", { n: <b>4</b> })}><Cards codes={["S7", "C7", "D7"]} tight /></Group>
      </div>
      <Group className={at(f.shown >= 5)} label={tx("howto.trump.rest", { n: <b>5</b> })}>
        <Cards codes={["HA", "HK", "HQ", "HJ", "H10", "H9", "H8", "H6", "H5", "H4", "H3", "H2"]} size="sm" tight />
      </Group>
    </>
  );
}

/* Declare to pick trump: one 7 is declared, then each stronger show
   replaces it (the gold outline marks the declaration standing). */
interface DeclareFrame { shown: number; standing: number | null }
const DECLARE_ROWS: { cards: string[]; what: MessageKey; trump: ReactNode }[] = [
  { cards: ["BJ", "BJ"], what: "howto.declare.bigJokers", trump: <Trump suit={null} rank="7" /> },
  { cards: ["LJ", "LJ"], what: "howto.declare.littleJokers", trump: <Trump suit={null} rank="7" /> },
  { cards: ["H7", "H7"], what: "howto.declare.pair", trump: <Trump suit="H" rank="7" /> },
  { cards: ["S7"], what: "howto.declare.single", trump: <Trump suit="S" rank="7" /> },
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
  const t = useT();
  const n = DECLARE_ROWS.length;
  return (
    <div className="howto-stack">
      <span className="howto-arrow-up" aria-hidden="true">{t("howto.declare.stronger")}</span>
      {DECLARE_ROWS.map((r, k) => (
        <div key={r.what} className={`howto-declare-row ${at(k >= n - f.shown)}${f.standing === k ? " standing" : ""}`}>
          <Cards codes={r.cards} size="sm" />
          <span className="howto-declare-what">{t(r.what)}</span>
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
  const t = useT();
  return (
    <>
      <Group label={t("howto.kitty.kitty")}>
        <div className={`howto-kitty-cards ${f.kitty}`}><Cards codes={Array(8).fill("")} faceDown size="sm" tight /></div>
      </Group>
      <span className="howto-arrow" aria-hidden="true">{t("howto.kitty.pickUp")}</span>
      <Group label={t("howto.kitty.bury")}>
        <Cards codes={KITTY_HAND} size="sm" lift={Array.from({ length: f.lifted }, (_, k) => k)} />
      </Group>
      <div className={`howto-row center ${at(f.teams)}`}>
        <span className="howto-pill def">{t("howto.kitty.defends")}</span>
        <span className="howto-pill att">{t("howto.kitty.attacks")}</span>
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

/** The example players' names, the same in every language. */
const SEAT_NAMES = { left: "Ana", top: "Bea", right: "Cal" };

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
  const t = useT();
  const trick = { leader: 1, plays: TRICK_PLAYS.slice(0, f.plays) } as unknown as Trick;
  return (
    <>
      <div className="howto-row center"><span className="howto-label">{t("howto.trick.trump")}</span><Trump suit="H" rank="7" /></div>
      <div className="replay-felt howto-felt" data-leading={f.leading ?? undefined}>
        <TrickArea state={TRICK_STATE} trick={f.plays ? trick : null} winner={f.winner} declaration={null} />
        <span className="howto-seat-name pos-left">{SEAT_NAMES.left}</span>
        <span className="howto-seat-name pos-top">{SEAT_NAMES.top}</span>
        <span className="howto-seat-name pos-right">{SEAT_NAMES.right}</span>
        <span className="howto-seat-name pos-bottom">{t("howto.trick.you")}</span>
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
  const t = useT();
  const s = f.shown;
  return (
    <>
      <div className="howto-order">
        <Group className={at(s >= 1)} label={t("howto.pairs.pair")}><Cards codes={["S9", "S9"]} tight /></Group>
        <Group className={at(s >= 2)} label={t("howto.pairs.tractor")}>
          <Cards codes={["S9", "S9", "S10", "S10"]} tight hide={s >= 3 ? [] : [2, 3]} />
        </Group>
        <Group className={at(s >= 4)} label={t("howto.pairs.levelTractor")} note={t("howto.pairs.levelNote")}>
          <Cards codes={["S6", "S6", "S8", "S8"]} tight />
        </Group>
      </div>
      <div className="howto-follow">
        <Group className={at(s >= 5)} label={t("howto.pairs.led")}><Cards codes={["DQ", "DQ"]} size="sm" tight /></Group>
        <span className={at(s >= 6, "howto-arrow side")} aria-hidden="true">→</span>
        <Group className={at(s >= 6)} label={t("howto.pairs.yours")} note={t("howto.pairs.mustPair")}>
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
  const t = useT();
  const s = f.shown;
  const fails = s >= 4;
  return (
    <>
      <div className="howto-follow">
        <Group className={at(s >= 1)} label={t("howto.throw.yours")}><Cards codes={["CA", "CQ", "CQ"]} tight /></Group>
        <span className={at(s >= 2, "howto-arrow side")} aria-hidden="true">{t("howto.throw.vs")}</span>
        {fails
          ? <Group key="fails" className="howto-in" label={t("howto.throw.someone")}><Cards codes={["CK", "CK"]} tight /></Group>
          : <Group key="stands" className={at(s >= 2)} label={t("howto.throw.nobody")}><Cards codes={["CK", "CJ"]} tight /></Group>}
      </div>
      {fails ? (
        <>
          <span key="fails-arrow" className={at(s >= 5, "howto-arrow")} aria-hidden="true">{t("howto.throw.fails")}</span>
          <Group key="fails-play" className={at(s >= 6)} label={t("howto.throw.failsPlay")}>
            <Cards codes={["CQ", "CQ"]} tight glow={[0, 1]} />
          </Group>
        </>
      ) : (
        <>
          <span key="stands-arrow" className={at(s >= 3, "howto-arrow")} aria-hidden="true">{t("howto.throw.stands")}</span>
          <Group key="stands-play" className={at(s >= 3)} label={t("howto.throw.standsPlay")}>
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
  const t = useT();
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
        <span className="howto-label">{t("howto.points.attackers")}</span>
        <span className="chip points-chip">
          <span className="points-big howto-count-up" key={points}>{points}</span>
          <span className="points-target">/ 80</span>
        </span>
      </div>
      <div className={`howto-kitty ${at(f.bonus)}`}>
        <span className="howto-kitty-head">{t("howto.points.bonusHead")}</span>
        <span>{t("howto.points.bonus")}</span>
        <span className="howto-kitty-mult">{tx("howto.points.multSingle", { n: <b>×2</b> })} · {tx("howto.points.multPair", { n: <b>×4</b> })} · {tx("howto.points.multTractor", { n: <b>×8</b> })}</span>
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
const OUTCOME: MessageKey[] = ["howto.score.def3", "howto.score.def2", "howto.score.def1",
  "howto.score.takeDeal", "howto.score.att1", "howto.score.att2"];

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
  const t = useT();
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
          {f.result ? <span className={`howto-pill ${won ? "att" : "def"} howto-result`}>{t(OUTCOME[band])}</span> : null}
        </div>
        <div className="howto-group">
          <span className="howto-label">{t("howto.points.attackers")}</span>
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
        {[0, 40, 80, 120, 160, 200].map((v) => <span key={v} style={{ left: `${v / 2}%` }}>{v}</span>)}
      </div>
      <ul className="howto-bands">
        {BANDS.map((b, i) => (
          <li key={b.text} className={`${b.side}${i === band && (f.haul !== null || f.result) ? " on" : ""}${i === band && f.result ? " final" : ""}`}>
            <span className="howto-band-pts">{b.text}</span>
            <span>{t(OUTCOME[i])}</span>
          </li>
        ))}
        <li className="att"><span className="howto-band-pts">200+</span><span>{t("howto.score.att3")}</span></li>
      </ul>
    </>
  );
}

/* Win a game: defending at Ace wins the game (a point on the games score),
   then both teams start again from 2. */
const WIN_FRAMES = count([300, 1100, 2000, 2700]);

function WinPicture({ f }: { f: CountFrame }) {
  const t = useT();
  const s = f.shown;
  return (
    <>
      <div className="howto-follow">
        <Group className={at(s >= 1)} label={t("howto.win.defendAce")}><Level team={0} level="A" /></Group>
        <span className={at(s >= 2, "howto-arrow side")} aria-hidden="true">→</span>
        <Group className={at(s >= 2)} label={t("howto.win.wins")}><Games us={1} them={0} /></Group>
      </div>
      <span className={at(s >= 3, "howto-arrow")} aria-hidden="true">{t("howto.win.again")}</span>
      <div className={`howto-row center ${at(s >= 4)}`}>
        <Level team={0} level="2" />
        <Level team={1} level="2" />
        <Games us={1} them={0} />
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
interface Step { titleKey: MessageKey; bodyKey: MessageKey; visual: ReactNode; captionKey?: MessageKey }

const STEPS: Step[] = [
  { titleKey: "howto.goal.title", bodyKey: "howto.goal.body", visual: picture(GOAL_FRAMES, (f) => <GoalPicture f={f} />) },
  { titleKey: "howto.trump.title", bodyKey: "howto.trump.body", visual: picture(TRUMP_FRAMES, (f) => <TrumpPicture f={f} />) },
  { titleKey: "howto.declare.title", bodyKey: "howto.declare.body", visual: picture(DECLARE_FRAMES, (f) => <DeclarePicture f={f} />) },
  { titleKey: "howto.kitty.title", bodyKey: "howto.kitty.body", visual: picture(KITTY_FRAMES, (f) => <KittyPicture f={f} />) },
  {
    titleKey: "howto.trick.title", bodyKey: "howto.trick.body",
    visual: picture(TRICK_FRAMES, (f) => <TrickPicture f={f} />),
    captionKey: "howto.trick.caption",
  },
  { titleKey: "howto.pairs.title", bodyKey: "howto.pairs.body", visual: picture(PAIRS_FRAMES, (f) => <PairsPicture f={f} />) },
  { titleKey: "howto.throw.title", bodyKey: "howto.throw.body", visual: picture(THROW_FRAMES, (f) => <ThrowPicture f={f} />) },
  { titleKey: "howto.points.title", bodyKey: "howto.points.body", visual: picture(POINTS_FRAMES, (f) => <PointsPicture f={f} />) },
  { titleKey: "howto.score.title", bodyKey: "howto.score.body", visual: picture(SCORE_FRAMES, (f) => <ScoringPicture f={f} />) },
  {
    titleKey: "howto.win.title", bodyKey: "howto.win.body",
    visual: picture(WIN_FRAMES, (f) => <WinPicture f={f} />),
    captionKey: "howto.win.caption",
  },
];

function Head({ count }: { count: ReactNode }) {
  const t = useT();
  return (
    <header className="howto-head">
      <button className="btn subtle games-back" onClick={closeHowto}>{t("howto.back")}</button>
      <h1 className="howto-page">{t("howto.page")}</h1>
      <span className="howto-count">{count}</span>
    </header>
  );
}

function Stepper({ step }: { step: number }) {
  const t = useT();
  const n = STEPS.length;
  const i = Math.min(Math.max(step, 1), n) - 1;
  const s = STEPS[i];
  const go = (to: number) => openHowto(Math.min(Math.max(to, 1), n));
  return (
    <div className="panel games-panel howto-panel">
      <Head count={t("howto.count", { n: i + 1, count: n })} />
      {/* Keyed by step, so a slide's picture starts afresh each time it is entered. */}
      <section key={i} className="howto-step" aria-roledescription="slide">
        <h2 className="howto-title">{t(s.titleKey)}</h2>
        <p className="howto-body">{t(s.bodyKey)}</p>
        {s.visual}
        <p className="howto-caption">{s.captionKey ? t(s.captionKey) : undefined}</p>
      </section>
      <nav className="howto-nav" aria-label={t("howto.steps")}>
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
            ? <button className="btn primary big" onClick={() => go(i + 2)}>{t("howto.next")}</button>
            : <button className="btn gold big" onClick={closeHowto}>{t("howto.startPlaying")}</button>}
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
  useScreen("howto");
  const swipe = useSwipe(route.step);
  return (
    <div className="screen lobby-screen howto-screen" {...swipe}>
      <Stepper step={route.step} />
    </div>
  );
}
