export type { ChatMsg } from "../protocol";
import type { ChatMsg } from "../protocol";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { conn } from "../ws";
import { usePresence } from "../usePresence";
import { useBlocks } from "../chatBlocks";
import { KEYBOARD_COVER_PX, SHORT_VISIBLE_PX, TIGHT_VISIBLE_PX, visibleArea, type VisibleArea } from "../visibleArea";
import { displayName, useT } from "../i18n";
import { formatSystemLine } from "../messageCopy";
import type { MessageKey } from "../i18n";
import "./ChatPanel.css";

/** The chat sheet's quick phrases, above the field: a tap sends one as an
 *  ordinary line, through the same validated, rate-limited path. They stay
 *  one row, which scrolls sideways when the chat is narrower than all five. */
const QUICK_PHRASES: readonly MessageKey[] = ["table.quickHi", "table.quickGg", "table.quickNice", "table.quickMore", "table.quickBrb"];

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
  const t = useT();
  const [draft, setDraft] = useState("");
  // On a touch screen the field's focus means the keyboard is up; the quick
  // phrases then give their row to the field.
  const [typing, setTyping] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // a blocked seat's lines stay hidden for this viewer; system lines never block
  const isBlocked = useBlocks();
  const shown = messages.filter((m) => m.seat === -1 || !isBlocked(m.room, m.seat));

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    // A touch screen raises its keyboard on focus, which would cover the
    // table before the player picks a quick phrase or taps the field.
    if (!touchFirst()) inputRef.current?.focus();
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
      <div className="chat-log" role="log" aria-label={t("table.chatLog")} aria-relevant="additions">
        {shown.map((m, i) =>
          m.seat === -1 ? (            // system line: joins, leaves, seat claims
            <div key={i} className="chat-msg system">
              {formatSystemLine(m.text)}
            </div>
          ) : (
            <div key={i} className={"chat-msg" + (m.seat === you ? " mine" : "")}>
              <span className="chat-name">{displayName(m.name)}</span>
              <span className="chat-text">{m.text}</span>
            </div>
          )
        )}
        <div ref={endRef} />
      </div>
      {typing && touchFirst() ? null : (
        <div className="chat-quick" role="group" aria-label={t("table.quickPhrases")}>
          {QUICK_PHRASES.map((key) => {
            const phrase = t(key);
            return (
              <button key={key} type="button" className="chat-quick-btn" onClick={() => say(phrase)}>
                {phrase}
              </button>
            );
          })}
        </div>
      )}
      <div className="chat-input">
        <input
          ref={inputRef}
          value={draft}
          maxLength={300}
          placeholder={t("table.chatPlaceholder")}
          aria-label={t("table.chatField")}
          enterKeyHint="send"
          onChange={(e) => setDraft(e.target.value)}
          onFocus={() => setTyping(true)}
          onBlur={() => setTyping(false)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) send();
          }}
        />
        {/* Send keeps the field's focus, so the keyboard stays up and the
            row does not move between the press and the click. */}
        <button className="btn" onMouseDown={(e) => e.preventDefault()} onClick={send} disabled={!draft.trim()}>
          {t("table.send")}
        </button>
      </div>
    </>
  );
}

function touchFirst(): boolean {
  try {
    return typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
  } catch {
    return false;
  }
}

/** Keeps the open panel inside the visible area, above the keyboard. */
function useVisibleArea(open: boolean): VisibleArea | null {
  const [area, setArea] = useState<VisibleArea | null>(null);
  useLayoutEffect(() => {
    if (!open || typeof window === "undefined" || !window.visualViewport) return;
    const vv = window.visualViewport;
    const update = () => setArea(visibleArea(window));
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, [open]);
  return open ? area : null;
}

/** In a game: a toggled overlay, not a side panel. In landscape the table
 *  already fills the screen, so chat slides over it and closes again. Unread
 *  count lives on the launcher button. Off the felt, chat opens in the
 *  shared Sheet with the same body. */
export default function ChatPanel({ messages, you, open, onClose, onSend }: ChatProps & {
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const presence = usePresence(open);
  const area = useVisibleArea(open);
  if (!presence.mounted) return null;
  const short = area !== null && (area.height < SHORT_VISIBLE_PX || area.covered > KEYBOARD_COVER_PX);
  const tight = short && area.height < TIGHT_VISIBLE_PX;
  const style = area && ({
    "--chat-vv-top": `${area.top}px`,
    "--chat-vv-h": `${area.height}px`,
    "--chat-kb": `${area.covered}px`,
  } as CSSProperties);
  return (
    <div className={`chat-panel${short ? " chat-short" : ""}${tight ? " chat-tight" : ""}${presence.className ? ` ${presence.className}` : ""}`}
         style={style || undefined} role="region" aria-label={t("table.chat")} aria-hidden={!open || undefined} inert={!open || undefined} onKeyDown={(event) => {
      if (event.key === "Escape" && !event.nativeEvent.isComposing) onClose();
      event.stopPropagation();
    }}>
      <div className="chat-head">
        <span>{t("table.chat")}</span>
        {/* pressing × leaves the field's focus alone: a blur would bring the
            quick phrases back and move × from under the finger */}
        <button className="chat-close" onMouseDown={(e) => e.preventDefault()} onClick={onClose} aria-label={t("table.closeChat")}>
          ×
        </button>
      </div>
      <ChatBody messages={messages} you={you} onSend={onSend} open={open} />
    </div>
  );
}
