import { Link, useParams } from "react-router-dom";
import TrendChart from "../components/TrendChart";
import { changeTitle, guidelineText } from "../components/flags";
import { useToast } from "../components/shell";
import { BlueDot, ErrorBanner, ReportChip, Skeleton, StatusPill, Triangle } from "../components/ui";
import { makeAxis } from "../lib/axis";
import { chartProps, openReportPdf, useWindows } from "../lib/charts";
import { fmtNum, fmtPercent, fmtUnit, plural, shortName } from "../lib/format";
import { labelRuns, useDocuments, useFlags, useMedications, useSystems } from "../lib/patient";
import { usePatientCtx } from "./PatientLayout";

export default function SystemPage() {
  const { system: id } = useParams();
  const { patient, trends, reports, base } = usePatientCtx();
  const systems = useSystems(patient.id);
  const flags = useFlags(patient.id);
  const meds = useMedications(patient.id);
  const docs = useDocuments(patient.id);
  const windows = useWindows(meds.data);
  const toast = useToast();
  const s = systems.data?.systems.find((x) => x.id === id);
  if (systems.error) return <main className="px-4 py-8 sm:px-8 lg:px-14"><ErrorBanner error={systems.error} onRetry={() => systems.refetch()} /></main>;
  if (!s || !trends) return <main className="px-4 py-8 sm:px-8 lg:px-14"><Skeleton className="h-[480px] rounded-[18px]" /></main>;

  const all = flags.data?.flags ?? [];
  const axis = makeAxis([...reports.list.map((r) => r.date), ...(meds.data ?? []).map((m) => m.date)]);
  const ids = s.analytes_with_data.map((a) => a.analyte_id);
  const head = s.headline?.analyte_id;
  const ordered = [head, ...ids.filter((a) => a !== head)].filter(Boolean) as string[];
  const open = async (rid: number) => { if (!(await openReportPdf(rid, docs.data))) toast("The report file was not found.", "amber"); };

  return (
    <>
      <section className="flex flex-wrap items-end gap-6 px-4 pb-[18px] pt-[26px] sm:px-8 lg:px-14">
        <div className="flex flex-col gap-1.5">
          <Link to={base} className="text-sm">← Trends</Link>
          <div className="flex items-center gap-3.5">
            <h2 className="m-0 font-serif text-[44px] font-medium leading-none tracking-[-0.02em]">{s.name}</h2>
            {s.status !== "no_data" && <StatusPill status={s.status} />}
          </div>
        </div>
        <div className="grow" />
        <span className="text-sm text-ink-3">{plural(ids.length, "parameter")} · {plural(s.flag_counts.guideline + s.flag_counts.change, "flag")} to review · {s.flag_counts.expected} expected after a drug start</span>
      </section>
      <main className="flex flex-col gap-5 px-4 pb-10 sm:px-8 lg:px-14">
        {ordered.map((aid, i) => {
          const t = trends.analytes.find((a) => a.analyte_id === aid);
          if (!t) return null;
          const fl = all.filter((f) => f.analyte_id === aid);
          const review = fl.filter((f) => !f.expected_effect);
          const expected = fl.filter((f) => f.expected_effect);
          const last = t.points[t.points.length - 1];
          const pct = t.baseline && last ? ((last.value - t.baseline) / t.baseline) * 100 : null;
          const props = chartProps(t, reports.byId, meds.data ?? [], windows, all);
          return (
            <section key={aid} className={`grid grid-cols-1 gap-6 rounded-[18px] border border-line bg-card px-6 py-5 ${i === 0 ? "min-[1100px]:grid-cols-[minmax(0,1fr)_300px]" : "min-[1100px]:grid-cols-[minmax(0,1fr)_300px]"}`}>
              <div className="flex min-w-0 flex-col gap-3">
                <div className="flex flex-wrap items-baseline gap-3">
                  <h3 className="m-0 font-serif text-2xl font-medium">{shortName(t.name)}</h3>
                  <span className="text-[13px] text-ink-3">{fmtUnit(t.canonical_unit)}</span>
                  <div className="grow" />
                  <Link to={`${base}/parameters/${aid}`} className="text-sm font-medium">Open {shortName(t.name)} →</Link>
                </div>
                <TrendChart {...props} axis={axis} height={i === 0 ? 320 : 220} onOpenReport={open} />
              </div>
              <div className="flex flex-col gap-3 text-sm">
                <dl className="m-0 grid grid-cols-[92px_1fr] gap-y-1.5 text-[13px]">
                  <dt className="text-ink-3">Latest</dt><dd className="num m-0 font-semibold">{last ? `${fmtNum(last.value)} · ${reports.byId.get(last.report_id)?.label}` : "—"}</dd>
                  <dt className="text-ink-3">Baseline</dt><dd className="num m-0">{fmtNum(t.baseline)}</dd>
                  <dt className="text-ink-3">vs baseline</dt><dd className="num m-0">{fmtPercent(pct)}</dd>
                  {t.slope && t.slope.status === "ok" && <><dt className="text-ink-3">Slope</dt><dd className="num m-0">{fmtNum(t.slope.per_year)} / yr</dd></>}
                </dl>
                {review.map((f) => (
                  <div key={f.id} className={`flex flex-col gap-1 rounded-xl px-3 py-2.5 ${f.level === "guideline" ? "border border-amber-line bg-amber-fill" : "border border-line"}`}>
                    <span className={`flex items-center gap-2 font-semibold ${f.level === "guideline" ? "text-amber-ink" : ""}`}>
                      {f.level === "guideline" ? <Triangle /> : <BlueDot />}
                      {f.level === "guideline" ? guidelineText(f, trends.analytes, all).title : changeTitle(f)}
                    </span>
                    <span className="flex flex-wrap gap-1">{labelRuns(f.report_ids, reports.byId).map((l) => <ReportChip key={l} label={l} tone={f.level === "guideline" ? "amber" : "plain"} />)}</span>
                  </div>
                ))}
                {expected.map((f) => (
                  <p key={f.id} className="m-0 rounded-xl border border-dashed border-dash px-3 py-2 text-[13px] text-ink-3">
                    Expected after {f.expected_effect!.drug.toLowerCase()}: {shortName(f.analyte_name)} {fmtPercent(f.change_percent)} · {f.expected_effect!.note}
                  </p>
                ))}
                {!review.length && !expected.length && <p className="m-0 text-[13px] text-ink-3">No flags. Within its change threshold.</p>}
              </div>
            </section>
          );
        })}
      </main>
    </>
  );
}
