import type { CSSProperties } from "react";
import { TOAST_MS } from "../toast";
import type { Toast } from "../toast";

/** An error toast. Callers key it by the toast's id, so each showing mounts a
 *  new element and its fade runs from the start; the fade's timing comes from
 *  TOAST_MS, the same number that unmounts it. */
export default function ToastView({ toast }: { toast: Toast }) {
  const style = { "--toast-ms": `${TOAST_MS}ms` } as CSSProperties;
  return <div className="toast" role="alert" style={style}>{toast.text}</div>;
}
