import { useState } from "react";
import PageHeader from "../components/PageHeader";
import ChangePasswordModal from "../components/ChangePasswordModal";
import { PathDisplay } from "../components/PathDisplay";
import { api } from "../api/client";
import { toast } from "../store/toast";
import { useSession } from "../store/session";
import { getAuthSemanticState, statusPillClass } from "../utils/authStatusSemantics";

export default function SecuritySettingsPage() {
  const appState = useSession((s) => s.appState);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await api.logout();
      window.location.reload();
    } catch (err) {
      toast.error(String(err));
      setLoggingOut(false);
    }
  };

  const authSemantic = getAuthSemanticState(appState?.auth_status);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Security"
        description="Password, session status, and authentication controls."
      />
      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-2xl space-y-5">

          {/* Auth status */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-[var(--text)]">Authentication</div>
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-dim)]">Auth status</span>
                <span className={statusPillClass(authSemantic.tone)}>
                  {authSemantic.label}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-dim)]">Session</span>
                <span className="text-xs font-mono text-[var(--text)]">active</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text-dim)]">Token storage</span>
                <span className="text-xs font-mono text-[var(--text)]">~/.harness/</span>
              </div>
            </div>
          </div>

          {/* Password controls */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-[var(--text)]">Password</div>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-[var(--text)]">Change password</div>
                <div className="mt-0.5 text-xs text-[var(--text-dim)]">
                  Update your local WebUI password.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowPasswordModal(true)}
                className="rounded-lg border border-cyan-400/40 bg-cyan-400/20 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:border-cyan-400/60 hover:bg-cyan-400/30"
              >
                Change
              </button>
            </div>
          </div>

          {/* Session controls */}
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-[var(--text)]">Session</div>
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-[var(--text)]">End session</div>
                  <div className="mt-0.5 text-xs text-[var(--text-dim)]">
                    Log out and clear the current session.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleLogout}
                  disabled={loggingOut}
                  className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm font-medium text-[var(--text-dim)] transition hover:border-red-400/40 hover:text-red-300 disabled:opacity-50"
                >
                  {loggingOut ? "Logging out…" : "Logout"}
                </button>
              </div>
              <div className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--text-dim)]">
                Config directory:{" "}
                <PathDisplay path={appState?.config_dir ?? "~/.harness/"} copyLabel="Copy config directory" />
              </div>
            </div>
          </div>

        </div>
      </div>
      <ChangePasswordModal
        open={showPasswordModal}
        onClose={() => setShowPasswordModal(false)}
        onChanged={() => {
          toast.success("Password updated.");
          setShowPasswordModal(false);
        }}
      />
    </div>
  );
}