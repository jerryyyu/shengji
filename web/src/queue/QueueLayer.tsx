import { useQueue } from "./store";

/** Everything of the queue that floats over any screen: its notices. The
 *  table itself is a panel on Play (TablePanel). */
export default function QueueLayer() {
  const q = useQueue();
  return q.note ? (
    <div key={q.note.id} className="q-toast" role="status">
      <span className="q-toast-i" aria-hidden="true">!</span>
      <span>{q.note.title}{q.note.sub ? <small>{q.note.sub}</small> : null}</span>
    </div>
  ) : null;
}
