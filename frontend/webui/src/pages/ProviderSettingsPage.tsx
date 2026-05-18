import { useEffect, useMemo, useState } from "react";
import { api, type ProviderProfile, type ProviderVerifyResponse } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";

interface VerifyResult extends ProviderVerifyResponse {
  verifiedAt?: string;
}

interface ConnectionStatus {
  state: "idle" | "checking" | "ok" | "error";
  result?: VerifyResult;
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

function formatLatency(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(iso: string | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

export default function ProviderSettingsPage() {
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ProviderProfile | null>(null);
  const [connectionStatuses, setConnectionStatuses] = useState<Record<string, ConnectionStatus>>({});
  const [batchVerifying, setBatchVerifying] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"all" | "healthy" | "ready" | "probe-failing" | "custom-router">("all");

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

  const configuredProviders = useMemo(
    () => providers.filter((p) => p.has_credentials),
    [providers],
  );

  const filteredProviders = useMemo(() => {
    if (statusFilter === "all") return providers;
    if (statusFilter === "healthy") return providers.filter((p) => p.health_label === "Healthy");
    if (statusFilter === "ready") return providers.filter((p) => p.health_label === "Ready");
    if (statusFilter === "probe-failing") return providers.filter((p) => p.health_label === "Probe failing");
    return providers.filter((p) => {
      const key = `${p.provider} ${p.api_format} ${p.id} ${p.label}`.toLowerCase();
      return key.includes("custom") || key.includes("router") || key.includes("openrouter");
    });
  }, [providers, statusFilter]);

  const verifyAll = async () => {
    if (batchVerifying || configuredProviders.length === 0) return;
    setBatchVerifying(true);
    // Mark all configured as checking
    setConnectionStatuses((prev) => {
      const next = { ...prev };
      for (const p of configuredProviders) {
        next[p.id] = { state: "checking" };
      }
      return next;
    });
    // Verify each in parallel
    const results = await Promise.allSettled(
      configuredProviders.map(async (p) => {
        const start = Date.now();
        const res = await api.verifyProvider(p.id);
        return { id: p.id, res, latency_ms: Date.now() - start };
      }),
    );
    setConnectionStatuses((prev) => {
      const next = { ...prev };
      for (const r of results) {
        if (r.status === "fulfilled") {
          const { id, res, latency_ms } = r.value;
          next[id] = {
            state: res.ok ? "ok" : "error",
            result: { ...res, latency_ms: res.latency_ms ?? latency_ms, verifiedAt: new Date().toISOString() },
          };
        } else {
          // failed provider — find id from position
          // settled index aligns with configuredProviders index
          const idx = results.indexOf(r);
          const providerId = configuredProviders[idx]?.id;
          if (providerId) {
            next[providerId] = {
              state: "error",
              result: { ok: false, error: String(r.reason), verifiedAt: new Date().toISOString() },
            };
          }
        }
      }
      return next;
    });
    setBatchVerifying(false);
  };

  const updateConnectionStatus = (providerId: string, status: ConnectionStatus) => {
    setConnectionStatuses((prev) => ({ ...prev, [providerId]: status }));
  };

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
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Providers"
        description="Configure API credentials and activate the provider used by new sessions. Click a card to add a key or change the base URL, then verify connectivity before activating."
        primaryAction={
          configuredProviders.length > 0 ? (
            <button
              type="button"
              onClick={verifyAll}
              disabled={batchVerifying}
              className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-cyan-400/40 disabled:opacity-60"
              title="Verify connectivity for all configured providers"
            >
              {batchVerifying ? "Verifying…" : "Verify all"}
            </button>
          ) : undefined
        }
        metadata={[
          { label: "Providers", value: String(providers.length) },
          ...(providers.some((p) => p.health_label === "Healthy")
            ? [{ label: "Healthy", value: providers.find((p) => p.health_label === "Healthy")?.label ?? "—", accent: "cyan" as const }]
            : []),
        ]}
      />

      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-5xl space-y-6">

        {error && <ErrorBanner message={error} />}

        <div className="flex flex-wrap gap-2">
          {[
            ["all", "All"],
            ["healthy", "Healthy"],
            ["ready", "Ready"],
            ["probe-failing", "Probe failing"],
            ["custom-router", "Custom/router"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setStatusFilter(value as "all" | "healthy" | "ready" | "probe-failing" | "custom-router")}
              className={`rounded-full border px-3 py-1 text-xs ${statusFilter === value ? "border-cyan-400/50 bg-cyan-500/10 text-cyan-100" : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)]"}`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredProviders.map((provider) => {
            const connStatus = connectionStatuses[provider.id];
            return (
              <button
                key={provider.id}
                type="button"
                onClick={() => setSelected(provider)}
                disabled={batchVerifying}
                className={`rounded-xl border bg-[var(--panel)] p-5 text-left shadow-lg transition hover:border-cyan-400/40 disabled:pointer-events-none disabled:opacity-60 ${
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
                  <StatusBadge status={provider.health_label} />
                </div>
                <div className="mt-4 text-xs uppercase tracking-wide text-[var(--text-dim)]">Default model</div>
                <div className="mt-1 truncate font-mono text-sm text-cyan-100">{provider.default_model || "—"}</div>
                {provider.base_url && (
                  <div className="mt-3 truncate text-xs text-[var(--text-dim)]">{provider.base_url}</div>
                )}
                {connStatus && (
                  <ConnectionStatusRow status={connStatus} />
                )}
              </button>
            );
          })}
        </div>

        {providers.length > 0 && (
          <p className="text-xs text-[var(--text-dim)]">
            <strong className="font-medium text-[var(--text-dim)]">Healthy</strong> — active route is usable for new sessions.&nbsp;
            <strong className="font-medium text-[var(--text-dim)]">Ready</strong> — credentials are saved but this provider is not the active route.&nbsp;
            <strong className="font-medium text-[var(--text-dim)]">Probe failing</strong> — the route cannot be used until credentials or connectivity are fixed.
            Latency and &ldquo;last verified&rdquo; time appear after running <em>Verify</em>.
          </p>
        )}

        {providers.length === 0 && (
          <EmptyState message="No providers returned." description="Add or sync a provider to get started." />
        )}

        {providers.length > 0 && filteredProviders.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--panel)] p-8 text-center">
            <span aria-hidden="true" className="mb-3 text-4xl">🔍</span>
            <p className="text-sm font-medium text-[var(--text)]">No providers match this filter.</p>
            <p className="mt-1 text-xs text-[var(--text-dim)]">
              Try a different filter or{" "}
              <button type="button" className="text-cyan-400 hover:underline" onClick={() => setStatusFilter("all")}>
                clear the filter
              </button>
              .
            </p>
          </div>
        )}
      </div>
      </div>

      {selected && !batchVerifying && (
        <ProviderModal
          provider={selected}
          initialStatus={connectionStatuses[selected.id]}
          onClose={() => setSelected(null)}
          onRefresh={async () => {
            await loadProviders();
            setSelected(null);
          }}
          onStatusChange={(status) => updateConnectionStatus(selected.id, status)}
        />
      )}
    </div>
  );
}

function ConnectionStatusRow({ status }: { status: ConnectionStatus }) {
  if (status.state === "idle") return null;
  if (status.state === "checking") {
    return (
      <div className="mt-3 flex items-center gap-1.5 text-xs text-[var(--text-dim)]">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-cyan-400/70" />
        Checking…
      </div>
    );
  }
  const ok = status.state === "ok";
  const res = status.result;
  return (
    <div className={`mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${ok ? "text-emerald-300" : "text-red-300"}`}>
      <span>{ok ? "✓" : "✗"}</span>
      {ok && res?.models && <span>{res.models.length} models</span>}
      {res?.latency_ms !== undefined && <span>{formatLatency(res.latency_ms)}</span>}
      {res?.verifiedAt && <span className="text-[var(--text-dim)]">{formatTime(res.verifiedAt)}</span>}
      {!ok && res?.error && <span className="truncate max-w-[160px]">{res.error}</span>}
    </div>
  );
}

function StatusBadge({ status }: { status?: "Ready" | "Healthy" | "Probe failing" }) {
  const label = status ?? "Probe failing";
  const classes =
    label === "Healthy"
      ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-100"
      : label === "Ready"
        ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100"
        : "border-red-400/40 bg-red-400/10 text-red-200";
  return <span className={`rounded-full border px-2 py-1 text-xs ${classes}`}>{label}</span>;
}

function ProviderModal({
  provider,
  initialStatus,
  onClose,
  onRefresh,
  onStatusChange,
}: {
  provider: ProviderProfile;
  initialStatus?: ConnectionStatus;
  onClose: () => void;
  onRefresh: () => Promise<void>;
  onStatusChange: (status: ConnectionStatus) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url || "");
  const [verifying, setVerifying] = useState(false);
  const [activating, setActivating] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(initialStatus?.result ?? null);
  const [error, setError] = useState<string | null>(null);

  const busy = verifying || activating;

  const saveCredentials = () =>
    api.saveProviderCredentials(provider.id, {
      api_key: apiKey || undefined,
      base_url: baseUrl || undefined,
    });

  const verify = async () => {
    setVerifying(true);
    setError(null);
    setVerifyResult(null);
    onStatusChange({ state: "checking" });
    const start = Date.now();
    try {
      await saveCredentials();
      const res = await api.verifyProvider(provider.id);
      const latency_ms = res.latency_ms ?? (Date.now() - start);
      const result: VerifyResult = { ...res, latency_ms, verifiedAt: new Date().toISOString() };
      setVerifyResult(result);
      onStatusChange({ state: res.ok ? "ok" : "error", result });
    } catch (err) {
      const result: VerifyResult = { ok: false, error: String(err), verifiedAt: new Date().toISOString() };
      setError(String(err));
      onStatusChange({ state: "error", result });
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
          <button type="button" onClick={onClose} disabled={busy} className="text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-40" aria-label="Close">✕</button>
        </div>

        <div className="mt-5 space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">API key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              disabled={busy}
              placeholder={provider.has_credentials ? "Existing key saved" : "Enter API key"}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60 disabled:opacity-60"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Base URL</span>
            <input
              type="url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              disabled={busy}
              placeholder="https://api.example.com/v1"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60 disabled:opacity-60"
            />
          </label>
        </div>

        {error && <div className="mt-4 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>}
        {verifyResult && (
          <div className={`mt-4 rounded-lg border p-3 text-sm ${verifyResult.ok ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100" : "border-red-400/30 bg-red-500/10 text-red-200"}`}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>{verifyResult.ok ? "Verification succeeded." : verifyResult.error || "Verification failed."}</span>
              {verifyResult.latency_ms !== undefined && (
                <span className="text-xs opacity-70">{formatLatency(verifyResult.latency_ms)}</span>
              )}
              {verifyResult.ok && verifyResult.models && (
                <span className="text-xs opacity-70">{verifyResult.models.length} models</span>
              )}
              {verifyResult.verifiedAt && (
                <span className="text-xs opacity-60">at {formatTime(verifyResult.verifiedAt)}</span>
              )}
            </div>
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
          <button type="button" onClick={verify} disabled={busy} className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-cyan-400/40 disabled:opacity-60">
            {verifying ? "Verifying…" : "Verify"}
          </button>
          <button type="button" onClick={activate} disabled={busy} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60">
            {activating ? "Activating…" : "Activate"}
          </button>
        </div>
      </div>
    </div>
  );
}
