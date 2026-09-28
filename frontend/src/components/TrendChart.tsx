import { useRef, useState, type KeyboardEvent } from "react";
import { valueRange, y as yOf, type TimeAxis } from "../lib/axis";
import { fmtDate, fmtNum, fmtUnit, parseDate } from "../lib/format";
import { useElementWidth } from "../lib/useWidth";

export interface ChartPoint {
  date: string;
  value: number;
  censored: boolean;
  comparator: string | null;
  reportLabel: string;
  reportId: number;
  lab: string | null;
  page: number;
  inTrend: boolean;
}

export interface ChartProps {
  points: ChartPoint[];
  baseline: number | null;
  baselineLabel?: string;
  threshold?: { value: number; label: string } | null;
  target?: { low: number | null; high: number | null; label: string; source: string } | null;
  /** ± percent around each result from lab and biological variation alone (the change threshold / √2). */
  noisePercent?: number | null;
  projection?: { fromDate: string; fromValue: number; date: string; earliest: string; latest: string | null; threshold: number; category: string } | null;
  windows: { from: string; to: string; label: string }[];
  drugStarts: { date: string; label: string }[];
  slope: { from: string; to: string; perYear: number } | null;
  axis: TimeAxis;
  height?: number;
  unit: string;
  name: string;
  onOpenReport?: (reportId: number) => void;
}

const PAD_L = 44, PAD_R = 16, PAD_T = 12, AXIS_H = 44;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "Mar ’26" */
function shortDate(d: string) {
  const [y, m] = d.split("-");
  return `${MONTHS[Number(m) - 1]} ’${y.slice(2)}`;
}
const DAY = 86_400_000;

/**
 * Hand-written SVG trend chart (decision: not Recharts, because drug windows, hollow/solid points,
 * the slope overlay and clickable source points have to match the design exactly).
 */
export default function TrendChart(props: ChartProps) {
  const { points, baseline, threshold, target, windows, drugStarts, slope, axis, unit, name, onOpenReport, noisePercent, projection } = props;
  const height = props.height ?? 384;
  const [wrap, width] = useElementWidth<HTMLDivElement>(832);
  const W = width - PAD_L - PAD_R;
  const H = height - PAD_T - AXIS_H;
  const [sel, setSel] = useState<number | null>(null);
  const refs = useRef<(SVGGElement | null)[]>([]);

  const u = noisePercent ? noisePercent / 100 : 0;
  const range = valueRange(points.flatMap((p) => (u && !p.censored ? [p.value * (1 - u), p.value * (1 + u)] : [p.value])),
    [baseline, threshold?.value, projection?.threshold]);
  const X = (d: string) => axis.x(d, W);
  const Y = (v: number) => yOf(v, range, H);
  const ticks = niceTicks(range[0], range[1]);
  const drawn = points.filter((p) => !p.censored);
  const line = drawn.map((p, i) => `${i ? "L" : "M"}${X(p.date)} ${Y(p.value)}`).join(" ");

  const noisePath = u && drawn.length > 1
    ? `M${drawn.map((p) => `${X(p.date)} ${Y(p.value * (1 + u))}`).join(" L")} L${[...drawn].reverse().map((p) => `${X(p.date)} ${Y(p.value * (1 - u))}`).join(" L")} Z`
    : "";
  let slopePath = "";
  if (slope) {
    const used = points.filter((p) => p.inTrend && !p.censored);
    if (used.length >= 2) {
      const t0 = parseDate(slope.from).getTime();
      const xs = used.map((p) => (parseDate(p.date).getTime() - t0) / (365.25 * DAY));
      const mx = xs.reduce((a, b) => a + b, 0) / xs.length;
      const my = used.reduce((a, p) => a + p.value, 0) / used.length;
      const b = slope.perYear;
      const a = my - b * mx;
      const x1 = (parseDate(slope.to).getTime() - t0) / (365.25 * DAY);
      slopePath = `M${X(slope.from)} ${Y(a)} L${X(slope.to)} ${Y(a + b * x1)}`;
    }
  }

  function key(e: KeyboardEvent, i: number) {
    let j = i;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") j = Math.min(points.length - 1, i + 1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") j = Math.max(0, i - 1);
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(sel === i ? null : i); return; }
    else if (e.key === "Escape") { setSel(null); return; }
    else return;
    e.preventDefault();
    refs.current[j]?.focus();
    if (sel !== null) setSel(j);
  }

  const s = sel !== null ? points[sel] : null;
  const calloutLeft = s ? Math.min(Math.max(PAD_L + X(s.date) - 107, 0), width - 222) : 0;
  const calloutTop = s ? (Y(s.value) + PAD_T > H / 2 ? PAD_T + Y(s.value) - 150 : PAD_T + Y(s.value) + 18) : 0;

  return (
    <div ref={wrap} className="relative w-full" style={{ height }}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" className="block"
        aria-label={`${name} across ${points.length} reports${baseline !== null ? `. Baseline ${fmtNum(baseline)}` : ""}${slope ? `. Slope ${fmtNum(slope.perYear)} per year` : ""}.`}>
        <g transform={`translate(${PAD_L} ${PAD_T})`}>
          {target && (() => {
            const top = target.high === null ? 0 : Math.max(0, Math.min(H, Y(target.high)));
            const bottom = target.low === null ? H : Math.max(0, Math.min(H, Y(target.low)));
            const org = target.source.match(/\b(ADA|KDIGO|ATA)\b/)?.[0];
            const text = `Target ${target.label}${org ? ` · ${org}` : ""}`;
            if (bottom - top < 1) {
              const above = target.low !== null && Y(target.low) < 0;
              return <text x={W} y={above ? 12 : H - 6} textAnchor="end" fontSize="11" fill="#1F5282">{text} ({above ? "above" : "below"} this chart)</text>;
            }
            return (
              <g>
                <rect x={0} y={top} width={W} height={bottom - top} fill="#EAF3FB" opacity="0.65" />
                <text x={W - 4} y={bottom - 5} textAnchor="end" fontSize="11" fill="#1F5282">{text}</text>
              </g>
            );
          })()}
          {windows.map((w, i) => (
            <rect key={i} x={X(w.from)} y={0} width={Math.max(2, X(w.to) - X(w.from))} height={H} fill={i % 2 ? "#F2EBDD" : "#EFE7D6"}>
              <title>{w.label}</title>
            </rect>
          ))}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={0} x2={W} y1={Y(t)} y2={Y(t)} stroke="#EDE5D5" />
              <text x={-10} y={Y(t)} dy={4} textAnchor="end" fontSize="12" fill="#4A5563">{fmtTick(t)}</text>
            </g>
          ))}
          {baseline !== null && (
            <>
              <line x1={0} x2={W} y1={Y(baseline)} y2={Y(baseline)} stroke="#6A7280" strokeWidth="1.2" strokeDasharray="5 5" />
              <text x={W} y={Y(baseline)} dy={-7} textAnchor="end" fontSize="12" fill="#3F4855">{props.baselineLabel ?? `Baseline ${fmtNum(baseline)}`}</text>
            </>
          )}
          {threshold && (
            <>
              <line x1={0} x2={W} y1={Y(threshold.value)} y2={Y(threshold.value)} stroke="#B9A98A" strokeDasharray="2 4" />
              <text x={6} y={Y(threshold.value)} dy={-7} fontSize="12" fill="#5B4C2E">{threshold.label}</text>
            </>
          )}
          {drugStarts.map((d) => <line key={d.date + d.label} x1={X(d.date)} x2={X(d.date)} y1={0} y2={H} stroke="#2F6DA3" strokeWidth="1.5" />)}
          {noisePath && <path d={noisePath} fill="#1D2733" opacity="0.07" />}
          {projection && (
            <g>
              <line x1={0} x2={W} y1={Y(projection.threshold)} y2={Y(projection.threshold)} stroke="#C8741F" strokeWidth="1" strokeDasharray="2 3" opacity="0.8" />
              <text x={6} y={Y(projection.threshold)} dy={14} fontSize="11" fill="#8A4507">KDIGO {projection.category} starts at {projection.threshold}</text>
              <rect x={X(projection.earliest)} y={Y(projection.threshold) - 4} height={8}
                width={Math.max(3, (projection.latest ? X(projection.latest) : W) - X(projection.earliest))} rx={4} fill="#FBEBD3" stroke="#EBC48E" />
              <path d={`M${X(projection.fromDate)} ${Y(projection.fromValue)} L${X(projection.date)} ${Y(projection.threshold)}`}
                stroke="#C8741F" strokeWidth="1.6" strokeDasharray="2 4" fill="none" />
              <circle cx={X(projection.date)} cy={Y(projection.threshold)} r={4} fill="#FFFDF9" stroke="#C8741F" strokeWidth="1.6" />
            </g>
          )}
          <path d={line} stroke="#1D2733" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
          {slopePath && <path d={slopePath} stroke="#C8741F" strokeWidth="2.5" strokeDasharray="7 5" fill="none" strokeLinecap="round" />}
          {points.map((p, i) => {
            const cx = X(p.date), cy = Y(p.value);
            const label = `${p.comparator ?? ""}${fmtNum(p.value)} ${fmtUnit(unit)}, ${fmtDate(p.date)}, report ${p.reportLabel}${p.lab ? `, ${p.lab}` : ""}${p.inTrend ? ", used in the trend" : ""}`;
            return (
              <g key={p.reportId + p.date} ref={(el) => { refs.current[i] = el; }} tabIndex={0} role="button" aria-label={label}
                aria-pressed={sel === i} onClick={() => setSel(sel === i ? null : i)} onKeyDown={(e) => key(e, i)}
                className="cursor-pointer outline-none [&:focus-visible>circle.ring]:opacity-100">
                <circle cx={cx} cy={cy} r={14} fill="transparent" />
                <circle className="ring" cx={cx} cy={cy} r={10} fill="none" stroke="#2F6DA3" strokeWidth="1.6" opacity={sel === i ? 1 : 0} />
                {p.censored ? (
                  <>
                    <circle cx={cx} cy={cy} r={5} fill="#FFFDF9" stroke="#1D2733" strokeWidth="1.6" strokeDasharray="2 2" />
                    <text x={cx} y={cy - 10} textAnchor="middle" fontSize="11" fill="#3F4855">{p.comparator}{fmtNum(p.value)}</text>
                  </>
                ) : p.inTrend ? <circle cx={cx} cy={cy} r={5.5} fill="#2F6DA3" />
                  : <circle cx={cx} cy={cy} r={5} fill="#FFFDF9" stroke="#6A7280" strokeWidth="1.6" />}
              </g>
            );
          })}
          <line x1={0} x2={W} y1={H} y2={H} stroke="#CFC5B2" />
        </g>
      </svg>
      {drugStarts.map((d, i) => (
        <div key={d.date + d.label} className="pointer-events-none absolute rounded bg-card px-1.5 py-px text-xs font-semibold text-blue-ink"
          style={{ top: 14 + (i % 3) * 20, left: PAD_L + X(d.date) + 4 }}>{d.label}</div>
      ))}
      <div className="pointer-events-none absolute" style={{ left: PAD_L, top: PAD_T + H + 6, width: W, height: 30 }}>
        {(() => {
          let lastX = -99;
          return points.map((p) => {
            const x = X(p.date);
            const showDate = x - lastX >= 38;
            if (showDate) lastX = x;
            return (
              <div key={"l" + p.reportId + p.date} className="absolute flex -translate-x-1/2 flex-col items-center leading-tight" style={{ left: x }}>
                <span className={`font-mono text-[11px] ${p.inTrend ? "text-blue-ink" : "text-ink-3"}`}>{p.reportLabel}</span>
                {showDate && <span className="num whitespace-nowrap text-[10px] text-ink-3">{shortDate(p.date)}</span>}
              </div>
            );
          });
        })()}
      </div>
      {s && (
        <div role="dialog" aria-label={`Selected result ${s.reportLabel}`} className="absolute z-10 flex w-[214px] flex-col gap-1.5 rounded-xl bg-ink px-3.5 py-3 text-paper shadow-[0_16px_30px_-18px_rgba(29,39,51,0.7)]"
          style={{ left: calloutLeft, top: Math.max(0, calloutTop) }}>
          <div className="flex items-baseline justify-between">
            <span className="font-mono text-xs text-[#C9D6E4]">{s.reportLabel} · {fmtDate(s.date)}</span>
            <button type="button" aria-label="Close" onClick={() => setSel(null)} className="text-[#C9D6E4]">×</button>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="num font-serif text-[28px] leading-none">{s.comparator ?? ""}{fmtNum(s.value)}</span>
            <span className="text-xs text-[#C9D6E4]">{fmtUnit(unit)}</span>
          </div>
          <span className="text-xs leading-[1.45] text-[#DCE3EA]">{s.lab ?? "Lab not printed"} · page {s.page}{s.inTrend ? " · used in the trend" : ""}</span>
          {u > 0 && !s.censored && (
            <span className="text-xs leading-[1.45] text-[#DCE3EA]">Noise alone: about {fmtNum(s.value * (1 - u))}–{fmtNum(s.value * (1 + u))}</span>
          )}
          {onOpenReport && (
            <button type="button" onClick={() => onOpenReport(s.reportId)} className="self-start text-[13px] font-semibold text-[#9DC6EE] hover:underline">Open report →</button>
          )}
        </div>
      )}
    </div>
  );
}

function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo;
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= 5) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}
function fmtTick(v: number) {
  return Math.abs(v) >= 10 || Number.isInteger(v) ? String(Math.round(v * 10) / 10) : String(v);
}
