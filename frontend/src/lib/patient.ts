import { useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Flag, TrendsResponse } from "../api/types";

export function usePatients(sort: "needs_review" | "name" | "latest_report" = "needs_review") {
  return useQuery({ queryKey: ["patients", sort], queryFn: () => api.patients(sort) });
}

/** The patient card for a route's :code (the UI shows codes; the API takes ids). */
export function usePatient(code: string | undefined) {
  const q = usePatients();
  const patient = q.data?.find((p) => p.patient_code === code);
  return { ...q, patient, notFound: q.isSuccess && !patient };
}

export const keys = {
  trends: (id: number) => ["trends", id] as const,
  flags: (id: number) => ["flags", id] as const,
  systems: (id: number) => ["systems", id] as const,
  medications: (id: number) => ["medications", id] as const,
  documents: (id: number) => ["documents", id] as const,
};

export function useTrends(id: number | undefined) {
  return useQuery({ queryKey: keys.trends(id ?? 0), queryFn: () => api.trends(id!), enabled: !!id });
}
export function useFlags(id: number | undefined) {
  return useQuery({ queryKey: keys.flags(id ?? 0), queryFn: () => api.flags(id!), enabled: !!id });
}
export function useSystems(id: number | undefined) {
  return useQuery({ queryKey: keys.systems(id ?? 0), queryFn: () => api.systems(id!), enabled: !!id });
}
export function useMedications(id: number | undefined) {
  return useQuery({ queryKey: keys.medications(id ?? 0), queryFn: () => api.medications(id!), enabled: !!id });
}
export function useDocuments(id: number | undefined) {
  return useQuery({ queryKey: keys.documents(id ?? 0), queryFn: () => api.documents(id!), enabled: !!id });
}

export interface ReportRef {
  id: number;
  label: string;
  date: string;
  lab: string | null;
}

/** Confirmed reports numbered R1..Rn by date, as the summaries number them. */
export function reportIndex(trends: TrendsResponse | undefined): { list: ReportRef[]; byId: Map<number, ReportRef> } {
  const seen = new Map<number, { date: string; lab: string | null }>();
  for (const a of trends?.analytes ?? []) {
    for (const p of a.points) if (!seen.has(p.report_id)) seen.set(p.report_id, { date: p.date, lab: p.lab });
  }
  const list = [...seen.entries()]
    .sort((a, b) => a[1].date.localeCompare(b[1].date) || a[0] - b[0])
    .map(([id, v], i) => ({ id, label: `R${i + 1}`, date: v.date, lab: v.lab }));
  return { list, byId: new Map(list.map((r) => [r.id, r])) };
}

/** Compress labels into runs: [R1,R2,R3,R10] → ["R1–R3","R10"]. */
export function labelRuns(ids: number[], byId: Map<number, ReportRef>): string[] {
  const nums = [...new Set(ids.map((id) => byId.get(id)?.label).filter(Boolean).map((l) => Number(l!.slice(1))))]
    .sort((a, b) => a - b);
  const out: string[] = [];
  let i = 0;
  while (i < nums.length) {
    let j = i;
    while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++;
    out.push(j > i ? `R${nums[i]}–R${nums[j]}` : `R${nums[i]}`);
    i = j + 1;
  }
  return out;
}

export function isReview(f: Flag) {
  return !f.expected_effect;
}

/** Warm the cache for a patient's pages (on hover or focus of their card), so opening it shows data at once. */
export function prefetchPatient(qc: QueryClient, id: number) {
  const opts = { staleTime: 30_000 };
  qc.prefetchQuery({ queryKey: keys.trends(id), queryFn: () => api.trends(id), ...opts });
  qc.prefetchQuery({ queryKey: keys.flags(id), queryFn: () => api.flags(id), ...opts });
  qc.prefetchQuery({ queryKey: keys.systems(id), queryFn: () => api.systems(id), ...opts });
  qc.prefetchQuery({ queryKey: keys.medications(id), queryFn: () => api.medications(id), ...opts });
}
