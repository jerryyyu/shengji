// The companions on the felt, in Team view: each team's people stand
// together in their team's corner (yours lower left, theirs upper right) on
// their team's pad in their team's scarf, so a team reads by place and shape
// as well as colour. A team's companions grow with its level, only at round
// end. A companion cheers when its person takes a trick and when its team
// climbs, and sleeps while its person is away. A bot, and a seat its owner
// left, has none. Nothing here takes a tap: the felt under it stays the
// table's.
import { useEffect, useRef, useState } from "react";
import type { GameState, StatePlayer } from "../protocol";
import { useAuth } from "../auth";
import { useMediaQuery, TABLET_SCREEN } from "../phoneLayout";
import { Companion } from "./Companion";
import type { Pose } from "./Companion";
import { useCollection } from "./feature";
import { parseLook } from "./look";
import { useCompanionMode } from "./mode";
import { LEVELS } from "./rig";
import "./tableCompanions.css";
import type { Team } from "./rig";

/** A companion's base size and the most its seat area allows, in px: a
 *  phone's table, and a tablet's (or a desktop window's). */
export const TABLE_SIZE = { phone: { base: 44, max: 56 }, tablet: { base: 56, max: 72 } } as const;

/** A team's level as the index companions grow by (2 is 0, A is 12). */
export const levelIndex = (rank: string | undefined): number => Math.max(0, LEVELS.indexOf((rank ?? "2") as (typeof LEVELS)[number]));

/** The seats whose companion cheers on this frame: the taker of a trick just
 *  finished, and at round end the people of the team that climbed. */
function cheering(state: GameState, prev: GameState | null): number[] {
  if (!prev) return [];
  const out: number[] = [];
  const done = state.last_trick;
  if (done && JSON.stringify(done) !== JSON.stringify(prev.last_trick)) out.push(done.winner);
  if (state.phase === "round_end" && prev.phase !== "round_end" && state.round_result && state.round_result.level_change > 0) {
    for (const p of state.players) if (p.team === state.round_result.winner_team) out.push(p.seat);
  }
  return out;
}

function Figure({ player, team, level, size, pose, flip, onEnd }: {
  player: StatePlayer; team: Team; level: number; size: { base: number; max: number }; pose: Pose; flip: boolean;
  onEnd: () => void;
}) {
  const { kind, colour } = parseLook(player.look);
  const away = !player.connected || player.away === true;
  return (
    <span className={`tc-fig${flip ? " tc-flip" : ""}`} data-seat={player.seat}>
      <Companion kind={kind} colour={colour} size={size.base} max={size.max} level={level} team={team}
                 state={away ? "sleep" : pose} onPoseEnd={onEnd} />
    </span>
  );
}

export default function TableCompanions({ state }: { state: GameState }) {
  const shown = useCollection();
  const account = useAuth();
  const mode = useCompanionMode(account.status === "in" ? account.user : null);
  const tablet = useMediaQuery(TABLET_SCREEN);
  const [poses, setPoses] = useState<Record<number, Pose>>({});
  const prev = useRef<GameState | null>(null);
  useEffect(() => {
    const seats = cheering(state, prev.current);
    prev.current = state;
    if (seats.length) setPoses((p) => ({ ...p, ...Object.fromEntries(seats.map((s) => [s, "cheer" as Pose])) }));
  }, [state]);
  if (!shown || mode !== "team") return null;
  const me = state.players.find((p) => p.seat === state.you);
  const ours = me?.team ?? 0;
  const size = tablet ? TABLE_SIZE.tablet : TABLE_SIZE.phone;
  const people = state.players.filter((p) => !p.is_bot && !p.left)
    .sort((a, b) => Number(b.seat === state.you) - Number(a.seat === state.you) || a.seat - b.seat);
  const end = (seat: number) => () => setPoses((p) => ({ ...p, [seat]: "idle" }));
  const side = (team: 0 | 1, name: Team) => {
    const here = people.filter((p) => p.team === team);
    if (here.length === 0) return null;
    const level = levelIndex(state.levels[team]);
    return (
      <div className={`tc-team tc-${name}`} data-level={state.levels[team]}>
        {here.map((p, i) => (
          <Figure key={p.seat} player={p} team={name} level={level} size={size} pose={poses[p.seat] ?? "idle"}
                  flip={name === "them" || i > 0} onEnd={end(p.seat)} />
        ))}
      </div>
    );
  };
  return (
    <div className="table-companions" aria-hidden="true">
      {side(ours, "us")}
      {side(ours === 0 ? 1 : 0, "them")}
    </div>
  );
}
