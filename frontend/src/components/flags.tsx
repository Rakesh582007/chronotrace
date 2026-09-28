import { Link } from "react-router-dom";
import type { Flag, Trend } from "../api/types";
import { capitalise, fmtDate, fmtMonth, fmtMonthLong, fmtNum, fmtPct, fmtUnit, shortName } from "../lib/format";
import { labelRuns, type ReportRef } from "../lib/patient";
import { BlueDot, DirectionTag, LabChangeNote, ReportChip, Triangle } from "./ui";

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
  const proj = trends?.find((t) => t.analyte_id === f.analyte_id)?.projection;
  return (
    <article className={`flex flex-col gap-2.5 rounded-2xl border border-amber-line bg-amber-fill px-5 py-5 ${arrive ? "arrive" : ""}`} data-testid="guideline-card">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-amber-ink">
        <Triangle />Guideline · {f.rule_id.startsWith("KDIGO") ? "KDIGO" : f.rule_id}
      </div>
      <h3 className="m-0 font-serif text-[22px] font-medium leading-[1.2]">{title}</h3>
      <div><DirectionTag direction={f.target_direction} rise={f.direction === "rise"} target={f.target} /></div>
      <p className="m-0 text-sm leading-[1.55] text-amber-deep">{body}</p>
      {proj && (
        <p className="m-0 rounded-[10px] border border-amber-line bg-amber-soft px-3 py-2 text-[13px] leading-normal text-amber-deep" data-testid="projection-line">
          <strong className="font-semibold">Straight line reaches {proj.threshold} (KDIGO {proj.category}) around {fmtMonth(proj.date)}</strong>
          {" "}· 95% range {fmtMonth(proj.date_earliest)} – {proj.date_latest ? fmtMonth(proj.date_latest) : "open"}. A projection of past results, not a forecast.
        </p>
      )}
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
    <article className="flex flex-col gap-2 rounded-[14px] border border-line bg-card px-5 py-4" data-testid="change-card">
      <div className="flex items-baseline gap-2.5">
        <span className="-translate-y-px"><BlueDot /></span>
        <h3 className="m-0 text-base font-semibold">{changeTitle(f)}</h3>
        <div className="grow" />
        {from && to && <span className="num whitespace-nowrap text-sm">{fmtNum(from.value)} → {fmtNum(to.value)}</span>}
      </div>
      <div className="ml-[18px] flex flex-wrap items-center gap-1.5">
        {from && labelRuns(from.report_ids, reports).map((l) => <ReportChip key={"f" + l} label={l} />)}
        {from && to && <span aria-hidden="true" className="text-xs text-ink-3">→</span>}
        {to && labelRuns(to.report_ids, reports).map((l) => <ReportChip key={"t" + l} label={l} />)}
        <div className="grow" />
        <DirectionTag direction={f.target_direction} rise={f.direction === "rise"} target={f.target} />
      </div>
      {f.lab_change?.same_lab_agrees && <LabChangeNote className="ml-[18px]" note={labNote(f, reports)} agrees />}
      <details className="group ml-[18px]">
        <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-ink-3 hover:text-ink-2 [&::-webkit-details-marker]:hidden">
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className="transition-transform duration-200 group-open:rotate-90"><path d="M4 2.5 7.5 6 4 9.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Details
        </summary>
        <div className="mt-2 flex flex-col gap-1.5 text-xs leading-normal text-ink-3">
          <span>
            Threshold {fmtPct(f.threshold.value)}% ({verified}).
            {drugs.length > 0 && <> Since {f.rule_id === "RCV_PREV" ? "the previous result" : "baseline"}: {drugs.join(", ")}.</>}
          </span>
          {from && to && (
            <span data-testid="flag-dates">
              {from.label === "baseline" ? "Baseline" : "Previous"} {dateSpan(from.dates ?? [])} → {fmtDate(to.date ?? f.date)}
            </span>
          )}
          {f.lab_change && !f.lab_change.same_lab_agrees && <LabChangeNote note={labNote(f, reports)} agrees={f.lab_change.same_lab_agrees} />}
        </div>
      </details>
    </article>
  );
}

export function ExpectedGroup({ flags, reports, open = false }: { flags: Flag[]; reports: Reports; open?: boolean }) {
  if (!flags.length) return null;
  return (
    <details open={open} className="rounded-[14px] border border-dashed border-dash px-5 py-3.5">
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

/** The engine's note with report labels instead of dates, where we know them. */
export function labNote(f: Flag, reports: Reports) {
  const lc = f.lab_change!;
  const same = lc.same_lab_report_ids.map((id) => reports.get(id)?.label).filter(Boolean).join(", ");
  if (lc.same_lab_agrees)
    return `${lc.from_lab} → ${lc.to_lab}. The ${same ? `${same} result` : "result"} from the same lab agrees with the earlier value within noise, so this change may reflect the difference between the labs rather than the patient.`;
  if (lc.same_lab_agrees === false)
    return `${lc.from_lab} → ${lc.to_lab}. Results from the same lab${same ? ` (${same})` : ""} show a change as well.`;
  return `${lc.from_lab} → ${lc.to_lab}. No result from the same lab to compare with yet.`;
}

function dateSpan(dates: string[]) {
  if (!dates.length) return "";
  const s = [...dates].sort();
  return s.length === 1 ? fmtDate(s[0]) : `${fmtDate(s[0])} – ${fmtDate(s[s.length - 1])}`;
}
