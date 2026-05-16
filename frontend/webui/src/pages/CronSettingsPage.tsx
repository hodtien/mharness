import { useEffect, useState } from "react";
import {
  api,
  type CronConfigResponse,
  type CronConfigPatch,
  type SchedulerDiagnosticsResponse,
} from "../api/client";
import {
  formatSchedulerDiagnostics,
  formatCronStatus,
  formatFeatureStatus,
} from "../utils/schedulerDiagnostics";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ErrorBanner from "../components/ErrorBanner";
import { toast } from "../store/toast";
import {
  useUnsavedWarning,
  FeedbackBadge,
  useFormFeedback,
} from "../hooks/useSettingsForm";
import PageHeader from "../components/PageHeader";

// Interval thresholds for "too frequent" warnings (in minutes)
const SCAN_THRESHOLD_MIN = 5;
const TICK_THRESHOLD_MIN = 15;

const CRON_EXAMPLES = [
  { label: "Every 5 minutes", value: "*/5 * * * *" },
  { label: "Every 15 minutes", value: "*/15 * * * *" },
  { label: "Every 30 minutes", value: "*/30 * * * *" },
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every 2 hours", value: "0 */2 * * *" },
  { label: "Daily at 9 AM", value: "0 9 * * *" },
  { label: "Weekdays at 9 AM", value: "0 9 * * 1-5" },
] as const;

function isValidCron(expr: string): boolean {
  // Basic 5-field validation: minute hour day month dow
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) return false;
  return true;
}

// Parse a simple */n interval into minutes, or return null
function parseIntervalMinutes(expr: string): number | null {
  const match = expr.trim().match(/^\*\/(\d+)\s+\*\s+\*\s+\*\s+\*$/);
  if (match) return parseInt(match[1], 10);
  return null;
}

function TooFrequentWarning({
  scanCron,
  tickCron,
}: {
  scanCron: string;
  tickCron: string;
}) {
  const scanMin = parseIntervalMinutes(scanCron);
  const tickMin = parseIntervalMinutes(tickCron);
  const messages: string[] = [];

  if (scanMin !== null && scanMin < SCAN_THRESHOLD_MIN) {
    messages.push(
      `Scan runs every ${scanMin} minute${scanMin !== 1 ? "s" : ""} — this is very frequent.`,
    );
  }
  if (tickMin !== null && tickMin < TICK_THRESHOLD_MIN) {
    messages.push(
      `Tick runs every ${tickMin} minutes — this is very frequent.`,
    );
  }

  if (messages.length === 0) return null;

  return (
    <div className="rounded-lg border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
      <div className="flex items-start gap-2">
        <span aria-hidden="true" className="mt-0.5 text-base">
          ⚠️
        </span>
        <div className="space-y-1">
          <div className="font-medium">Schedule may be too frequent</div>
          {messages.map((m, i) => (
            <div key={i} className="text-xs text-amber-200/80">
              {m}
            </div>
          ))}
          <div className="text-xs text-amber-200/60">
            Frequent schedules increase API usage and system load.
          </div>
        </div>
      </div>
    </div>
  );
}

function formatNextRuns(runs: string[]): string[] {
  return runs.map((iso) => {
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  });
}

export default function CronSettingsPage() {
  const [config, setConfig] = useState<CronConfigResponse | null>(null);
  const [diagnostics, setDiagnostics] =
    useState<SchedulerDiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [lastApplied, setLastApplied] = useState<{
    scan_cron: string;
    tick_cron: string;
    enabled: boolean;
    install_mode: string;
    install_result?: CronConfigResponse["install_result"];
  } | null>(null);
  const [installMode, setInstallMode] = useState<"auto" | "manual">("auto");
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Draft inputs (separate from saved config)
  const [draftScanCron, setDraftScanCron] = useState("");
  const [draftTickCron, setDraftTickCron] = useState("");
  const [draftEnabled, setDraftEnabled] = useState(true);
  const [scanDirty, setScanDirty] = useState(false);
  const [tickDirty, setTickDirty] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getCronConfig()
      .then((data) => {
        if (cancelled) return;
        setConfig(data);
        setDraftScanCron(data.scan_cron);
        setDraftTickCron(data.tick_cron);
        setDraftEnabled(data.enabled);
        setInstallMode((data.install_mode as "auto" | "manual") || "auto");
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    // Also load diagnostics for consistent status display
    api
      .getSchedulerDiagnostics()
      .then((d) => {
        if (!cancelled) setDiagnostics(d);
      })
      .catch(() => {
        if (!cancelled) setDiagnostics(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const schedulerDisplay = formatSchedulerDiagnostics(diagnostics);
  const cronDisplay = formatCronStatus(diagnostics);
  const featureDisplay = formatFeatureStatus(diagnostics);

  const applyDraft = (patch: CronConfigPatch) => {
    setSaving(true);
    showSaving();
    setError(null);
    api
      .patchCronConfig(patch)
      .then((updated) => {
        setConfig(updated);
        setDraftScanCron(updated.scan_cron);
        setDraftTickCron(updated.tick_cron);
        setDraftEnabled(updated.enabled);
        setScanDirty(false);
        setTickDirty(false);
        setLastApplied({
          scan_cron: updated.scan_cron,
          tick_cron: updated.tick_cron,
          enabled: updated.enabled,
          install_mode: (updated as CronConfigResponse).install_mode || "auto",
          install_result: updated.install_result,
        });
        showSaved();
        toast.success("Cron schedule updated.");
      })
      .catch((err) => {
        const msg = String(err);
        setError(msg);
        showSaveError();
        toast.error(String(err));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedField(field);
      toast.success("Copied to clipboard!");
      setTimeout(() => setCopiedField(null), 2000);
    });
  };

  const handleApply = () => {
    const patch: CronConfigPatch = { enabled: draftEnabled };
    if (scanDirty) patch.scan_cron = draftScanCron.trim();
    if (tickDirty) patch.tick_cron = draftTickCron.trim();
    applyDraft(patch);
  };

  const handlePreset = (scanVal: string, tickVal: string) => {
    setDraftScanCron(scanVal);
    setDraftTickCron(tickVal);
    setScanDirty(true);
    setTickDirty(true);
  };

  const handleScanChange = (val: string) => {
    setDraftScanCron(val);
    setScanDirty(true);
  };

  const handleTickChange = (val: string) => {
    setDraftTickCron(val);
    setTickDirty(true);
  };

  const handleToggle = (checked: boolean) => {
    setDraftEnabled(checked);
    // Apply immediately since toggle is a meaningful state change
    applyDraft({ enabled: checked });
  };

  const handleInstallModeChange = (mode: "auto" | "manual") => {
    setInstallMode(mode);
    applyDraft({ install_mode: mode });
  };

  const hasChanges = scanDirty || tickDirty;
  const previewEnabled = draftEnabled;

  const {
    feedback: saveFeedback,
    showSaving,
    showSaved,
    showError: showSaveError,
  } = useFormFeedback();

  // Warn before navigating away when there are unsaved cron expression changes
  useUnsavedWarning({ isDirty: hasChanges });

  if (loading) {
    return (
      <div className="flex flex-1 overflow-y-auto p-6">
        <div className="w-full max-w-3xl space-y-4">
          <LoadingSkeleton rows={4} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Autopilot Schedule"
        description="Configure the scheduling feature, the scheduler runtime, and the cron entries used for autopilot scans and ticks."
        metadata={[
          ...(config
            ? [
                {
                  label: "Scan",
                  value: config.scan_cron_description || config.scan_cron,
                },
                {
                  label: "Tick",
                  value: config.tick_cron_description || config.tick_cron,
                },
                {
                  label: featureDisplay.label,
                  value: featureDisplay.value,
                  accent: (featureDisplay.tone === "success"
                    ? "cyan"
                    : "none") as "cyan" | "none",
                },
                {
                  label: schedulerDisplay.label,
                  value: schedulerDisplay.value,
                  accent: (schedulerDisplay.tone === "success"
                    ? "cyan"
                    : schedulerDisplay.tone === "warning"
                      ? "amber"
                      : "none") as "cyan" | "amber" | "none",
                },
                {
                  label: cronDisplay.label,
                  value: cronDisplay.value,
                  accent: (cronDisplay.tone === "success"
                    ? "cyan"
                    : cronDisplay.tone === "warning"
                      ? "amber"
                      : "none") as "cyan" | "amber" | "none",
                },
              ]
            : []),
        ]}
      />
      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-3xl space-y-6">
          {error && (
            <ErrorBanner message={error} onRetry={() => setError(null)} />
          )}

          {/* Enabled toggle */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-lg">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">
                  Autopilot Scheduling Feature
                </h2>
                <p className="mt-1 text-xs text-[var(--text-dim)]">
                  Turns autopilot scheduling on or off. When disabled, the
                  scheduler should not install or run jobs.
                </p>
              </div>
              <label className="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  role="switch"
                  aria-label="Enable autopilot scheduling"
                  checked={draftEnabled}
                  onChange={(e) => handleToggle(e.target.checked)}
                  disabled={saving}
                  className="peer sr-only"
                />
                <div className="peer h-6 w-11 rounded-full bg-[var(--panel-2)] transition peer-checked:bg-cyan-400/40 peer-disabled:opacity-50" />
                <div className="pointer-events-none absolute left-1 top-1 h-4 w-4 rounded-full bg-[var(--border)] transition peer-checked:translate-x-5 peer-checked:bg-cyan-300" />
              </label>
            </div>
          </div>

          {/* Cron inputs */}
          <div
            className={`rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-lg transition ${!draftEnabled ? "opacity-50" : ""}`}
          >
            <div className="mb-4">
              <h2 className="text-base font-semibold text-[var(--text)]">
                Cron Schedules
              </h2>
              <p className="mt-1 text-xs text-[var(--text-dim)]">
                Standard 5-field cron expression: minute hour day month weekday
              </p>
            </div>

            {/* Too-frequent warning */}
            {draftEnabled && (
              <TooFrequentWarning
                scanCron={draftScanCron}
                tickCron={draftTickCron}
              />
            )}

            <div className="mt-4 space-y-4">
              {/* Scan cron */}
              <div>
                <label
                  htmlFor="scan-cron"
                  className="block text-sm font-medium text-[var(--text)]"
                >
                  Scan Cron
                </label>
                <input
                  id="scan-cron"
                  type="text"
                  value={draftScanCron}
                  onChange={(e) => handleScanChange(e.target.value)}
                  disabled={!draftEnabled || saving}
                  placeholder="*/15 * * * *"
                  className={`mt-1 w-full rounded-lg border bg-[var(--panel-2)] px-3 py-2 text-sm font-mono text-[var(--text)] outline-none focus:border-cyan-400/60 ${scanDirty && !isValidCron(draftScanCron) ? "border-red-400/50" : "border-[var(--border)]"} disabled:opacity-50`}
                />
                <div className="mt-1 text-xs text-[var(--text-dim)]">
                  How often to scan for new ideas.{" "}
                  {config?.scan_cron_description && !scanDirty && (
                    <span className="text-cyan-400/70">
                      Currently: {config.scan_cron_description}
                    </span>
                  )}
                </div>
              </div>

              {/* Tick cron */}
              <div>
                <label
                  htmlFor="tick-cron"
                  className="block text-sm font-medium text-[var(--text)]"
                >
                  Tick Cron
                </label>
                <input
                  id="tick-cron"
                  type="text"
                  value={draftTickCron}
                  onChange={(e) => handleTickChange(e.target.value)}
                  disabled={!draftEnabled || saving}
                  placeholder="0 * * * *"
                  className={`mt-1 w-full rounded-lg border bg-[var(--panel-2)] px-3 py-2 text-sm font-mono text-[var(--text)] outline-none focus:border-cyan-400/60 ${tickDirty && !isValidCron(draftTickCron) ? "border-red-400/50" : "border-[var(--border)]"} disabled:opacity-50`}
                />
                <div className="mt-1 text-xs text-[var(--text-dim)]">
                  How often to tick/check autopilot job progress.{" "}
                  {config?.tick_cron_description && !tickDirty && (
                    <span className="text-cyan-400/70">
                      Currently: {config.tick_cron_description}
                    </span>
                  )}
                </div>
              </div>

              {/* Presets */}
              <div>
                <div className="mb-2 text-sm font-medium text-[var(--text-dim)]">
                  Presets
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handlePreset("*/5 * * * *", "*/15 * * * *")}
                    disabled={!draftEnabled || saving}
                    className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] transition hover:border-cyan-400/40 hover:text-[var(--text)] disabled:opacity-50"
                  >
                    Aggressive (5m / 15m)
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePreset("*/15 * * * *", "0 * * * *")}
                    disabled={!draftEnabled || saving}
                    className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] transition hover:border-cyan-400/40 hover:text-[var(--text)] disabled:opacity-50"
                  >
                    Default (15m / 1h)
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePreset("*/30 * * * *", "0 */2 * * *")}
                    disabled={!draftEnabled || saving}
                    className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] transition hover:border-cyan-400/40 hover:text-[var(--text)] disabled:opacity-50"
                  >
                    Conservative (30m / 2h)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDraftEnabled(false);
                      applyDraft({ enabled: false });
                    }}
                    disabled={saving}
                    className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] transition hover:border-cyan-400/40 hover:text-[var(--text)] disabled:opacity-50"
                  >
                    Disabled
                  </button>
                </div>
                <div className="mt-2 text-xs text-[var(--text-dim)] opacity-60">
                  More frequent schedules increase API usage and system load.
                  Presets fill the form but you can still adjust values
                  manually.
                </div>
              </div>
            </div>

            {/* Next runs preview */}
            {previewEnabled && config && (
              <div className="mt-6 grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="mb-2 text-sm font-medium text-[var(--text-dim)]">
                    Next scan runs
                  </div>
                  <div className="space-y-1">
                    {formatNextRuns(config.next_scan_runs).length > 0 ? (
                      formatNextRuns(config.next_scan_runs).map((label, i) => (
                        <div
                          key={i}
                          className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 font-mono text-xs text-[var(--text)]"
                        >
                          {label}
                        </div>
                      ))
                    ) : (
                      <div className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)]">
                        No upcoming runs
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <div className="mb-2 text-sm font-medium text-[var(--text-dim)]">
                    Next tick runs
                  </div>
                  <div className="space-y-1">
                    {formatNextRuns(config.next_tick_runs).length > 0 ? (
                      formatNextRuns(config.next_tick_runs).map((label, i) => (
                        <div
                          key={i}
                          className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 font-mono text-xs text-[var(--text)]"
                        >
                          {label}
                        </div>
                      ))
                    ) : (
                      <div className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)]">
                        No upcoming runs
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {!previewEnabled && (
              <div className="mt-4 rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--text-dim)]">
                Scheduling is disabled. Enable it above to see upcoming run
                times.
              </div>
            )}
          </div>

          {/* Apply button */}
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <FeedbackBadge feedback={saveFeedback} />
              {hasChanges && saveFeedback === "idle" && (
                <span className="text-xs text-[var(--text-dim)]">
                  {scanDirty && "Scan schedule changed. "}
                  {tickDirty && "Tick schedule changed. "}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={handleApply}
              disabled={saving || !hasChanges}
              className="rounded-lg border border-cyan-400/40 bg-cyan-400/20 px-5 py-2 text-sm font-medium text-cyan-100 transition hover:border-cyan-400/60 hover:bg-cyan-400/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving…" : "Apply"}
            </button>
          </div>

          {/* Install mode toggle */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-lg">
            <div className="mb-4">
              <h2 className="text-base font-semibold text-[var(--text)]">
                Installation Mode
              </h2>
              <p className="mt-1 text-xs text-[var(--text-dim)]">
                Choose how to install cron jobs on your system.
              </p>
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => handleInstallModeChange("auto")}
                disabled={saving}
                className={`flex-1 rounded-lg border px-4 py-3 text-sm font-medium transition ${
                  installMode === "auto"
                    ? "border-cyan-400/50 bg-cyan-400/20 text-cyan-100"
                    : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:border-cyan-400/30"
                }`}
              >
                <div className="text-left">
                  <div className="font-medium">⚡ Auto Install</div>
                  <div className="mt-0.5 text-xs opacity-70">
                    Automatically install crontab entries
                  </div>
                </div>
              </button>
              <button
                type="button"
                onClick={() => handleInstallModeChange("manual")}
                disabled={saving}
                className={`flex-1 rounded-lg border px-4 py-3 text-sm font-medium transition ${
                  installMode === "manual"
                    ? "border-cyan-400/50 bg-cyan-400/20 text-cyan-100"
                    : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:border-cyan-400/30"
                }`}
              >
                <div className="text-left">
                  <div className="font-medium">📋 Manual</div>
                  <div className="mt-0.5 text-xs opacity-70">
                    Show commands to install manually
                  </div>
                </div>
              </button>
            </div>
          </div>

          {/* Result panel - shown after successful apply */}
          {lastApplied && lastApplied.install_result && (
            <div
              className={`rounded-xl border p-5 shadow-lg ${
                lastApplied.install_result
                  ? lastApplied.install_result.success
                    ? "rounded-xl border-emerald-400/30 bg-emerald-500/10"
                    : "rounded-xl border-red-400/30 bg-red-500/10"
                  : "rounded-xl border-emerald-400/30 bg-emerald-500/10"
              }`}
            >
              <div className="mb-4 flex items-center gap-2">
                {lastApplied.install_result ? (
                  lastApplied.install_result.success ? (
                    <>
                      <span className="text-lg">✅</span>
                      <h2 className="text-base font-semibold text-emerald-200">
                        Configuration Applied
                      </h2>
                    </>
                  ) : (
                    <>
                      <span className="text-lg">❌</span>
                      <h2 className="text-base font-semibold text-red-200">
                        Installation Failed
                      </h2>
                    </>
                  )
                ) : (
                  <>
                    <span className="text-lg">✅</span>
                    <h2 className="text-base font-semibold text-emerald-200">
                      Configuration Applied
                    </h2>
                  </>
                )}
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-emerald-400/20 bg-[var(--panel-2)] px-4 py-2">
                  <div>
                    <div className="text-xs text-emerald-200/60">Scan Cron</div>
                    <div className="font-mono text-sm text-emerald-100">
                      {lastApplied.scan_cron}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      copyToClipboard(lastApplied.scan_cron, "scan")
                    }
                    className="rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200 transition hover:bg-emerald-400/20"
                  >
                    {copiedField === "scan" ? "✓ Copied" : "Copy"}
                  </button>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-emerald-400/20 bg-[var(--panel-2)] px-4 py-2">
                  <div>
                    <div className="text-xs text-emerald-200/60">Tick Cron</div>
                    <div className="font-mono text-sm text-emerald-100">
                      {lastApplied.tick_cron}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      copyToClipboard(lastApplied.tick_cron, "tick")
                    }
                    className="rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200 transition hover:bg-emerald-400/20"
                  >
                    {copiedField === "tick" ? "✓ Copied" : "Copy"}
                  </button>
                </div>

                {/* Install result details */}
                {lastApplied.install_result && (
                  <>
                    {lastApplied.install_result.success ? (
                      <div className="space-y-2">
                        {lastApplied.install_result.scan_line && (
                          <div className="flex items-center gap-2">
                            <code className="flex-1 overflow-x-auto rounded border border-emerald-400/20 bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-emerald-100">
                              {lastApplied.install_result.scan_line}
                            </code>
                            <button
                              type="button"
                              onClick={() =>
                                copyToClipboard(
                                  lastApplied.install_result!.scan_line,
                                  "scan-line",
                                )
                              }
                              className="shrink-0 rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200 transition hover:bg-emerald-400/20"
                            >
                              {copiedField === "scan-line" ? "✓" : "Copy"}
                            </button>
                          </div>
                        )}
                        {lastApplied.install_result.tick_line && (
                          <div className="flex items-center gap-2">
                            <code className="flex-1 overflow-x-auto rounded border border-emerald-400/20 bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-emerald-100">
                              {lastApplied.install_result.tick_line}
                            </code>
                            <button
                              type="button"
                              onClick={() =>
                                copyToClipboard(
                                  lastApplied.install_result!.tick_line,
                                  "tick-line",
                                )
                              }
                              className="shrink-0 rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200 transition hover:bg-emerald-400/20"
                            >
                              {copiedField === "tick-line" ? "✓" : "Copy"}
                            </button>
                          </div>
                        )}
                        <div className="text-xs text-emerald-200/70">
                          {lastApplied.install_result.scan_installed &&
                          lastApplied.install_result.tick_installed
                            ? "Both scan and tick cron jobs installed."
                            : lastApplied.install_result.scan_installed
                              ? "Only scan cron job installed."
                              : lastApplied.install_result.tick_installed
                                ? "Only tick cron job installed."
                                : "Cron jobs registered in local registry."}
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <div className="rounded-md border border-red-400/20 bg-red-900/20 px-3 py-2 text-sm text-red-200">
                          {lastApplied.install_result.message}
                        </div>
                        <div className="text-xs text-red-200/60">
                          Falling back to manual installation. Use the commands
                          below:
                        </div>
                        {lastApplied.install_result.manual_commands?.map(
                          (cmd, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <code className="flex-1 overflow-x-auto rounded border border-red-400/20 bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-red-100">
                                {cmd}
                              </code>
                              <button
                                type="button"
                                onClick={() =>
                                  copyToClipboard(cmd, `manual-${i}`)
                                }
                                className="shrink-0 rounded border border-red-400/30 bg-red-400/10 px-2 py-1 text-xs text-red-200 transition hover:bg-red-400/20"
                              >
                                {copiedField === `manual-${i}` ? "✓" : "Copy"}
                              </button>
                            </div>
                          ),
                        )}
                      </div>
                    )}
                  </>
                )}

                {lastApplied.enabled ? (
                  <div className="text-xs text-emerald-200/70">
                    Scheduling is{" "}
                    <span className="font-medium text-emerald-200">
                      enabled
                    </span>
                    .
                  </div>
                ) : (
                  <div className="text-xs text-amber-200/70">
                    Scheduling is{" "}
                    <span className="font-medium text-amber-200">disabled</span>
                    .
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Manual instructions fallback */}
          {installMode === "manual" && (
            <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-5 shadow-lg">
              <div className="mb-4 flex items-center gap-2">
                <span className="text-lg">📋</span>
                <h2 className="text-base font-semibold text-amber-200">
                  Manual Installation
                </h2>
              </div>
              <p className="mb-4 text-sm text-amber-200/80">
                Run these commands in your terminal to install the cron jobs
                manually:
              </p>
              <div className="space-y-3">
                <div>
                  <div className="mb-1 text-xs font-medium text-amber-200/60">
                    Scan Job
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 overflow-x-auto rounded border border-amber-400/20 bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-amber-100">
                      {`(crontab -l 2>/dev/null | grep -v 'oh autopilot scan all'; echo "${config?.scan_cron || "*/15 * * * *"} oh autopilot scan all --cwd <your-project-path>") | crontab -`}
                    </code>
                    <button
                      type="button"
                      onClick={() =>
                        copyToClipboard(
                          `(crontab -l 2>/dev/null | grep -v 'oh autopilot scan all'; echo "${config?.scan_cron || "*/15 * * * *"} oh autopilot scan all --cwd <your-project-path>") | crontab -`,
                          "manual-scan",
                        )
                      }
                      className="shrink-0 rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-xs text-amber-200 transition hover:bg-amber-400/20"
                    >
                      {copiedField === "manual-scan" ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-xs font-medium text-amber-200/60">
                    Tick Job
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 overflow-x-auto rounded border border-amber-400/20 bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-amber-100">
                      {`(crontab -l 2>/dev/null | grep -v 'oh autopilot tick'; echo "${config?.tick_cron || "0 * * * *"} oh autopilot tick --cwd <your-project-path>") | crontab -`}
                    </code>
                    <button
                      type="button"
                      onClick={() =>
                        copyToClipboard(
                          `(crontab -l 2>/dev/null | grep -v 'oh autopilot tick'; echo "${config?.tick_cron || "0 * * * *"} oh autopilot tick --cwd <your-project-path>") | crontab -`,
                          "manual-tick",
                        )
                      }
                      className="shrink-0 rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-xs text-amber-200 transition hover:bg-amber-400/20"
                    >
                      {copiedField === "manual-tick" ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                </div>
                <p className="mt-2 text-xs text-amber-200/60">
                  Copy-paste these commands into your terminal. Replace
                  &lt;your-project-path&gt; with your actual project directory.
                </p>
              </div>
            </div>
          )}

          {/* Helper text */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-lg">
            <h2 className="mb-3 text-sm font-semibold text-[var(--text)]">
              Cron Expression Examples
            </h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {CRON_EXAMPLES.map((ex) => (
                <button
                  key={ex.value}
                  type="button"
                  onClick={() => {
                    handlePreset(ex.value, ex.value);
                  }}
                  disabled={!draftEnabled || saving}
                  className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs transition hover:border-cyan-400/30 hover:bg-[var(--panel)] disabled:opacity-50"
                >
                  <span className="text-[var(--text-dim)]">{ex.label}</span>
                  <code className="font-mono text-[var(--text)]">
                    {ex.value}
                  </code>
                </button>
              ))}
            </div>
            <p className="mt-3 text-xs text-[var(--text-dim)]">
              Format:{" "}
              <code className="font-mono text-[var(--text)]">
                minute hour day month weekday
              </code>
              . Use <code className="font-mono text-[var(--text)]">*</code> for
              any,
              <code className="font-mono text-[var(--text)]">*/n</code> for
              every n units.
            </p>
          </div>

          {/* Timezone info */}
          {config?.timezone && (
            <div className="text-xs text-[var(--text-dim)]">
              All times shown in{" "}
              <span className="font-mono text-[var(--text)]">
                {config.timezone}
              </span>
              .
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
