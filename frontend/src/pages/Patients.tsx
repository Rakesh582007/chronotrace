import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PatientCard, Sex } from "../api/types";
import { AppHeader, useTitle } from "../components/shell";
import { Avatar, BlueDot, ConditionChip, ErrorBanner, Icon, Skeleton, Spinner, Triangle } from "../components/ui";
import { age, capitalise, fmtDate, plural, sexLabel } from "../lib/format";
import { prefetchPatient, usePatients } from "../lib/patient";

type Sort = "needs_review" | "name" | "latest_report";
type Filter = "all" | "review" | "few";

const needsReview = (p: PatientCard) => p.guideline_flags + p.change_flags > 0;
const tooFew = (p: PatientCard) => p.report_count < 2;

export default function Patients() {
  const [sort, setSort] = useState<Sort>("needs_review");
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  useTitle("My patients");
  const { data, isLoading, error, refetch } = usePatients(sort);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((p) =>
      (!needle || p.name.toLowerCase().includes(needle) || p.patient_code.toLowerCase().includes(needle)) &&
      (filter === "all" || (filter === "review" ? needsReview(p) : tooFew(p))));
  }, [data, q, filter]);

  const all = data ?? [];
  const sortText = sort === "needs_review" ? "sorted by who needs review first" : sort === "name" ? "sorted by name" : "sorted by latest report";

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader />
      <main className="flex flex-col gap-7 px-4 py-8 sm:px-8 lg:px-14 lg:py-11">
        <div className="flex flex-wrap items-end gap-6">
          <div className="flex flex-col gap-1.5">
            <h1 className="m-0 font-serif text-[40px] font-medium leading-none tracking-[-0.02em]">My patients</h1>
            <p className="m-0 text-[15px] text-ink-3">
              {isLoading ? "Loading…" : `${plural(all.length, "patient")} assigned to you · ${sortText}`}
            </p>
          </div>
          <div className="grow" />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="search" className="text-[13px] font-medium text-ink-3">Search</label>
            <div className="flex h-11 w-[300px] max-w-full items-center gap-2 rounded-[10px] border border-field-line bg-white px-3 focus-within:border-blue focus-within:shadow-[0_0_0_3px_#D4E4F4]">
              {Icon.search}
              <input id="search" type="search" placeholder="Name or patient ID" value={q} onChange={(e) => setQ(e.target.value)}
                className="grow border-0 bg-transparent text-[15px] outline-none" />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="sort" className="text-[13px] font-medium text-ink-3">Sort by</label>
            <select id="sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}
              className="field h-11 w-[200px] rounded-[10px] border border-field-line bg-white px-3 text-[15px]">
              <option value="needs_review">Needs review first</option>
              <option value="name">Name</option>
              <option value="latest_report">Latest report</option>
            </select>
          </div>
          <button type="button" onClick={() => setAdding(true)}
            className="flex h-11 items-center gap-2 rounded-[10px] bg-blue px-5 text-[15px] font-semibold text-white hover:bg-blue-hover">
            {Icon.plus}Add patient
          </button>
        </div>

        <div role="group" aria-label="Filter patients" className="flex flex-wrap gap-2">
          {([["all", "All", all.length], ["review", "Needs review", all.filter(needsReview).length],
            ["few", "Not enough reports", all.filter(tooFew).length]] as const).map(([key, label, n]) => (
            <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}
              className={`h-9 rounded-full border px-3.5 text-sm ${filter === key ? "border-ink bg-ink font-medium text-card" : "border-field-line bg-card text-ink"}`}>
              {label} · {n}
            </button>
          ))}
        </div>

        {error && <ErrorBanner error={error} onRetry={() => refetch()} />}

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
          {isLoading && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="min-h-[300px] rounded-[18px]" />)}
          {shown.map((p) => <PatientCardView key={p.id} p={p} />)}
          {!isLoading && !error && (
            <button type="button" onClick={() => setAdding(true)}
              className="flex min-h-[300px] flex-col items-center justify-center gap-3 rounded-[18px] border-[1.5px] border-dashed border-dash bg-transparent text-ink-3 hover:border-blue-line-2">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-tint text-blue-ink">{Icon.plus}</span>
              <span className="text-base font-semibold text-ink">Add patient</span>
              <span className="max-w-[200px] text-center text-[13px] leading-normal">Name, sex, birth year and conditions. The patient ID is created for you.</span>
            </button>
          )}
        </div>
        {!isLoading && data && shown.length === 0 && (
          <p className="m-0 text-[15px] text-ink-3">No patients match {q ? `“${q}”` : "this filter"}.</p>
        )}
      </main>
      {adding && <AddPatientDialog onClose={() => setAdding(false)} />}
    </div>
  );
}

function PatientCardView({ p }: { p: PatientCard }) {
  const changes = p.change_flags;
  const qc = useQueryClient();
  const warm = () => prefetchPatient(qc, p.id);
  return (
    <Link to={`/patients/${p.patient_code}`} onMouseEnter={warm} onFocus={warm}
      className="plain lift flex min-h-[300px] flex-col gap-4 rounded-[18px] border border-line bg-card p-6 shadow-soft">
      <div className="flex items-center gap-3.5">
        <Avatar id={p.id} name={p.name} hasPhoto={p.has_photo} size={56} />
        <div className="flex min-w-0 flex-col gap-[3px]">
          <span className="font-serif text-[22px] font-medium leading-[1.1] tracking-[-0.01em]">{p.name}</span>
          <span className="font-mono text-[13px] text-ink-3">{p.patient_code}</span>
        </div>
      </div>
      <div className="flex flex-col gap-2.5">
        <span className="text-sm text-ink-3">{sexLabel(p.sex)} · {age(p.birth_year)}</span>
        <div className="flex flex-wrap gap-1.5">{p.conditions.map((c) => <ConditionChip key={c}>{capitalise(c)}</ConditionChip>)}</div>
      </div>
      <div className="h-px bg-paper-2" />
      <div className="flex grow flex-col gap-2">
        {p.guideline_flags > 0 && (
          <span className="flex items-center gap-2 self-start rounded-full border border-amber-line bg-amber-fill px-[11px] py-[5px] text-[13px] font-semibold text-amber-ink">
            <Triangle />{plural(p.guideline_flags, "guideline alert")}
          </span>
        )}
        {changes > 0 && (
          <span className="flex items-center gap-2 text-sm text-blue-ink"><BlueDot />{plural(changes, "change")} from baseline or previous</span>
        )}
        {p.guideline_flags + changes === 0 && (
          <span className="text-sm text-ink-3">
            {p.report_count < 2 ? (p.report_count === 0 ? "No reports yet. Trends start from the second report." : "One report so far. Trends start from the second report.")
              : "No flags · every value within its change threshold"}
          </span>
        )}
        {p.expected_flags > 0 && (
          <span className="text-[13px] text-ink-3">{plural(p.expected_flags, "change")} expected after a drug start</span>
        )}
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-[13px] text-ink-3">
        <span>Latest report <span className="num font-medium text-ink">{fmtDate(p.latest_report_date)}</span></span>
        <span className="num">{plural(p.report_count, "report")} · {plural(p.lab_count, "lab")}</span>
      </div>
    </Link>
  );
}

function AddPatientDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [sex, setSex] = useState<Sex>("female");
  const [birth, setBirth] = useState("");
  const [conds, setConds] = useState<string[]>([]);
  const [cond, setCond] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { ref.current?.showModal(); }, []);

  const m = useMutation({
    mutationFn: async () => {
      const p = await api.createPatient({ name: name.trim(), sex, birth_year: Number(birth), conditions: conds });
      if (photo) await api.uploadPhoto(p.id, photo);
      return p;
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["patients"] }); onClose(); },
    onError: (e) => setErr(e instanceof Error ? e.message : "Could not add the patient"),
  });

  function addCond() {
    const c = cond.trim().toLowerCase();
    if (c && !conds.includes(c)) setConds([...conds, c]);
    setCond("");
  }
  function onCondKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addCond(); }
    if (e.key === "Backspace" && !cond && conds.length) setConds(conds.slice(0, -1));
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    const y = Number(birth);
    if (!name.trim()) return setErr("Enter the patient's name.");
    if (!y || y < 1900 || y > new Date().getFullYear()) return setErr("Enter a birth year between 1900 and this year.");
    setErr(null);
    m.mutate();
  }

  const input = "field h-11 rounded-[10px] border border-field-line bg-white px-3 text-[15px]";
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="add-h"
      className="m-auto w-[min(520px,calc(100vw-32px))] rounded-[20px] border border-line bg-card p-0 text-ink shadow-panel backdrop:bg-ink/40">
      <form onSubmit={submit} className="flex flex-col gap-5 p-8">
        <div className="flex items-center">
          <h2 id="add-h" className="m-0 font-serif text-[26px] font-medium">Add patient</h2>
          <div className="grow" />
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-lg p-1 text-ink-3">{Icon.close}</button>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-name" className="text-sm font-medium">Name</label>
          <input id="np-name" className={input} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div className="flex gap-4">
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1.5 text-sm font-medium">Sex</legend>
            <div className="flex h-11 rounded-[10px] bg-paper-2 p-1">
              {(["female", "male"] as const).map((s) => (
                <label key={s} className={`flex cursor-pointer items-center rounded-lg px-4 text-sm ${sex === s ? "bg-card font-semibold shadow-sm" : "text-ink-3"}`}>
                  <input type="radio" name="sex" value={s} checked={sex === s} onChange={() => setSex(s)} className="sr-only" />
                  {sexLabel(s)}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex grow flex-col gap-1.5">
            <label htmlFor="np-birth" className="text-sm font-medium">Birth year</label>
            <input id="np-birth" inputMode="numeric" className={input} value={birth} onChange={(e) => setBirth(e.target.value.replace(/\D/g, "").slice(0, 4))} />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-cond" className="text-sm font-medium">Conditions</label>
          <div className="flex min-h-11 flex-wrap items-center gap-1.5 rounded-[10px] border border-field-line bg-white px-2 py-1.5 focus-within:border-blue focus-within:shadow-[0_0_0_3px_#D4E4F4]">
            {conds.map((c) => (
              <span key={c} className="flex items-center gap-1 rounded-full bg-chip py-[3px] pl-2.5 pr-1 text-[13px] text-ink-2">
                {capitalise(c)}
                <button type="button" aria-label={`Remove ${c}`} onClick={() => setConds(conds.filter((x) => x !== c))} className="rounded-full px-1 text-ink-3">×</button>
              </span>
            ))}
            <input id="np-cond" value={cond} onChange={(e) => setCond(e.target.value)} onKeyDown={onCondKey} onBlur={addCond}
              placeholder={conds.length ? "" : "Type and press Enter"} className="min-w-[120px] grow border-0 bg-transparent px-1 text-[15px] outline-none" />
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="np-photo" className="text-sm font-medium">Photo <span className="font-normal text-ink-3">(optional)</span></label>
          <input id="np-photo" type="file" accept="image/png,image/jpeg" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} className="text-sm" />
        </div>
        <p className="m-0 text-[13px] text-ink-3">The patient ID (CT-…) is created for you.</p>
        {err && <p role="alert" className="m-0 text-sm font-medium text-amber-ink">{err}</p>}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="h-11 rounded-[10px] border border-field-line bg-card px-4 text-[15px] font-medium">Cancel</button>
          <button type="submit" disabled={m.isPending} className="flex h-11 items-center gap-2 rounded-[10px] bg-blue px-5 text-[15px] font-semibold text-white hover:bg-blue-hover">
            {m.isPending && <Spinner />}Add patient
          </button>
        </div>
      </form>
    </dialog>
  );
}
