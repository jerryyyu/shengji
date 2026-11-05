/** Play/pause, replay and the still-image switch: small quiet icon buttons
 *  in the picture's corner. */
export default function TimelineControls({ playing, still, onToggle, onReplay, onStill }: {
  playing: boolean;
  still: boolean;
  onToggle: () => void;
  onReplay: () => void;
  onStill: () => void;
}) {
  return (
    <div className="howto-anim-controls">
      <button type="button" className="howto-anim-btn" onClick={onToggle}
              aria-label={playing ? "Pause animation" : "Play animation"}>
        {playing
          ? <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4" y="3" width="3" height="10" rx="1" /><rect x="9" y="3" width="3" height="10" rx="1" /></svg>
          : <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L5.9 2.7a.6.6 0 0 0-.9.5z" /></svg>}
      </button>
      <button type="button" className="howto-anim-btn" onClick={onReplay} aria-label="Replay animation">
        <svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 8a5 5 0 1 0 1.6-3.7" /><path d="M3.2 2.2v2.6h2.6" />
        </svg>
      </button>
      <button type="button" className={`howto-anim-btn${still ? " on" : ""}`} onClick={onStill}
              aria-label="Show still image" aria-pressed={still}>
        <svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
          <rect x="2.5" y="3.5" width="11" height="9" rx="1.5" />
          <path d="M2.8 11.2l3.4-3.4 2.6 2.6 1.6-1.6 2.8 2.8" strokeLinecap="round" />
          <circle cx="10.6" cy="6.2" r="1" fill="currentColor" stroke="none" />
        </svg>
      </button>
    </div>
  );
}
