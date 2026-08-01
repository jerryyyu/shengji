import { useState } from "react";
import type { RoomMsg } from "../protocol";
import { conn } from "../ws";
import MuteButton from "./MuteButton";

export default function Room({ room }: { room: RoomMsg }) {
  const [copied, setCopied] = useState(false);
  const isHost = room.you === room.host;
  const full = room.players.length === 4;
  const hasBot = room.players.some((p) => p.is_bot);

  const copyCode = () => {
    navigator.clipboard
      .writeText(room.room)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {
        /* clipboard unavailable; ignore */
      });
  };

  return (
    <div className="screen room-screen">
      <div className="panel room-panel">
        <MuteButton />
        <div className="room-code-label">Room code — click to copy</div>
        <button className="room-code" onClick={copyCode} title="Copy room code">
          {room.room}
          <span className={`copied-tag${copied ? " show" : ""}`}>Copied!</span>
        </button>

        <div className="seat-list">
          {[0, 1, 2, 3].map((seat) => {
            const p = room.players.find((pl) => pl.seat === seat);
            const team = seat % 2;
            return (
              <div key={seat} className={`seat-row team${team}${p ? "" : " empty"}`}>
                <span className={`team-dot t${team}`} />
                <span className="seat-num">Seat {seat}</span>
                {p ? (
                  <>
                    <span className="seat-name">
                      {p.name}
                      {p.is_bot ? <span className="bot-tag">BOT</span> : null}
                      {seat === room.you ? <span className="you-tag">you</span> : null}
                      {seat === room.host ? <span className="host-tag">host</span> : null}
                    </span>
                    <span className={`conn-pip${p.connected || p.is_bot ? " on" : ""}`} />
                  </>
                ) : (
                  <span className="seat-name waiting">waiting…</span>
                )}
              </div>
            );
          })}
        </div>

        <div className="team-legend">
          <span>
            <span className="team-dot t0" /> Team seats 0 + 2
          </span>
          <span>
            <span className="team-dot t1" /> Team seats 1 + 3
          </span>
        </div>

        {isHost ? (
          <div className="room-actions">
            <button className="btn" disabled={full} onClick={() => conn.send({ type: "add_bot" })}>
              Add bot
            </button>
            <button className="btn" disabled={!hasBot} onClick={() => conn.send({ type: "remove_bot" })}>
              Remove bot
            </button>
            <button
              className="btn primary"
              disabled={!full}
              onClick={() => conn.send({ type: "start_game" })}
            >
              Start game
            </button>
          </div>
        ) : (
          <div className="room-hint">Waiting for the host to start…</div>
        )}

        <button
          className="btn subtle danger leave-room-btn"
          onClick={() => conn.send({ type: "leave_room" })}
        >
          Leave room
        </button>
      </div>
    </div>
  );
}
