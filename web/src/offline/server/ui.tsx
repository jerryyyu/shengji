// What offline mode shows outside a game: the home Play tab in its offline
// state, whose Play opens a table with three SmartBot seats on this device.
// Lazy-loaded with the rest of offline play.
import type { ConnStatus } from "../../ws";
import HomeShell from "../../home/HomeShell";
import OfflinePlay from "../../components/OfflinePlay";
import "./offline.css";

interface OfflineHomeProps {
  status: ConnStatus;
  error: string | null;
  /** The room the offline table's Start made, until its game starts. */
  room: string | null;
  /** Arm App's fill-with-bots-then-start chain before creating the room. */
  onArmAutoFill: () => void;
}

export function OfflineHome({ status, error, room, onArmAutoFill }: OfflineHomeProps) {
  return (
    <HomeShell active="play">
      <OfflinePlay local status={status} error={error} room={room} onArmAutoFill={onArmAutoFill} />
    </HomeShell>
  );
}
