import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";

interface ChangePasswordModalProps {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export default function ChangePasswordModal({ open, onClose, onChanged }: ChangePasswordModalProps) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setOldPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    if (!oldPassword || !newPassword) {
      setError("Enter both passwords.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.changePassword(oldPassword, newPassword);
      onChanged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change password");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--panel)] p-5 shadow-xl"
      >
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-[var(--text)]">Change password</h2>
          <p className="mt-1 text-xs text-[var(--text-dim)]">Update the local WebUI password.</p>
        </div>

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1.5 block text-xs font-medium text-[var(--text-dim)]">Current password</span>
            <input
              type="password"
              value={oldPassword}
              onChange={(event) => setOldPassword(event.target.value)}
              autoComplete="current-password"
              autoFocus
              className="w-full rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/60"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block text-xs font-medium text-[var(--text-dim)]">New password</span>
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              autoComplete="new-password"
              className="w-full rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/60"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block text-xs font-medium text-[var(--text-dim)]">Confirm new password</span>
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              className="w-full rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/60"
            />
          </label>
        </div>

        {error ? (
          <div className="mt-4 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </div>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-9 items-center rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="inline-flex min-h-9 items-center rounded-md border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-3 text-xs font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Saving..." : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
