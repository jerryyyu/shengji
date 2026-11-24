export type Params = Record<string, string | number>;

/** A message is a whole sentence with `{name}` placeholders, or, where
 *  English grammar needs the numbers (plurals), a function of them. */
export type Message = string | ((p: Params) => string);

export interface Entry {
  en: Message;
  zh: Message;
}

/** Declares one area's messages. Keys are per use ("home.play",
 *  "table.play"), never per English string: one English word can be three
 *  Chinese ones. Both languages are required by the type. */
export function defineMessages<K extends string>(table: Record<K, Entry>): Record<K, Entry> {
  return table;
}
