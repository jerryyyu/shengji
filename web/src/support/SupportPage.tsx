import { useId, useState } from "react";
import type { FormEvent } from "react";
import InfoHead from "./InfoHead";
import { followInfoLink } from "./route";
import { EMAIL_MAX, EMAIL_RE, MESSAGE_MAX, MESSAGE_MIN, sendSupport } from "./api";
import type { SendResult, SupportTopic } from "./api";

const TOPICS: { value: SupportTopic; label: string }[] = [
  { value: "bug", label: "Bug" },
  { value: "feedback", label: "Feedback" },
  { value: "account", label: "Account" },
  { value: "other", label: "Other" },
];

const ERRORS: Record<Exclude<SendResult, "ok">, string> = {
  rate_limited: "Too many messages. Try again later.",
  invalid: "Check the message and the email address, then send again.",
  failed: "Couldn’t send. Check your connection.",
};

type Phase = "editing" | "sending" | "sent";

export default function SupportPage() {
  const id = useId();
  const [topic, setTopic] = useState<SupportTopic>("bug");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [phase, setPhase] = useState<Phase>("editing");
  const [error, setError] = useState<string | null>(null);

  const length = message.trim().length;
  const emailBad = email.trim() !== "" && (email.trim().length > EMAIL_MAX || !EMAIL_RE.test(email.trim()));
  const ready = length >= MESSAGE_MIN && length <= MESSAGE_MAX && !emailBad;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || phase === "sending") return;
    setPhase("sending");
    setError(null);
    const result = await sendSupport({ topic, message, email, website });
    if (result === "ok") {
      setPhase("sent");
      return;
    }
    setPhase("editing");
    setError(ERRORS[result]);
  };

  const again = () => {
    setMessage("");
    setError(null);
    setPhase("editing");
  };

  return (
    <div className="screen lobby-screen info-screen">
      <div className="panel games-panel info-panel">
        <InfoHead title="Support" />
        {phase === "sent" ? (
          <div className="support-thanks" role="status">
            <p className="support-thanks-title">Thanks — we read every message.</p>
            {email.trim() ? <p className="info-text">We’ll reply if we can.</p> : null}
            <button type="button" className="btn big" onClick={again}>Send another</button>
          </div>
        ) : (
          <form className="support-form" onSubmit={submit} noValidate>
            <label className="field">
              <span className="field-label">Topic</span>
              <select value={topic} onChange={(e) => setTopic(e.target.value as SupportTopic)}>
                {TOPICS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Message</span>
              <textarea
                className="support-message"
                value={message}
                required
                minLength={MESSAGE_MIN}
                maxLength={MESSAGE_MAX}
                rows={6}
                aria-describedby={`${id}-count`}
                onChange={(e) => setMessage(e.target.value)}
              />
              <span id={`${id}-count`} className="field-hint support-count">
                {length < MESSAGE_MIN ? `At least ${MESSAGE_MIN} characters` : `${length} / ${MESSAGE_MAX}`}
              </span>
            </label>
            <label className="field">
              <span className="field-label">Email (optional)</span>
              <input
                type="email"
                value={email}
                maxLength={EMAIL_MAX}
                autoComplete="email"
                inputMode="email"
                autoCapitalize="off"
                spellCheck={false}
                aria-invalid={emailBad}
                aria-describedby={`${id}-email`}
                onChange={(e) => setEmail(e.target.value)}
              />
              <span id={`${id}-email`} className="field-hint">
                {emailBad ? "That doesn’t look like an email address." : null}
              </span>
            </label>
            <div className="support-trap" aria-hidden="true">
              <label>
                Website
                <input type="text" name="website" tabIndex={-1} autoComplete="off"
                       value={website} onChange={(e) => setWebsite(e.target.value)} />
              </label>
            </div>
            {error ? <p className="support-error" role="alert">{error}</p> : null}
            <button type="submit" className="btn primary big" disabled={!ready || phase === "sending"}>
              {phase === "sending" ? "Sending…" : "Send"}
            </button>
            <p className="info-small">
              What we keep when you send this is in the{" "}
              <a href="/privacy" onClick={(e) => followInfoLink(e, "privacy")}>privacy policy</a>.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
