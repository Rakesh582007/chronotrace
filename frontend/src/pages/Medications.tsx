import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Medication } from "../api/types";
import { lanes } from "../components/timeline";
import { useToast } from "../components/shell";
import { ErrorBanner, Icon, Skeleton, Spinner } from "../components/ui";
import { makeAxis } from "../lib/axis";
import { capitalise, fmtDate, fmtNum, fmtPct, fmtUnit, shortName } from "../lib/format";
import { labelRuns, useMedications } from "../lib/patient";
import { useElementWidth } from "../lib/useWidth";
import { usePatientCtx } from "./PatientLayout";

interface Side { value: number; label?: string; date?: string; report_ids: number[] }
interface RespAnalyte {
  analyte_id: string; name: string; unit: string;
  expected: { note: string; source: string; status: string; applies: boolean } | null;
  window: { start: string; end: string } | null;
  before: Side | null; after: Side | null; change_percent: number | null; rcv_percent: number | null;
  beyond_rcv: boolean | null; cross_lab: boolean; expected_effect: { note: string } | null; status: string;
  confounders: { drug: string; date: string }[];
}
interface Resp { event: { drug: string; dose_text: string | null; date: string; drug_class_name: string | null }; note: string | null; caveat: string; analytes: RespAnalyte[] }

const CHANGE: Record<string, string> = { start: "Start", stop: "Stop", dose_change: "Dose change" };

export default function Medications() {
  const { patient, reports } = usePatientCtx();
  const meds = useMedications(patient.id);
  const [selected, setSelected] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [ref, W] = useElementWidth<HTMLDivElement>(700);
  const list = meds.data ?? [];
  const ls = lanes(list);
  const axis = makeAxis([...reports.list.map((r) => r.date), ...list.map((m) => m.date)]);
  const current = selected ?? ls[ls.length - 1]?.id ?? null;

  return (
    <main className="grid grid-cols-1 items-start gap-8 px-4 pb-10 pt-7 sm:px-8 lg:px-14 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(340px,440px)]">
      <div className="flex min-w-0 flex-col gap-5">
        <div className="flex flex-wrap items-baseline gap-4">
          <h2 className="m-0 font-serif text-[26px] font-medium">Medications and lab response</h2>
          <div className="grow" />
          <button type="button" onClick={() => setAdding(true)} className="flex h-11 items-center gap-2 rounded-[10px] bg-blue px-[18px] text-[15px] font-semibold text-white hover:bg-blue-hover">
            {Icon.plus}Add medication change
          </button>
        </div>
        {meds.error && <ErrorBanner error={meds.error} onRetry={() => meds.refetch()} />}
        {meds.isLoading && <Skeleton className="h-60 rounded-[18px]" />}
        {meds.data && (
          <section aria-label="Medication lanes" className="flex flex-col gap-3 rounded-[18px] border border-line bg-card px-[22px] py-5">
            <div className="flex items-center gap-[18px]">
              <span className="w-[150px] shrink-0 text-[13px] text-ink-3">Reports</span>
              <div ref={ref} className="relative h-[34px] min-w-0 grow">
                <div className="absolute inset-x-0 top-2.5 h-px bg-line" />
                {reports.list.map((r) => (
                  <div key={r.id} className="absolute top-[5px] flex -translate-x-1/2 flex-col items-center gap-1" style={{ left: axis.x(r.date, W) }}>
                    <span className="box-border h-2.5 w-2.5 rounded-full border-2 border-ink bg-card" />
                    <span className="font-mono text-[10px] text-ink-3">{r.label}</span>
                  </div>
                ))}
              </div>
            </div>
            {ls.length === 0 && <p className="m-0 text-sm text-ink-3">No medication changes recorded yet.</p>}
            {ls.map((l) => (
              <button key={l.id} type="button" onClick={() => setSelected(l.id)} aria-pressed={current === l.id}
                className={`flex items-center gap-[18px] rounded-[10px] px-2 py-1.5 text-left -mx-2 ${current === l.id ? "bg-blue-tint-2" : "hover:bg-[#FBF8F2]"}`}>
                <span className="flex w-[150px] shrink-0 flex-col">
                  <span className="truncate text-sm font-semibold">{l.drug}</span>
                  <span className="text-xs text-ink-3">{l.dose ?? ""} · {fmtDate(l.start)}</span>
                </span>
                <span className="relative h-[22px] min-w-0 grow">
                  <span className="absolute top-[5px] box-border block h-3 rounded-l-md border border-blue-line bg-blue-tint"
                    style={{ left: axis.x(l.start, W), width: (l.end ? axis.x(l.end, W) : W) - axis.x(l.start, W) }} />
                  <span className="absolute top-0 block h-[22px] w-0.5 bg-blue" style={{ left: axis.x(l.start, W) }} />
                </span>
              </button>
            ))}
            <div className="flex items-center gap-[18px]">
              <span className="w-[150px] shrink-0" />
              <div className="relative h-4 min-w-0 grow">
                {axis.years.map((y) => <span key={y} className="num absolute -translate-x-1/2 text-xs text-ink-3" style={{ left: axis.x(y, W) }}>{y.slice(0, 4)}</span>)}
              </div>
            </div>
          </section>
        )}
        {meds.data && list.length > 0 && <EventsTable meds={list} />}
      </div>
      <aside className="flex flex-col gap-4">
        {current !== null ? <ResponsePanel id={current} reports={reports.byId} /> : <p className="m-0 text-sm text-ink-3">Select a medication to see the lab response.</p>}
      </aside>
      {adding && <AddMedDialog patientId={patient.id} onClose={() => setAdding(false)} />}
    </main>
  );
}

function ResponsePanel({ id, reports }: { id: number; reports: Parameters<typeof labelRuns>[1] }) {
  const q = useQuery({ queryKey: ["response", id], queryFn: () => api.medicationResponse(id) as unknown as Promise<Resp> });
  if (q.isLoading) return <Skeleton className="h-80 rounded-[18px]" />;
  if (q.error) return <ErrorBanner error={q.error} onRetry={() => q.refetch()} />;
  const r = q.data!;
  const assessed = r.analytes.filter((a) => a.before && a.after);
  const withExpected = assessed.filter((a) => a.expected?.applies);
  const others = assessed.filter((a) => !a.expected?.applies);
  return (
    <section className="flex flex-col gap-4 overflow-hidden rounded-[18px] border border-line bg-card" aria-label={`${r.event.drug} response`}>
      <div className="flex flex-col gap-1 border-b border-blue-line bg-blue-tint-2 px-[22px] py-4">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-blue-ink">Lab response</span>
        <h3 className="m-0 font-serif text-2xl font-medium">{r.event.drug} {r.event.dose_text ?? ""}</h3>
        <span className="text-[13px] text-ink-2">Started {fmtDate(r.event.date)}{r.event.drug_class_name ? ` · ${r.event.drug_class_name}` : ""}</span>
      </div>
      <div className="flex flex-col gap-3 px-[22px] pb-5">
        {r.note && <p className="m-0 text-sm text-ink-2">{capitalise(r.note)}</p>}
        {assessed.length === 0 && <p className="m-0 text-sm text-ink-3">Not enough results before and after this start to compare.</p>}
        {[...withExpected, ...others].map((a) => {
          const pct = a.change_percent ?? 0;
          return (
            <div key={a.analyte_id} className="flex flex-col gap-1.5 border-t border-paper-2 pt-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-[15px] font-semibold">{shortName(a.name)}</span>
                <span className="num text-sm">{fmtNum(a.before!.value)} → {fmtNum(a.after!.value)} {fmtUnit(a.unit)}</span>
                <div className="grow" />
                <span className="num text-sm font-semibold">{pct < 0 ? "−" : "+"}{Math.abs(pct).toFixed(1)}%</span>
                {a.rcv_percent !== null && (
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${a.beyond_rcv ? "bg-blue-tint text-blue-ink" : "bg-stable text-ink-2"}`}>
                    {a.beyond_rcv ? "beyond" : "within"} {fmtPct(a.rcv_percent)}%
                  </span>
                )}
              </div>
              <span className="text-xs text-ink-3">
                {a.before!.label ?? "before"} ({labelRuns(a.before!.report_ids, reports).join(", ")}) → {labelRuns(a.after!.report_ids, reports).join(", ")}
              </span>
              {a.expected?.applies && (
                <p className="m-0 text-[13px] leading-normal text-ink-2">
                  Expected: {a.expected.note}{a.expected_effect && a.expected_effect.note !== a.expected.note ? ` · ${a.expected_effect.note}` : ""}.{" "}
                  <span className="text-ink-3" title={a.expected.source}>Source: {a.expected.source.split(/[(:]/)[0].trim()}{a.expected.status !== "verified" ? " (not yet verified)" : ""}</span>
                </p>
              )}
              {a.confounders.length > 0 && <p className="m-0 text-xs text-ink-3">Other changes in the window: {a.confounders.map((c) => `${c.drug} (${fmtDate(c.date)})`).join(", ")}</p>}
              {a.cross_lab && <p className="m-0 text-xs text-ink-3">Values from different labs.</p>}
            </div>
          );
        })}
        <p className="m-0 border-t border-paper-2 pt-3 text-xs leading-normal text-ink-3">{r.caveat}</p>
      </div>
    </section>
  );
}

function EventsTable({ meds }: { meds: Medication[] }) {
  return (
    <section className="overflow-hidden rounded-[18px] border border-line bg-card">
      <div className="border-b border-paper-2 px-6 py-4"><h3 className="m-0 font-serif text-[22px] font-medium">Events</h3></div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-[0.05em] text-ink-3">
            <th scope="col" className="px-6 py-2.5 font-semibold">Date</th><th scope="col" className="px-2 py-2.5 font-semibold">Drug</th>
            <th scope="col" className="px-2 py-2.5 font-semibold">Change</th><th scope="col" className="px-2 py-2.5 font-semibold">Dose</th>
            <th scope="col" className="px-6 py-2.5 font-semibold">Class</th></tr></thead>
          <tbody>
            {[...meds].sort((a, b) => b.date.localeCompare(a.date)).map((m) => (
              <tr key={m.id} className="border-t border-[#F0E9DB]">
                <td className="num px-6 py-2">{fmtDate(m.date)}</td><td className="px-2 py-2 font-semibold">{m.drug}</td>
                <td className="px-2 py-2">{CHANGE[m.change]}</td><td className="px-2 py-2">{m.dose_text ?? "—"}</td>
                <td className="px-6 py-2 text-ink-3">{m.drug_class_name ?? (m.drug_class === "unknown" ? "Not in the drug list" : "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AddMedDialog({ patientId, onClose }: { patientId: number; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const [drug, setDrug] = useState("");
  const [change, setChange] = useState("start");
  const [dose, setDose] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  const m = useMutation({
    mutationFn: () => api.addMedication(patientId, { drug: drug.trim(), change, dose_text: dose.trim() || undefined, date }),
    onSuccess: (r) => {
      ["medications", "flags", "trends", "systems", "patients"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast(`${r.drug} recorded`); onClose();
    },
    onError: (e) => setErr((e as Error).message),
  });
  const f = "field h-11 rounded-[10px] border border-field-line bg-white px-3 text-[15px]";
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="med-h" className="m-auto w-[min(480px,calc(100vw-32px))] rounded-[20px] border border-line bg-card p-0 text-ink shadow-panel backdrop:bg-ink/40">
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); if (drug && date) m.mutate(); }} className="flex flex-col gap-4 p-8">
        <div className="flex items-center"><h2 id="med-h" className="m-0 font-serif text-[26px] font-medium">Add medication change</h2><div className="grow" />
          <button type="button" aria-label="Close" onClick={onClose} className="p-1 text-ink-3">{Icon.close}</button></div>
        <label className="flex flex-col gap-1.5 text-sm font-medium">Drug<input className={f} value={drug} onChange={(e) => setDrug(e.target.value)} autoFocus placeholder="e.g. Atorvastatin" /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1.5 text-sm font-medium">Change
            <select className={f} value={change} onChange={(e) => setChange(e.target.value)}>
              <option value="start">Start</option><option value="stop">Stop</option><option value="dose_change">Dose change</option>
            </select></label>
          <label className="flex flex-col gap-1.5 text-sm font-medium">Dose<input className={f} value={dose} onChange={(e) => setDose(e.target.value)} placeholder="e.g. 10 mg OD" /></label>
        </div>
        <label className="flex flex-col gap-1.5 text-sm font-medium">Date<input className={f} type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        {err && <p role="alert" className="m-0 text-sm font-medium text-amber-ink">{err}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="h-11 rounded-[10px] border border-field-line bg-card px-4 text-[15px] font-medium">Cancel</button>
          <button type="submit" disabled={m.isPending || !drug} className="flex h-11 items-center gap-2 rounded-[10px] bg-blue px-[18px] text-[15px] font-semibold text-white hover:bg-blue-hover disabled:opacity-70">
            {m.isPending && <Spinner />}Add
          </button>
        </div>
      </form>
    </dialog>
  );
}
