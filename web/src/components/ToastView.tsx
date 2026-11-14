import type { CSSProperties } from "react";
import { TOAST_MS } from "../toast";
import type { Toast } from "../toast";

/** An error toast, or with `info` a neutral notice that does not interrupt. Callers key it by the toast's id, so each showing mounts a
 *  new element and its fade runs from the start; the fade's timing comes from
 *  TOAST_MS, the same number that unmounts it. */
export default function ToastView({ toast, info = toast.info === true }: { toast: Toast; info?: boolean }) {
  const style = { "--toast-ms": `${TOAST_MS}ms` } as CSSProperties;
  return info
    ? <div className="toast toast-info" role="status" style={style}>{toast.text}</div>
    : <div className="toast" role="alert" style={style}>{toast.text}</div>;
}
