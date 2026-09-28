import { useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, authedBlobUrl } from "../api/client";
import type { ConfirmBody, Observation, PatientDocument, ReportDetail, SkippedLine } from "../api/types";
import { useToast } from "../components/shell";
import { ErrorBanner, Icon, Skeleton, Spinner } from "../components/ui";
import { fmtDate, fmtNum, fmtUnit, plural, shortName } from "../lib/format";
import { keys, useDocuments } from "../lib/patient";
import { usePatientCtx } from "./PatientLayout";

type Edit = { value_text?: string; unit_text?: string; reject?: boolean };
type Add = { page: number; line: number; test_text: string; value_text: string; unit_text: string };

const DPI = 110;

export default function Documents() {
  const { patient, base } = usePatientCtx();
  const docs = useDocuments(patient.id);
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<number, Edit>>({});
  const [adds, setAdds] = useState<Add[]>([]);
  const [date, setDate] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [confirmErr, setConfirmErr] = useState<string | null>(null);
  const [attached, setAttached] = useState<Record<string, PatientDocument>>({});

  // Resume a lab report that was uploaded but not confirmed yet.
  const pending = docs.data?.find((d) => d.kind === "lab_report" && d.report_status === "extracted");
  useEffect(() => {
    if (!detail && pending?.report_id) api.report(pending.report_id).then(setDetail).catch(() => undefined);
  }, [pending?.report_id, detail]);

  const upload = useMutation({
    mutationFn: (f: File) => api.uploadReport(patient.id, f),
    onMutate: () => setUploadErr(null),
    onSuccess: (d) => {
      setDetail(d); setEdits({}); setAdds([]); setDate("");
      setSelected(d.observations.find((o) => o.status !== "not_tracked")?.id ?? null);
      qc.invalidateQueries({ queryKey: keys.documents(patient.id) });
    },
    onError: (e) => setUploadErr(e instanceof ApiError && e.status === 409
      ? "This file was already uploaded for this patient." : e instanceof Error ? e.message : "Upload failed"),
  });

  const attach = useMutation({
    mutationFn: ({ kind, file }: { kind: "prescription" | "doctor_note"; file: File }) =>
      api.uploadDocument(patient.id, kind, file, detail?.report.collected_at ?? (date || undefined)),
    onSuccess: (d) => { setAttached((a) => ({ ...a, [d.kind]: d })); qc.invalidateQueries({ queryKey: keys.documents(patient.id) }); },
    onError: (e) => toast(e instanceof ApiError && e.status === 409 ? "That file is already stored." : (e as Error).message, "amber"),
  });

  const confirm = useMutation({
    mutationFn: async () => {
      const before = new Set((qc.getQueryData<{ flags: { id: string; level: string }[] }>(keys.flags(patient.id))?.flags
        ?? (await api.flags(patient.id)).flags).filter((f) => f.level === "guideline").map((f) => f.id));
      const body: ConfirmBody = {};
      if (!detail!.report.collected_at && date) body.collected_at = date;
      const obs = Object.entries(edits).map(([id, e]) => ({ id: Number(id), ...e }));
      if (obs.length) body.observations = obs;
      if (adds.length) body.add = adds.map((a) => ({ ...a, unit_text: a.unit_text || undefined }));
      await api.confirmReport(detail!.report.id, body);
      const after = (await api.flags(patient.id)).flags.filter((f) => f.level === "guideline" && !before.has(f.id));
      return after;
    },
    onMutate: () => setConfirmErr(null),
    onSuccess: async (fresh) => {
      await Promise.all(["trends", "flags", "systems", "documents", "patients", "medications"].map((k) => qc.invalidateQueries({ queryKey: [k] })));
      toast(fresh.length ? `Report confirmed · trends updated · ${plural(fresh.length, "new guideline alert")}` : "Report confirmed · trends updated",
        fresh.length ? "amber" : "info");
      setDetail(null);
      navigate(base, { state: { newGuideline: fresh[0]?.id } });
    },
    onError: (e) => setConfirmErr(e instanceof ApiError && typeof e.detail === "object" ? JSON.stringify(e.detail) : (e as Error).message),
  });

  const visible = detail?.observations ?? [];
  const status = (o: Observation) => (edits[o.id]?.reject ? "rejected" : o.status);
  const counts = useMemo(() => {
    const c = { ready: 0, not_tracked: 0, review: 0, rejected: 0 };
    for (const o of visible) {
      const s = status(o);
      if (s === "rejected") c.rejected++;
      else if (s === "needs_review") c.review += edits[o.id]?.value_text || edits[o.id]?.unit_text ? 0 : 1;
      else if (s === "not_tracked") c.not_tracked++;
      else c.ready++;
    }
    return c;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, edits]);
  const needsDate = !!detail && !detail.report.collected_at;
  const canConfirm = !!detail && counts.review === 0 && (!needsDate || !!date) && !confirm.isPending;

  return (
    <div className="flex flex-col">
      <section className="flex flex-wrap items-end gap-6 px-4 pb-[18px] pt-6 sm:px-8 lg:px-14">
        <div className="flex flex-col gap-1.5">
          <h2 className="m-0 font-serif text-[38px] font-medium leading-none tracking-[-0.02em]">Add documents</h2>
          <span className="text-[15px] text-ink-3">{patient.name} · {patient.patient_code} · nothing reaches the trends until you confirm</span>
        </div>
        <div className="grow" />
        <Steps step={detail ? 2 : 1} />
      </section>

      <section aria-label="Documents" className="grid grid-cols-1 gap-4 px-4 sm:px-8 md:grid-cols-3 lg:px-14">
        <FileSlot title="Lab report · required" accept="application/pdf" primary
          file={detail?.report.filename} busy={upload.isPending}
          info={detail ? `${plural(detail.report.pages, "page")} · read by the model · ${plural(detail.observations.length, "result")} found` : undefined}
          hint="Choose the report PDF" sub="PDF with a text layer · read by the model"
          onFile={(f) => upload.mutate(f)} testId="lab-input" />
        <FileSlot title="Prescription · optional" accept="application/pdf,image/png,image/jpeg"
          file={attached.prescription?.filename} busy={attach.isPending && attach.variables?.kind === "prescription"}
          info={attached.prescription ? "Stored with the report. Add the drugs it lists below." : undefined}
          hint="Drop this visit's prescription, or choose a file" sub="PDF or photo · stored, not read"
          onFile={(f) => attach.mutate({ kind: "prescription", file: f })} />
        <FileSlot title="Doctor's note · optional" accept="application/pdf,image/png,image/jpeg"
          file={attached.doctor_note?.filename} busy={attach.isPending && attach.variables?.kind === "doctor_note"}
          info={attached.doctor_note ? "Stored with the report." : undefined}
          hint="Drop this visit's note, or choose a file" sub="PDF or photo · stored, not read"
          onFile={(f) => attach.mutate({ kind: "doctor_note", file: f })} />
      </section>
      {uploadErr && <div className="px-4 pt-4 sm:px-8 lg:px-14"><ErrorBanner error={new Error(uploadErr)} /></div>}
      {upload.isPending && (
        <div className="grid grid-cols-1 gap-8 px-4 pt-5 sm:px-8 lg:px-14 min-[1100px]:grid-cols-[400px_1fr]">
          <Skeleton className="h-[520px]" /><div className="flex flex-col gap-3"><Skeleton className="h-8 w-80" /><Skeleton className="h-[360px]" /></div>
        </div>
      )}

      {detail && (
        <>
          <main className="grid grid-cols-1 items-start gap-8 px-4 pt-[18px] sm:px-8 lg:px-14 min-[1100px]:grid-cols-[minmax(340px,400px)_minmax(0,1fr)]">
            <PagePreview detail={detail} selected={visible.find((o) => o.id === selected) ?? null} />
            <section aria-labelledby="rev-h" className="flex min-w-0 flex-col gap-3.5">
              <div className="flex flex-wrap items-center gap-3">
                <h3 id="rev-h" className="m-0 font-serif text-2xl font-medium">Check the extracted values</h3>
                <div className="grow" />
                {detail.report.collected_at ? (
                  <span className="rounded-full border border-line bg-card px-2.5 py-1 text-[13px]">
                    {detail.report.date_label ?? "Date"} <strong className="num font-semibold">{fmtDate(detail.report.collected_at)}</strong>
                    {detail.report.date_label && <> · from the “{detail.report.date_label}” label</>}
                  </span>
                ) : (
                  <label className="flex items-center gap-2 rounded-full border border-amber-line bg-amber-fill px-3 py-1 text-[13px] text-amber-ink">
                    No collected date on the report — enter it
                    <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="field rounded-md border border-field-line bg-white px-2 py-0.5 text-ink" aria-label="Report date" />
                  </label>
                )}
                {detail.report.lab && <span className="rounded-full border border-line bg-card px-2.5 py-1 text-[13px]">Lab <strong className="font-semibold">{detail.report.lab}</strong></span>}
              </div>
              {detail.report.layout === "no header" && (
                <p className="m-0 rounded-[10px] border border-amber-line bg-amber-fill px-3 py-2 text-[13px] text-amber-ink">No table header was found on this report. Check each value carefully.</p>
              )}
              <ReviewTable obs={visible} edits={edits} setEdits={setEdits} selected={selected} setSelected={setSelected} status={status} />
              <OtherLines detail={detail} adds={adds} setAdds={setAdds} />
              <DrugForm patientId={patient.id} defaultDate={detail.report.collected_at ?? date} />
            </section>
          </main>
          <footer className="no-print sticky bottom-0 z-10 mt-[18px] flex min-h-[76px] flex-wrap items-center gap-4 border-t border-line bg-card px-4 py-3 sm:px-8 lg:px-14">
            <span className="text-sm text-ink-2">
              <strong className="font-semibold text-ink">{plural(counts.ready + adds.length, "value")} ready</strong>
              {" "}· {counts.not_tracked} not tracked · {counts.review} need review{counts.rejected ? ` · ${counts.rejected} rejected` : ""}
              {needsDate && !date && " · enter the report date"}
            </span>
            {confirmErr && <span role="alert" className="text-sm font-medium text-amber-ink">{confirmErr}</span>}
            <div className="grow" />
            <button type="button" onClick={() => { setDetail(null); navigate(base); }} className="px-3 text-[15px] font-medium text-blue hover:underline">Cancel</button>
            <button type="button" disabled={!canConfirm} onClick={() => confirm.mutate()} data-testid="confirm-report"
              className="flex h-[46px] items-center gap-2 rounded-[10px] bg-blue px-[22px] text-[15px] font-semibold text-white hover:bg-blue-hover disabled:bg-muted-mark">
              {confirm.isPending ? <Spinner /> : Icon.check}Confirm report and update trends
            </button>
          </footer>
        </>
      )}

      <StoredDocuments docs={docs.data} loading={docs.isLoading} error={docs.error} retry={() => docs.refetch()} patientId={patient.id} />
    </div>
  );
}

function Steps({ step }: { step: 1 | 2 | 3 }) {
  const items = ["Add files", "Review values", "Confirm"];
  return (
    <ol aria-label="Steps" className="m-0 flex list-none items-center gap-2.5 p-0 text-sm">
      {items.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const current = n === step;
        return (
          <li key={label} className="flex items-center gap-2.5">
            {i > 0 && <span aria-hidden="true" className="h-px w-7 bg-dash" />}
            <span aria-current={current ? "step" : undefined} className={`flex items-center gap-2 ${current ? "font-semibold" : done ? "text-ink-2" : "text-ink-3"}`}>
              <span className={`box-border flex h-6 w-6 items-center justify-center rounded-full text-xs ${done ? "bg-blue text-white" : current ? "border-2 border-blue text-blue-ink" : "border-[1.5px] border-dash"}`}>
                {done ? "✓" : n}
              </span>{label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function FileSlot({ title, accept, file, info, hint, sub, onFile, busy, primary, testId }: {
  title: string; accept: string; file?: string; info?: string; hint: string; sub: string; onFile: (f: File) => void;
  busy?: boolean; primary?: boolean; testId?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const pick = (e: ChangeEvent<HTMLInputElement>) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; };
  const hidden = <input ref={input} type="file" accept={accept} className="sr-only" onChange={pick} data-testid={testId} aria-label={title} />;
  if (file)
    return (
      <div className={`flex items-start gap-3.5 rounded-2xl border bg-card px-[18px] py-4 ${primary ? "border-blue-line-2 shadow-[0_0_0_3px_#EAF3FB]" : "border-line"}`}>
        {hidden}
        <span className={`flex h-12 w-10 shrink-0 items-center justify-center rounded-md border text-[10px] font-semibold ${primary ? "border-blue-line bg-blue-tint-2 text-blue-ink" : "border-line bg-paper text-ink-2"}`}>
          {file.toLowerCase().endsWith(".pdf") ? "PDF" : "IMG"}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <span className={`text-xs font-semibold uppercase tracking-[0.06em] ${primary ? "text-blue-ink" : "text-ink-3"}`}>{title}</span>
          <span className="truncate font-mono text-[13px]">{file}</span>
          {info && <span className="text-[13px] text-ink-2">{info}</span>}
        </div>
      </div>
    );
  return (
    <button type="button" onClick={() => input.current?.click()} disabled={busy}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}
      className={`flex items-center gap-3.5 rounded-2xl border-[1.5px] border-dashed px-[18px] py-4 text-left ${over ? "border-blue bg-blue-tint-2" : primary ? "border-blue-line-2 bg-card" : "border-dash bg-transparent"}`}>
      {hidden}
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${primary ? "bg-blue-tint text-blue-ink" : "bg-chip text-ink-2"}`}>
        {busy ? <Spinner /> : Icon.upload}
      </span>
      <span className="flex flex-col gap-1">
        <span className="text-xs font-semibold uppercase tracking-[0.06em] text-ink-3">{title}</span>
        <span className="text-sm text-ink">{busy ? "Reading the report…" : hint}</span>
        <span className="text-xs text-ink-3">{sub}</span>
      </span>
    </button>
  );
}

function PagePreview({ detail, selected }: { detail: ReportDetail; selected: Observation | null }) {
  const [page, setPage] = useState(1);
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const shown = selected?.page ?? page;
  useEffect(() => {
    let url: string | null = null;
    let live = true;
    setSrc(null); setErr(false);
    authedBlobUrl(`/reports/${detail.report.id}/pages/${shown}.png`)
      .then((u) => { url = u; if (live) setSrc(u); }).catch(() => live && setErr(true));
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [detail.report.id, shown]);
  const box = selected?.bbox && natural ? selected.bbox.map((v) => (v * DPI) / 72) : null;
  return (
    <section aria-label="Report preview" className="flex flex-col gap-2.5 min-[1100px]:sticky min-[1100px]:top-4">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-semibold text-ink-2">Page {shown} of {detail.report.pages}</span>
        <span className="text-xs text-ink-3">{selected ? "Selected row is highlighted" : "Select a row to find it on the page"}</span>
      </div>
      <div className="relative overflow-hidden rounded-md border border-line bg-white shadow-[0_14px_30px_-24px_rgba(29,39,51,0.5)]">
        {!src && !err && <Skeleton className="h-[520px] rounded-none" />}
        {err && <p className="m-0 p-6 text-sm text-ink-3">The page preview could not be rendered.</p>}
        {src && (
          <div className="relative">
            <img src={src} alt={`Page ${shown} of the uploaded report`} className="block w-full"
              onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
            {box && natural && (
              <div aria-hidden="true" className="absolute rounded-[3px] bg-blue/15 outline outline-[1.5px] outline-blue"
                style={{
                  left: `${((box[0] - 4) / natural.w) * 100}%`, top: `${((box[1] - 3) / natural.h) * 100}%`,
                  width: `${((box[2] - box[0] + 8) / natural.w) * 100}%`, height: `${((box[3] - box[1] + 6) / natural.h) * 100}%`,
                }} />
            )}
          </div>
        )}
      </div>
      {detail.report.pages > 1 && (
        <div className="flex gap-2">
          {Array.from({ length: detail.report.pages }, (_, i) => i + 1).map((n) => (
            <button key={n} type="button" onClick={() => setPage(n)} aria-pressed={shown === n}
              className={`h-8 w-8 rounded-lg border text-sm ${shown === n ? "border-blue bg-blue-tint text-blue-ink" : "border-field-line bg-card"}`}>{n}</button>
          ))}
        </div>
      )}
    </section>
  );
}

const PILL: Record<string, [string, string]> = {
  Ready: ["bg-blue-tint", "text-blue-ink"], Recalculated: ["bg-blue-tint-2", "text-blue-ink"], Edited: ["bg-blue-tint-2", "text-blue-ink"],
  "Needs review": ["bg-amber-fill", "text-amber-ink"], "Not tracked": ["bg-stable", "text-ink-2"], Rejected: ["bg-paper-2", "text-ink-3"],
};

function ReviewTable({ obs, edits, setEdits, selected, setSelected, status }: {
  obs: Observation[]; edits: Record<number, Edit>; setEdits: (f: (e: Record<number, Edit>) => Record<number, Edit>) => void;
  selected: number | null; setSelected: (id: number) => void; status: (o: Observation) => string;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const rows = [...obs].sort((a, b) => (a.status === "not_tracked" ? 1 : 0) - (b.status === "not_tracked" ? 1 : 0) || a.page - b.page || a.line - b.line);
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-card">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-[#FBF8F2] text-left text-xs uppercase tracking-[0.05em] text-ink-3">
              <th scope="col" className="px-4 py-2.5 font-semibold">Status</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">As printed</th>
              <th scope="col" className="px-2 py-2.5 text-right font-semibold">Value</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">Unit</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">Tracked as</th>
              <th scope="col" className="px-2 py-2.5 font-semibold">Where</th>
              <th scope="col" className="py-2.5 pl-2 pr-4"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => {
              const s = status(o);
              const e = edits[o.id] ?? {};
              const label = s === "rejected" ? "Rejected" : s === "needs_review" && !(e.value_text || e.unit_text) ? "Needs review" : s === "not_tracked" ? "Not tracked"
                : e.value_text || e.unit_text ? "Edited" : o.analyte_id === "egfr" ? "Recalculated" : "Ready";
              const [bg, fg] = PILL[label];
              const note = o.analyte_id === "egfr" ? `from creatinine, age and sex · printed ${o.value_text} kept`
                : s === "needs_review" ? o.status_reason : s === "not_tracked" ? "kept on the report only"
                  : o.notes.length ? plural(o.notes.length, "note") + " attached" : o.match ? `${o.match} name match` : "";
              const value = o.analyte_id === "egfr" && o.canonical_value != null ? fmtNum(o.canonical_value) : (e.value_text ?? o.value_text);
              return (
                <tr key={o.id} onClick={() => setSelected(o.id)} aria-selected={selected === o.id}
                  className={`cursor-pointer border-t border-[#F0E9DB] ${selected === o.id ? "bg-blue-tint-2" : "hover:bg-[#FBF8F2]"} ${s === "rejected" ? "text-ink-3 line-through" : ""}`}>
                  <td className="px-4 py-[9px]"><span className={`whitespace-nowrap rounded-full px-[9px] py-[3px] text-xs font-semibold no-underline ${bg} ${fg}`}>{label}</span></td>
                  <td className="px-2 py-[9px] font-mono text-[12.5px]">{o.test_text}</td>
                  {editing === o.id ? (
                    <>
                      <td className="px-2 py-1 text-right" onClick={(ev) => ev.stopPropagation()}>
                        <input aria-label={`Value for ${o.test_text}`} defaultValue={e.value_text ?? o.value_text} autoFocus
                          onChange={(ev) => setEdits((x) => ({ ...x, [o.id]: { ...x[o.id], value_text: ev.target.value } }))}
                          className="field h-8 w-20 rounded-md border border-field-line bg-white px-2 text-right" />
                      </td>
                      <td className="px-2 py-1" onClick={(ev) => ev.stopPropagation()}>
                        <input aria-label={`Unit for ${o.test_text}`} defaultValue={e.unit_text ?? o.unit_text}
                          onChange={(ev) => setEdits((x) => ({ ...x, [o.id]: { ...x[o.id], unit_text: ev.target.value } }))}
                          onKeyDown={(ev) => ev.key === "Enter" && setEditing(null)}
                          className="field h-8 w-24 rounded-md border border-field-line bg-white px-2" />
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="num px-2 py-[9px] text-right font-semibold">{o.comparator ?? ""}{value || "—"}</td>
                      <td className="px-2 py-[9px] text-ink-2">{o.analyte_id === "egfr" ? fmtUnit(o.canonical_unit) : (e.unit_text ?? o.unit_text)}</td>
                    </>
                  )}
                  <td className="px-2 py-[9px]">
                    {o.analyte_name ? shortName(o.analyte_name) : s === "not_tracked" ? "Not in the tracked list" : "—"}
                    {note && <span className="block text-xs text-ink-3 no-underline">{note}</span>}
                  </td>
                  <td className="whitespace-nowrap px-2 py-[9px] font-mono text-xs text-ink-3">p{o.page} · line {o.line}</td>
                  <td className="py-1.5 pl-2 pr-4" onClick={(ev) => ev.stopPropagation()}>
                    <div className="flex gap-0.5">
                      {o.analyte_id !== "egfr" && s !== "rejected" && (
                        <button type="button" aria-label={editing === o.id ? `Done editing ${o.test_text}` : `Edit ${o.test_text}`}
                          onClick={() => { setSelected(o.id); setEditing(editing === o.id ? null : o.id); }}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-2 hover:bg-paper-2">
                          {editing === o.id ? Icon.check : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z" /></svg>}
                        </button>
                      )}
                      {o.status !== "not_tracked" && (
                        <button type="button" aria-label={s === "rejected" ? `Restore ${o.test_text}` : `Reject ${o.test_text}`} aria-pressed={s === "rejected"}
                          onClick={() => setEdits((x) => ({ ...x, [o.id]: { ...x[o.id], reject: !x[o.id]?.reject } }))}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-2 hover:bg-paper-2">
                          {s === "rejected" ? "↺" : Icon.close}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OtherLines({ detail, adds, setAdds }: { detail: ReportDetail; adds: Add[]; setAdds: (a: Add[]) => void }) {
  const [adding, setAdding] = useState<SkippedLine | null>(null);
  const notes = detail.observations.filter((o) => o.notes.length);
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-line bg-[#FBF8F2] px-4 py-3">
      <span className="text-xs font-semibold uppercase tracking-[0.05em] text-ink-3">Other lines on the page</span>
      <span className="text-[13px] text-ink-2">
        {notes.length > 0 && <>{plural(notes.reduce((n, o) => n + o.notes.length, 0), "method or specimen line")} attached to {plural(notes.length, "result")} as notes · </>}
        {detail.skipped.length > 0 && <>{plural(detail.skipped.length, "line")} not read as a result (below) · </>}
        every line is accounted for
      </span>
      {detail.skipped.map((s) => {
        const added = adds.some((a) => a.page === s.page && a.line === s.line);
        return (
          <div key={`${s.page}-${s.line}`} className="flex flex-wrap items-baseline gap-2 text-[13px]">
            <span className="font-mono text-xs text-ink-3">p{s.page} · line {s.line}</span>
            <span className="font-mono text-xs">{s.text}</span>
            <span className="text-ink-3">— {s.reason}</span>
            <div className="grow" />
            {added ? <span className="text-xs font-semibold text-blue-ink">Added as a result</span> : (
              <button type="button" onClick={() => setAdding(s)} className="text-xs font-semibold text-blue hover:underline">Add as a result</button>
            )}
          </div>
        );
      })}
      {adding && <AddLineForm line={adding} onCancel={() => setAdding(null)} onAdd={(a) => { setAdds([...adds, a]); setAdding(null); }} />}
    </div>
  );
}

function AddLineForm({ line, onAdd, onCancel }: { line: SkippedLine; onAdd: (a: Add) => void; onCancel: () => void }) {
  const [test, setTest] = useState(line.text.split(/\s{2,}|\s(?=\d)/)[0] ?? "");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const submit = (e: FormEvent) => { e.preventDefault(); if (test && value) onAdd({ page: line.page, line: line.line, test_text: test, value_text: value, unit_text: unit }); };
  const f = "field h-9 rounded-lg border border-field-line bg-white px-2 text-sm";
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded-xl border border-line bg-card p-3">
      <label className="flex flex-col gap-1 text-xs text-ink-2">Test<input className={f} value={test} onChange={(e) => setTest(e.target.value)} /></label>
      <label className="flex flex-col gap-1 text-xs text-ink-2">Value<input className={`${f} w-24`} value={value} onChange={(e) => setValue(e.target.value)} autoFocus /></label>
      <label className="flex flex-col gap-1 text-xs text-ink-2">Unit<input className={`${f} w-24`} value={unit} onChange={(e) => setUnit(e.target.value)} /></label>
      <button type="submit" className="h-9 rounded-lg border border-blue-line-2 bg-blue-tint-2 px-3 text-sm font-semibold text-blue-ink">Add</button>
      <button type="button" onClick={onCancel} className="h-9 px-2 text-sm text-blue">Cancel</button>
    </form>
  );
}

function DrugForm({ patientId, defaultDate }: { patientId: number; defaultDate: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [drug, setDrug] = useState("");
  const [change, setChange] = useState("start");
  const [dose, setDose] = useState("");
  const [date, setDate] = useState(defaultDate);
  useEffect(() => setDate(defaultDate), [defaultDate]);
  const m = useMutation({
    mutationFn: () => api.addMedication(patientId, { drug: drug.trim(), change, dose_text: dose.trim() || undefined, date }),
    onSuccess: (r) => {
      toast(`${r.drug} ${change === "start" ? "start" : change === "stop" ? "stop" : "dose change"} recorded`);
      setDrug(""); setDose("");
      ["medications", "flags", "trends", "systems"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e) => toast((e as Error).message, "amber"),
  });
  const f = "field h-10 rounded-lg border border-field-line bg-white px-2.5 text-sm";
  return (
    <form id="drugs" onSubmit={(e) => { e.preventDefault(); if (drug && date) m.mutate(); }}
      className="flex flex-col gap-2.5 rounded-2xl border border-line bg-card px-4 py-3.5">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <span className="text-[15px] font-semibold">Drugs from the prescription</span>
        <span className="text-[13px] text-ink-3">Prescriptions are stored, not read. Enter only what changed.</span>
      </div>
      <div className="grid grid-cols-2 items-end gap-2.5 md:grid-cols-[1.4fr_1fr_1fr_1fr_auto]">
        <label className="flex flex-col gap-1 text-xs text-ink-2">Drug<input className={f} placeholder="e.g. Empagliflozin" value={drug} onChange={(e) => setDrug(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs text-ink-2">Change
          <select className={f} value={change} onChange={(e) => setChange(e.target.value)}>
            <option value="start">Start</option><option value="stop">Stop</option><option value="dose_change">Dose change</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-2">Dose<input className={f} placeholder="e.g. 10 mg OD" value={dose} onChange={(e) => setDose(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs text-ink-2">Date<input className={f} type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
        <button type="submit" disabled={m.isPending || !drug || !date} className="h-10 rounded-lg border border-blue-line-2 bg-blue-tint-2 px-3.5 text-sm font-semibold text-blue-ink disabled:opacity-60">
          {m.isPending ? "Adding…" : "Add"}
        </button>
      </div>
    </form>
  );
}

const KIND: Record<string, string> = { lab_report: "Lab report", prescription: "Prescription", doctor_note: "Doctor's note" };

function StoredDocuments({ docs, loading, error, retry, patientId }: {
  docs: PatientDocument[] | undefined; loading: boolean; error: unknown; retry: () => void; patientId: number;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const del = useMutation({
    mutationFn: (id: number) => api.deleteDocument(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents(patientId) }),
    onError: (e) => toast(e instanceof ApiError && e.status === 409 ? "A confirmed lab report can't be deleted: its values are in the trends." : (e as Error).message, "amber"),
  });
  async function open(d: PatientDocument) {
    try { window.open(await authedBlobUrl(api.documentUrl(d.id)), "_blank", "noopener"); } catch { toast("Could not open the file.", "amber"); }
  }
  return (
    <section aria-labelledby="docs-h" className="flex flex-col gap-3 px-4 pb-12 pt-8 sm:px-8 lg:px-14">
      <h3 id="docs-h" className="m-0 font-serif text-2xl font-medium">Stored documents</h3>
      {error ? <ErrorBanner error={error} onRetry={retry} /> : null}
      {loading && <Skeleton className="h-40 rounded-2xl" />}
      {docs && docs.length === 0 && <p className="m-0 text-sm text-ink-3">No documents yet.</p>}
      {docs && docs.length > 0 && (
        <div className="overflow-x-auto rounded-2xl border border-line bg-card">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-[#FBF8F2] text-left text-xs uppercase tracking-[0.05em] text-ink-3">
                <th scope="col" className="px-4 py-2.5 font-semibold">Kind</th>
                <th scope="col" className="px-2 py-2.5 font-semibold">File</th>
                <th scope="col" className="px-2 py-2.5 font-semibold">Date</th>
                <th scope="col" className="px-2 py-2.5 font-semibold">Status</th>
                <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-t border-[#F0E9DB]">
                  <td className="px-4 py-2.5">{KIND[d.kind]}</td>
                  <td className="px-2 py-2.5 font-mono text-[12.5px]">{d.filename}</td>
                  <td className="num px-2 py-2.5">{fmtDate(d.document_date ?? d.uploaded_at)}</td>
                  <td className="px-2 py-2.5 text-ink-3">{d.kind === "lab_report" ? (d.report_status === "confirmed" ? "Confirmed" : "Waiting for review") : "Stored, not read"}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex justify-end gap-3">
                      <button type="button" onClick={() => open(d)} className="text-sm text-blue hover:underline">Open</button>
                      {!(d.kind === "lab_report" && d.report_status === "confirmed") && (
                        <button type="button" onClick={() => del.mutate(d.id)} className="text-sm text-ink-3 hover:underline">Delete</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
