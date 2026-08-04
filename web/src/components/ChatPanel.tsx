import { useEffect, useRef, useState } from "react";
import { conn } from "../ws";

export interface ChatMsg {
  seat: number;
  name: string;
  text: string;
  t: number;
}

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

  useEffect(() => {
    if (open) {
      endRef.current?.scrollIntoView({ block: "end" });
      inputRef.current?.focus();
    }
  }, [open, messages.length]);

  if (!open) return null;

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    conn.send({ type: "chat", text });
    setDraft("");
  };

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <span>Chat</span>
        <button className="chat-close" onClick={onClose} aria-label="Close chat">
          ×
        </button>
      </div>
      <div className="chat-log">
        {messages.length === 0 && <div className="chat-empty">No messages yet</div>}
        {messages.map((m, i) =>
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
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
            e.stopPropagation();   // don't trigger table hotkeys (e.g. X-ray)
          }}
        />
        <button className="btn" onClick={send} disabled={!draft.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
