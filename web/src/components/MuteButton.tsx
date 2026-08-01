import { useState } from "react";
import { isMuted, setMuted } from "../audio";

export default function MuteButton() {
  const [muted, setLocal] = useState(isMuted());
  const toggle = () => {
    setMuted(!muted);
    setLocal(!muted);
  };
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
