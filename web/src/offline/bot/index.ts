// Offline bots: TypeScript ports of shengji/ai/heuristic.py (HeuristicBot) and
// shengji/ai/smart.py (SmartBot), held to the Python bots decision for decision
// by fixtures from server/scripts/gen_offline_bot_fixtures.py. A bot sees only
// a BotView: its own hand and public information.
export { HeuristicBot, declareOptions } from "./heuristic";
export { SmartBot } from "./smart";
export { Memory } from "./memory";
export { type BotView, type PublicTrick, viewFor } from "./view";
