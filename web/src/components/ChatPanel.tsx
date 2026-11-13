export type { ChatMsg } from "../protocol";
import type { ChatMsg } from "../protocol";
import { useEffect, useRef, useState } from "react";
import { conn } from "../ws";
import { usePresence } from "../usePresence";
import { useMutes } from "../chatMute";

/** Toggled overlay, not a side panel: in landscape the table already fills
 *  the screen, so chat slides over it and closes again. Unread count lives
 *  on the launcher button. */
export default function ChatPanel({
  messages,
  you,
  open,
  onClose,
}: {
  messages: ChatMsg[];
  you: number;
  open: boolean;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const presence = usePresence(open);
  // a muted seat's lines stay hidden for this viewer; system lines never mute
  const isMuted = useMutes();
  const shown = messages.filter((m) => m.seat === -1 || !isMuted(m.room, m.seat));

  useEffect(() => {
    if (open) {
      const previous = document.activeElement;
      inputRef.current?.focus();
      return () => {
        if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
      };
    }
  }, [open]);
  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [open, messages.length]);

  if (!presence.mounted) return null;

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    conn.send({ type: "chat", text });
    setDraft("");
  };

  return (
    <div className={`chat-panel${presence.className ? ` ${presence.className}` : ""}`} role="region"
         aria-label="Chat" aria-hidden={!open || undefined} inert={!open || undefined} onKeyDown={(event) => {
      if (event.key === "Escape" && !event.nativeEvent.isComposing) onClose();
      event.stopPropagation();
    }}>
      <div className="chat-head">
        <span>Chat</span>
        <button className="chat-close" onClick={onClose} aria-label="Close chat">
          ×
        </button>
      </div>
      <div className="chat-log" role="log" aria-label="Messages" aria-relevant="additions">
        {shown.map((m, i) =>
          m.seat === -1 ? (            // system line: joins, leaves, seat claims
            <div key={i} className="chat-msg system">
              {m.text}
            </div>
          ) : (
            <div key={i} className={"chat-msg" + (m.seat === you ? " mine" : "")}>
              <span className="chat-name">{m.name}</span>
              <span className="chat-text">{m.text}</span>
            </div>
          )
        )}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <input
          ref={inputRef}
          value={draft}
          maxLength={300}
          placeholder="Message…"
          aria-label="Chat message"
          enterKeyHint="send"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) send();
          }}
        />
        <button className="btn" onClick={send} disabled={!draft.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
