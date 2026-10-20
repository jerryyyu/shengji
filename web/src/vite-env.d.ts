/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The game server's origin (`https://host`) for a build that is not served
   *  by the server itself, such as the Capacitor shell. Unset: same-origin. */
  readonly VITE_SERVER_ORIGIN?: string;
}
