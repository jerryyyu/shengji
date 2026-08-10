// Hidden debug overlay: "what would the bot do in my position".
//
// Activation (deliberately hidden, no visible UI for normal users): set the
// debug token manually in the devtools console —
//     localStorage.setItem("shengji.debug", "<SHENGJI_DEBUG_TOKEN>")
// then press "x" on the Table screen to toggle this panel. The server only
// answers /debug/xray when it was started with a matching SHENGJI_DEBUG_TOKEN.

import { useEffect, useState } from "react";
import type { GameState } from "../protocol";
import { SUIT_SYMBOL, isRedCode, shortLabel } from "./Card";

interface XrayCandidate {
  play: string[];
  attackers_avg: number;
  heuristic_pick: boolean;
  bot_plays: boolean;
}

interface XrayBuryCandidate {
  cards: string[];
  sources: string[];
  banker_avg: number | null;
  worlds: number;
  incumbent: boolean;
  raw_winner: boolean;
  bot_buries: boolean;
}

interface XrayBuryWork {
  cap?: number;
  worlds_requested?: number;
  worlds_used?: number;
  attempts?: number;
  attempt_cap?: number;
  candidate_rollouts?: number;
  complete?: boolean;
}

interface XrayBuryAnalysis {
  policy: string;
  mode: string;
  chosen: string[];
  reason: string;
  fallback: boolean;
  margin: number | null;
  gap_vs_incumbent: number | null;
  search_secs: number;
  work: XrayBuryWork | null;
  sampler_delta: Record<string, number> | null;
  candidates: XrayBuryCandidate[];
}

interface XrayData {
  seat: number;
  hand: string[];
  is_attacker: boolean | null;
  voids: Record<string, string[]>;
  unseen_trumps: number;
  unseen_by_suit: Record<string, string[]>;
  boss_cards: string[];
  ruff_risky_suits: string[];
  candidates: XrayCandidate[] | null;
  bury: XrayBuryAnalysis | null;
}

type XrayResp = XrayData | { error: string };

function isError(r: XrayResp): r is { error: string } {
  return "error" in r;
}

/** Card code rendered with a suit symbol, colored like the rest of the app. */
function CodeSpan({ c, boss }: { c: string; boss?: boolean }) {
  return (
    <span className={`xr-code ${isRedCode(c) ? "red" : "black"}${boss ? " boss" : ""}`}>
      {shortLabel(c)}
    </span>
  );
}

function SuitSpan({ s }: { s: string }) {
  if (s === "T") return <span className="xr-suit trump">T</span>;
  const red = s === "H" || s === "D";
  return <span className={`xr-suit ${red ? "red" : "black"}`}>{SUIT_SYMBOL[s] ?? s}</span>;
}

export default function XrayPanel({ state, onClose }: { state: GameState; onClose: () => void }) {
  const [data, setData] = useState<XrayResp | null>(null);
  const room = state.room;
  const seat = state.you;

  // Fetch fresh on every open (the panel unmounts when toggled closed).
  useEffect(() => {
    let cancelled = false;
    const token = localStorage.getItem("shengji.debug") ?? "";
    // Same origin as the WS: the vite dev server proxies nothing, so target
    // the backend port directly in dev.
    const base = import.meta.env.DEV ? `http://${location.hostname}:8000` : "";
    const url = `${base}/debug/xray?room=${encodeURIComponent(room)}&seat=${seat}&token=${encodeURIComponent(token)}`;
    fetch(url)
      .then((r) => r.json() as Promise<XrayResp>)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setData({ error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [room, seat]);

  const nameOf = (s: number) => state.players.find((p) => p.seat === s)?.name ?? `Seat ${s}`;

  let body;
  if (data === null) {
    body = <div className="xr-dim">loading…</div>;
  } else if (isError(data)) {
    body = <div className="xr-error">{data.error}</div>;
  } else {
    const boss = new Set(data.boss_cards);
    body = (
      <>
        <div className="xr-section">
          <div className="xr-head">
            hand ({data.hand.length})
            {data.is_attacker !== null ? (
              <span className="xr-dim"> — {data.is_attacker ? "attacker" : "defender"}</span>
            ) : null}
          </div>
          <div className="xr-cards">
            {data.hand.map((c, i) => (
              <CodeSpan key={i} c={c} boss={boss.has(c)} />
            ))}
          </div>
        </div>

        <div className="xr-section">
          <div className="xr-head">boss cards</div>
          <div className="xr-cards">
            {data.boss_cards.length > 0 ? (
              data.boss_cards.map((c, i) => <CodeSpan key={i} c={c} boss />)
            ) : (
              <span className="xr-dim">none</span>
            )}
          </div>
        </div>

        <div className="xr-section">
          <div className="xr-head">voids</div>
          {Object.entries(data.voids).map(([s, suits]) => (
            <div key={s} className="xr-row">
              <span className="xr-label">{nameOf(Number(s))}</span>
              {suits.length > 0 ? (
                suits.map((su, i) => <SuitSpan key={i} s={su} />)
              ) : (
                <span className="xr-dim">—</span>
              )}
            </div>
          ))}
        </div>

        <div className="xr-section">
          <div className="xr-head">
            unseen <span className="xr-dim">(trumps: {data.unseen_trumps})</span>
          </div>
          {Object.entries(data.unseen_by_suit).map(([s, codes]) => (
            <div key={s} className="xr-row">
              <SuitSpan s={s} />
              <span className="xr-cards">
                {codes.length > 0 ? (
                  codes.map((c, i) => <CodeSpan key={i} c={c} boss={boss.has(c)} />)
                ) : (
                  <span className="xr-dim">—</span>
                )}
              </span>
            </div>
          ))}
        </div>

        <div className="xr-section">
          <div className="xr-head">ruff-risky suits</div>
          <div className="xr-cards">
            {data.ruff_risky_suits.length > 0 ? (
              data.ruff_risky_suits.map((s, i) => <SuitSpan key={i} s={s} />)
            ) : (
              <span className="xr-dim">none</span>
            )}
          </div>
        </div>

        {data.bury !== null ? (
          <div className="xr-section">
            <div className="xr-head">
              kitty bury — {data.bury.policy} / {data.bury.mode}
            </div>
            <div className="xr-row">
              <span className="xr-label">chosen</span>
              <span className="xr-cards">
                {data.bury.chosen.map((c, i) => <CodeSpan key={i} c={c} />)}
              </span>
              {data.bury.fallback ? <span className="xr-tag">fallback</span> : null}
            </div>
            <div className="xr-row">
              <span className="xr-label">reason</span>
              <span>{data.bury.reason}</span>
            </div>
            {data.bury.work === null ? (
              <div className="xr-dim">heuristic decision — no rollout search</div>
            ) : (
              <div className="xr-dim">
                {data.bury.work.worlds_used ?? 0}/{data.bury.work.worlds_requested ?? 0} worlds
                {" · "}{data.bury.work.candidate_rollouts ?? 0} candidate rollouts
                {" · "}{data.bury.search_secs.toFixed(3)}s
                {data.bury.work.complete === false ? " · underfilled" : ""}
              </div>
            )}
            {data.bury.sampler_delta !== null ? (
              <div className="xr-dim">
                sampler: {data.bury.sampler_delta.accepted_worlds ?? 0} accepted /
                {" "}{data.bury.sampler_delta.sample_attempts ?? 0} attempts
                {" · "}{data.bury.sampler_delta.failed_worlds ?? 0} failed
                {" · "}{data.bury.sampler_delta.rejected_worlds ?? 0} rejected
              </div>
            ) : null}
            <table className="xr-table">
              <thead>
                <tr>
                  <th>bury</th>
                  <th>banker avg</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.bury.candidates.map((cand, i) => (
                  <tr key={i} className={cand.bot_buries ? "bot" : ""}>
                    <td>
                      {cand.cards.map((c, j) => (
                        <CodeSpan key={j} c={c} />
                      ))}
                    </td>
                    <td className="xr-num">
                      {cand.banker_avg === null ? "—" : cand.banker_avg.toFixed(1)}
                    </td>
                    <td>
                      {cand.incumbent ? <span className="xr-tag">incumbent</span> : null}
                      {cand.raw_winner ? <span className="xr-tag">raw best</span> : null}
                      {cand.bot_buries ? <span className="xr-tag bot">BOT</span> : null}
                      {cand.sources.length > 0 ? (
                        <span className="xr-tag" title={cand.sources.join(", ")}>
                          {cand.sources.join("+")}
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="xr-section">
            <div className="xr-head">play candidates</div>
            {data.candidates === null ? (
              <div className="xr-dim">press x on your play turn for candidate analysis</div>
            ) : (
              <table className="xr-table">
                <thead>
                  <tr>
                    <th>play</th>
                    <th>atk avg</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.map((cand, i) => (
                    <tr key={i} className={cand.bot_plays ? "bot" : ""}>
                      <td>
                        {cand.play.map((c, j) => (
                          <CodeSpan key={j} c={c} />
                        ))}
                      </td>
                      <td className="xr-num">{cand.attackers_avg.toFixed(1)}</td>
                      <td>
                        {cand.heuristic_pick ? <span className="xr-tag">heuristic</span> : null}
                        {cand.bot_plays ? <span className="xr-tag bot">BOT</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </>
    );
  }

  return (
    <div className="xray-panel">
      <div className="xr-titlebar">
        <span>
          xray — {room} seat {seat}
        </span>
        <button className="xr-close" onClick={onClose} title="Close (or press x)">
          ×
        </button>
      </div>
      {body}
    </div>
  );
}
