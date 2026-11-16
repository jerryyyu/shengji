// A scripted socket for states a live game reaches only by luck (you are the
// banker, it is not your turn, you have played, the trick is full...). The page
// runs the real app; only the server's frames are made up here.
export const now = () => Date.now() / 1000;

export const NAMES = ["Cheerful Tractor", "Bot Wei", "Alice", "Bot Li"];
/** The longest names the server lets through (20 characters), wide and narrow. */
export const LONG_NAMES = ["Maximilian Featherst", "WWWWWWWWWWWWWWWWWWWW", "张伟张伟张伟张伟张伟张伟", "Bartholomew-Christop"];

export const pl = (seat, over = {}) => ({
  seat, name: NAMES[seat], is_bot: seat === 1 || seat === 3, connected: true, team: seat % 2,
  cards_left: 25, is_banker: false, takeover_in: null, controller: seat === 1 || seat === 3 ? "bot" : "human",
  reserved_for: null, reserved_secs: null, ...over,
});

export const HAND25 = ["S3", "S5", "S5", "S9", "SK", "SA", "H3", "H4", "H10", "HK", "HK", "HA", "D6", "D7", "D7", "D10", "DA", "C2", "C5", "C8", "C10", "CQ", "CA", "H2", "BJ"];
export const hand = (codes) => codes.map((code, i) => ({ id: i + 1, code }));

/** A full `state` frame; `over` replaces fields, `names` the four names, `banker` sets the crown. */
export function base(over = {}, { names = NAMES, banker = 1, humans = [0, 2] } = {}) {
  return {
    type: "state", room: "4N5Z", you: 0, phase: "play", matched: false, ranked: false, guest: true, opener: 0,
    allow_joiners: true, joining: [],
    players: [0, 1, 2, 3].map((s) => pl(s, { name: names[s], is_banker: s === banker, is_bot: !humans.includes(s), controller: humans.includes(s) ? "human" : "bot" })),
    hand: hand(HAND25), levels: ["2", "2"], games_won: [0, 0], banker,
    trump: { suit: "C", rank: "2", declarer: banker }, turn: 0, declare_options: [], current_declaration: null, passed: [],
    trick: { leader: 1, plays: [] }, last_trick: null, ready: [], attacker_points: 35, kitty_count: 8,
    message: null, notice: null, round_result: null, ...over,
  };
}

/** Plays of one trick: `n` seats from `leader` on, each `cards` wide. */
export function plays(leader, n, width = 1) {
  const SETS = {
    1: [["HA"], ["H5"], ["H9"], ["HQ"]],
    2: [["HA", "HA"], ["H5", "H5"], ["H9", "H8"], ["HQ", "H6"]],
    4: [["HQ", "HQ", "HK", "HK"], ["H5", "H5", "H6", "H6"], ["H9", "H8", "H7", "H3"], ["HJ", "H10", "H4", "H3"]],
    6: [["HA", "HK", "HK", "HQ", "HQ", "H10"], ["H5", "H5", "H6", "H6", "H7", "H8"], ["H9", "H8", "H7", "H3", "S3", "S4"], ["HJ", "H10", "H4", "H3", "D3", "D4"]],
  };
  return Array.from({ length: n }, (_, i) => ({ seat: (leader + i) % 4, cards: SETS[width][i] }));
}

/** Init script: replaces WebSocket. Frames go in with window.__fake.push(frame). */
export function fakeSocketScript(first = []) {
  return `(() => {
    const FIRST = ${JSON.stringify(first)};
    const fake = (window.__fake = { socks: [], sent: [], refuse: false,
      push(m) { for (const s of fake.socks) if (s.readyState === 1 && s.onmessage) s.onmessage({ data: JSON.stringify(m) }); },
      drop() { for (const s of fake.socks) if (s.readyState <= 1) { s.readyState = 3; s.onclose && s.onclose({ code: 1006 }); } },
    });
    class FakeWS {
      constructor(url) {
        this.url = url; this.readyState = 0; fake.socks.push(this);
        if (fake.refuse) { setTimeout(() => { this.readyState = 3; this.onerror && this.onerror({}); this.onclose && this.onclose({ code: 1006 }); }, 150); return; }
        setTimeout(() => {
          if (this.readyState !== 0) return;
          this.readyState = 1; this.onopen && this.onopen({});
          setTimeout(() => { for (const m of (fake.onOpen ?? FIRST)) this.onmessage && this.onmessage({ data: JSON.stringify(m) }); }, 60);
        }, 60);
      }
      send(raw) { try { fake.sent.push(JSON.parse(raw)); } catch {} }
      close() { if (this.readyState === 3) return; this.readyState = 3; this.onclose && this.onclose({ code: 1000 }); }
      addEventListener(t, f) { this["on" + t] = f; } removeEventListener() {}
    }
    FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
    window.WebSocket = FakeWS;
  })();`;
}

export const push = (page, frame) => page.evaluate((m) => window.__fake.push(m), frame);
