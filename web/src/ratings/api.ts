// Ratings: the leaderboard, the account's own stats and its leaderboard
// opt-out. Same-origin requests, so the session cookie goes along; a 401
// means signed out.

export interface LeaderRow {
  rank: number | null;
  name: string;
  rating: number;
  rounds: number;
  levels_per_round: number;
  week_delta: number;
  provisional: boolean;
  you: boolean;
  /** Only on the viewer's own row: whether they show to others. */
  visible?: boolean;
}

export type Period = "week" | "all";

export interface Leaderboard {
  period: Period;
  players: LeaderRow[];
  me: LeaderRow | null;
  anchor: { name: string; rating: number };
}

export interface RecentGame {
  started_at: number;
  ended_at: number;
  rounds: number;
  delta: number;
  games_won: number;
  partner: string | null;
  partner_bot: boolean;
  opponents_bots: number;
}

export interface MyStats {
  name: string;
  rating: number;
  rank: number | null;
  rounds: number;
  provisional: boolean;
  levels_per_round: number | null;
  won_pct: number | null;
  defender_won_pct: number | null;
  attacker_won_pct: number | null;
  best_streak: number;
  games_won: number;
  week_delta: number;
  history: number[];
  recent_games: RecentGame[];
  visible: boolean;
}

export type Loaded<T> =
  | { ok: true; data: T }
  | { ok: false; reason: "signed_out" | "error"; status: number };

async function getJson<T>(path: string): Promise<Loaded<T>> {
  let resp: Response;
  try {
    resp = await fetch(path, { credentials: "same-origin" });
  } catch {
    return { ok: false, reason: "error", status: 0 };
  }
  if (resp.status === 401) return { ok: false, reason: "signed_out", status: 401 };
  if (resp.status !== 200) return { ok: false, reason: "error", status: resp.status };
  try {
    return { ok: true, data: (await resp.json()) as T };
  } catch {
    return { ok: false, reason: "error", status: resp.status };
  }
}

export function fetchLeaderboard(period: Period): Promise<Loaded<Leaderboard>> {
  return getJson<Leaderboard>(`/api/leaderboard?period=${period}`);
}

export function fetchStats(): Promise<Loaded<MyStats>> {
  return getJson<MyStats>("/api/me/stats");
}

/** Show or hide the account on the leaderboard; resolves with the stored
 *  choice, throws when the server did not take it. */
export async function setVisibility(visible: boolean): Promise<boolean> {
  let resp: Response;
  try {
    resp = await fetch("/api/me/leaderboard-visibility", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible }),
    });
  } catch {
    throw new Error("Could not save: no connection.");
  }
  if (resp.status !== 200) throw new Error(`Could not save (${resp.status}).`);
  const body = (await resp.json()) as { visible: boolean };
  return body.visible;
}

/** "▲ 12", "▼ 8" or "±0" for a whole-point rating change. */
export function deltaText(delta: number): string {
  if (delta > 0) return `▲ ${delta}`;
  if (delta < 0) return `▼ ${Math.abs(delta)}`;
  return "±0";
}

/** "+0.31", "−0.04": a signed figure with a real minus sign. */
export function signed(value: number, digits = 2): string {
  const text = Math.abs(value).toFixed(digits);
  if (value > 0) return `+${text}`;
  if (value < 0) return `−${text}`;
  return text;
}
