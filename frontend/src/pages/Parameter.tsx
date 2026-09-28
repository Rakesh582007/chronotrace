import { Link, useParams } from "react-router-dom";
import type { Flag, Trend } from "../api/types";
import TrendChart from "../components/TrendChart";
import { guidelineText } from "../components/flags";
import { useToast } from "../components/shell";
import { DirectionTag, ErrorBanner, Skeleton, Triangle } from "../components/ui";
import { makeAxis } from "../lib/axis";
import { chartProps, openReportPdf, useWindows } from "../lib/charts";
import { fmtDate, fmtMonth, fmtNum, fmtPct, fmtUnit, shortName } from "../lib/format";
import { labelRuns, useDocuments, useFlags, useMedications, useSystems, type ReportRef } from "../lib/patient";
import { usePatientCtx } from "./PatientLayout";

export default function Parameter() {
  const { analyte } = useParams();
  const { patient, trends, reports, base } = usePatientCtx();
  const flags = useFlags(patient.id);
  const meds = useMedications(patient.id);
  const systems = useSystems(patient.id);
  const docs = useDocuments(patient.id);
  const windows = useWindows(meds.data);
  const toast = useToast();
  const t = trends?.analytes.find((a) => a.analyte_id === analyte);
  const system = systems.data?.systems.find((s) => s.analytes_with_data.some((a) => a.analyte_id === analyte));
  const all = flags.data?.flags ?? [];
  const mine = all.filter((f) => f.analyte_id === analyte);
  const guideline = mine.find((f) => f.level === "guideline" && !f.expected_effect);
  const baseFlag = mine.find((f) => f.rule_id === "RCV_BASELINE");

  if (!trends) return <main className="px-4 py-8 sm:px-8 lg:px-14"><Skeleton className="h-[480px] rounded-[18px]" /></main>;
  if (!t) return <main className="px-4 py-8 text-ink-3 sm:px-8 lg:px-14">No confirmed results for this parameter. <Link to={base}>Back to trends</Link></main>;

  const axis = makeAxis([...reports.list.map((r) => r.date), ...(meds.data ?? []).map((m) => m.date)]);
  const props = chartProps(t, reports.byId, meds.data ?? [], windows, all);
  const excluded = t.slope?.excluded_points ?? [];
  const excludedForDrug = excluded.filter((e) => /window/.test(e.reason));
  const open = async (rid: number) => { if (!(await openReportPdf(rid, docs.data))) toast("The report file was not found.", "amber"); };
  const egfr = t.analyte_id === "egfr";
  const creat = trends.analytes.find((a) => a.analyte_id === "creatinine");

  return (
    <>
      <section className="flex flex-wrap items-end gap-6 px-4 pb-[18px] pt-[26px] sm:px-8 lg:px-14">
        <div className="flex flex-col gap-1.5">
          {system && <Link to={`${base}/systems/${system.id}`} className="text-sm">← {system.name}</Link>}
          <div className="flex flex-wrap items-baseline gap-3.5">
            <h2 className="m-0 font-serif text-[44px] font-medium leading-none tracking-[-0.02em]">{shortName(t.name)}</h2>
            <span className="text-[15px] text-ink-3">{fmtUnit(t.canonical_unit)}{egfr ? " · CKD-EPI 2021, recalculated from creatinine for every report" : ""}</span>
          </div>
        </div>
      </section>
      <main className="grid grid-cols-1 items-start gap-8 px-4 pb-10 sm:px-8 lg:px-14 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(320px,416px)]">
        <div className="flex min-w-0 flex-col gap-5">
          <section aria-label={`${shortName(t.name)} chart`} className="flex flex-col gap-3.5 rounded-[18px] border border-line bg-card px-6 pb-[18px] pt-[22px]">
            <TrendChart {...props} axis={axis} onOpenReport={open} />
            <Legend slope={props.slope ? labelRuns(t.slope?.observation_ids.length ? t.points.filter((p) => t.slope!.observation_ids.includes(p.observation_id)).map((p) => p.report_id) : [], reports.byId).join(", ") : null} hasWindows={props.windows.length > 0} />
          </section>
          <ResultsTable t={t} reports={reports.byId} creat={egfr ? creat : undefined} onOpen={open} inTrend={new Set(props.points.filter((p) => p.inTrend).map((p) => p.reportId))} />
        </div>
        <aside className="flex flex-col gap-4">
          {flags.error && <ErrorBanner error={flags.error} onRetry={() => flags.refetch()} />}
          {guideline && <GuidelinePanel f={guideline} t={t} all={all} reports={reports.byId} trends={trends.analytes} />}
          {excludedForDrug.length > 0 && t.slope && (
            <section className="flex flex-col gap-2.5 rounded-[18px] border border-line bg-card px-[22px] py-[18px]">
              <h3 className="m-0 font-serif text-xl font-medium">Why the early {t.slope.per_year < 0 ? "drop" : "change"} is not in the trend</h3>
              <p className="m-0 text-sm leading-[1.6] text-ink-2">
                {(() => { const l = labelRuns(t.points.filter((p) => p.in_window.length).map((p) => p.report_id), reports.byId); return `${l.join(", ")} ${l.length === 1 && !l[0].includes("–") ? "falls" : "fall"}`; })()} inside the expected-effect
                {" "}{props.drugStarts.length > 1 ? "windows" : "window"} of {props.drugStarts.map((d) => d.label.toLowerCase()).join(" and ")}.
                {" "}The slope starts after the last window closed, so an expected change after a drug start isn't counted in it.
              </p>
            </section>
          )}
          {baseFlag || t.baseline !== null ? <BaselinePanel t={t} f={baseFlag} reports={reports.byId} /> : null}
          <section className="flex flex-col gap-2 rounded-[18px] border border-dashed border-dash px-[22px] py-4">
            <h3 className="m-0 text-sm font-semibold text-ink-2">Data notes</h3>
            <p className="m-0 text-[13px] leading-[1.55] text-ink-3">
              {new Set(t.points.map((p) => p.lab)).size > 1 ? `Results come from ${new Set(t.points.map((p) => p.lab)).size} labs, which adds uncertainty to the comparisons. ` : ""}
              {egfr ? "Age is taken from the birth year (±1 year). The lab's printed eGFR is kept on each report for reference. " : ""}
              {t.rcv_status !== "verified" ? "This parameter's change threshold is not yet verified against a published source. " : ""}
              Adherence is not recorded.
            </p>
          </section>
        </aside>
      </main>
    </>
  );
}

function Legend({ slope, hasWindows }: { slope: string | null; hasWindows: boolean }) {
  return (
    <div className="flex flex-wrap gap-5 border-t border-paper-2 pt-2.5 text-[13px] text-ink-2">
      <span className="flex items-center gap-[7px]"><svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="#2F6DA3" /></svg>Used in the trend</span>
      <span className="flex items-center gap-[7px]"><svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="#FFFDF9" stroke="#6A7280" strokeWidth="1.5" /></svg>Before or inside a drug window</span>
      {hasWindows && <span className="flex items-center gap-[7px]"><svg width="16" height="12" aria-hidden="true"><rect width="16" height="12" fill="#EFE7D6" /></svg>Expected-effect window</span>}
      {slope && <span className="flex items-center gap-[7px]"><svg width="24" height="6" aria-hidden="true"><line x1="0" y1="3" x2="24" y2="3" stroke="#C8741F" strokeWidth="2.5" strokeDasharray="7 5" /></svg>Slope {slope}</span>}
    </div>
  );
}

function GuidelinePanel({ f, t, all, reports, trends }: { f: Flag; t: Trend; all: Flag[]; reports: Map<number, ReportRef>; trends: Trend[] }) {
  const s = f.compared.slope;
  const { body } = guidelineText(f, trends, all);
  const labels = f.report_ids.map((id) => reports.get(id)?.label).filter(Boolean);
  return (
    <section className="flex flex-col gap-3 rounded-[18px] border border-amber-line bg-amber-fill px-[22px] py-5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-amber-ink"><Triangle />Guideline · KDIGO</div>
      {s && (
        <div className="flex items-baseline gap-2">
          <span className="num font-serif text-[52px] font-medium leading-none tracking-[-0.02em]">{fmtNum(s.per_year)}</span>
          <span className="text-[15px] text-[#5A3A12]">per year</span>
        </div>
      )}
      <p className="m-0 text-sm leading-[1.55] text-amber-deep">{body}</p>
      <dl className="m-0 grid grid-cols-[110px_1fr] gap-y-1.5 text-[13px]">
        <dt className="text-[#6B4A20]">Results</dt><dd className="m-0">{labels.length} · {labels.join(", ")}</dd>
        {s && <><dt className="text-[#6B4A20]">Span</dt><dd className="m-0">{s.span_days} days · {fmtMonth(s.first_date)} – {fmtMonth(s.last_date)}</dd></>}
        <dt className="text-[#6B4A20]">Rule</dt><dd className="m-0 font-mono text-xs">{f.rule_id}</dd>
        <dt className="text-[#6B4A20]">Threshold</dt><dd className="m-0">−{fmtPct(Math.abs(f.threshold.value))} {fmtUnit(t.canonical_unit)} per year · KDIGO 2012</dd>
      </dl>
    </section>
  );
}

function BaselinePanel({ t, f, reports }: { t: Trend; f: Flag | undefined; reports: Map<number, ReportRef> }) {
  const last = t.points[t.points.length - 1];
  const pct = t.baseline && last ? ((last.value - t.baseline) / t.baseline) * 100 : null;
  const baseReports = t.points.filter((p) => t.baseline_observation_ids.includes(p.observation_id)).map((p) => p.report_id);
  const drugs = f?.drug_events_since_baseline ?? [];
  return (
    <section className="flex flex-col gap-2.5 rounded-[18px] border border-line bg-card px-[22px] py-[18px]">
      <div className="flex items-baseline gap-2.5">
        <h3 className="m-0 font-serif text-xl font-medium">Change from baseline</h3>
        <div className="grow" />
        {pct !== null && <span className={`num font-serif text-[26px] ${f ? "text-blue-ink" : "text-ink-2"}`}>{pct < 0 ? "−" : "+"}{Math.abs(pct).toFixed(1)}%</span>}
      </div>
      <dl className="m-0 grid grid-cols-[110px_1fr] gap-y-1.5 text-[13px]">
        <dt className="text-ink-3">Baseline</dt><dd className="num m-0">{fmtNum(t.baseline)} · {baseReports.length > 1 ? `median of ${labelRuns(baseReports, reports).join(", ")}` : labelRuns(baseReports, reports).join("")}</dd>
        {last && <><dt className="text-ink-3">Latest</dt><dd className="num m-0">{fmtNum(last.value)} · {reports.get(last.report_id)?.label} · {fmtDate(last.date)}</dd></>}
        {t.target && <><dt className="text-ink-3">Target</dt><dd className="m-0">{t.target.label} · {t.target.source.split(/[,:(]/)[0]}{t.target.status !== "verified" ? " (not yet verified)" : ""}
          {t.baseline !== null && last && <> · <DirectionTag direction={targetDir(t, t.baseline, last.value)} rise={last.value > t.baseline} target={t.target} compact /></>}</dd></>}
        {t.rcv_percent !== null && <><dt className="text-ink-3">Threshold</dt><dd className="m-0">{fmtPct(t.rcv_percent)}% · {t.rcv_status === "verified" ? <span className="font-semibold text-[#2F5A3C]">verified</span> : "not yet verified"}</dd></>}
        {drugs.length > 0 && <><dt className="text-ink-3">Since baseline</dt><dd className="m-0">{drugs.map((d) => `${d.drug} (${fmtMonth(d.date)})`).join(", ")}</dd></>}
        <dt className="text-ink-3">Flag</dt><dd className="m-0">{f ? f.message : "Within the change threshold"}</dd>
      </dl>
    </section>
  );
}

function ResultsTable({ t, reports, creat, onOpen, inTrend }: { t: Trend; reports: Map<number, ReportRef>; creat?: Trend; onOpen: (id: number) => void; inTrend: Set<number> }) {
  return (
    <section aria-labelledby="results-h" className="overflow-hidden rounded-[18px] border border-line bg-card">
      <div className="flex items-baseline gap-3 border-b border-paper-2 px-6 py-4">
        <h3 id="results-h" className="m-0 font-serif text-[22px] font-medium">Results</h3>
        <span className="text-[13px] text-ink-3">{t.points.length} confirmed reports · click a row to open the report</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-[0.05em] text-ink-3">
              <th scope="col" className="px-6 py-2.5 font-semibold">Report</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">Collected</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">Lab</th>
              {creat && <th scope="col" className="px-2 py-2.5 text-right font-semibold">Creatinine</th>}
              <th scope="col" className="px-2 py-2.5 text-right font-semibold">{shortName(t.name)}</th>
              <th scope="col" className="px-2 py-2.5 text-right font-semibold">vs previous</th>
              <th scope="col" className="py-2.5 pl-5 pr-6 font-semibold">In trend</th>
            </tr>
          </thead>
          <tbody>
            {t.points.map((p, i) => {
              const prev = t.points[i - 1];
              const d = prev ? ((p.value - prev.value) / prev.value) * 100 : null;
              const c = creat?.points.find((x) => x.report_id === p.report_id);
              const use = inTrend.has(p.report_id) ? "Yes" : p.in_window.length ? "Drug window" : t.slope && p.date < t.slope.first_date ? "Before drug windows" : "No";
              return (
                <tr key={p.observation_id} tabIndex={0} onClick={() => onOpen(p.report_id)} onKeyDown={(e) => e.key === "Enter" && onOpen(p.report_id)}
                  className="cursor-pointer border-t border-[#F0E9DB] hover:bg-[#FBF8F2]">
                  <td className="px-6 py-2 font-mono text-[13px]">{reports.get(p.report_id)?.label}</td>
                  <td className="num px-2 py-2">{fmtDate(p.date)}</td>
                  <td className="px-2 py-2 text-ink-2">{p.lab ?? "—"}</td>
                  {creat && <td className="num px-2 py-2 text-right">{c ? fmtNum(c.value) : "—"}</td>}
                  <td className="num px-2 py-2 text-right font-semibold">{p.comparator ?? ""}{fmtNum(p.value)}</td>
                  <td className="num px-2 py-2 text-right text-ink-2">{d === null ? "—" : `${d < 0 ? "−" : "+"}${Math.abs(d).toFixed(1)}%`}</td>
                  <td className={`py-2 pl-5 pr-6 text-[13px] ${use === "Yes" ? "text-blue-ink" : "text-ink-3"}`}>{use}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function targetDir(t: Trend, a: number, b: number): "toward" | "away" | "within" | "unchanged" | null {
  if (!t.target) return null;
  const d = (v: number) => (t.target!.low !== null && v < t.target!.low ? t.target!.low - v : t.target!.high !== null && v > t.target!.high ? v - t.target!.high : 0);
  const d0 = d(a), d1 = d(b);
  if (d0 === 0 && d1 === 0) return "within";
  if (Math.abs(d1 - d0) < 1e-9) return "unchanged";
  return d1 < d0 ? "toward" : "away";
}
