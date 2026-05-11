import { useEffect, useRef, useState } from "react";
import { api, type ModesPayload, type ModesPatch } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ErrorBanner from "../components/ErrorBanner";
import { toast } from "../store/toast";
import { FeedbackBadge, useFormFeedback } from "../hooks/useSettingsForm";
import PageHeader from "../components/PageHeader";

type PermissionMode = "default" | "plan" | "full_auto";
type Effort = "low" | "medium" | "high";

const permissionOptions: Array<{ value: PermissionMode; label: string; description: string }> = [
  { value: "default", label: "Default", description: "Ask before risky actions; balanced control." },
  { value: "plan", label: "Plan", description: "Review a plan before code or tool changes." },
  { value: "full_auto", label: "Full Auto", description: "Run safe tasks with minimal interruption." },
];

const compactOptions = [
  { value: 80_000, label: "80k tokens" },
  { value: 120_000, label: "120k tokens" },
  { value: 160_000, label: "160k tokens" },
  { value: 200_000, label: "200k tokens" },
];

const outputStyles = ["default", "concise", "detailed", "json"];
const themes = ["default", "dark", "light", "system"];

export default function ModesSettingsPage() {
  const [modes, setModes] = useState<ModesPayload | null>(null);
  const [passesInput, setPassesInput] = useState("1");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const passesTimer = useRef<number | null>(null);
  const { feedback, showSaving, showSaved, showError: showSaveError } = useFormFeedback();

  useEffect(() => {
    let cancelled = false;
    api
      .getModes()
      .then((data) => {
        if (cancelled) return;
        setModes(data);
        setPassesInput(String(data.passes));
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (passesTimer.current !== null) window.clearTimeout(passesTimer.current);
    };
  }, []);

  const patchModes = async (patch: ModesPatch) => {
    setSaving(true);
    showSaving();
    setError(null);
    try {
      const updated = await api.patchModes(patch);
      setModes(updated);
      if (patch.passes !== undefined) setPassesInput(String(updated.passes));
      showSaved();
      toast.success("Modes updated.");
    } catch (err) {
      showSaveError();
      setError(String(err));
      toast.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  const updateMode = (patch: ModesPatch) => {
    setModes((current) => (current ? { ...current, ...patch } : current));
    void patchModes(patch);
  };

  const updatePasses = (value: string) => {
    setPassesInput(value);
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > 5) return;
    setModes((current) => (current ? { ...current, passes: parsed } : current));
    if (passesTimer.current !== null) window.clearTimeout(passesTimer.current);
    passesTimer.current = window.setTimeout(() => {
      void patchModes({ passes: parsed });
    }, 300);
  };

  if (loading) {
    return (
      <div className="flex flex-1 overflow-y-auto p-6">
        <div className="w-full max-w-3xl space-y-4">
          <LoadingSkeleton rows={4} />
        </div>
      </div>
    );
  }

  if (!modes) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorBanner message={`Failed to load modes${error ? `: ${error}` : "."}`} />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Modes"
        description="Configure runtime behavior for OpenHarness sessions."
        metadata={[
          {
            label: "Permission Mode",
            value: modes.permission_mode,
          },
          {
            label: "Effort",
            value: modes.effort,
          },
        ]}
      />

      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-3xl space-y-6">

        {error && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {error}
          </div>
        )}

        <Section title="Permission Mode" description="Choose how much confirmation OpenHarness should request.">
          <div className="grid gap-3 sm:grid-cols-3">
            {permissionOptions.map((option) => (
              <label
                key={option.value}
                className={`cursor-pointer rounded-lg border p-4 transition ${
                  modes.permission_mode === option.value
                    ? "border-cyan-400/60 bg-cyan-400/10"
                    : "border-[var(--border)] bg-[var(--panel-2)] hover:border-cyan-400/30"
                }`}
              >
                <input
                  className="sr-only"
                  type="radio"
                  name="permission_mode"
                  checked={modes.permission_mode === option.value}
                  onChange={() => updateMode({ permission_mode: option.value })}
                />
                <div className="font-medium text-[var(--text)]">{option.label}</div>
                <div className="mt-1 text-xs leading-relaxed text-[var(--text-dim)]">
                  {option.description}
                </div>
              </label>
            ))}
          </div>
        </Section>

        <Section title="Effort">
          <div className="inline-flex overflow-hidden rounded-lg border border-[var(--border)]">
            {(["low", "medium", "high"] as Effort[]).map((effort) => (
              <button
                key={effort}
                type="button"
                onClick={() => updateMode({ effort })}
                className={`px-4 py-2 text-sm capitalize transition ${
                  modes.effort === effort
                    ? "bg-cyan-400/20 text-cyan-100"
                    : "bg-[var(--panel-2)] text-[var(--text-dim)] hover:text-[var(--text)]"
                }`}
              >
                {effort}
              </button>
            ))}
          </div>
        </Section>

        <Section title="Passes" description="Number of agent passes, from 1 to 5.">
          <div className="flex items-center gap-4">
            <div className="inline-flex items-center overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--panel-2)]">
              <button
                type="button"
                aria-label="Decrease passes"
                onClick={() => updatePasses(String(Math.max(1, Number(passesInput) - 1)))}
                disabled={Number(passesInput) <= 1}
                className="px-3 py-2 text-[var(--text-dim)] transition-colors hover:bg-[var(--border)] hover:text-[var(--text)] disabled:opacity-50 disabled:hover:bg-transparent"
              >
                -
              </button>
              <input
                aria-label="Passes"
                type="number"
                min={1}
                max={5}
                value={passesInput}
                onChange={(event) => updatePasses(event.target.value)}
                className="w-12 bg-transparent px-1 py-2 text-center text-[var(--text)] outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <button
                type="button"
                aria-label="Increase passes"
                onClick={() => updatePasses(String(Math.min(5, Number(passesInput) + 1)))}
                disabled={Number(passesInput) >= 5}
                className="px-3 py-2 text-[var(--text-dim)] transition-colors hover:bg-[var(--border)] hover:text-[var(--text)] disabled:opacity-50 disabled:hover:bg-transparent"
              >
                +
              </button>
            </div>
            
            <div className="flex gap-1.5" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((dot) => (
                <div
                  key={dot}
                  className={`h-2 w-2 rounded-full transition-colors ${
                    dot <= Number(passesInput) ? "bg-cyan-400" : "bg-[var(--border)]"
                  }`}
                />
              ))}
            </div>
          </div>
        </Section>

        <div className="grid gap-6 sm:grid-cols-2">
          <Section
            title="Runtime controls"
            description="Settings that affect session behavior while OpenHarness is running."
          >
            <div className="space-y-4">
              <ToggleRow
                label="Fast Mode"
                helperText="Use faster responses when available."
                checked={modes.fast_mode}
                onChange={(checked) => updateMode({ fast_mode: checked })}
              />
              <ToggleRow
                label="Vim keybindings"
                helperText="Enable vim key navigation in the chat input."
                checked={modes.vim_enabled}
                onChange={(checked) => updateMode({ vim_enabled: checked })}
              />
              <ToggleRow
                label="Notifications"
                helperText="Receive WebUI/autopilot event notifications."
                checked={Boolean(modes.notifications_enabled)}
                onChange={(checked) => updateMode({ notifications_enabled: checked })}
              />
            </div>
          </Section>

          <Section
            title="UX preferences"
            description="Visual and workflow preferences saved with your profile."
          >
            <div className="space-y-4">
              <div>
                <div className="text-sm font-medium text-[var(--text)]">Output Style</div>
                <div className="mt-1 text-xs text-[var(--text-dim)]">Choose how responses are formatted.</div>
                <div className="mt-2">
                  <Select
                    value={modes.output_style}
                    options={uniqueOption(outputStyles, modes.output_style)}
                    onChange={(output_style) => updateMode({ output_style })}
                  />
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-[var(--text)]">Theme</div>
                <div className="mt-1 text-xs text-[var(--text-dim)]">Pick the app color theme.</div>
                <div className="mt-2">
                  <Select
                    value={modes.theme}
                    options={uniqueOption(themes, modes.theme)}
                    onChange={(theme) => updateMode({ theme })}
                  />
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-[var(--text)]">Auto-compact</div>
                <div className="mt-1 text-xs text-[var(--text-dim)]">Compact transcripts sooner to keep long sessions responsive.</div>
                <div className="mt-2">
                  <Select
                    value={modes.auto_compact_threshold_tokens ? String(modes.auto_compact_threshold_tokens) : "160000"}
                    options={["off", ...compactOptions.map((option) => String(option.value))]}
                    onChange={(value) => updateMode({ auto_compact_threshold_tokens: value === "off" ? null : Number(value) })}
                  />
                </div>
              </div>
            </div>
          </Section>
        </div>

        <div className="flex items-center gap-3 text-xs text-[var(--text-dim)]">
          <FeedbackBadge feedback={feedback} />
          <span>{saving ? "Saving…" : "Changes save automatically."}</span>
        </div>
      </div>
      </div>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-lg">
      <div className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text)]">{title}</h2>
        {description && <p className="mt-1 text-xs text-[var(--text-dim)]">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function Select({ value, options, onChange }: { value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

function ToggleRow({
  label,
  helperText,
  checked,
  onChange,
}: {
  label: string;
  helperText?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex-1">
        <div className="text-sm font-medium text-[var(--text)]">{label}</div>
        {helperText && <div className="mt-0.5 text-xs text-[var(--text-dim)]">{helperText}</div>}
      </div>
      <div className="mt-0.5 flex-shrink-0">
        <input
          aria-label={label}
          type="checkbox"
          className="h-5 w-5 accent-cyan-400"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
      </div>
    </div>
  );
}

function uniqueOption(options: string[], current: string) {
  return Array.from(new Set([current, ...options].filter(Boolean)));
}
