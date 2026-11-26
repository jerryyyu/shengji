export type { ChatMsg } from "../protocol";
import type { ChatMsg } from "../protocol";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { conn } from "../ws";
import { usePresence } from "../usePresence";
import { useBlocks } from "../chatBlocks";
import { KEYBOARD_COVER_PX, SHORT_VISIBLE_PX, TIGHT_VISIBLE_PX, visibleArea, type VisibleArea } from "../visibleArea";
import { useT } from "../i18n";
import { formatChatLine, formatSystemLine } from "../messageCopy";
import { QUICK_PHRASE_IDS, QUICK_PHRASE_KEY } from "../quickPhrases";
import "./ChatPanel.css";
import { Portrait } from "../companion/Companion";

interface ChatProps {
  messages: ChatMsg[];
  you: number;
  /** The companion look of the person at a seat, for each line's portrait;
   *  without it every line shows the default. */
  lookOf?: (seat: number) => string | null | undefined;
  /** Where a line goes: room chat unless a waiting table sends its own.
   *  `phrase`: the quick phrase `text` words in this player's language. */
  onSend?: (text: string, phrase?: string) => void;
}

interface BodyProps extends ChatProps {
  /** Shown, not sliding out: the field holds focus and the log its end. */
  open?: boolean;
}

/** What chat holds, wherever it is drawn: the log, the quick phrases and the
 *  field, which takes focus when it opens and gives it back when it closes. */
export function ChatBody({ messages, you, onSend, lookOf, open = true }: BodyProps) {
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

  const say = (text: string, phrase?: string) => {
    if (onSend) onSend(text, phrase);
    else conn.send(phrase === undefined ? { type: "table_chat", text } : { type: "table_chat", text, phrase });
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
              {formatSystemLine(m)}
            </div>
          ) : (
            <div key={i} className={"chat-msg" + (m.seat === you ? " mine" : "")}>
              <span className="chat-portrait" aria-hidden="true">
                <Portrait look={m.seat === null ? null : lookOf?.(m.seat)} size={20} />
              </span>
              <span className="chat-name">{m.name}</span>
              <span className="chat-text">{formatChatLine(m)}</span>
            </div>
          )
        )}
        <div ref={endRef} />
      </div>
      {/* The quick phrases, above the field: a tap sends the phrase's id
          with this player's wording, through the same validated,
          rate-limited path as a typed line. They stay one row, which
          scrolls sideways when the chat is narrower than all of them. */}
      {typing && touchFirst() ? null : (
        <div className="chat-quick" role="group" aria-label={t("table.quickPhrases")}>
          {QUICK_PHRASE_IDS.map((id) => {
            const words = t(QUICK_PHRASE_KEY[id]);
            return (
              <button key={id} type="button" className="chat-quick-btn" onClick={() => say(words, id)}>
                {words}
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
export default function ChatPanel({ messages, you, open, onClose, onSend, lookOf }: ChatProps & {
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
      <ChatBody messages={messages} you={you} onSend={onSend} lookOf={lookOf} open={open} />
    </div>
  );
}
