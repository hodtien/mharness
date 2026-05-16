import type { SchedulerDiagnosticsResponse } from "../api/client";

export type SchedulerTone = "success" | "warning" | "danger" | "neutral";

export interface SchedulerStatusDisplay {
  label: string;
  value: string;
  tone: SchedulerTone;
}

export function formatSchedulerDiagnostics(
  diagnostics: SchedulerDiagnosticsResponse | null,
): SchedulerStatusDisplay {
  if (!diagnostics) {
    return {
      label: "Scheduler",
      value: "No diagnostics",
      tone: "neutral",
    };
  }

  const installed = diagnostics.cron_entries_installed > 0;
  const enabled = diagnostics.cron_entries_enabled > 0;
  const alive = diagnostics.scheduler_process_alive;

  if (diagnostics.scheduling_feature_enabled && alive && enabled) {
    return { label: "Scheduler", value: "running", tone: "success" };
  }

  if (diagnostics.scheduling_feature_enabled && installed && !alive) {
    return {
      label: "Scheduler",
      value: "Cron installed, scheduler process stopped",
      tone: "warning",
    };
  }

  if (!diagnostics.scheduling_feature_enabled && !installed) {
    return { label: "Scheduler", value: "Feature disabled, no cron jobs", tone: "neutral" };
  }

  if (!diagnostics.scheduling_feature_enabled && installed) {
    return { label: "Scheduler", value: "Feature disabled, cron installed", tone: "warning" };
  }

  if (alive) {
    return { label: "Scheduler", value: "scheduler process alive", tone: "warning" };
  }

  return { label: "Scheduler", value: "scheduler process stopped", tone: "danger" };
}

export function formatCronStatus(
  diagnostics: SchedulerDiagnosticsResponse | null,
): SchedulerStatusDisplay {
  if (!diagnostics) {
    return { label: "Cron entries", value: "No diagnostics", tone: "neutral" };
  }

  if (diagnostics.cron_entries_installed === 0) {
    return { label: "Cron entries", value: "No cron jobs installed", tone: "neutral" };
  }

  if (diagnostics.cron_entries_enabled === 0) {
    return { label: "Cron entries", value: "Installed, all disabled", tone: "warning" };
  }

  if (diagnostics.cron_entries_enabled < diagnostics.cron_entries_installed) {
    return {
      label: "Cron entries",
      value: `${diagnostics.cron_entries_enabled}/${diagnostics.cron_entries_installed} enabled`,
      tone: "warning",
    };
  }

  return {
    label: "Cron entries",
    value: `${diagnostics.cron_entries_enabled}/${diagnostics.cron_entries_installed} enabled`,
    tone: diagnostics.scheduler_process_alive ? "success" : "warning",
  };
}

export function formatFeatureStatus(
  diagnostics: SchedulerDiagnosticsResponse | null,
): SchedulerStatusDisplay {
  if (!diagnostics) {
    return { label: "Feature", value: "No diagnostics", tone: "neutral" };
  }

  return diagnostics.scheduling_feature_enabled
    ? { label: "Feature", value: "enabled", tone: "success" }
    : { label: "Feature", value: "disabled", tone: "neutral" };
}
