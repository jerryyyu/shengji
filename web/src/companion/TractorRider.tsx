// The Tractor's rider: a farm kid in a straw hat at the cab window. The
// Tractor's builder draws `inside` over the glass (it is clipped to the
// window) and `outside` after the cab, so the waving arm reaches out of the
// window. The shirt, hat band and neckerchief take the Tractor colour's hood
// and stripe, the same wherever it is drawn.
import { part } from "./rig";
import type { CharPose } from "./rig";

/** The part of a Tractor colour the rider wears. */
export interface RiderAccents { hood: string; stripe?: string }

const SKIN = "#f6d2ac", STRAW = "#f3d58a", STRAW_LO = "#c99a3c", INK = "#2b1713";

/** The rider's markup for the Tractor's 400 box. `id` is the Tractor's own. */
export function riderMarkup(accents: RiderAccents, id: string, { pose = "idle", still = false }: { pose?: CharPose; still?: boolean } = {}): { defs: string; inside: string; outside: string } {
  const asleep = pose === "sleep", happy = pose === "cheer" || pose === "hop" || pose === "react";
  const band = accents.stripe ?? "#c22a36";
  const eyes = asleep ? `<path d="M146 159q4 3 8 0M162 159q4 3 8 0" fill="none" stroke="${INK}" stroke-width="2.6" stroke-linecap="round"/>`
    : happy ? `<path d="M146 160q4-6 8 0M162 160q4-6 8 0" fill="none" stroke="${INK}" stroke-width="2.8" stroke-linecap="round"/>`
      : `<circle cx="150" cy="158" r="3.6" fill="${INK}"/><circle cx="166" cy="158" r="3.6" fill="${INK}"/><circle cx="149" cy="156.6" r="1.2" fill="#fff"/><circle cx="165" cy="156.6" r="1.2" fill="#fff"/>`;
  const mouth = pose === "cheer" || pose === "react" ? `<path d="M153 166q5 2 10 0q-1 7-5 7q-4 0-5-7z" fill="#8a3038"/>`
    : `<path d="M154 167q4 3 8 0" fill="none" stroke="#8a5240" stroke-width="2.2" stroke-linecap="round"/>`;
  const hat = `<ellipse cx="158" cy="141" rx="36" ry="8.5" fill="${STRAW_LO}"/><ellipse cx="158" cy="139" rx="35" ry="7.5" fill="${STRAW}"/>`
    + `<path d="M138 139C138 122 148 116 158 116C168 116 178 122 178 139Z" fill="${STRAW}"/><path d="M139 133Q158 139 177 133L178 139Q158 145 138 139Z" fill="${band}"/>`;
  const head = `<circle cx="158" cy="156" r="21" fill="${SKIN}"/><ellipse cx="143" cy="164" rx="5.5" ry="3.6" fill="#f08f84" opacity=".6"/><ellipse cx="173" cy="164" rx="5.5" ry="3.6" fill="#f08f84" opacity=".6"/>`
    + eyes + mouth + part("cmp-hat", hat, still && pose === "react" ? "translate(2 -12) rotate(-14 158 140)" : asleep ? "translate(0 9) rotate(6 158 140)" : "");
  const inside = `<g clip-path="url(#cab-${id})">`
    + `<ellipse cx="158" cy="194" rx="30" ry="20" fill="${accents.hood}"/>`
    + `<path fill="${band}" d="M136 178Q158 190 180 178L182 186Q158 200 134 186Z"/>`
    + part("cmp-rider", head, asleep ? "translate(5 8) rotate(16 158 178)" : still && pose === "cheer" ? "translate(0 -3) rotate(-6 158 178)" : "")
    + `</g>`;
  const arm = `<path d="M118 166L92 134" stroke="${accents.hood}" stroke-width="13" stroke-linecap="round"/><path d="M96 139L88 129" stroke="${SKIN}" stroke-width="12" stroke-linecap="round"/>`;
  const outside = pose === "cheer" || pose === "react" ? part("cmp-wave", arm, still ? "rotate(-12 118 166)" : "") : "";
  return { defs: `<clipPath id="cab-${id}"><rect x="112" y="118" width="96" height="62" rx="12"/></clipPath>`, inside, outside };
}
