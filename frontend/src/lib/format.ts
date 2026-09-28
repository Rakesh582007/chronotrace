// Display helpers. Numbers follow the summary rule: 10 or more → one decimal; below 10 → as the API gives them.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LONG_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

export function parseDate(d: string): Date {
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, day));
}

/** 02 Mar 2026 */
export function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  const x = parseDate(d);
  return `${String(x.getUTCDate()).padStart(2, "0")} ${MONTHS[x.getUTCMonth()]} ${x.getUTCFullYear()}`;
}

/** Mar 2026 */
export function fmtMonth(d: string): string {
  const x = parseDate(d);
  return `${MONTHS[x.getUTCMonth()]} ${x.getUTCFullYear()}`;
}

/** March 2026 */
export function fmtMonthLong(d: string): string {
  const x = parseDate(d);
  return `${LONG_MONTHS[x.getUTCMonth()]} ${x.getUTCFullYear()}`;
}

/** Trim a float to what the API meant: ≥10 → 1 decimal, below 10 → up to 2 decimals (1.11, 7.08). */
export function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const s = a >= 10 ? v.toFixed(1).replace(/\.0$/, "") : Number.isInteger(v) ? v.toFixed(1) : String(Math.round(v * 100) / 100);
  return s.replace(/^-/, "−");
}

export function fmtSigned(v: number, suffix = ""): string {
  const s = fmtNum(Math.abs(v));
  return `${v < 0 ? "−" : v > 0 ? "+" : ""}${s}${suffix}`;
}

export function fmtPercent(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v < 0 ? "−" : "+"}${Math.round(Math.abs(v))}%`;
}

export function age(birthYear: number, today = new Date()): number {
  return today.getFullYear() - birthYear;
}

export function sexLabel(s: string): string {
  return s === "male" ? "Male" : s === "female" ? "Female" : s;
}

export function capitalise(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

export function initials(name: string): string {
  const parts = name.replace(/\./g, " ").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[parts.length - 1]?.[0] ?? "")).toUpperCase();
}

const AVATARS = [
  ["#DCE8F4", "#1F5282"], ["#EFE3CC", "#6B4A12"], ["#E9E4F1", "#4A3D6B"], ["#E2EBE4", "#2F5A3C"],
];
export function avatarColours(id: number): { bg: string; fg: string } {
  const [bg, fg] = AVATARS[(id - 1) % AVATARS.length];
  return { bg, fg };
}

export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Short analyte names for headings ("eGFR (CKD-EPI 2021)" → "eGFR"). */
export function shortName(name: string): string {
  return name.replace(/\s*\(.*\)\s*$/, "").replace(/^Serum /, "").replace(/^Fasting Plasma Glucose$/, "Fasting glucose")
    .replace(/^Urine Albumin\/Creatinine Ratio$/, "UACR");
}

/** "mL/min/1.73m²" → "mL/min/1.73 m²" */
export function fmtUnit(u: string | null | undefined): string {
  return (u ?? "").replace("1.73m²", "1.73 m²");
}

/** A threshold percentage: 20 → "20", 6.3 → "6.3". */
export function fmtPct(v: number): string {
  return String(Math.round(v * 10) / 10);
}
