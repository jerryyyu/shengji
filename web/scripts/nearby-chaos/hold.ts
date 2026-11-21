// The plugin's chaos stall hold (NearbyPlugin.swift's chaosHold and the
// stall's flush), for the simulator's stallPhone fault and for the test that
// pins its rule: a frame held during a stall is let go at the stall's end
// only if the link it was held on still serves its peer; a frame held on a
// link that has since gone is dropped, never sent on (or delivered as if
// from) the link made after it. The hold lasts until the flush clears it, so
// no frame overtakes one held before it.

export class PhoneHold<L> {
  /** A stall runs: frames wait. Only `flush` clears it. */
  stalling = false;
  private held: (() => void)[] = [];
  private stale = 0;

  /** While a stall runs, `work` for a frame on `peer`'s link waits for its
   *  end; `linkOf` reads the link that serves a peer now. True when held. */
  hold(peer: string, linkOf: (peer: string) => L | null, work: () => void, dropped: () => void): boolean {
    if (!this.stalling) return false;
    const link = linkOf(peer);
    this.held.push(() => {
      if (linkOf(peer) !== link) {
        this.stale += 1;
        dropped();
        return;
      }
      work();
    });
    return true;
  }

  /** The stall's end: everything held runs (or is dropped) in order. */
  flush(): { held: number; dropped: number } {
    const work = this.held;
    this.held = [];
    this.stalling = false;
    this.stale = 0;
    for (const w of work) w();
    return { held: work.length, dropped: this.stale };
  }
}
