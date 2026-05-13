import { useState, type FormEvent } from "react";
import { api, type AuthSessionSnapshot } from "../api/client";

interface LoginScreenProps {
  onAuthenticated: (snapshot: AuthSessionSnapshot) => void;
  /** Show the default password warning only when true (backend confirmed default password is still in use). */
  isDefaultPassword?: boolean;
}

export default function LoginScreen({ onAuthenticated, isDefaultPassword = false }: LoginScreenProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!password || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const snapshot = await api.login(password);
      setPassword("");
      onAuthenticated(snapshot);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex h-full min-h-0 items-center justify-center bg-[var(--bg)] p-4">
      <section className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--panel)] p-5 shadow-xl">
        <div className="mb-5">
          <h1 className="text-base font-semibold text-[var(--text)]">OpenHarness</h1>
          <p className="mt-1 text-sm text-[var(--text-dim)]">Enter the WebUI password.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1.5 block text-xs font-medium text-[var(--text-dim)]">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoFocus
              autoComplete="current-password"
              className="w-full rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-dim)] focus:border-[var(--accent)]/60"
            />
          </label>

          {error ? (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </div>
          ) : null}

          {isDefaultPassword ? (
            <div role="alert" className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              Default password: <span className="font-mono">123456</span>. Change it after login.
            </div>
          ) : (
            <div className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--text-dim)]">
              Sign in to continue.
            </div>
          )}

          <button
            type="submit"
            disabled={!password || submitting}
            className="inline-flex min-h-9 w-full items-center justify-center rounded-md border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-3 text-sm font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
