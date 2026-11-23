// Demo data for the mocks: no real players.
export const ME = { name: "Cheerful Tractor", email: "demo@example.com", picture: null, display_name: "Cheerful Tractor", name_shown: "Cheerful Tractor", rounds_played: 86, linked: true };
const names = ["Lucky Dragon", "Quiet Panda", "Swift Tiger", "Brave Lotus", "Cheerful Tractor", "Golden Crane", "Jade Rabbit", "Silver Fox", "Happy Dumpling", "Red Lantern", "Calm River", "Bold Phoenix"];
export const BOARD = (period) => ({
  period,
  players: names.map((n, i) => ({ rank: i + 1, name: n, rating: i === 4 ? 1212 : 1312 - i * 23 - (i % 3) * 4, rounds: 240 - i * 13, levels_per_round: +(0.62 - i * 0.031).toFixed(2), week_delta: [18, 9, -4, 12, 7, 0, -11, 5, 3, -2, 6, 1][i], provisional: i === 11, you: n === "Cheerful Tractor" })),
  me: { rank: 5, name: "Cheerful Tractor", rating: 1212, rounds: 188, levels_per_round: 0.5, week_delta: 7, provisional: false, you: true, visible: true },
  anchor: { name: "Sheng Ji bot", rating: 1000 },
});
export const STATS = {
  name: "Cheerful Tractor", rating: 1212, rank: 5, rounds: 188, provisional: false, levels_per_round: 0.5, won_pct: 54, defender_won_pct: 61, attacker_won_pct: 47,
  best_streak: 6, games_won: 9, week_delta: 7,
  history: [1000, 1012, 1030, 1021, 1044, 1060, 1075, 1068, 1090, 1110, 1131, 1125, 1150, 1170, 1162, 1188, 1205, 1212],
  recent_games: [], visible: true,
};
export async function mockApi(ctx, { signedIn }) {
  await ctx.route(/accounts\.google\.com|appleid\.cdn-apple\.com/, (r) => r.abort());
  await ctx.route("**/api/leaderboard?**", (r) => r.fulfill({ json: BOARD(new URL(r.request().url()).searchParams.get("period") ?? "week") }));
  if (signedIn) {
    await ctx.route("**/api/auth/config", (r) => r.fulfill({ json: { google_client_id: "demo.apps.googleusercontent.com", device_accounts: false } }));
    await ctx.route("**/api/me", (r) => r.fulfill({ json: ME }));
    await ctx.route("**/api/me/stats", (r) => r.fulfill({ json: STATS }));
  }
}
