import { NavLink, Navigate, Outlet, useOutletContext, useParams } from "react-router-dom";
import type { PatientCard, TrendsResponse } from "../api/types";
import { AppHeader } from "../components/shell";
import { Avatar, ConditionChip, ErrorBanner, Icon, PrimaryLink, QuietLink, Skeleton } from "../components/ui";
import { age, capitalise, fmtMonth, sexLabel } from "../lib/format";
import { reportIndex, usePatient, useTrends, type ReportRef } from "../lib/patient";

export interface PatientCtx {
  patient: PatientCard;
  trends: TrendsResponse | undefined;
  reports: { list: ReportRef[]; byId: Map<number, ReportRef> };
  base: string;
}
export const usePatientCtx = () => useOutletContext<PatientCtx>();

export default function PatientLayout() {
  const { code } = useParams();
  const { patient, isLoading, error, refetch, notFound } = usePatient(code);
  const trends = useTrends(patient?.id);
  if (notFound) return <Navigate to="/patients" replace />;
  const reports = reportIndex(trends.data);
  const base = `/patients/${code}`;
  const first = reports.list[0]?.date;
  const last = reports.list[reports.list.length - 1]?.date;

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader crumb={patient?.name ?? "…"} />
      {error && <div className="px-4 pt-6 sm:px-8 lg:px-14"><ErrorBanner error={error} onRetry={() => refetch()} /></div>}
      {isLoading || !patient ? (
        <div className="flex flex-col gap-4 px-4 pt-7 sm:px-8 lg:px-14">
          <div className="flex items-center gap-5"><Skeleton className="h-[76px] w-[76px] rounded-full" /><Skeleton className="h-12 w-80" /></div>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-[480px] w-full rounded-[18px]" />
        </div>
      ) : (
        <>
          <section className="no-print flex flex-wrap items-center gap-x-[22px] gap-y-4 px-4 pt-7 sm:px-8 lg:px-14">
            <Avatar id={patient.id} name={patient.name} hasPhoto={patient.has_photo} size={76} />
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline gap-3.5">
                <h1 className="m-0 font-serif text-[42px] font-medium leading-none tracking-[-0.02em]">{patient.name}</h1>
                <span className="font-mono text-sm text-ink-3">{patient.patient_code}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2.5 text-sm text-ink-3">
                <span>{sexLabel(patient.sex)} · {age(patient.birth_year)} (born {patient.birth_year})</span>
                {patient.conditions.map((c) => <ConditionChip key={c}>{capitalise(c)}</ConditionChip>)}
              </div>
            </div>
            <div className="ml-auto flex flex-wrap items-center justify-end gap-x-8 gap-y-4">
            <dl className="m-0 flex gap-8">
              <Stat label="Reports" value={String(patient.report_count)} />
              <Stat label="Labs" value={String(patient.lab_count)} />
              <Stat label="Period" value={first && last ? `${fmtMonth(first)} – ${fmtMonth(last)}` : "—"} />
            </dl>
            <div className="flex gap-2.5">
              <QuietLink to={`${base}/summary`}>{Icon.doc}Summary</QuietLink>
              <PrimaryLink to={`${base}/documents`}>{Icon.upload}Add documents</PrimaryLink>
            </div>
            </div>
          </section>
          <nav aria-label="Patient sections" className="no-print mx-4 mt-[22px] flex gap-7 overflow-x-auto border-b border-line sm:mx-8 lg:mx-14">
            {([["", "Trends", true], ["medications", "Medications", false], ["documents", "Documents", false], ["summary", "Summary", false]] as const)
              .map(([to, label, end]) => (
                <NavLink key={label} to={to ? `${base}/${to}` : base} end={end}
                  className={({ isActive }) => `plain -mb-px whitespace-nowrap border-b-2 px-0.5 py-3 text-[15px] ${isActive || (label === "Trends" && isTrendsChild()) ? "border-blue font-semibold text-ink" : "border-transparent font-medium text-ink-3"}`}>
                  {label}
                </NavLink>
              ))}
          </nav>
          <Outlet context={{ patient, trends: trends.data, reports, base } satisfies PatientCtx} />
        </>
      )}
    </div>
  );
}

function isTrendsChild() {
  return /\/(systems|parameters)\//.test(window.location.pathname);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-[0.06em] text-ink-3">{label}</dt>
      <dd className="num m-0 font-serif text-[26px]">{value}</dd>
    </div>
  );
}
