import { parseDate } from "./format";

/** One time scale shared by sparklines, charts and the report/medication strip. */
export interface TimeAxis {
  from: number;
  to: number;
  x: (date: string, width: number) => number;
  years: string[];
}

const DAY = 86_400_000;

export function makeAxis(dates: string[]): TimeAxis {
  const ts = dates.map((d) => parseDate(d).getTime());
  const lo = ts.length ? Math.min(...ts) : Date.now() - 365 * DAY;
  const hi = ts.length ? Math.max(...ts) : Date.now();
  const pad = Math.max(30 * DAY, (hi - lo) * 0.04);
  const from = lo - pad;
  const to = hi + pad;
  const years: string[] = [];
  for (let y = new Date(from).getUTCFullYear() + 1; y <= new Date(to).getUTCFullYear(); y++) years.push(`${y}-01-01`);
  return {
    from, to, years,
    x: (date, width) => Math.round(((parseDate(date).getTime() - from) / (to - from)) * width * 10) / 10,
  };
}

/** A padded value range; includes extra values such as the baseline or a threshold. */
export function valueRange(values: number[], extra: (number | null | undefined)[] = []): [number, number] {
  const all = [...values, ...extra.filter((v): v is number => typeof v === "number")];
  if (!all.length) return [0, 1];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
  const pad = (hi - lo) * 0.14;
  return [lo - pad, hi + pad];
}

export function y(v: number, [lo, hi]: [number, number], h: number) {
  return Math.round((1 - (v - lo) / (hi - lo)) * h * 10) / 10;
}
