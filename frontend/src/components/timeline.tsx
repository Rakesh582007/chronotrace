import { useId } from "react";
import type { Medication, TrendPoint } from "../api/types";
import { valueRange, y, type TimeAxis } from "../lib/axis";
import type { ReportRef } from "../lib/patient";
import { useElementWidth } from "../lib/useWidth";

export function Sparkline({ points, baseline, axis, drugDates, lastColour, label, height = 72 }: {
  points: TrendPoint[]; baseline: number | null; axis: TimeAxis; drugDates: string[]; lastColour: string; label: string; height?: number;
}) {
  const [ref, W] = useElementWidth<HTMLDivElement>(366);
  const vals = points.filter((p) => !p.censored);
  const range = valueRange(vals.map((p) => p.value), [baseline]);
  const pts = vals.map((p) => [axis.x(p.date, W), y(p.value, range, height)] as const);
  const last = pts[pts.length - 1];
  const gid = useId().replace(/:/g, "");
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0]} ${p[1]}`).join(" ");
  const area = pts.length > 1 ? `${line} L${last[0]} ${height} L${pts[0][0]} ${height} Z` : "";
  return (
    <div ref={ref} className="w-full">
      <svg width={W} height={height} viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label} className="block overflow-visible">
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={lastColour} stopOpacity="0.14" />
            <stop offset="1" stopColor={lastColour} stopOpacity="0" />
          </linearGradient>
        </defs>
        {area && <path d={area} fill={`url(#${gid})`} className="fade-in" />}
        {drugDates.map((d) => <line key={d} x1={axis.x(d, W)} x2={axis.x(d, W)} y1={0} y2={height} stroke="#9DBFE0" strokeWidth="1" />)}
        {baseline !== null && (
          <line x1={0} x2={W} y1={y(baseline, range, height)} y2={y(baseline, range, height)} stroke="#9AA3AF" strokeWidth="1" strokeDasharray="3 4" />
        )}
        <path d={line} pathLength={1} className="draw" stroke="#1D2733" strokeWidth="1.6" fill="none" strokeLinejoin="round" strokeLinecap="round" />
        {pts.slice(0, -1).map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="2.5" fill="#1D2733" />)}
        {last && (
          <>
            <circle cx={last[0]} cy={last[1]} r="8" fill={lastColour} opacity="0.15" className="fade-in" />
            <circle cx={last[0]} cy={last[1]} r="4.5" fill={lastColour} stroke="#FFFDF9" strokeWidth="1.5" />
          </>
        )}
      </svg>
    </div>
  );
}

/** Reports and medication lanes on the same time axis as the charts. */
export function TimeStrip({ axis, reports, meds, labelWidth = 150 }: {
  axis: TimeAxis; reports: ReportRef[]; meds: Medication[]; labelWidth?: number;
}) {
  const [ref, W] = useElementWidth<HTMLDivElement>(640);
  const drugs = lanes(meds);
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center gap-5">
        <span className="shrink-0 text-[13px] text-ink-3" style={{ width: labelWidth }}>Reports</span>
        <div ref={ref} className="relative h-[34px] min-w-0 grow">
          <div className="absolute inset-x-0 top-2.5 h-px bg-line" />
          {reports.map((r) => (
            <div key={r.id} className="absolute top-[5px] flex -translate-x-1/2 flex-col items-center gap-1" style={{ left: axis.x(r.date, W) }} title={`${r.label} · ${r.date} · ${r.lab ?? ""}`}>
              <span className="box-border h-2.5 w-2.5 rounded-full border-2 border-ink bg-card" />
              <span className="font-mono text-[10px] text-ink-3">{r.label}</span>
            </div>
          ))}
        </div>
      </div>
      {drugs.map((d) => (
        <div key={d.drug} className="flex items-center gap-5">
          <span className="shrink-0 truncate text-sm font-medium" style={{ width: labelWidth }}>{d.drug}</span>
          <div className="relative h-[22px] min-w-0 grow">
            <div className="absolute top-[5px] box-border h-3 rounded-l-md border border-blue-line bg-blue-tint"
              style={{ left: axis.x(d.start, W), width: (d.end ? axis.x(d.end, W) : W) - axis.x(d.start, W) }} />
            <div className="absolute top-0 h-[22px] w-0.5 bg-blue" style={{ left: axis.x(d.start, W) }} title={`${d.drug} started ${d.start}`} />
          </div>
        </div>
      ))}
      <div className="flex items-center gap-5">
        <span className="shrink-0" style={{ width: labelWidth }} />
        <div className="relative h-4 min-w-0 grow">
          {axis.years.map((yr) => (
            <span key={yr} className="num absolute -translate-x-1/2 text-xs text-ink-3" style={{ left: axis.x(yr, W) }}>{yr.slice(0, 4)}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function lanes(meds: Medication[]) {
  const out: { drug: string; start: string; end: string | null; id: number; dose: string | null }[] = [];
  for (const m of [...meds].sort((a, b) => a.date.localeCompare(b.date))) {
    if (m.change === "start") out.push({ drug: m.drug, start: m.date, end: null, id: m.id, dose: m.dose_text });
    else if (m.change === "stop") {
      const lane = [...out].reverse().find((l) => l.drug.toLowerCase() === m.drug.toLowerCase() && !l.end);
      if (lane) lane.end = m.date;
    }
  }
  return out;
}
