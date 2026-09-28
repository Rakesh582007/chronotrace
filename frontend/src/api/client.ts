// One typed client for docs/api.md. The token lives in memory and sessionStorage.
import type {
  Clinical, ConfirmBody, Doctor, FlagsResponse, Medication, NewPatient, Patient, PatientCard, PatientDocument,
  ReportDetail, Summary, SummaryPeriod, SystemsResponse, TrendsResponse,
} from "./types";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";
const KEY = "chronotrace.token";
const DOCTOR_KEY = "chronotrace.doctor";

let token: string | null = null;
try { token = sessionStorage.getItem(KEY); } catch { token = null; }

export class ApiError extends Error {
  status: number;
  detail: unknown;
  body: unknown;
  constructor(status: number, detail: unknown, body: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

type Listener = () => void;
const expiredListeners = new Set<Listener>();
export function onSessionExpired(fn: Listener) {
  expiredListeners.add(fn);
  return () => { expiredListeners.delete(fn); };
}

export function getToken() { return token; }
export function getStoredDoctor(): Doctor | null {
  try { const d = sessionStorage.getItem(DOCTOR_KEY); return d ? JSON.parse(d) as Doctor : null; } catch { return null; }
}
export function setSession(t: string | null, doctor?: Doctor | null) {
  token = t;
  try {
    if (t) sessionStorage.setItem(KEY, t); else sessionStorage.removeItem(KEY);
    if (doctor) sessionStorage.setItem(DOCTOR_KEY, JSON.stringify(doctor));
    if (!t) sessionStorage.removeItem(DOCTOR_KEY);
  } catch { /* storage unavailable: memory only */ }
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth && token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(API_URL + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the ChronoTrace server. Is the backend running?", null);
  }
  if (res.status === 401 && auth) {
    setSession(null);
    expiredListeners.forEach((fn) => fn());
    throw new ApiError(401, "Session expired, please sign in again.", null);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : body;
    throw new ApiError(res.status, detail, body);
  }
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; doctor: Doctor }>("/auth/login", { method: "POST", body: json({ username, password }) }, false),
  me: () => request<Doctor>("/auth/me"),

  patients: (sort: "needs_review" | "name" | "latest_report" = "needs_review") =>
    request<PatientCard[]>(`/patients?sort=${sort}`),
  createPatient: (p: NewPatient) => request<Patient>("/patients", { method: "POST", body: json(p) }),
  uploadPhoto: (id: number, file: File) => {
    const f = new FormData(); f.append("file", file);
    return request<unknown>(`/patients/${id}/photo`, { method: "POST", body: f });
  },
  photoUrl: (id: number) => `${API_URL}/patients/${id}/photo`,

  ask: (id: number, question: string) =>
    request<{ question: string; answer: { text: string; report_ids: number[] }[]; in_facts: boolean;
      reports: { report_id: number; label: string; date: string | null }[]; model: string }>(
      `/patients/${id}/ask`, { method: "POST", body: json({ question }) }),
  clinical: (id: number) => request<Clinical>(`/patients/${id}/clinical`),
  updatePatient: (id: number, body: { weight_kg?: number | null; conditions?: string[] }) =>
    request<Patient>(`/patients/${id}`, { method: "PATCH", body: json(body) }),
  trends: (id: number) => request<TrendsResponse>(`/patients/${id}/trends`),
  flags: (id: number) => request<FlagsResponse>(`/patients/${id}/flags`),
  systems: (id: number) => request<SystemsResponse>(`/patients/${id}/systems`),
  medications: (id: number) => request<Medication[]>(`/patients/${id}/medications`),
  addMedication: (id: number, m: { drug: string; change: string; dose_text?: string; date: string }) =>
    request<Medication>(`/patients/${id}/medications`, { method: "POST", body: json(m) }),
  medicationResponse: (mid: number) => request<Record<string, unknown>>(`/medications/${mid}/response`),

  documents: (id: number) => request<PatientDocument[]>(`/patients/${id}/documents`),
  uploadDocument: (id: number, kind: "prescription" | "doctor_note", file: File, date?: string) => {
    const f = new FormData(); f.append("kind", kind); f.append("file", file);
    if (date) f.append("document_date", date);
    return request<PatientDocument>(`/patients/${id}/documents`, { method: "POST", body: f });
  },
  deleteDocument: (docId: number) => request<void>(`/documents/${docId}`, { method: "DELETE" }),
  documentUrl: (docId: number) => `${API_URL}/documents/${docId}/file`,

  uploadReport: (id: number, file: File) => {
    const f = new FormData(); f.append("file", file);
    return request<ReportDetail>(`/patients/${id}/reports`, { method: "POST", body: f });
  },
  report: (rid: number) => request<ReportDetail>(`/reports/${rid}`),
  confirmReport: (rid: number, body: ConfirmBody) =>
    request<ReportDetail>(`/reports/${rid}/confirm`, { method: "POST", body: json(body) }),

  latestSummary: (id: number, period: SummaryPeriod) =>
    request<Summary>(`/patients/${id}/summaries/latest?period=${period}`),
  writeSummary: (id: number, period: SummaryPeriod, from?: string, to?: string) =>
    request<Summary>(`/patients/${id}/summaries`, { method: "POST", body: json(period === "range" ? { period, from, to } : { period }) }),
};

/** Fetch a protected binary (report page PNG, photo, PDF) as an object URL. */
export async function authedBlobUrl(path: string): Promise<string> {
  const res = await fetch(path.startsWith("http") ? path : API_URL + path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, `Could not load ${path}`, null);
  return URL.createObjectURL(await res.blob());
}
