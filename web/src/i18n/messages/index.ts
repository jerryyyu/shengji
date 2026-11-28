import { common } from "./common";
import { home } from "./home";
import { howto } from "./howto";
import { me } from "./me";
import { nearby } from "./nearby";
import { queue } from "./queue";
import { roundend } from "./roundend";
import { support } from "./support";
import { table } from "./table";
import { watch } from "./watch";

/** The area tables; each area file owns its key prefix ("me.", "table.").
 *  i18n.test.ts fails a key defined in two areas. */
export const AREAS = { common, home, howto, me, nearby, queue, roundend, support, table, watch } as const;

export const MESSAGES = {
  ...common, ...home, ...howto, ...me, ...nearby, ...queue, ...roundend, ...support, ...table, ...watch,
};
