import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { getStoredDoctor, getToken, onSessionExpired, setSession } from "../api/client";
import type { Doctor } from "../api/types";
import { initials } from "../lib/format";
import { Logo } from "./ui";

/* ---------- auth ---------- */

interface AuthState {
  doctor: Doctor | null;
  signedIn: boolean;
  signIn: (token: string, doctor: Doctor) => void;
  signOut: (message?: string) => void;
  notice: string | null;
}
const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(!!getToken());
  const [doctor, setDoctor] = useState<Doctor | null>(getStoredDoctor());
  const [notice, setNotice] = useState<string | null>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const where = useRef(location);
  where.current = location;

  const signOut = useCallback((message?: string) => {
    setSession(null);
    setSignedIn(false);
    setDoctor(null);
    qc.clear();
    setNotice(message ?? null);
    const next = where.current.pathname.startsWith("/login") ? "" : `?next=${encodeURIComponent(where.current.pathname)}`;
    navigate(`/login${message ? next : ""}`, { replace: true });
  }, [navigate, qc]);

  useEffect(() => onSessionExpired(() => signOut("Session expired, please sign in again.")), [signOut]);

  const signIn = useCallback((token: string, d: Doctor) => {
    setSession(token, d);
    setDoctor(d);
    setSignedIn(true);
    setNotice(null);
  }, []);

  return <AuthCtx.Provider value={{ doctor, signedIn, signIn, signOut, notice }}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const a = useContext(AuthCtx);
  if (!a) throw new Error("useAuth outside AuthProvider");
  return a;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { signedIn } = useAuth();
  const loc = useLocation();
  if (!signedIn) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;
  return <>{children}</>;
}

/* ---------- toasts ---------- */

interface Toast { id: number; text: string; tone: "info" | "amber" }
const ToastCtx = createContext<(text: string, tone?: "info" | "amber") => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "info" | "amber" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="no-print pointer-events-none fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((t) => (
          <div key={t.id} role="status"
            className={`arrive pointer-events-auto flex items-center gap-3 rounded-xl px-5 py-3 text-[15px] font-medium shadow-panel ${t.tone === "amber" ? "border border-amber-line bg-amber-fill text-amber-ink" : "bg-ink text-card"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ---------- page title ---------- */

export function useTitle(...parts: (string | undefined | null | false)[]) {
  const title = [...parts.filter(Boolean), "ChronoTrace"].join(" · ");
  useEffect(() => {
    document.title = title;
  }, [title]);
}

/* ---------- header ---------- */

export function AppHeader({ crumb, actions }: { crumb?: ReactNode; actions?: ReactNode }) {
  const { doctor, signOut } = useAuth();
  const name = doctor?.name ?? "Doctor";
  return (
    <header className="no-print sticky top-0 z-40 flex h-14 shrink-0 items-center gap-4 border-b border-line bg-card/85 px-4 backdrop-blur-md backdrop-saturate-150 sm:gap-6 sm:px-6 lg:px-10">
      <Link to="/patients" className="plain flex items-center gap-2.5">
        <Logo />
        <span className="hidden font-serif text-[22px] font-semibold tracking-[-0.01em] min-[420px]:inline">ChronoTrace</span>
      </Link>
      {crumb && (
        <nav aria-label="Breadcrumb" className="hidden items-center gap-2 text-sm text-ink-3 md:flex">
          <Link to="/patients">My patients</Link>
          <span aria-hidden="true">/</span>
          <span className="font-medium text-ink">{crumb}</span>
        </nav>
      )}
      <div className="grow" />
      {actions}
      <span className="hidden rounded-full border border-line px-2.5 py-1 text-xs text-ink-3 xl:inline">Demo login · synthetic data</span>
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-tint text-[13px] font-semibold text-blue-ink">
          {initials(name.replace(/^Dr\.?\s*/i, ""))}
        </span>
        <span className="hidden text-sm font-medium lg:inline">{name}</span>
      </div>
      <button type="button" onClick={() => signOut()} className="text-sm text-blue hover:text-blue-ink hover:underline">Sign out</button>
    </header>
  );
}
