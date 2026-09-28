import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, authedBlobUrl } from "../api/client";
import { avatarColours, initials } from "../lib/format";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="#2F6DA3" />
      <path d="M5 17h5l2.5-7 3.5 10 2.5-6H23" stroke="#FFFDF9" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Triangle({ w = 12, h = 11 }: { w?: number; h?: number }) {
  return (
    <svg width={w} height={h} viewBox="0 0 12 11" aria-hidden="true" className="shrink-0">
      <path d="M6 0.5L11.5 10.5H0.5Z" fill="#C8741F" />
    </svg>
  );
}

export function BlueDot({ size = 8 }: { size?: number }) {
  return <span aria-hidden="true" className="inline-block shrink-0 rounded-full bg-blue" style={{ width: size, height: size }} />;
}

export function HollowDot({ size = 8 }: { size?: number }) {
  return <span aria-hidden="true" className="inline-block shrink-0 rounded-full border-[1.5px] border-muted-mark box-border" style={{ width: size, height: size }} />;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`spin ${className}`} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".3" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function StatusPill({ status }: { status: "guideline" | "changed" | "stable" }) {
  if (status === "guideline")
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-amber-line bg-amber-fill px-2.5 py-1 text-xs font-semibold text-amber-ink">
        <Triangle w={10} h={9} />Guideline alert
      </span>
    );
  if (status === "changed")
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-blue-line bg-blue-tint px-2.5 py-1 text-xs font-semibold text-blue-ink">
        <BlueDot size={7} />Changed
      </span>
    );
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-stable-line bg-stable px-2.5 py-1 text-xs font-semibold text-ink-2">
      <HollowDot size={7} />Stable
    </span>
  );
}

export function ConditionChip({ children }: { children: ReactNode }) {
  return <span className="rounded-full bg-chip px-2.5 py-[3px] text-[13px] text-ink-2">{children}</span>;
}

export function ReportChip({ label, tone = "plain", title }: { label: string; tone?: "plain" | "amber" | "blue"; title?: string }) {
  const cls = tone === "amber"
    ? "border border-amber-line bg-amber-soft text-[#6B3A08] px-2 py-[3px]"
    : tone === "blue" ? "border border-blue-line bg-blue-tint-2 text-blue-ink px-2 py-[2px]"
      : "bg-paper text-ink-2 px-[7px] py-[2px]";
  return <span title={title} className={`rounded-md font-mono text-xs ${cls}`}>{label}</span>;
}

export function Skeleton({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />;
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex items-center gap-4 rounded-xl border border-amber-line bg-amber-fill px-4 py-3 text-sm text-amber-deep">
      <Triangle />
      <span className="grow">{msg}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="h-9 rounded-[10px] border border-amber-line bg-card px-3 font-medium text-amber-ink">
          Retry
        </button>
      )}
    </div>
  );
}

export function Avatar({ id, name, hasPhoto, size }: { id: number; name: string; hasPhoto: boolean; size: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!hasPhoto) return;
    let url: string | null = null;
    let live = true;
    authedBlobUrl(api.photoUrl(id)).then((u) => { url = u; if (live) setSrc(u); }).catch(() => undefined);
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [id, hasPhoto]);
  const { bg, fg } = avatarColours(id);
  if (hasPhoto && src)
    return <img src={src} alt={`Photo of ${name}`} className="shrink-0 rounded-full object-cover" style={{ width: size, height: size }} />;
  return (
    <div title="No photo on file" className="flex shrink-0 items-center justify-center rounded-full font-semibold"
      style={{ width: size, height: size, background: bg, color: fg, fontSize: Math.round(size * 0.34) }}>
      {initials(name)}
    </div>
  );
}

export function PrimaryLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="plain flex h-11 items-center gap-2 rounded-[10px] bg-blue px-[18px] text-[15px] font-semibold text-white hover:bg-blue-hover hover:text-white">
      {children}
    </Link>
  );
}

export function QuietLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="plain flex h-11 items-center gap-2 rounded-[10px] border border-field-line bg-card px-4 text-[15px] font-medium hover:border-blue-line-2">
      {children}
    </Link>
  );
}

export const Icon = {
  upload: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M5 20h14" /></svg>,
  doc: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 3h9l4 4v14H6z" /><path d="M9 12h7M9 16h7M9 8h3" /></svg>,
  plus: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>,
  search: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6A7280" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>,
  eye: <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>,
  close: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>,
  check: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12l5 5L20 7" /></svg>,
};

/** Position against a guideline target: an arrow for the value's direction, words for toward/away. Never good/bad. */
export function DirectionTag({ direction, rise, target, compact = false }: {
  direction: "toward" | "away" | "within" | "unchanged" | null | undefined;
  rise: boolean;
  target: { label: string; source: string; status: string } | null | undefined;
  compact?: boolean;
}) {
  if (!direction || !target) return null;
  const arrow = rise ? "▲" : "▼";
  const words = direction === "toward" ? "toward target" : direction === "away" ? "away from target"
    : direction === "within" ? "within target" : "no nearer the target";
  const tone = direction === "toward" ? "border-blue-line bg-blue-tint-2 text-blue-ink"
    : direction === "away" ? "border-amber-line bg-amber-soft text-amber-ink" : "border-stable-line bg-stable text-ink-2";
  const org = target.source.match(/\b(ADA|KDIGO|ATA|AACE)\b/)?.[0];
  return (
    <span title={`Target ${target.label} · ${target.source}${target.status !== "verified" ? " (not yet verified)" : ""}`}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-[2px] text-xs font-semibold ${tone}`}>
      <span aria-hidden="true">{direction === "within" || direction === "unchanged" ? "•" : arrow}</span>
      {words}{!compact && <span className="font-normal"> {target.label}{org ? ` · ${org}` : ""}</span>}
    </span>
  );
}

export function LabChangeNote({ note, agrees, className = "" }: { note: string; agrees: boolean | null; className?: string }) {
  return (
    <p className={`m-0 flex gap-2 rounded-[10px] border border-dashed px-3 py-2 text-[13px] leading-normal ${agrees ? "border-amber-line bg-amber-soft text-amber-deep" : "border-dash text-ink-2"} ${className}`}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="mt-0.5 shrink-0"><path d="M7 7h11l-3-3M17 17H6l3 3" /></svg>
      <span><strong className="font-semibold">Change of lab:</strong> {note}</span>
    </p>
  );
}
