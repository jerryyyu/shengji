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
  // Play analysis was added after the original xray endpoint. Keep all of
  // these optional so a browser can still inspect an older server.
  attackers_avg?: number | null;
  se?: number | null;
  paired_se_vs_incumbent?: number | null;
  selection_worlds?: number | null;
  model_score?: number | null;
  old_ballot?: boolean | null;
  incumbent?: boolean | null;
  model_nominated?: boolean | null;
  heuristic_pick?: boolean;
  report_finalist?: boolean;
  bot_plays?: boolean;
}

interface XrayAnalysis {
  source?: string;
  historical_decision?: boolean;
  policy?: string;
  reason?: string;
  snapshot?: {
    trick_number?: number | null;
    plays_in_trick?: number | null;
    acting_seat?: number | null;
  } | null;
  model?: {
    backend?: string | null;
    checkpoint_sha256?: string | null;
    source_checkpoint_sha256?: string | null;
    encoding?: string | null;
    effective_encoding?: string | null;
    max_batch?: number | null;
    device?: string | null;
    encoder_version?: number | null;
  } | null;
  model_score_units?: string;
  selection_score_units?: string;
  report_gap_units?: string;
  report?: {
    gap?: number | null;
    se?: number | null;
    worlds?: number | null;
    critical?: number | null;
    statistic?: number | null;
    min_gain?: number | null;
    rule?: string;
    complete?: boolean | null;
  } | null;
  recipe?: {
    worlds?: number | null;
    alternatives?: number | null;
    selection_worlds?: number | null;
    batch_size?: number | null;
    report_worlds_requested?: number | null;
    report_min_gain?: number | null;
  } | null;
  shortlist?: {
    legal_count?: number | null;
    production_count?: number | null;
    wall_seconds?: number | null;
    retained_count?: number | null;
    offballot_played?: boolean;
  } | null;
  work?: {
    selection_rollouts?: number | null;
    report_rollouts?: number | null;
    total_rollouts?: number | null;
  } | null;
  search_seconds?: number | null;
  evaluation_seconds?: number | null;
  candidate_count?: number | null;
  candidates_truncated?: boolean;
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
  analysis?: XrayAnalysis | null;
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

function metric(value: number | null | undefined, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "unavailable";
}

function integerMetric(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? String(value)
    : "unavailable";
}

function seconds(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(3)}s`
    : "unavailable";
}

function Flag({ children }: { children: string }) {
  return <span className="xr-tag">{children}</span>;
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

        {data.analysis !== null && data.analysis !== undefined ? (
          <div className="xr-section">
            <div className="xr-head">play analysis</div>
            <div className="xr-dim">isolated current-state replay · not historical decision</div>
            {data.analysis.snapshot !== null && data.analysis.snapshot !== undefined ? (
              <div className="xr-dim">
                state trick {integerMetric(data.analysis.snapshot.trick_number)}
                {" · "}plays {integerMetric(data.analysis.snapshot.plays_in_trick)}
                {" · "}acting seat {integerMetric(data.analysis.snapshot.acting_seat)}
              </div>
            ) : null}
            <div className="xr-row">
              <span className="xr-label">policy</span>
              <span>{data.analysis.policy ?? "unavailable"}</span>
            </div>
            <div className="xr-row">
              <span className="xr-label">model backend</span>
              <span>{data.analysis.model?.backend ?? "unavailable"}</span>
            </div>
            <div className="xr-row">
              <span className="xr-label">package checkpoint</span>
              <span style={{ overflowWrap: "anywhere" }}>
                {data.analysis.model?.checkpoint_sha256 ?? "unavailable"}
              </span>
            </div>
            <div className="xr-row">
              <span className="xr-label">source checkpoint</span>
              <span style={{ overflowWrap: "anywhere" }}>
                {data.analysis.model?.source_checkpoint_sha256 ?? "unavailable"}
              </span>
            </div>
            <div className="xr-dim">
              recipe W={integerMetric(data.analysis.recipe?.worlds)}
              {" · "}K={integerMetric(data.analysis.recipe?.alternatives)}
              {" · "}N={integerMetric(data.analysis.recipe?.selection_worlds)}
              {" · "}R={integerMetric(data.analysis.recipe?.report_worlds_requested)}
            </div>
            <div className="xr-dim">
              W ranking worlds · K alternatives plus incumbent · N selection worlds · R report worlds
            </div>
            <div className="xr-dim">
              model score is not win probability; MC points use attacker perspective (defenders prefer fewer).
            </div>
            <div className="xr-dim">
              ranking {seconds(data.analysis.shortlist?.wall_seconds)}
              {" · "}search {seconds(data.analysis.search_seconds)}
              {" · "}evaluation {seconds(data.analysis.evaluation_seconds)}
            </div>
            <div className="xr-dim">
              rollouts: selection {integerMetric(data.analysis.work?.selection_rollouts)}
              {" · "}report {integerMetric(data.analysis.work?.report_rollouts)}
              {" · "}total {integerMetric(data.analysis.work?.total_rollouts)}
            </div>
            <div className="xr-dim">
              candidates {integerMetric(data.analysis.candidate_count)}
              {data.analysis.candidates_truncated ? (
                <>
                  {" · "}
                  {data.analysis.candidate_count !== null && data.analysis.candidate_count !== undefined && data.candidates !== null
                    ? `${Math.max(0, data.analysis.candidate_count - data.candidates.length)} truncated`
                    : "unavailable truncated"}
                </>
              ) : null}
            </div>
            {data.analysis.report !== null && data.analysis.report !== undefined ? (
              <>
                <div className="xr-row">
                  <span className="xr-label">report reason</span>
                  <span>{data.analysis.reason ?? "unavailable"}</span>
                </div>
                <div className="xr-dim">
                  gap {metric(data.analysis.report.gap)} acting-team points
                  {" · "}SE {metric(data.analysis.report.se)} acting-team points
                  {" · "}decision statistic {metric(data.analysis.report.statistic)} acting-team points
                  {" · "}min gain {metric(data.analysis.report.min_gain)} acting-team points
                </div>
                <div className="xr-dim">
                  rule {data.analysis.report.rule || "unavailable"}
                  {" · "}worlds {integerMetric(data.analysis.report.worlds)}
                  {" · "}complete {data.analysis.report.complete == null ? "unavailable" : String(data.analysis.report.complete)}
                  {" · "}gap is challenger minus incumbent, in acting-team points.
                </div>
              </>
            ) : (
              <div className="xr-dim">report unavailable · reason {data.analysis.reason ?? "unavailable"}</div>
            )}
          </div>
        ) : null}

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
                    <th>values</th>
                    <th>markers</th>
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
                      <td>
                        <div>MC avg · final attacker points: {metric(cand.attackers_avg)}</div>
                        <div>model · expected signed levels (acting team): {metric(cand.model_score)}</div>
                        <div>paired SE vs incumbent: {metric(cand.paired_se_vs_incumbent)}</div>
                        <div>selection worlds: {integerMetric(cand.selection_worlds)}</div>
                        <div>individual SE: {metric(cand.se)}</div>
                      </td>
                      <td>
                        {cand.old_ballot === true ? <Flag>old ballot</Flag> : null}
                        {cand.incumbent === true || (i === 0 && cand.heuristic_pick === true) ? (
                          <Flag>incumbent</Flag>
                        ) : null}
                        {cand.model_nominated === true ? <Flag>model nominated</Flag> : null}
                        {cand.heuristic_pick === true ? <Flag>heuristic</Flag> : null}
                        {cand.report_finalist === true ? <Flag>report finalist</Flag> : null}
                        {cand.bot_plays === true ? <span className="xr-tag bot">chosen</span> : null}
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
    <div className="xray-panel" style={{ width: 640 }}>
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
