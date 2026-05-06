import { useEffect, useState } from "react";
import { api, type ProviderProfile } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";

interface VerifyResult {
  ok: boolean;
  error?: string;
  models?: string[];
}

const providerIcons: Record<string, string> = {
  anthropic: "🟠",
  openai: "🤖",
  openrouter: "🧭",
  ollama: "🦙",
  groq: "⚡",
  google: "🔎",
  dashscope: "☁️",
};

function providerIcon(provider: ProviderProfile): string {
  const key = `${provider.provider} ${provider.api_format} ${provider.id}`.toLowerCase();
  for (const [needle, icon] of Object.entries(providerIcons)) {
    if (key.includes(needle)) return icon;
  }
  return "🔌";
}

function statusLabel(provider: ProviderProfile): "Active" | "Configured" | "Not configured" {
  if (provider.is_active) return "Active";
  if (provider.has_credentials) return "Configured";
  return "Not configured";
}

export default function ProviderSettingsPage() {
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ProviderProfile | null>(null);

  const loadProviders = async () => {
    setError(null);
    const data = await api.listProviders();
    setProviders(data.providers);
  };

  useEffect(() => {
    let cancelled = false;
    api
      .listProviders()
      .then((data) => {
        if (!cancelled) setProviders(data.providers);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-1 overflow-y-auto p-6">
        <div className="w-full max-w-5xl space-y-4">
          <LoadingSkeleton rows={3} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-y-auto p-6">
      <div className="w-full max-w-5xl space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text)]">Providers</h1>
          <p className="mt-1 text-sm text-[var(--text-dim)]">
            Configure API credentials and activate the provider used by new sessions.
          </p>
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {providers.map((provider) => (
            <button
              key={provider.id}
              type="button"
              onClick={() => setSelected(provider)}
              className={`rounded-xl border bg-[var(--panel)] p-5 text-left shadow-lg transition hover:border-cyan-400/40 ${
                provider.is_active ? "border-cyan-400/70 ring-1 ring-cyan-400/30" : "border-[var(--border)]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-2xl" aria-hidden="true">{providerIcon(provider)}</span>
                  <div>
                    <div className="font-semibold text-[var(--text)]">{provider.label}</div>
                    <div className="text-xs text-[var(--text-dim)]">{provider.provider}</div>
                  </div>
                </div>
                <StatusBadge status={statusLabel(provider)} />
              </div>
              <div className="mt-4 text-xs uppercase tracking-wide text-[var(--text-dim)]">Default model</div>
              <div className="mt-1 truncate font-mono text-sm text-cyan-100">{provider.default_model || "—"}</div>
              {provider.base_url && (
                <div className="mt-3 truncate text-xs text-[var(--text-dim)]">{provider.base_url}</div>
              )}
            </button>
          ))}
        </div>

        {providers.length === 0 && (
          <EmptyState message="No providers returned." description="Add or sync a provider to get started." />
        )}
      </div>

      {selected && (
        <ProviderModal
          provider={selected}
          onClose={() => setSelected(null)}
          onRefresh={async () => {
            await loadProviders();
            setSelected(null);
          }}
        />
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: "Active" | "Configured" | "Not configured" }) {
  const classes =
    status === "Active"
      ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100"
      : status === "Configured"
        ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-100"
        : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)]";
  return <span className={`rounded-full border px-2 py-1 text-xs ${classes}`}>{status}</span>;
}

function ProviderModal({ provider, onClose, onRefresh }: { provider: ProviderProfile; onClose: () => void; onRefresh: () => Promise<void> }) {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url || "");
  const [verifying, setVerifying] = useState(false);
  const [activating, setActivating] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const saveCredentials = () =>
    api.saveProviderCredentials(provider.id, {
      api_key: apiKey || undefined,
      base_url: baseUrl || undefined,
    });

  const verify = async () => {
    setVerifying(true);
    setError(null);
    setVerifyResult(null);
    try {
      await saveCredentials();
      setVerifyResult(await api.verifyProvider(provider.id));
    } catch (err) {
      setError(String(err));
    } finally {
      setVerifying(false);
    }
  };

  const activate = async () => {
    setActivating(true);
    setError(null);
    try {
      await saveCredentials();
      await api.activateProvider(provider.id);
      await onRefresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setActivating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-[var(--text)]">{provider.label}</h2>
            <p className="mt-1 text-sm text-[var(--text-dim)]">Configure credentials, verify connectivity, or activate this provider.</p>
          </div>
          <button type="button" onClick={onClose} className="text-[var(--text-dim)] hover:text-[var(--text)]" aria-label="Close">✕</button>
        </div>

        <div className="mt-5 space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">API key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={provider.has_credentials ? "Existing key saved" : "Enter API key"}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Base URL</span>
            <input
              type="url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.example.com/v1"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            />
          </label>
        </div>

        {error && <div className="mt-4 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}
        {verifyResult && (
          <div className={`mt-4 rounded-lg border p-3 text-sm ${verifyResult.ok ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100" : "border-red-400/30 bg-red-500/10 text-red-200"}`}>
            {verifyResult.ok ? "Verification succeeded." : verifyResult.error || "Verification failed."}
            {verifyResult.ok && verifyResult.models && verifyResult.models.length > 0 && (
              <div className="mt-3">
                <div className="mb-2 text-xs uppercase tracking-wide text-[var(--text-dim)]">Models available to import</div>
                <div className="max-h-40 overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-2">
                  {verifyResult.models.map((model) => (
                    <div key={model} className="font-mono text-xs text-[var(--text)]">{model}</div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={verify} disabled={verifying || activating} className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-cyan-400/40 disabled:opacity-60">
            {verifying ? "Verifying…" : "Verify"}
          </button>
          <button type="button" onClick={activate} disabled={verifying || activating} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60">
            {activating ? "Activating…" : "Activate"}
          </button>
        </div>
      </div>
    </div>
  );
}
