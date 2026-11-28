export const ORIENTS: Record<"portrait" | "left" | "right", { code: number; angle: number }>;
export const MENUS: string[];
export const SHOTS: string[];
export function parseOrients(arg: string | undefined, rotate: string | undefined): { orients?: string[]; error?: string };
export function observedOrient(page: { angle: number | null; w: number; h: number }): string | null;
export function staticFile(dist: string, urlPath: string): string | null;
export function failures(requested: string[], results: object[]): string[];
