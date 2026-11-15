export type { ChatMsg } from "../protocol";
import type { ChatMsg } from "../protocol";
import { useEffect, useRef, useState } from "react";
import { conn } from "../ws";
import { usePresence } from "../usePresence";
import { useMutes } from "../chatMute";
import "./ChatPanel.css";

/** The chat sheet's quick phrases, above the field: a tap sends one as an
 *  ordinary line, through the same validated, rate-limited path. All five fit
 *  one row of the narrowest chat. */
const QUICK_PHRASES = ["Hi!", "GG", "Nice!", "One more?", "Brb"] as const;

interface ChatProps {
  messages: ChatMsg[];
  you: number;
  /** Where a line goes: room chat unless a waiting table sends its own. */
  onSend?: (text: string) => void;
}

interface BodyProps extends ChatProps {
  /** Shown, not sliding out: the field holds focus and the log its end. */
  open?: boolean;
}

/** What chat holds, wherever it is drawn: the log, the quick phrases and the
 *  field, which takes focus when it opens and gives it back when it closes. */
export function ChatBody({ messages, you, onSend, open = true }: BodyProps) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // a muted seat's lines stay hidden for this viewer; system lines never mute
  const isMuted = useMutes();
  const shown = messages.filter((m) => m.seat === -1 || !isMuted(m.room, m.seat));

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    inputRef.current?.focus();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [open]);
  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [open, messages.length]);

  const say = (text: string) => {
    if (onSend) onSend(text);
    else conn.send({ type: "table_chat", text });
  };
  const send = () => {
    const text = draft.trim();
    if (!text) return;
    say(text);
    setDraft("");
  };

  return (
    <>
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
      <div className="chat-quick" role="group" aria-label="Quick phrases">
        {QUICK_PHRASES.map((phrase) => (
          <button key={phrase} type="button" className="chat-quick-btn" onClick={() => say(phrase)}>
            {phrase}
          </button>
        ))}
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
    </>
  );
}

/** In a game: a toggled overlay, not a side panel. In landscape the table
 *  already fills the screen, so chat slides over it and closes again. Unread
 *  count lives on the launcher button. Off the felt, chat opens in the
 *  shared Sheet with the same body. */
export default function ChatPanel({ messages, you, open, onClose, onSend }: ChatProps & {
  open: boolean;
  onClose: () => void;
}) {
  const presence = usePresence(open);
  if (!presence.mounted) return null;
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
      <ChatBody messages={messages} you={you} onSend={onSend} open={open} />
    </div>
  );
}
