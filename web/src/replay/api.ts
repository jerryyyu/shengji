// Saved games ("My games"): the account's game history and per-round
// replays. Same-origin requests, so the session cookie goes along as it does
// for `/api/me`. A 401 means signed out; a 404 means the game or round is
// not this account's to read (the server never distinguishes the two).
import type { RoundReplayDoc } from "./reducer";

export interface GameRow {
  id: string;
  room_code: string;
  /** Unix seconds. */
  started_at: number;
  ended_at: number | null;
  /** The viewer's seat. */
  seat: number;
  /** Names by seat. */
  players: string[];
  /** Round numbers this account may replay. */
  rounds: number[];
  final_levels: unknown;
  games_won: unknown;
  incomplete: boolean;
}

export interface GameDetail extends GameRow {
  round_results: { round: number; seat: number; result: Record<string, unknown> }[];
}

export interface GamesPage {
  games: GameRow[];
  next_before: number | null;
}

export type Fetched<T> =
  | { ok: true; data: T }
  | { ok: false; reason: "signed_out" | "not_found" | "error"; status: number };

export const PAGE_SIZE = 20;

async function getJson<T>(path: string): Promise<Fetched<T>> {
  let resp: Response;
  try {
    resp = await fetch(path, { credentials: "same-origin" });
  } catch {
    return { ok: false, reason: "error", status: 0 };
  }
  if (resp.status === 401) return { ok: false, reason: "signed_out", status: 401 };
  if (resp.status === 404) return { ok: false, reason: "not_found", status: 404 };
  if (resp.status !== 200) return { ok: false, reason: "error", status: resp.status };
  try {
    return { ok: true, data: (await resp.json()) as T };
  } catch {
    return { ok: false, reason: "error", status: resp.status };
  }
}

export function fetchGames(before: number | null, limit = PAGE_SIZE): Promise<Fetched<GamesPage>> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (before !== null) q.set("before", String(before));
  return getJson<GamesPage>(`/api/me/games?${q.toString()}`);
}

export function fetchGame(id: string): Promise<Fetched<GameDetail>> {
  return getJson<GameDetail>(`/api/me/games/${encodeURIComponent(id)}`);
}

export function fetchRound(id: string, round: number): Promise<Fetched<RoundReplayDoc>> {
  return getJson<RoundReplayDoc>(`/api/me/games/${encodeURIComponent(id)}/rounds/${round}`);
}

/** Hide a game from this account's history. Resolves on 204 (or 404: it is
 *  already gone); throws otherwise so the caller can say it failed. */
export async function removeGame(id: string): Promise<void> {
  let status: number;
  try {
    ({ status } = await fetch(`/api/me/games/${encodeURIComponent(id)}`,
                              { method: "DELETE", credentials: "same-origin" }));
  } catch {
    throw new Error("Could not remove the game: no connection.");
  }
  if (status === 401) throw new Error("Sign in to change your history.");
  if (status !== 204 && status !== 200 && status !== 404) {
    throw new Error(`Could not remove the game (${status}).`);
  }
}

/** A per-team pair from the summary's JSON: `[a, b]`, `{"0": a, "1": b}` or
 *  `{"team0": a, "team1": b}`. Null when the shape is not one of these. */
export function teamPair(v: unknown): [string, string] | null {
  if (v === null || v === undefined) return null;
  if (Array.isArray(v) && v.length >= 2) return [String(v[0]), String(v[1])];
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const a = o["0"] ?? o.team0;
    const b = o["1"] ?? o.team1;
    if (a !== undefined && b !== undefined) return [String(a), String(b)];
  }
  return null;
}
