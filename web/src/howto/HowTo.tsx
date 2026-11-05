import { useRef } from "react";
import type { ReactNode } from "react";
import type { GameState, Trick } from "../protocol";
import Card from "../components/Card";
import TrickArea from "../components/TrickArea";
import { closeHowto, openHowto } from "./route";
import type { HowtoRoute } from "./route";

const RANK_LADDER = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];

/** A row of real table cards. `glow` marks cards by index with the winner ring. */
function Cards({ codes, size = "md", tight = false, glow = [], lift = [], faceDown = false }: {
  codes: string[]; size?: "sm" | "md" | "lg"; tight?: boolean; glow?: number[]; lift?: number[]; faceDown?: boolean;
}) {
  return (
    <div className={`howto-cards ${size}${tight ? " tight" : ""}`}>
      {codes.map((c, i) => (
        <Card key={i} code={faceDown ? undefined : c}
              className={[glow.includes(i) ? "glow" : "", lift.includes(i) ? "lifted" : ""].filter(Boolean).join(" ")} />
      ))}
    </div>
  );
}

function Group({ label, children, note }: { label?: ReactNode; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="howto-group">
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

function GoalVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-seats">
        <span className="replay-seat team0 you pos-bottom"><span className="replay-seat-name">You</span></span>
        <span className="replay-seat team1 pos-left"><span className="replay-seat-name">Ana</span></span>
        <span className="replay-seat team0 pos-top"><span className="replay-seat-name">Bea · partner</span></span>
        <span className="replay-seat team1 pos-right"><span className="replay-seat-name">Cal</span></span>
        <span className="howto-seats-mark" aria-hidden="true">升级</span>
      </div>
      <div className="howto-ladder" aria-label="Levels 2 to Ace">
        {RANK_LADDER.map((r) => (
          <span key={r} className={`howto-rung${r === "A" ? " finish" : ""}`}>
            {r}
            {r === "5" ? <span className="team-dot t0" /> : null}
            {r === "3" ? <span className="team-dot t1" /> : null}
          </span>
        ))}
      </div>
      <div className="howto-row center">
        <Level team={0} level="5" />
        <Level team={1} level="3" />
      </div>
    </div>
  );
}

function TrumpVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-row center"><span className="howto-label">Example</span><Trump suit="H" rank="7" /></div>
      <div className="howto-order">
        <Group label={<><b>1</b> Big Joker</>}><Cards codes={["BJ"]} /></Group>
        <Group label={<><b>2</b> Little Joker</>}><Cards codes={["LJ"]} /></Group>
        <Group label={<><b>3</b> ♥7</>}><Cards codes={["H7"]} /></Group>
        <Group label={<><b>4</b> other 7s, equal</>}><Cards codes={["S7", "C7", "D7"]} tight /></Group>
      </div>
      <Group label={<><b>5</b> then the rest of ♥, Ace down to 2</>}>
        <Cards codes={["HA", "HK", "HQ", "HJ", "H10", "H9", "H8", "H6", "H5", "H4", "H3", "H2"]} size="sm" tight />
      </Group>
    </div>
  );
}

function DeclareVisual() {
  const rows: { cards: string[]; what: string; trump: ReactNode }[] = [
    { cards: ["BJ", "BJ"], what: "Pair of Big Jokers", trump: <Trump suit={null} rank="7" /> },
    { cards: ["LJ", "LJ"], what: "Pair of Little Jokers", trump: <Trump suit={null} rank="7" /> },
    { cards: ["H7", "H7"], what: "Pair of 7s", trump: <Trump suit="H" rank="7" /> },
    { cards: ["S7"], what: "One 7", trump: <Trump suit="S" rank="7" /> },
  ];
  return (
    <div className="howto-visual">
      <div className="howto-stack">
        <span className="howto-arrow-up" aria-hidden="true">stronger ↑</span>
        {rows.map((r) => (
          <div key={r.what} className="howto-declare-row">
            <Cards codes={r.cards} size="sm" />
            <span className="howto-declare-what">{r.what}</span>
            {r.trump}
          </div>
        ))}
      </div>
    </div>
  );
}

function KittyVisual() {
  return (
    <div className="howto-visual">
      <Group label="The kitty: 8 cards, face down">
        <Cards codes={Array(8).fill("")} faceDown size="sm" tight />
      </Group>
      <span className="howto-arrow" aria-hidden="true">↓ the banker picks it up</span>
      <Group label="…then picks 8 of their 33 cards to bury">
        <Cards codes={["S3", "S4", "S6", "C2", "C6", "C8", "D3", "D9", "HK", "HA", "S7", "BJ"]}
               size="sm" lift={[0, 1, 2, 3, 4, 5, 6, 7]} />
      </Group>
      <div className="howto-row center">
        <span className="howto-pill def">Banker's team defends</span>
        <span className="howto-pill att">Other team attacks</span>
      </div>
    </div>
  );
}

const TRICK_STATE = {
  you: 0,
  hand: [],
  players: [
    { seat: 0, name: "You" }, { seat: 1, name: "Ana" }, { seat: 2, name: "Bea" }, { seat: 3, name: "Cal" },
  ],
} as unknown as GameState;

const TRICK: Trick = {
  leader: 1,
  plays: [
    { seat: 1, cards: ["SK"] },
    { seat: 2, cards: ["SA"] },
    { seat: 3, cards: ["H4"] },
    { seat: 0, cards: ["S2"] },
  ],
} as unknown as Trick;

function TrickVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-row center"><span className="howto-label">Trump</span><Trump suit="H" rank="7" /></div>
      <div className="replay-felt howto-felt">
        <TrickArea state={TRICK_STATE} trick={TRICK} winner={3} declaration={null} />
        <span className="howto-seat-name pos-left">Ana</span>
        <span className="howto-seat-name pos-top">Bea</span>
        <span className="howto-seat-name pos-right">Cal</span>
        <span className="howto-seat-name pos-bottom">You</span>
      </div>
    </div>
  );
}

function PairsVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-order">
        <Group label="Pair"><Cards codes={["S9", "S9"]} tight /></Group>
        <Group label="Tractor"><Cards codes={["S9", "S9", "S10", "S10"]} tight /></Group>
        <Group label="Tractor at level 7" note="the 7 is trump, so 6 and 8 touch">
          <Cards codes={["S6", "S6", "S8", "S8"]} tight />
        </Group>
      </div>
      <div className="howto-follow">
        <Group label="Led"><Cards codes={["DQ", "DQ"]} size="sm" tight /></Group>
        <span className="howto-arrow side" aria-hidden="true">→</span>
        <Group label="Your diamonds" note="you must play the pair">
          <Cards codes={["D5", "D5", "D9", "DJ"]} size="sm" tight glow={[0, 1]} />
        </Group>
      </div>
    </div>
  );
}

function ThrowVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-follow">
        <Group label="You throw ♣A and ♣Q♣Q"><Cards codes={["CA", "CQ", "CQ"]} tight /></Group>
        <span className="howto-arrow side" aria-hidden="true">vs</span>
        <Group label="Someone holds ♣K♣K"><Cards codes={["CK", "CK"]} tight /></Group>
      </div>
      <span className="howto-arrow" aria-hidden="true">↓ the throw fails</span>
      <Group label="You must play only the part that can be beaten">
        <Cards codes={["CQ", "CQ"]} tight glow={[0, 1]} />
      </Group>
    </div>
  );
}

function PointsVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-order">
        <Group label={<span className="win-tag">5</span>}><Cards codes={["H5"]} size="lg" glow={[0]} /></Group>
        <Group label={<span className="win-tag">10</span>}><Cards codes={["S10"]} size="lg" glow={[0]} /></Group>
        <Group label={<span className="win-tag">10</span>}><Cards codes={["DK"]} size="lg" glow={[0]} /></Group>
      </div>
      <div className="howto-row center">
        <span className="howto-label">Attackers</span>
        <span className="chip points-chip">
          <span className="points-big">65</span>
          <span className="points-target">/ 80</span>
        </span>
      </div>
      <div className="howto-kitty">
        <span className="howto-kitty-head">Last trick bonus</span>
        <span>If attackers win the last trick, they also score the kitty's points, multiplied by twice the cards led:</span>
        <span className="howto-kitty-mult"><b>×2</b> single · <b>×4</b> pair · <b>×8</b> tractor of 2 pairs</span>
      </div>
    </div>
  );
}

const BANDS: { from: number; to: number; text: string; side: "def" | "att" }[] = [
  { from: 0, to: 5, text: "0", side: "def" },
  { from: 5, to: 40, text: "5–35", side: "def" },
  { from: 40, to: 80, text: "40–75", side: "def" },
  { from: 80, to: 120, text: "80–115", side: "att" },
  { from: 120, to: 160, text: "120–155", side: "att" },
  { from: 160, to: 200, text: "160–195", side: "att" },
];

function ScoringVisual() {
  const outcome = ["Defenders +3", "Defenders +2", "Defenders +1",
    "Attackers take the deal", "Attackers +1", "Attackers +2"];
  return (
    <div className="howto-visual">
      <div className="howto-scale" aria-hidden="true">
        {BANDS.map((b) => (
          <span key={b.text} className={`howto-band ${b.side}`} style={{ flexGrow: b.to - b.from }} />
        ))}
        <span className="howto-scale-line" style={{ left: "40%" }}><span>80</span></span>
      </div>
      <div className="howto-ticks" aria-hidden="true">
        {[0, 40, 80, 120, 160, 200].map((t) => <span key={t} style={{ left: `${t / 2}%` }}>{t}</span>)}
      </div>
      <ul className="howto-bands">
        {BANDS.map((b, i) => (
          <li key={b.text} className={b.side}>
            <span className="howto-band-pts">{b.text}</span>
            <span>{outcome[i]}</span>
          </li>
        ))}
        <li className="att"><span className="howto-band-pts">200+</span><span>Attackers +3, and +1 per 40 more</span></li>
      </ul>
    </div>
  );
}

function WinVisual() {
  return (
    <div className="howto-visual">
      <div className="howto-follow">
        <Group label="Your team defends at Ace…"><Level team={0} level="A" /></Group>
        <span className="howto-arrow side" aria-hidden="true">→</span>
        <Group label="…and wins a game"><Level team={0} level="A" star={1} /></Group>
      </div>
      <span className="howto-arrow" aria-hidden="true">↓ both teams start again</span>
      <div className="howto-row center">
        <Level team={0} level="2" star={1} />
        <Level team={1} level="2" />
      </div>
    </div>
  );
}

/** One step: a headline, a line or two of rules, a picture and an optional
 *  caption under it. The text here is the guide's copy. */
interface Step { title: string; body: ReactNode; visual: ReactNode; caption?: ReactNode }

const STEPS: Step[] = [
  {
    title: "Climb from 2 to Ace",
    body: <>Four players in two teams: you and the partner across from you. Win rounds to climb levels from 2 up to Ace.</>,
    visual: <GoalVisual />,
  },
  {
    title: "Trump beats everything",
    body: <>The level card's rank and the jokers are always trump. One suit is trump too. Highest trump first:</>,
    visual: <TrumpVisual />,
  },
  {
    title: "Declare to pick trump",
    body: <>While the cards are dealt, show a card of the level's rank to make its suit trump. A stronger show replaces it; a joker pair means no trump suit.</>,
    visual: <DeclareVisual />,
  },
  {
    title: "Banker and kitty",
    body: <>The banker picks up the 8 leftover cards, then buries any 8 face down. The banker leads the first trick.</>,
    visual: <KittyVisual />,
  },
  {
    title: "Play a trick",
    body: <>Follow the led suit if you can. The highest card of that suit wins, unless someone out of it plays trump. The winner leads next.</>,
    visual: <TrickVisual />,
    caption: <>Ana leads ♠K. Bea plays ♠A, but Cal has no spades and plays ♥4: trump wins.</>,
  },
  {
    title: "Pairs and tractors",
    body: <>Two identical cards are a pair; pairs next to each other are a tractor. When a pair is led, you must answer with a pair of that suit if you have one.</>,
    visual: <PairsVisual />,
  },
  {
    title: "Throws",
    body: <>You may lead several cards of one suit at once. If another player could beat any part of it, the throw fails.</>,
    visual: <ThrowVisual />,
  },
  {
    title: "Points",
    body: <>Only 5s, 10s and Kings score: 200 points in all. Attackers keep the points in the tricks they win.</>,
    visual: <PointsVisual />,
  },
  {
    title: "Scoring a round",
    body: <>Attackers need 80 to win the round. Every 40 points either way moves a level.</>,
    visual: <ScoringVisual />,
  },
  {
    title: "Win a game",
    body: <>Reach Ace, then defend it as the banker's team. Winning as attackers at Ace only takes the deal.</>,
    visual: <WinVisual />,
    caption: <>The ★ on your level chip counts games won. The table keeps playing.</>,
  },
];

function Head({ count }: { count: ReactNode }) {
  return (
    <header className="howto-head">
      <button className="btn subtle games-back" onClick={closeHowto}>‹ Lobby</button>
      <span className="howto-page">How to play</span>
      <span className="howto-count">{count}</span>
    </header>
  );
}

function Stepper({ step }: { step: number }) {
  const n = STEPS.length;
  const i = Math.min(Math.max(step, 1), n) - 1;
  const s = STEPS[i];
  const touch = useRef<{ x: number; y: number } | null>(null);
  const go = (to: number) => openHowto(Math.min(Math.max(to, 1), n));
  return (
    <div className="panel games-panel howto-panel">
      <Head count={`${i + 1} of ${n}`} />
      <section className="howto-step" aria-roledescription="slide"
               onTouchStart={(e) => {
                 touch.current = e.touches.length === 1
                   ? { x: e.touches[0].clientX, y: e.touches[0].clientY } : null;
               }}
               onTouchMove={(e) => { if (e.touches.length !== 1) touch.current = null; }}
               onTouchCancel={() => { touch.current = null; }}
               onTouchEnd={(e) => {
                 const start = touch.current; touch.current = null;
                 if (start === null || e.changedTouches.length !== 1) return;
                 const dx = e.changedTouches[0].clientX - start.x;
                 const dy = e.changedTouches[0].clientY - start.y;
                 if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) go(i + 1 + (dx < 0 ? 1 : -1));
               }}>
        <h2 className="howto-title">{s.title}</h2>
        <p className="howto-body">{s.body}</p>
        {s.visual}
        <p className="howto-caption">{s.caption}</p>
      </section>
      <nav className="howto-nav" aria-label="Steps">
        <div className="howto-dots">
          {STEPS.map((_, k) => (
            <button key={k} className={`howto-dot${k === i ? " on" : ""}`}
                    aria-label={`Step ${k + 1}`} aria-current={k === i ? "step" : undefined} onClick={() => go(k + 1)} />
          ))}
        </div>
        <div className="howto-buttons">
          <button className="btn big" disabled={i === 0} onClick={() => go(i)}>Back</button>
          {i < n - 1
            ? <button className="btn primary big" onClick={() => go(i + 2)}>Next</button>
            : <button className="btn gold big" onClick={closeHowto}>Start playing</button>}
        </div>
      </nav>
    </div>
  );
}

export default function HowTo({ route }: { route: HowtoRoute }) {
  return (
    <div className="screen lobby-screen howto-screen">
      <Stepper step={route.step} />
    </div>
  );
}
