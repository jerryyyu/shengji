// `POST /api/support`: the server stores the message and answers only
// `{ok: true}` or an error code, so nothing typed here is ever read back.
import { isNative } from "../native";

export type SupportTopic = "bug" | "feedback" | "account" | "other";

export interface SupportMessage {
  topic: SupportTopic;
  message: string;
  email: string;
  /** The honeypot: hidden from people, so only a form-filling script sets it. */
  website: string;
}

export type SendResult = "ok" | "rate_limited" | "invalid" | "failed";

export const MESSAGE_MIN = 10;
export const MESSAGE_MAX = 4000;
export const EMAIL_MAX = 254;
// The server's shape check, so the form refuses what the server would.
export const EMAIL_RE = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/;

/** The web build that is running: Vite names the entry script by its content
 *  hash, so its file name tells one deploy from the next. */
export function buildVersion(): string | null {
  try {
    const script = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"]');
    const name = script?.src.split("/").pop() ?? null;
    const shell = isNative() ? "ios-app" : "web";
    return name ? `${shell} ${name}` : shell;
  } catch {
    return null;
  }
}

export async function sendSupport(msg: SupportMessage): Promise<SendResult> {
  let status: number;
  try {
    const resp = await fetch("/api/support", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...msg, email: msg.email.trim() || null, version: buildVersion() }),
    });
    status = resp.status;
  } catch {
    return "failed";
  }
  if (status === 200) return "ok";
  if (status === 429) return "rate_limited";
  if (status === 400 || status === 422) return "invalid";
  return "failed";
}
