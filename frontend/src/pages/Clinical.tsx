import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Clinical, Criterion, KdigoPosition, NutritionGroup, NutritionItem } from "../api/types";
import { useToast } from "../components/shell";
import { ErrorBanner, Icon, ReportChip, Skeleton, Spinner } from "../components/ui";
import { capitalise, fmtDate, fmtMonth, fmtNum } from "../lib/format";
import { labelRuns, type ReportRef } from "../lib/patient";
import { usePatientCtx } from "./PatientLayout";

const G = ["G1", "G2", "G3a", "G3b", "G4", "G5"];
const G_RANGE: Record<string, string> = { G1: "≥ 90", G2: "60–89", G3a: "45–59", G3b: "30–44", G4: "15–29", G5: "< 15" };
const A = ["A1", "A2", "A3"];
const A_RANGE: Record<string, string> = { A1: "< 30", A2: "30–300", A3: "> 300" };

export default function ClinicalPage() {
  const { patient, reports } = usePatientCtx();
  const q = useQuery({ queryKey: ["clinical", patient.id], queryFn: () => api.clinical(patient.id) });
  if (q.error) return <main className="px-4 py-8 sm:px-8 lg:px-14"><ErrorBanner error={q.error} onRetry={() => q.refetch()} /></main>;
  if (!q.data) return <main className="grid grid-cols-1 gap-8 px-4 py-8 sm:px-8 lg:grid-cols-2 lg:px-14"><Skeleton className="h-96 rounded-[18px]" /><Skeleton className="h-96 rounded-[18px]" /></main>;
  const c = q.data;
  return (
    <main className="grid grid-cols-1 items-start gap-8 px-4 pb-12 pt-7 sm:px-8 lg:px-14 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(360px,460px)]">
      <div className="flex min-w-0 flex-col gap-6">
        <KdigoGrid c={c} reports={reports.byId} />
        <CodesTable c={c} />
      </div>
      <aside className="flex flex-col gap-4">
        <div className="flex items-baseline gap-2">
          <h2 className="m-0 font-serif text-[26px] font-medium">Guideline criteria</h2>
          <div className="grow" />
          <span className="text-[13px] text-ink-3">for you to confirm</span>
        </div>
        {c.criteria.length === 0 && <p className="m-0 text-sm text-ink-3">No criteria apply to the tests in these reports.</p>}
        {c.criteria.map((cr) => <CriterionCard key={cr.id} c={cr} reports={reports.byId} />)}
      </aside>
      <Nutrition c={c} reports={reports.byId} />
    </main>
  );
}

function KdigoGrid({ c, reports }: { c: Clinical; reports: Map<number, ReportRef> }) {
  const cur = c.kdigo.current;
  const paired = c.kdigo.history.filter((h) => h.a);
  const cell = (g: string, a: string) => paired.filter((h) => h.g === g && h.a === a);
  if (!cur)
    return (
      <section className="flex flex-col gap-2 rounded-[18px] border border-dashed border-dash px-6 py-5" data-testid="kdigo-grid">
        <h2 className="m-0 font-serif text-[22px] font-medium text-ink-2">KDIGO category grid</h2>
        <p className="m-0 text-sm text-ink-3">No eGFR in these reports. The grid appears once a confirmed report has creatinine (eGFR is computed from it).</p>
      </section>
    );
  return (
    <section aria-labelledby="kdigo-h" className="flex flex-col gap-4 rounded-[18px] border border-line bg-card px-6 py-5" data-testid="kdigo-grid">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 id="kdigo-h" className="m-0 font-serif text-[26px] font-medium">KDIGO category grid</h2>
        <span className="text-[13px] text-ink-3">GFR category × albuminuria category</span>
      </div>
      {cur ? (
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <span className="num font-serif text-[40px] font-medium leading-none">{cur.g}{cur.a ? ` ${cur.a}` : ""}</span>
          <span className="text-sm text-ink-2">
            eGFR {fmtNum(cur.egfr.value)} ({reports.get(cur.egfr.report_id)?.label} · {fmtDate(cur.egfr.date)})
            {cur.uacr && <> · urine ACR {fmtNum(cur.uacr.value)} mg/g ({reports.get(cur.uacr.report_id)?.label} · {fmtDate(cur.uacr.date)})</>}
          </span>
        </div>
      ) : <p className="m-0 text-sm text-ink-3">No eGFR result yet.</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-separate border-spacing-1 text-sm">
          <thead>
            <tr>
              <th scope="col" className="w-[120px] text-left text-xs font-semibold uppercase tracking-[0.05em] text-ink-3">eGFR ↓ · ACR →</th>
              {A.map((a) => (
                <th key={a} scope="col" className="text-left text-xs font-semibold text-ink-2">{a} <span className="font-normal text-ink-3">{A_RANGE[a]} mg/g</span></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {G.map((g) => (
              <tr key={g}>
                <th scope="row" className="text-left text-xs font-semibold text-ink-2">{g} <span className="font-normal text-ink-3">{G_RANGE[g]}</span></th>
                {A.map((a) => {
                  const here = cell(g, a);
                  const isCur = cur && cur.g === g && cur.a === a;
                  return (
                    <td key={a} className={`h-12 rounded-lg px-2 align-middle ${isCur ? "bg-blue-tint-2 outline outline-2 outline-offset-[-2px] outline-blue" : here.length ? "bg-paper" : "border border-line bg-card"}`}
                      title={`${g} ${a}${here.length ? ` · ${here.map((h) => reports.get(h.egfr.report_id)?.label).join(", ")}` : ""}`}>
                      <div className="flex items-center gap-1.5">
                        {isCur && <span className="text-xs font-semibold text-blue-ink">latest</span>}
                        <div className="grow" />
                        {here.map((h) => (
                          <span key={h.date} className={`rounded font-mono text-[10px] ${isCur && h === cur ? "bg-ink px-1 text-card" : "text-ink-2"}`}>
                            {reports.get(h.egfr.report_id)?.label}
                          </span>
                        ))}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Path history={paired} reports={reports} />
      <p className="m-0 text-xs leading-normal text-ink-3">{c.kdigo.source}. Each eGFR is paired with the latest urine ACR up to a year before it.</p>
    </section>
  );
}

function Path({ history, reports }: { history: KdigoPosition[]; reports: Map<number, ReportRef> }) {
  const moves = history.filter((h, i) => i === 0 || h.g !== history[i - 1].g || h.a !== history[i - 1].a);
  if (moves.length < 2) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[13px] text-ink-2">
      <span className="font-semibold text-ink">Path:</span>
      {moves.map((h, i) => (
        <span key={h.date} className="flex items-center gap-1.5">
          {i > 0 && <span aria-hidden="true" className="text-ink-3">→</span>}
          <span className="rounded-md bg-paper px-1.5 py-0.5 font-mono text-xs">{h.g} {h.a}</span>
          <span className="text-xs text-ink-3">{reports.get(h.egfr.report_id)?.label} · {fmtMonth(h.date)}</span>
        </span>
      ))}
    </div>
  );
}

const STATUS: Record<string, [string, string]> = {
  met: ["Criteria met", "border-amber-line bg-amber-fill text-amber-ink"],
  "not met": ["Not met", "border-stable-line bg-stable text-ink-2"],
  "not enough data": ["Not enough data", "border-stable-line bg-stable text-ink-2"],
};

function CriterionCard({ c, reports }: { c: Criterion; reports: Map<number, ReportRef> }) {
  const [s, tone] = STATUS[c.status];
  return (
    <article className="flex flex-col gap-2 rounded-[14px] border border-line bg-card px-5 py-4" data-testid={`criterion-${c.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="m-0 text-base font-semibold">{c.title}</h3>
        <div className="grow" />
        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${tone}`}>{s}</span>
      </div>
      <p className="m-0 text-[13px] leading-normal text-ink-2">{c.evidence}</p>
      {c.status === "met" && (
        <p className={`m-0 text-[13px] font-medium ${c.recorded ? "text-ink-3" : "text-amber-ink"}`}>
          {c.recorded ? "✓ Already among the recorded conditions." : "▲ Not among the recorded conditions."}
        </p>
      )}
      {c.codes.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {c.codes.map((k) => (
            <span key={k.system + k.code} title={`${k.title} · ${k.why}`} className="rounded-md border border-blue-line bg-blue-tint-2 px-2 py-0.5 text-xs text-blue-ink">
              <span className="font-semibold">{k.system}</span> <span className="font-mono">{k.code}</span>
            </span>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {labelRuns(c.report_ids, reports).map((l) => <ReportChip key={l} label={l} />)}
        <span className="text-xs leading-normal text-ink-3">{c.source}</span>
      </div>
    </article>
  );
}

function CodesTable({ c }: { c: Clinical }) {
  return (
    <section aria-labelledby="codes-h" className="overflow-hidden rounded-[18px] border border-line bg-card">
      <div className="flex flex-wrap items-baseline gap-3 border-b border-paper-2 px-6 py-4">
        <h2 id="codes-h" className="m-0 font-serif text-[22px] font-medium">Codes</h2>
        <span className="text-[13px] text-ink-3">ICD-10 · SNOMED CT · LOINC</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-[0.05em] text-ink-3">
              <th scope="col" className="px-6 py-2.5 font-semibold">Recorded condition</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">ICD-10</th>
              <th scope="col" className="px-6 py-2.5 font-semibold">SNOMED CT</th>
            </tr>
          </thead>
          <tbody>
            {c.codes.conditions.map((k) => (
              <tr key={k.text} className="border-t border-[#F0E9DB]">
                <td className="px-6 py-2">{capitalise(k.text)}</td>
                <td className="px-2 py-2">{k.icd10 ? <><span className="font-mono font-semibold">{k.icd10}</span> <span className="text-xs text-ink-3">{k.icd10_title}</span></> : <span className="text-ink-3">not in the code table</span>}</td>
                <td className="px-6 py-2">{k.snomed ? <><span className="font-mono font-semibold">{k.snomed}</span> <span className="text-xs text-ink-3">{k.snomed_term}</span></> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-[0.05em] text-ink-3">
              <th scope="col" className="px-6 py-2.5 font-semibold">Test</th>
              <th scope="col" className="px-6 py-2.5 font-semibold">LOINC</th>
            </tr>
          </thead>
          <tbody>
            {c.codes.tests.map((t) => (
              <tr key={t.analyte_id} className="border-t border-[#F0E9DB]">
                <td className="px-6 py-2">{t.name}</td>
                <td className="px-6 py-2"><span className="font-mono font-semibold">{t.loinc}</span> <span className="text-xs text-ink-3">{t.loinc_name}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="m-0 border-t border-paper-2 px-6 py-3 text-xs leading-normal text-ink-3">{c.codes.note} Condition codes are from an offline table, not yet checked in the official browsers.</p>
    </section>
  );
}

const amountFmt = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const GROUP_ORDER: Record<string, string> = { kidney: "Kidney", glucose: "Diabetes", pressure: "Blood pressure", lipids: "Lipids", thyroid: "Thyroid" };

function Nutrition({ c, reports }: { c: Clinical; reports: Map<number, ReportRef> }) {
  const { patient } = usePatientCtx();
  const qc = useQueryClient();
  const toast = useToast();
  const [w, setW] = useState(c.weight_kg ? String(c.weight_kg) : "");
  const m = useMutation({
    mutationFn: () => api.updatePatient(patient.id, { weight_kg: w ? Number(w) : null }),
    onSuccess: () => { ["clinical", "patients"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); toast("Weight saved"); },
    onError: (e) => toast((e as Error).message, "amber"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  const groups = c.nutrition.groups;
  const labels = Object.fromEntries(groups.map((g) => [g.id, GROUP_ORDER[g.id] ?? g.label]));
  return (
    <section aria-labelledby="nut-h" className="flex flex-col gap-5 min-[1100px]:col-span-2" data-testid="nutrition">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3 border-t border-line pt-7">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id="nut-h" className="m-0 font-serif text-[26px] font-medium">Nutrition figures for {patient.name}</h2>
          <p className="m-0 max-w-[68ch] text-sm text-ink-3">
            Grouped by this patient's conditions and tied to their own results and medicines
            {c.weight_kg ? <> · amounts at <span className="num">{amountFmt.format(c.weight_kg)}</span> kg</> : " · add a weight for daily amounts"}.
          </p>
        </div>
        <div className="grow" />
        <form onSubmit={submit} className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-ink-2">Weight (kg)
            <input inputMode="decimal" value={w} onChange={(e) => setW(e.target.value.replace(/[^\d.]/g, ""))} className="field num h-9 w-24 rounded-lg border border-field-line bg-white px-2 text-sm" />
          </label>
          <button type="submit" disabled={m.isPending} className="flex h-9 items-center gap-1.5 rounded-lg border border-blue-line-2 bg-blue-tint-2 px-3 text-sm font-semibold text-blue-ink">
            {m.isPending ? <Spinner /> : Icon.check}Save
          </button>
        </form>
      </div>
      {groups.length === 0 ? (
        <p className="m-0 rounded-[14px] border border-dashed border-dash px-5 py-4 text-sm text-ink-3">
          No recorded condition or met criterion has a guideline nutrition figure yet.
        </p>
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
          {groups.map((g) => <NutritionCard key={g.id} g={g} reports={reports} labels={labels} />)}
        </div>
      )}
      <p className="m-0 text-xs leading-normal text-ink-3">{c.nutrition.note} Not a meal plan. Figures are marked unverified until checked against the cited guideline.</p>
    </section>
  );
}

function NutritionCard({ g, reports, labels }: { g: NutritionGroup; reports: Map<number, ReportRef>; labels: Record<string, string> }) {
  return (
    <article className="flex flex-col rounded-[18px] border border-line bg-card" data-testid={`nutrition-${g.id}`}>
      <header className="flex flex-col gap-2 border-b border-paper-2 px-5 pb-4 pt-5">
        <div className="flex flex-wrap items-baseline gap-2">
          <h3 className="m-0 font-serif text-[22px] font-medium">{g.label}</h3>
          <div className="grow" />
          <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${g.recorded ? "border-stable-line bg-stable text-ink-2" : "border-amber-line bg-amber-soft text-amber-ink"}`}>
            {g.recorded ? "Recorded condition" : "From results, not recorded"}
          </span>
        </div>
        <p className="m-0 text-[13px] leading-normal text-ink-2">{g.basis}</p>
        {g.report_ids.length > 0 && (
          <div className="flex flex-wrap gap-1.5">{labelRuns(g.report_ids, reports).map((l) => <ReportChip key={l} label={l} />)}</div>
        )}
      </header>
      <ul className="m-0 flex list-none flex-col p-0">
        {g.items.map((n) => <NutritionRow key={n.id} n={n} reports={reports} labels={labels} />)}
      </ul>
    </article>
  );
}

function Amount({ n }: { n: NutritionItem }) {
  if (n.amount === null) return null;
  const v = n.amount_high !== null ? `${amountFmt.format(n.amount)}–${amountFmt.format(n.amount_high)}` : amountFmt.format(n.amount);
  const [unit, qualifier] = n.unit.split(" (");
  return (
    <span className="flex shrink-0 flex-col items-end leading-tight">
      <span className="num font-serif text-[22px]">{v} <span className="font-sans text-xs text-ink-3">{unit}</span></span>
      {qualifier && <span className="text-xs text-ink-3">{qualifier.replace(/\)$/, "")}</span>}
    </span>
  );
}

function NutritionRow({ n, reports, labels }: { n: NutritionItem; reports: Map<number, ReportRef>; labels: Record<string, string> }) {
  const off = !!n.superseded_by;
  return (
    <li className={`flex flex-col gap-2 border-t border-paper-2 px-5 py-4 first:border-t-0 ${off ? "bg-paper/40" : ""}`} data-testid={`nutrition-item-${n.id}`}>
      <div className="flex items-start gap-4">
        <div className={`flex min-w-0 grow flex-col gap-0.5 ${off ? "opacity-60" : ""}`}>
          <span className="text-[15px] font-semibold">{n.title}</span>
          <span className="text-sm leading-snug">{capitalise(n.figure)}</span>
        </div>
        {off
          ? <span className="shrink-0 rounded-full border border-blue-line bg-blue-tint-2 px-2.5 py-0.5 text-xs font-semibold text-blue-ink">{labels[n.superseded_by!] ?? n.superseded_by} figure applies</span>
          : <Amount n={n} />}
      </div>
      <p className="m-0 text-[13px] leading-normal text-ink-2">
        <span className="font-medium text-ink">For this patient: </span>{n.applies_because}
        {n.report_ids.length > 0 && (
          <span className="ml-1.5 inline-flex gap-1 align-middle">{labelRuns(n.report_ids, reports).map((l) => <ReportChip key={l} label={l} />)}</span>
        )}
      </p>
      {n.note && (
        <p className="m-0 rounded-[10px] border border-blue-line bg-blue-tint-2 px-3 py-2 text-[13px] leading-normal text-blue-ink">{n.note}</p>
      )}
      <span className="text-xs leading-normal text-ink-3">{n.source}{n.status !== "verified" ? " · not yet verified" : ""}</span>
    </li>
  );
}
