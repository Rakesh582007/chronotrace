import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { Cited, Summary, SummaryPeriod } from "../api/types";
import { useToast } from "../components/shell";
import { BlueDot, ErrorBanner, Logo, Skeleton, Spinner } from "../components/ui";
import { age, capitalise, fmtDate, fmtMonth, plural, sexLabel } from "../lib/format";
import { useFlags } from "../lib/patient";
import { usePatientCtx } from "./PatientLayout";

const PERIOD_NAME: Record<SummaryPeriod, string> = { since_last_visit: "Since last visit", range: "Chosen dates", all: "Whole history" };

function stamp(iso: string) {
  const d = new Date(iso);
  return `${fmtDate(iso.slice(0, 10))}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function SummaryPage() {
  const { patient, reports } = usePatientCtx();
  const flags = useFlags(patient.id);
  const qc = useQueryClient();
  const toast = useToast();
  const [period, setPeriod] = useState<SummaryPeriod>("all");
  const list = reports.list;
  const [from, setFrom] = useState(list[0]?.date ?? "");
  const [to, setTo] = useState(list[list.length - 1]?.date ?? "");

  const saved = useQuery({
    queryKey: ["summary", patient.id, period],
    queryFn: async () => {
      try { return await api.latestSummary(patient.id, period); } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });

  const write = useMutation({
    mutationFn: () => api.writeSummary(patient.id, period, from, to),
    onSuccess: (s) => qc.setQueryData(["summary", patient.id, period], s),
    onError: (e) => {
      const last = e instanceof ApiError && e.body && typeof e.body === "object" ? (e.body as { last_saved?: Summary | null }).last_saved : null;
      if (e instanceof ApiError && e.status === 502) {
        if (last) qc.setQueryData(["summary", patient.id, period], last);
        toast(last ? `Couldn't reach the summary service. Showing the summary saved on ${fmtDate(last.created_at.slice(0, 10))}.`
          : "Couldn't reach the summary service. No saved summary for this period yet.", "amber");
      } else toast(e instanceof Error ? e.message : "The summary could not be written.", "amber");
    },
  });

  const n = flags.data?.flags.length ?? 0;
  const last2 = list.slice(-2);
  const options: { key: SummaryPeriod; label: string; sub: string }[] = [
    { key: "since_last_visit", label: "Since last visit", sub: last2.length === 2 ? `${fmtDate(last2[0].date)} – ${fmtDate(last2[1].date)} · 2 reports` : "Needs two reports" },
    { key: "range", label: "Choose dates", sub: "Any range with at least one report" },
    { key: "all", label: "Whole history", sub: list.length ? `${fmtDate(list[0].date)} – ${fmtDate(list[list.length - 1].date)} · ${plural(list.length, "report")}` : "No reports yet" },
  ];
  const s = saved.data;

  return (
    <main className="grid grid-cols-1 items-start gap-8 px-4 pb-10 pt-6 sm:px-8 lg:px-14 min-[1100px]:grid-cols-[minmax(320px,380px)_minmax(0,1fr)]">
      <aside className="no-print flex flex-col gap-4">
        <fieldset className="m-0 flex flex-col gap-2.5 rounded-2xl border border-line bg-card px-5 pb-[18px] pt-2">
          <legend className="px-1.5 font-serif text-xl font-medium">Period</legend>
          {options.map((o) => (
            <label key={o.key} className={`flex cursor-pointer items-start gap-2.5 rounded-[10px] px-3 py-2.5 ${period === o.key ? "border-[1.5px] border-blue bg-blue-tint-2" : "border border-line"}`}>
              <input type="radio" name="period" checked={period === o.key} onChange={() => setPeriod(o.key)} className="mt-[3px] accent-blue" />
              <span className="flex flex-col gap-0.5">
                <span className={`text-[15px] ${period === o.key ? "font-semibold" : "font-medium"}`}>{o.label}</span>
                <span className="num text-[13px] text-ink-3">{o.sub}</span>
              </span>
            </label>
          ))}
          {period === "range" && (
            <div className="flex gap-2">
              <label className="flex grow flex-col gap-1 text-xs text-ink-2">From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="field h-10 rounded-lg border border-field-line bg-white px-2 text-sm" /></label>
              <label className="flex grow flex-col gap-1 text-xs text-ink-2">To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="field h-10 rounded-lg border border-field-line bg-white px-2 text-sm" /></label>
            </div>
          )}
        </fieldset>

        <div className="flex flex-col gap-2.5 rounded-2xl border border-line bg-card px-5 py-4">
          <div className="flex items-center gap-2"><BlueDot /><span className="text-sm font-semibold">{s ? "Saved summary" : "No saved summary"}</span></div>
          <p className="m-0 text-[13px] leading-[1.55] text-ink-2">
            {s ? <>Written by an LLM (<span className="font-mono text-xs">{s.model}</span>) on <span className="num">{stamp(s.created_at)}</span> from the computed flags, trends and medication responses. It never sees the raw reports, and every number it writes is checked against the computed facts before it is saved.</>
              : "No saved summary for this period yet."}
          </p>
          <p className="m-0 text-[13px] leading-[1.55] text-ink-3">If regenerating fails, the saved version stays on screen with its date.</p>
        </div>

        <div className="flex gap-2.5">
          <button type="button" onClick={() => write.mutate()} disabled={write.isPending || !list.length}
            className="flex h-[46px] grow items-center justify-center gap-2 rounded-[10px] border border-field-line bg-card text-[15px] font-medium hover:border-blue-line-2 disabled:opacity-70">
            {write.isPending ? <Spinner /> : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" /></svg>}
            {s ? "Regenerate" : "Generate"}
          </button>
          <button type="button" onClick={() => window.print()} disabled={!s}
            className="flex h-[46px] grow items-center justify-center gap-2 rounded-[10px] bg-blue text-[15px] font-semibold text-white hover:bg-blue-hover disabled:bg-muted-mark">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 4v12M7 11l5 5 5-5M5 20h14" /></svg>
            Download PDF
          </button>
        </div>
        {write.isPending && <p role="status" className="m-0 text-sm text-ink-3">Writing the summary from {plural(n, "flag")}… this can take up to a minute.</p>}
      </aside>

      <div className="min-w-0">
        {saved.error && <ErrorBanner error={saved.error} onRetry={() => saved.refetch()} />}
        {saved.isLoading && <Skeleton className="h-[700px] rounded-[4px]" />}
        {saved.data === null && !write.isPending && (
          <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 rounded-[4px] border border-dashed border-dash text-center">
            <p className="m-0 font-serif text-[22px]">No saved summary for this period yet.</p>
            <p className="m-0 max-w-md text-sm text-ink-3">Generate one: an LLM writes it from ChronoTrace's computed flags and values only, and every sentence cites its reports.</p>
          </div>
        )}
        {saved.data === null && write.isPending && <Skeleton className="h-[700px] rounded-[4px]" />}
        {s && renderArticle(s)}
      </div>
    </main>
  );

  function renderArticle(s: Summary) {
    const labels = new Map(s.content.reports.map((r) => [r.report_id, Number(r.label.slice(1))]));
    const chips = (c: Cited) => runs(c.report_ids.map((id) => labels.get(id)).filter((x): x is number => !!x))
      .map((r) => <span key={r} className="ml-1 whitespace-nowrap rounded-md border border-blue-line bg-blue-tint-2 px-1.5 py-px align-[1px] font-mono text-[11.5px] text-blue-ink">{r}</span>);
    const labsN = new Set(s.content.reports.map((r) => r.lab)).size;
    return (
      <article aria-label="Summary document" className="print-article flex flex-col gap-5 rounded-[4px] border border-line bg-white px-6 pb-10 pt-12 shadow-[0_30px_60px_-40px_rgba(29,39,51,0.55)] sm:px-[60px]">
        <div className="flex items-center gap-2.5 border-b-[1.5px] border-ink pb-4">
          <Logo size={22} />
          <span className="font-serif text-[17px] font-semibold">ChronoTrace</span>
          <div className="grow" />
          <span className="text-xs text-ink-3">For clinician review · not a diagnosis</span>
        </div>
        <div className="flex flex-col gap-2">
          <h2 className="m-0 font-serif text-[34px] font-medium leading-[1.1] tracking-[-0.015em]">Lab trend summary · {patient.name}</h2>
          <div className="flex flex-wrap gap-x-[18px] gap-y-1.5 text-[13px] text-ink-2">
            <span>{patient.patient_code} · {sexLabel(patient.sex)} · {age(patient.birth_year)}</span>
            <span>{patient.conditions.map(capitalise).join(", ")}</span>
            <span className="num">{PERIOD_NAME[s.period]} · {fmtDate(s.from)} – {fmtDate(s.to)}</span>
            <span>{plural(s.content.reports.length, "report")} · {plural(labsN, "lab")}</span>
          </div>
        </div>
        <section className="flex flex-col gap-1.5 rounded-lg bg-amber-fill px-5 py-4">
          <span className="text-xs font-semibold uppercase tracking-[0.1em] text-amber-ink">Key finding</span>
          <p className="m-0 font-serif text-lg leading-normal text-[#2A1B08]">{s.content.key_finding.text}{chips(s.content.key_finding)}</p>
        </section>
        {s.content.sections.map((sec) => (
          <section key={sec.title} className="flex flex-col gap-2">
            <h3 className="m-0 text-[13px] font-semibold uppercase tracking-[0.08em] text-blue-ink">{sec.title}</h3>
            <p className="m-0 text-[15px] leading-[1.65]">{sec.sentences.map((c, i) => <span key={i}>{i ? " " : ""}{c.text}{chips(c)}</span>)}</p>
          </section>
        ))}
        {s.content.medication_rows.length > 0 && (
          <section className="flex flex-col gap-2">
            <h3 className="m-0 text-[13px] font-semibold uppercase tracking-[0.08em] text-blue-ink">Medication changes</h3>
            <table className="w-full border-collapse text-sm">
              <tbody>
                {s.content.medication_rows.map((r, i) => (
                  <tr key={i} className="border-y border-paper-2">
                    <td className="num w-[110px] py-2 align-top text-ink-2">{fmtMonth(r.date)}</td>
                    <td className="w-[210px] py-2 align-top font-semibold">{r.drug} {r.dose}</td>
                    <td className="py-2 text-ink-2">{r.observed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
        {s.content.data_notes.length > 0 && (
          <section className="flex flex-col gap-1.5">
            <h3 className="m-0 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-3">Data notes</h3>
            <p className="m-0 text-[13px] leading-[1.6] text-ink-2">{s.content.data_notes.join(" ")}</p>
          </section>
        )}
        <div className="mt-1 flex flex-wrap justify-between gap-2 border-t border-paper-2 pt-3 text-xs text-ink-3">
          <span>Written by an LLM from ChronoTrace's computed flags and values only. Every statement cites its reports.</span>
          <span className="num">Generated {stamp(s.created_at)} · {s.model}</span>
        </div>
      </article>
    );
  }
}

function runs(nums: number[]): string[] {
  const n = [...new Set(nums)].sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < n.length;) {
    let j = i;
    while (j + 1 < n.length && n[j + 1] === n[j] + 1) j++;
    out.push(j > i ? `R${n[i]}–R${n[j]}` : `R${n[i]}`);
    i = j + 1;
  }
  return out;
}
