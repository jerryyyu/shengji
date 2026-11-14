import type { ReactNode, RefObject } from "react";
import YourTablePill from "../queue/YourTablePill";
import { useLargeTitle } from "./useLargeTitle";
import { usePullToRefresh } from "./usePullToRefresh";

/** iOS's activity indicator: eight spokes, each a step dimmer round the
 *  circle; it turns in steps while the page reloads. */
function Spinner() {
  return (
    <span className="ptr-spinner">
      {Array.from({ length: 8 }, (_, i) => <i key={i} style={{ transform: `rotate(${i * 45}deg)` }} />)}
    </span>
  );
}

/** A home tab's page: its own scroller holding the column, with the page
 *  title drawn large at the top. On a phone (`phone`) the title collapses
 *  into a sticky compact bar as the page scrolls, and pulling down at the
 *  top calls `onRefresh`. Otherwise the page is the plain scroller and
 *  title, with no bar and no pull. A
 *  phone's title row ends with the Your table pill (the top bar holds it on
 *  a wide layout). */
export default function LargeTitlePage({ className, scroller, title, phone, onRefresh, children }: {
  className: string; scroller: RefObject<HTMLDivElement | null>; title: string; phone: boolean;
  onRefresh: () => Promise<unknown>; children: ReactNode;
}) {
  const { bar, title: titleRef, collapsed } = useLargeTitle(scroller, phone);
  const { phase, animate } = usePullToRefresh(scroller, onRefresh, phone);
  let cls = `screen home-page ${className}`;
  if (phone) {
    cls += " has-nav";
    if (animate) cls += " nav-animate";
    if (phase !== "idle") cls += " ptr-on";
    if (phase === "pulling" || phase === "armed") cls += " ptr-drag";
    if (phase === "armed") cls += " ptr-armed";
    if (phase === "refreshing") cls += " ptr-refreshing";
  }
  return (
    <div className={cls} ref={scroller}>
      {phone ? (
        <div className={`nav-bar${collapsed ? " collapsed" : ""}`} ref={bar}>
          <span className="nav-bar-title" aria-hidden="true">{title}</span>
        </div>
      ) : null}
      {phone ? (
        <div className="ptr" role={phase === "refreshing" ? "status" : undefined}
             aria-label={phase === "refreshing" ? "Refreshing" : undefined} aria-hidden={phase !== "refreshing"}>
          <Spinner />
        </div>
      ) : null}
      <div className="home-col">
        {phone ? (
          <div className="large-title-row">
            <h1 className="large-title" ref={titleRef}>{title}</h1>
            <YourTablePill />
          </div>
        ) : <h1 className="large-title" ref={titleRef}>{title}</h1>}
        {children}
      </div>
    </div>
  );
}
