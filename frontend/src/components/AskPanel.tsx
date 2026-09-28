import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { Flag } from "../api/types";
import { fmtDate } from "../lib/format";
import { Icon, ReportChip, Spinner } from "./ui";

interface Turn {
  q: string;
  a?: { text: string; labels: string[] }[];
  inFacts?: boolean;
  failed?: string;
  model?: string;
}

const SUGGESTED = [
  "Why is the kidney card amber?",
  "What changed since the last visit?",
  "What happened after each drug was started?",
  "Which guideline criteria are met?",
];

export default function AskPanel({ patientId, name, flags, onClose }: { patientId: number; name: string; flags: Flag[]; onClose: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [turns]);
  useEffect(() => {
    input.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const [pending, setPending] = useState(false);
  const answer = (patch: Partial<Turn>) => setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, ...patch } : x)));

  async function run(question: string) {
    setPending(true);
    try {
      const r = await api.ask(patientId, question);
      answer({
        inFacts: r.in_facts, model: r.model,
        a: r.answer.map((s) => ({ text: s.text, labels: s.report_ids.map((id) => r.reports.find((p) => p.report_id === id)?.label ?? "") })),
      });
    } catch (e) {
      answer({ failed: e instanceof ApiError && (e.status === 502 || e.status === 503)
        ? "The answer service is unavailable right now, or its answer did not pass the checks." : (e as Error).message });
    } finally {
      setPending(false);
    }
  }

  function send(question: string) {
    const text = question.trim();
    if (!text || pending) return;
    setTurns((t) => [...t, { q: text }]);
    setQ("");
    void run(text);
  }
  const submit = (e: FormEvent) => { e.preventDefault(); send(q); };
  const review = flags.filter((f) => !f.expected_effect);

  return (
    <aside role="dialog" aria-label={`Ask about ${name}`} className="no-print fixed inset-y-0 right-0 z-40 flex w-[min(460px,100vw)] flex-col border-l border-line bg-card shadow-panel">
      <div className="flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-blue-ink">Ask about this patient</span>
          <span className="font-serif text-xl font-medium">{name}</span>
          <span className="text-xs text-ink-3">Answers come only from the computed results and cite their reports. Checked before they are shown.</span>
        </div>
        <div className="grow" />
        <button type="button" aria-label="Close" onClick={onClose} className="rounded-lg p-1 text-ink-3 hover:bg-paper-2">{Icon.close}</button>
      </div>
      <div className="flex grow flex-col gap-4 overflow-y-auto px-5 py-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-[13px] text-ink-3">Try:</span>
            {SUGGESTED.map((s) => (
              <button key={s} type="button" onClick={() => send(s)} className="self-start rounded-full border border-blue-line bg-blue-tint-2 px-3 py-1.5 text-left text-sm text-blue-ink hover:border-blue">{s}</button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="flex flex-col gap-2">
            <div className="self-end rounded-2xl rounded-br-md bg-ink px-3.5 py-2 text-sm text-card">{t.q}</div>
            {!t.a && !t.failed && (
              <div className="flex items-center gap-2 self-start text-sm text-ink-3"><Spinner />Reading the computed results…</div>
            )}
            {t.a && (
              <div className={`flex flex-col gap-2 self-start rounded-2xl rounded-bl-md border px-3.5 py-2.5 text-sm leading-normal ${t.inFacts ? "border-line bg-[#FBF8F2]" : "border-dashed border-dash bg-card text-ink-2"}`}>
                {t.a.map((s, j) => (
                  <p key={j} className="m-0">{s.text}{s.labels.filter(Boolean).map((l) => <span key={l} className="ml-1"><ReportChip label={l} tone="blue" /></span>)}</p>
                ))}
                <span className="text-[11px] text-ink-3">{t.inFacts ? "From the computed results" : "Not in the computed results"} · {t.model}</span>
              </div>
            )}
            {t.failed && (
              <div className="flex flex-col gap-2 self-start rounded-2xl rounded-bl-md border border-amber-line bg-amber-soft px-3.5 py-2.5 text-sm text-amber-deep">
                <span>{t.failed} What the engine computed:</span>
                {review.length ? review.slice(0, 5).map((f) => <span key={f.id} className="text-[13px]">• {f.message} <span className="text-ink-3">({fmtDate(f.date)})</span></span>)
                  : <span className="text-[13px]">No flags beyond the thresholds.</span>}
              </div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="flex items-end gap-2 border-t border-line px-4 py-3">
        <label htmlFor="ask-q" className="sr-only">Question</label>
        <textarea id="ask-q" ref={input} rows={2} maxLength={500} value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }}
          placeholder="Ask about trends, flags, drugs or criteria…" className="field grow resize-none rounded-[10px] border border-field-line bg-white px-3 py-2 text-sm" />
        <button type="submit" disabled={!q.trim() || pending} className="flex h-10 items-center rounded-[10px] bg-blue px-4 text-sm font-semibold text-white hover:bg-blue-hover disabled:bg-muted-mark">Ask</button>
      </form>
    </aside>
  );
}
