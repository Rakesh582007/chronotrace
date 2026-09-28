import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth, useTitle } from "../components/shell";
import { Icon, Logo, Spinner } from "../components/ui";

export default function Login() {
  useTitle("Sign in");
  const { signIn, signedIn, notice } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = params.get("next");
  const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/patients";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (signedIn && !busy) return <Navigate to={target} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.login(username.trim(), password);
      signIn(r.token, r.doctor);
      navigate(target, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Username or password is incorrect" :
        err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ledger flex min-h-screen flex-col items-center justify-center gap-7 bg-paper px-4 py-10">
      <div className="flex items-center gap-3">
        <Logo size={36} />
        <span className="font-serif text-[30px] font-semibold tracking-[-0.01em]">ChronoTrace</span>
      </div>
      <form onSubmit={submit} noValidate
        className="flex w-full max-w-[420px] flex-col gap-6 rounded-[20px] border border-line bg-card p-8 shadow-panel sm:p-10">
        <div className="flex flex-col gap-1.5">
          <h1 className="m-0 font-serif text-[34px] font-medium tracking-[-0.015em]">Sign in</h1>
          <p className="m-0 text-[15px] text-ink-3">Doctor access to your assigned patients.</p>
        </div>
        {notice && !error && (
          <p role="status" className="m-0 rounded-[10px] border border-blue-line bg-blue-tint-2 px-3 py-2 text-sm text-blue-ink">{notice}</p>
        )}
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="username" className="text-sm font-medium">Username</label>
            <input id="username" className="field h-[46px] rounded-[10px] border border-field-line bg-white px-3.5 text-[15px]"
              type="text" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
              aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="password" className="text-sm font-medium">Password</label>
            <div className="flex h-[46px] items-center rounded-[10px] border border-field-line bg-white pr-1 focus-within:border-blue focus-within:shadow-[0_0_0_3px_#D4E4F4]">
              <input id="password" className="h-11 grow rounded-[10px] border-0 bg-transparent px-3.5 text-[15px] outline-none"
                type={show ? "text" : "password"} autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} aria-invalid={!!error}
                aria-describedby={error ? "login-error" : undefined} />
              <button type="button" aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}
                onClick={() => setShow((s) => !s)} className="flex h-[38px] w-11 items-center justify-center rounded-lg text-ink-3">
                {Icon.eye}
              </button>
            </div>
          </div>
          {error && <p id="login-error" role="alert" className="m-0 text-sm font-medium text-amber-ink">{error}</p>}
        </div>
        <button type="submit" disabled={busy}
          className="flex h-12 items-center justify-center gap-2 rounded-[10px] bg-blue text-base font-semibold text-white hover:bg-blue-hover disabled:opacity-80">
          {busy && <Spinner />}{busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="m-0 text-center text-[13px] text-ink-3">Demo login · synthetic patients only</p>
      </form>
    </div>
  );
}
