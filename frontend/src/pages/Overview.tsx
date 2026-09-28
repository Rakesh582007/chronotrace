import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import type { BodySystem, Flag, Trend } from "../api/types";
import { ChangeCard, CrossLabNote, ExpectedGroup, GuidelineCard } from "../components/flags";
import { Sparkline, TimeStrip } from "../components/timeline";
import { BlueDot, DirectionTag, ErrorBanner, HollowDot, Skeleton, StatusPill, Triangle } from "../components/ui";
import { makeAxis, type TimeAxis } from "../lib/axis";
import { fmtNum, fmtPercent, fmtUnit, plural, shortName } from "../lib/format";
import { useFlags, useMedications, useSystems } from "../lib/patient";
import { usePatientCtx } from "./PatientLayout";

export const STATUS_COLOUR = { guideline: "#C8741F", changed: "#2F6DA3", stable: "#6A7280", no_data: "#6A7280" } as const;

export function sortReview(flags: Flag[]) {
  const review = flags.filter((f) => !f.expected_effect);
  return {
    guideline: review.filter((f) => f.level === "guideline"),
    change: review.filter((f) => f.level !== "guideline"),
    expected: flags.filter((f) => f.expected_effect),
  };
}

/** Drug start dates whose expected-effect window touches any of these analytes' points. */
export function drugDatesFor(trends: Trend[], analyteIds: string[], meds: { id: number; date: string }[]) {
  const ids = new Set<number>();
  for (const t of trends) if (analyteIds.includes(t.analyte_id)) for (const p of t.points) p.in_window.forEach((i) => ids.add(i));
  return meds.filter((m) => ids.has(m.id)).map((m) => m.date);
}

export default function Overview() {
  const { patient, trends, reports, base } = usePatientCtx();
  const flags = useFlags(patient.id);
  const systems = useSystems(patient.id);
  const meds = useMedications(patient.id);
  const location = useLocation();
  const newGuideline = (location.state as { newGuideline?: string } | null)?.newGuideline;

  useEffect(() => { if (newGuideline) window.scrollTo({ top: 0 }); }, [newGuideline]);
  const all = flags.data?.flags ?? [];
  const { guideline, change, expected } = sortReview(all);
  const axis = makeAxis([...reports.list.map((r) => r.date), ...(meds.data ?? []).map((m) => m.date)]);
  const withData = (systems.data?.systems ?? []).filter((s) => s.status !== "no_data");
  const noData = (systems.data?.systems ?? []).filter((s) => s.status === "no_data");

  return (
    <main className="grid grid-cols-1 items-start gap-8 px-4 pb-10 pt-7 sm:px-8 lg:px-14 min-[1100px]:grid-cols-[minmax(360px,440px)_minmax(0,1fr)]">
      <section aria-labelledby="review-h" className="flex flex-col gap-3.5">
        <div className="flex items-baseline justify-between">
          <h2 id="review-h" className="m-0 font-serif text-[26px] font-medium">Needs your review</h2>
          {flags.data && <span className="text-sm text-ink-3">{guideline.length + change.length} of {plural(all.length, "flag")}</span>}
        </div>
        {flags.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}
        {flags.error && <ErrorBanner error={flags.error} onRetry={() => flags.refetch()} />}
        {guideline.map((f) => (
          <GuidelineCard key={f.id} f={f} trends={trends?.analytes} allFlags={all} reports={reports.byId} base={base} arrive={f.id === newGuideline} />
        ))}
        {(() => {
          const lab = change.filter((f) => f.lab_change?.same_lab_agrees);
          return lab.length > 0 && (
            <p className="m-0 rounded-[14px] border border-amber-line bg-amber-soft px-[18px] py-3 text-sm leading-normal text-amber-deep" data-testid="lab-change-summary">
              <strong className="font-semibold">{lab.length} of {change.length} changes</strong> coincide with a change of lab, and results from the
              same lab agree within noise. They may reflect the labs rather than the patient.
            </p>
          );
        })()}
        {change.map((f) => <ChangeCard key={f.id} f={f} reports={reports.byId} />)}
        <ExpectedGroup flags={expected} reports={reports.byId} />
        {flags.data && all.length === 0 && (
          <p className="m-0 rounded-[14px] border border-line bg-card px-[18px] py-4 text-sm text-ink-3">
            {reports.list.length < 2 ? "Trends start from the second confirmed report." : "No flags. Every value is within its change threshold."}
          </p>
        )}
        <CrossLabNote flags={[...guideline, ...change]} />
      </section>

      <section aria-labelledby="systems-h" className="flex min-w-0 flex-col gap-3.5">
        <div className="flex flex-wrap items-baseline gap-4">
          <h2 id="systems-h" className="m-0 font-serif text-[26px] font-medium">Body systems</h2>
          <div className="grow" />
          <div className="flex gap-4 text-[13px] text-ink-3">
            <span className="flex items-center gap-1.5"><Triangle />Guideline alert</span>
            <span className="flex items-center gap-1.5"><BlueDot />Changed</span>
            <span className="flex items-center gap-1.5"><HollowDot />Stable</span>
          </div>
        </div>
        {systems.error && <ErrorBanner error={systems.error} onRetry={() => systems.refetch()} />}
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {systems.isLoading && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[210px] rounded-[18px]" />)}
          {withData.map((s) => (
            <SystemCard key={s.id} s={s} base={base} axis={axis} trends={trends?.analytes ?? []} meds={meds.data ?? []} />
          ))}
          {noData.length > 0 && (
            <div className="flex flex-col gap-3 rounded-[18px] border-[1.5px] border-dashed border-dash px-[22px] py-5">
              <h3 className="m-0 font-serif text-[22px] font-medium text-ink-2">Not in these reports</h3>
              <div className="flex flex-wrap gap-2">
                {noData.map((s) => <span key={s.id} className="rounded-full bg-chip px-3 py-1.5 text-sm text-ink-2">{s.name}</span>)}
              </div>
              <p className="m-0 text-sm leading-[1.55] text-ink-3">No results yet. A system appears as a card once a confirmed report contains one of its tests.</p>
            </div>
          )}
        </div>
        <Link to={`${base}/medications`} className="plain lift mt-1.5 flex flex-col gap-3 rounded-[18px] border border-line bg-card px-[22px] pb-5 pt-[18px]">
          <div className="flex flex-wrap items-baseline gap-3">
            <h3 className="m-0 font-serif text-[22px] font-medium">Reports and medications</h3>
            <span className="text-[13px] text-ink-3">same time axis as the charts</span>
            <div className="grow" />
            <span className="text-[13px] font-medium text-blue">Open medications →</span>
          </div>
          {reports.list.length ? <TimeStrip axis={axis} reports={reports.list} meds={meds.data ?? []} /> : <p className="m-0 text-sm text-ink-3">No confirmed reports yet.</p>}
        </Link>
      </section>
    </main>
  );
}

function SystemCard({ s, base, axis, trends, meds }: { s: BodySystem; base: string; axis: TimeAxis; trends: Trend[]; meds: { id: number; date: string }[] }) {
  const h = s.headline;
  const status = s.status as "guideline" | "changed" | "stable";
  const trend = trends.find((t) => t.analyte_id === h?.analyte_id);
  const n = s.analytes_with_data.length;
  let side: { text: string; cls: string } = { text: "within threshold", cls: "text-ink-3 font-normal" };
  if (status === "guideline" && h?.slope) side = { text: `${fmtNum(h.slope.per_year)} / yr`, cls: "text-amber-ink font-semibold" };
  else if (status === "changed" && h?.change_vs_baseline_percent != null) side = { text: `${fmtPercent(h.change_vs_baseline_percent)} vs baseline`, cls: "text-blue-ink font-semibold" };
  else if (status === "guideline" && h?.change_vs_baseline_percent != null) side = { text: `${fmtPercent(h.change_vs_baseline_percent)} vs baseline`, cls: "text-amber-ink font-semibold" };
  return (
    <Link to={`${base}/systems/${s.id}`} className="plain lift flex min-w-0 flex-col gap-3 rounded-[18px] border border-line bg-card px-[22px] py-5" data-testid={`system-${s.id}`}>
      <div className="flex items-center gap-2.5">
        <h3 className="m-0 font-serif text-2xl font-medium">{s.name}</h3>
        <StatusPill status={status} />
        <div className="grow" />
        <span className="whitespace-nowrap text-[13px] text-ink-3">{plural(n, "parameter")} →</span>
      </div>
      {h?.latest ? (
        <div className="flex flex-wrap items-baseline gap-2.5">
          <span className="text-sm text-ink-3">{shortName(h.name)}</span>
          <span className="num font-serif text-[34px] font-medium leading-none">{h.latest.comparator ?? ""}{fmtNum(h.latest.value)}</span>
          <span className="text-[13px] text-ink-3">{fmtUnit(h.unit)}</span>
          <div className="grow" />
          <span className={`num text-sm ${side.cls}`}>{side.text}</span>
        </div>
      ) : <span className="text-sm text-ink-3">No headline value</span>}
      {h?.target && h.target_direction && h.change_vs_baseline_percent != null && (
        <div className="-mt-1"><DirectionTag direction={h.target_direction} rise={h.change_vs_baseline_percent > 0} target={h.target} /></div>
      )}
      {trend && (
        <Sparkline points={trend.points} baseline={trend.baseline} axis={axis} lastColour={STATUS_COLOUR[status]}
          drugDates={drugDatesFor(trends, s.analytes_with_data.map((a) => a.analyte_id), meds)}
          label={`${shortName(trend.name)} sparkline across ${plural(trend.points.length, "report")}`} />
      )}
      <div className="text-[13px] text-ink-3">{s.analytes_with_data.map((a) => shortName(a.name)).join(" · ")}</div>
    </Link>
  );
}
