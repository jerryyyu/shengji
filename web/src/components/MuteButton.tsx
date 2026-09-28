import { useMuted } from "../useMuted";

export default function MuteButton() {
  const [muted, toggle] = useMuted();
  return (
    <button
      className="mute-btn"
      onClick={toggle}
      title={muted ? "Unmute announcements" : "Mute announcements"}
    >
      {muted ? "🔇" : "🔊"}
    </button>
  );
}
