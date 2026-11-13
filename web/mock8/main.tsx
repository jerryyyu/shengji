// Mock harness for proposal 8: a following hand against a 3-card diamond lead.
import { createRoot } from "react-dom/client";
import "../src/index.css";
import Table from "../src/components/Table";
import { conn } from "../src/ws";
import type { GameState, HandCard, StatePlayer } from "../src/protocol";

(conn as unknown as { status: string }).status = "open";
(conn as unknown as { send: (m: unknown) => boolean }).send = (m) => { console.log("SEND", JSON.stringify(m)); return false; };

const codes = ["C4", "C6", "C9", "CJ", "CQ", "D3", "D7", "D10", "H3", "H6", "H8", "HJ", "HK",
               "S4", "S6", "S9", "SQ", "SA", "H2", "C2", "SJ", "BJ", "S5", "C5", "H10"];
const hand: HandCard[] = codes.map((code, id) => ({ id: id + 1, code }));
const pl = (seat: number, name: string, team: 0 | 1): StatePlayer => ({
  seat, name, is_bot: seat !== 0, connected: true, team, cards_left: 25,
  is_banker: seat === 1, takeover_in: null, controller: seat === 0 ? "human" : "bot",
  reserved_for: null, reserved_secs: null,
} as StatePlayer);
const state = {
  type: "state", room: "MOCK", you: 0, phase: "play",
  players: [pl(0, "You", 0), pl(1, "Bot 1", 1), pl(2, "Bot 2", 0), pl(3, "Bot 3", 1)],
  hand, levels: ["2", "2"], games_won: [0, 0], banker: 1,
  trump: { suit: "S", rank: "2", declarer: 1 },
  turn: 0, declare_options: [], current_declaration: null, passed: [],
  trick: { leader: 3, plays: [{ seat: 3, cards: ["DA", "DA", "DK"] }] },
  last_trick: null, attacker_points: 0, kitty_count: 8,
  round_result: null, message: null, notice: null,
} as unknown as GameState;

createRoot(document.getElementById("root")!).render(
  <div className="app"><Table state={state} /></div>,
);
