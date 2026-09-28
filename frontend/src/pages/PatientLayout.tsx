import { NavLink, Navigate, Outlet, useLocation, useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import AskPanel from "../components/AskPanel";
import { api } from "../api/client";
import type { PatientCard, TrendsResponse } from "../api/types";
import { AppHeader, useTitle } from "../components/shell";
import { Avatar, ConditionChip, ErrorBanner, Icon, PrimaryLink, QuietLink, Skeleton } from "../components/ui";
import { age, capitalise, fmtMonth, sexLabel } from "../lib/format";
import { reportIndex, useDocuments, useFlags, useMedications, usePatient, useSystems, useTrends, type ReportRef } from "../lib/patient";

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
  const [asking, setAsking] = useState(false);
  const flags = useFlags(patient?.id);
  const clinical = useQuery({ queryKey: ["clinical", patient?.id ?? 0], queryFn: () => api.clinical(patient!.id), enabled: !!patient });
  // Load every tab's data up front, so switching tabs never shows a loading state.
  useSystems(patient?.id);
  useMedications(patient?.id);
  useDocuments(patient?.id);
  const location = useLocation();
  const section = sectionOf(location.pathname);
  useTitle(section, patient?.name);
  if (notFound) return <Navigate to="/patients" replace />;
  const reports = reportIndex(trends.data);
  const base = `/patients/${code}`;
  const first = reports.list[0]?.date;
  const last = reports.list[reports.list.length - 1]?.date;

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader crumb={patient?.name ?? "…"} actions={patient && (
        <button type="button" onClick={() => setAsking((a) => !a)} data-testid="ask-open" aria-expanded={asking}
          className="flex h-9 items-center gap-2 rounded-full bg-ink px-3 text-sm font-semibold text-card hover:bg-ink-2 sm:px-4">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /></svg>
          <span className="hidden sm:inline">Ask about this patient</span><span className="sm:hidden">Ask</span>
        </button>
      )} />
      {error && <div className="px-4 pt-6 sm:px-8 lg:px-14"><ErrorBanner error={error} onRetry={() => refetch()} /></div>}
      {isLoading || !patient ? (
        <div className="flex flex-col gap-4 px-4 pt-7 sm:px-8 lg:px-14">
          <div className="flex items-center gap-5"><Skeleton className="h-[76px] w-[76px] rounded-full" /><Skeleton className="h-12 w-80" /></div>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-[480px] w-full rounded-[18px]" />
        </div>
      ) : (
        <>
          <section className="no-print flex flex-wrap items-center gap-x-6 gap-y-4 px-4 pt-8 sm:px-8 lg:px-14">
            <Avatar id={patient.id} name={patient.name} hasPhoto={patient.has_photo} size={76} />
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline gap-3.5">
                <h1 className="m-0 font-serif text-[40px] font-medium leading-none tracking-[-0.02em]">{patient.name}</h1>
                <span className="font-mono text-sm text-ink-3">{patient.patient_code}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2.5 text-sm text-ink-3">
                <span>{sexLabel(patient.sex)} · {age(patient.birth_year)} (born {patient.birth_year})</span>
                {patient.conditions.map((c) => {
                  const code = clinical.data?.codes.conditions.find((k) => k.text === c);
                  return (
                    <ConditionChip key={c}>
                      <span title={code?.icd10 ? `ICD-10 ${code.icd10} ${code.icd10_title ?? ""} · SNOMED CT ${code.snomed ?? ""}` : undefined}>
                        {capitalise(c)}{code?.icd10 && <span className="ml-1.5 font-mono text-xs text-ink-3">{code.icd10}</span>}
                      </span>
                    </ConditionChip>
                  );
                })}
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
          <div className="no-print sticky top-14 z-30 mt-6 bg-paper/90 px-4 backdrop-blur-md sm:px-8 lg:px-14">
            <nav aria-label="Patient sections" className="flex gap-7 overflow-x-auto border-b border-line">
              {([["", "Trends", true], ["clinical", "Clinical", false], ["medications", "Medications", false], ["documents", "Documents", false], ["summary", "Summary", false]] as const)
                .map(([to, label, end]) => (
                  <NavLink key={label} to={to ? `${base}/${to}` : base} end={end}
                    className={({ isActive }) => {
                      const on = isActive || (label === "Trends" && /\/(systems|parameters)\//.test(location.pathname));
                      return `plain tab-link whitespace-nowrap px-0.5 py-3 text-[15px] ${on ? "font-semibold text-ink" : "font-medium text-ink-3 hover:text-ink-2"}`;
                    }}
                    data-active={section === label}>
                    {label}
                  </NavLink>
                ))}
            </nav>
          </div>
          <div key={location.pathname} className="page-in">
            <Outlet context={{ patient, trends: trends.data, reports, base } satisfies PatientCtx} />
          </div>
          {asking && <AskPanel patientId={patient.id} name={patient.name} flags={flags.data?.flags ?? []} onClose={() => setAsking(false)} />}
        </>
      )}
    </div>
  );
}

/** The tab a path belongs to (system and parameter pages sit under Trends). */
function sectionOf(path: string) {
  const m = path.match(/\/patients\/[^/]+\/(clinical|medications|documents|summary)/);
  return m ? m[1][0].toUpperCase() + m[1].slice(1) : "Trends";
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-[0.06em] text-ink-3">{label}</dt>
      <dd className="num m-0 font-serif text-[26px]">{value}</dd>
    </div>
  );
}
