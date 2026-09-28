import { useQueries } from "@tanstack/react-query";
import { api, authedBlobUrl } from "../api/client";
import type { Flag, Medication, PatientDocument, Trend } from "../api/types";
import type { ChartProps } from "../components/TrendChart";
import { fmtNum, fmtPct } from "./format";
import type { ReportRef } from "./patient";

interface ResponseAnalyte { analyte_id: string; window: { start: string; end: string } | null }

/** Expected-effect windows per analyte, from each medication's response. */
export function useWindows(meds: Medication[] | undefined) {
  const qs = useQueries({
    queries: (meds ?? []).filter((m) => m.change === "start").map((m) => ({
      queryKey: ["response", m.id], queryFn: () => api.medicationResponse(m.id),
    })),
  });
  const out = new Map<string, { from: string; to: string; label: string }[]>();
  qs.forEach((q) => {
    const r = q.data as { event?: { drug: string }; analytes?: ResponseAnalyte[] } | undefined;
    for (const a of r?.analytes ?? []) {
      if (!a.window) continue;
      const list = out.get(a.analyte_id) ?? [];
      list.push({ from: a.window.start, to: a.window.end, label: `${r?.event?.drug ?? "Drug"} expected-effect window` });
      out.set(a.analyte_id, list);
    }
  });
  return out;
}

export function chartProps(t: Trend, reports: Map<number, ReportRef>, meds: Medication[], windows: Map<string, { from: string; to: string; label: string }[]>,
  flags: Flag[]): Omit<ChartProps, "axis" | "onOpenReport" | "height"> {
  // Solid = not held back for a drug window (the points the slope may use); hollow = before or inside a window.
  const heldBack = new Set((t.slope?.excluded_points ?? []).flatMap((e) => e.observation_ids));
  const guideline = flags.find((f) => f.analyte_id === t.analyte_id && f.level === "guideline");
  const fall = t.points.length && t.baseline !== null ? t.points[t.points.length - 1].value < t.baseline : true;
  const touched = new Set(t.points.flatMap((p) => p.in_window));
  const baseRuns = t.baseline_dates.length > 1 ? "median of the first reports" : "first report";
  return {
    name: t.name,
    unit: t.canonical_unit,
    points: t.points.map((p) => ({
      date: p.date, value: p.value, censored: p.censored, comparator: p.comparator,
      reportLabel: reports.get(p.report_id)?.label ?? "R?", reportId: p.report_id, lab: p.lab, page: p.page,
      inTrend: !heldBack.has(p.observation_id) && p.in_window.length === 0,
    })),
    baseline: t.baseline,
    baselineLabel: t.baseline !== null ? `Baseline ${fmtNum(t.baseline)} · ${baseRuns}` : undefined,
    threshold: t.baseline !== null && t.rcv_percent
      ? { value: t.baseline * (fall ? 1 - t.rcv_percent / 100 : 1 + t.rcv_percent / 100), label: `${fall ? "−" : "+"}${fmtPct(t.rcv_percent)}% from baseline · ${fmtNum(t.baseline * (fall ? 1 - t.rcv_percent / 100 : 1 + t.rcv_percent / 100))}` }
      : null,
    target: t.target,
    windows: windows.get(t.analyte_id) ?? [],
    drugStarts: meds.filter((m) => m.change === "start" && touched.has(m.id)).map((m) => ({ date: m.date, label: m.drug })),
    slope: t.slope && guideline ? { from: t.slope.first_date, to: t.slope.last_date, perYear: t.slope.per_year } : null,
  };
}

export async function openReportPdf(reportId: number, docs: PatientDocument[] | undefined) {
  const d = docs?.find((x) => x.report_id === reportId);
  if (!d) return false;
  window.open(await authedBlobUrl(api.documentUrl(d.id)), "_blank", "noopener");
  return true;
}
