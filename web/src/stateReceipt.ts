import type { GameState } from "./protocol";

/** Which socket delivered a state frame, and for which room: noted when the
 *  frame arrives, not when something renders it. A render after a reconnect
 *  (the socket's open status) still shows the older frame, which belongs to
 *  the socket that sent it. */
export interface Receipt {
  generation: number;
  room: string;
}

const receipts = new WeakMap<GameState, Receipt>();

export function noteReceipt(state: GameState, generation: number): void {
  receipts.set(state, { generation, room: state.room });
}

export function receiptOf(state: GameState): Receipt | null {
  return receipts.get(state) ?? null;
}

export function sameSocket(a: Receipt | null, b: Receipt | null): boolean {
  return a !== null && b !== null && a.generation === b.generation && a.room === b.room;
}
