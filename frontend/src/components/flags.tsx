import { Link } from "react-router-dom";
import type { Flag, Trend } from "../api/types";
import { capitalise, fmtMonthLong, fmtNum, fmtPct, fmtUnit, shortName } from "../lib/format";
import { labelRuns, type ReportRef } from "../lib/patient";
import { BlueDot, ReportChip, Triangle } from "./ui";

type Reports = Map<number, ReportRef>;

function pointAt(trends: Trend[] | undefined, analyte: string, date: string) {
  return trends?.find((t) => t.analyte_id === analyte)?.points.find((p) => p.date === date);
}

/** Wording for the KDIGO eGFR slope card. Never "rapid progression" (banned wording). */
export function guidelineText(f: Flag, trends: Trend[] | undefined, allFlags: Flag[]) {
  const s = f.compared.slope;
  const perYear = s ? fmtNum(Math.abs(s.per_year)) : "";
  const first = s ? pointAt(trends, f.analyte_id, s.first_date) : undefined;
  const last = s ? pointAt(trends, f.analyte_id, s.last_date) : undefined;
  const rcv = trends?.find((t) => t.analyte_id === f.analyte_id)?.rcv_percent;
  const stepFlag = allFlags.some((x) => x.analyte_id === f.analyte_id && x.rule_id === "RCV_PREV" && !x.expected_effect && s && x.date >= s.first_date);
  const title = `${shortName(f.analyte_name)} is ${f.direction === "fall" ? "falling" : "rising"} ${perYear} per year`;
  const parts: string[] = [];
  if (s && first && last)
    parts.push(`From ${fmtNum(first.value)} to ${fmtNum(last.value)} over ${s.n_points} reports since ${fmtMonthLong(s.first_date)} (${s.span_days} days).`);
  parts.push(`Beyond the KDIGO threshold of −${fmtPct(Math.abs(f.threshold.value))} ${fmtUnit(f.unit)}/yr.`);
  if (rcv && !stepFlag) parts.push(`No single step crossed the ${fmtPct(rcv)}% change threshold.`);
  return { title, body: parts.join(" ") };
}

export function GuidelineCard({ f, trends, allFlags, reports, base, link = true, arrive = false }: {
  f: Flag; trends: Trend[] | undefined; allFlags: Flag[]; reports: Reports; base: string; link?: boolean; arrive?: boolean;
}) {
  const { title, body } = guidelineText(f, trends, allFlags);
  return (
    <article className={`flex flex-col gap-2.5 rounded-2xl border border-amber-line bg-amber-fill px-5 py-[18px] ${arrive ? "arrive" : ""}`} data-testid="guideline-card">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-amber-ink">
        <Triangle />Guideline · {f.rule_id.startsWith("KDIGO") ? "KDIGO" : f.rule_id}
      </div>
      <h3 className="m-0 font-serif text-[23px] font-medium leading-[1.2]">{title}</h3>
      <p className="m-0 text-sm leading-[1.55] text-amber-deep">{body}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {f.report_ids.map((id) => reports.get(id)).filter(Boolean).map((r) => (
          <ReportChip key={r!.id} label={r!.label} tone="amber" title={`${r!.label} · ${r!.date} · ${r!.lab ?? ""}`} />
        ))}
        <div className="grow" />
        {link && <Link to={`${base}/parameters/${f.analyte_id}`} className="text-sm font-semibold text-amber-ink hover:text-amber-ink">Open {shortName(f.analyte_name)} →</Link>}
      </div>
    </article>
  );
}

export function changeTitle(f: Flag) {
  const pct = Math.round(Math.abs(f.change_percent ?? 0));
  const vs = f.rule_id === "RCV_PREV" ? "the previous result" : "baseline";
  return `${shortName(f.analyte_name)} ${pct}% ${f.direction === "fall" ? "below" : "above"} ${vs}`;
}

export function ChangeCard({ f, reports }: { f: Flag; reports: Reports }) {
  const from = f.compared.from;
  const to = f.compared.to;
  const drugs = [...new Set(f.drug_events_since_baseline.map((d) => d.drug.toLowerCase()))];
  const verified = f.threshold.rcv_status === "verified" ? "verified" : "not yet verified";
  return (
    <article className="flex flex-col gap-2 rounded-[14px] border border-line bg-card px-[18px] py-4" data-testid="change-card">
      <div className="flex items-baseline gap-2.5">
        <span className="-translate-y-px"><BlueDot /></span>
        <h3 className="m-0 text-base font-semibold">{changeTitle(f)}</h3>
        <div className="grow" />
        {from && to && <span className="num whitespace-nowrap text-sm">{fmtNum(from.value)} → {fmtNum(to.value)}</span>}
      </div>
      <p className="m-0 ml-[18px] text-[13px] leading-normal text-ink-3">
        Threshold {fmtPct(f.threshold.value)}% ({verified}).
        {drugs.length > 0 && <> Since {f.rule_id === "RCV_PREV" ? "the previous result" : "baseline"}: {drugs.join(", ")}.</>}
      </p>
      <div className="ml-[18px] flex flex-wrap gap-1.5">
        {from && labelRuns(from.report_ids, reports).map((l) => <ReportChip key={"f" + l} label={l} />)}
        {to && labelRuns(to.report_ids, reports).map((l) => <ReportChip key={"t" + l} label={l} />)}
      </div>
    </article>
  );
}

export function ExpectedGroup({ flags, reports, open = false }: { flags: Flag[]; reports: Reports; open?: boolean }) {
  if (!flags.length) return null;
  return (
    <details open={open} className="rounded-[14px] border border-dashed border-dash px-[18px] py-3.5">
      <summary className="cursor-pointer text-sm font-semibold text-ink-2">Expected after a drug start · {flags.length}</summary>
      <div className="mt-3 flex flex-col gap-3">
        {flags.map((f) => {
          const e = f.expected_effect!;
          const pct = f.change_percent ?? 0;
          const runs = [...labelRuns(f.compared.from?.report_ids ?? [], reports), ...labelRuns(f.compared.to?.report_ids ?? [], reports)];
          return (
            <div key={f.id} className="flex flex-col gap-1">
              <div className="flex items-baseline gap-2.5">
                <span className="text-sm font-medium">{shortName(f.analyte_name)} {pct < 0 ? "−" : "+"}{Math.round(Math.abs(pct))}% after {e.drug.toLowerCase()}</span>
                <div className="grow" />
                <span className="font-mono text-xs text-ink-3">{runs.join(" → ")}</span>
              </div>
              <span className="text-[13px] leading-normal text-ink-3">{capitalise(e.note)}.</span>
            </div>
          );
        })}
      </div>
    </details>
  );
}

export function CrossLabNote({ flags }: { flags: Flag[] }) {
  if (!flags.some((f) => f.cross_lab)) return null;
  return <p className="m-0 mt-0.5 text-xs leading-normal text-ink-3">These comparisons span different labs. Between-lab variation is larger than the thresholds assume.</p>;
}
