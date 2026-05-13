/**
 * Auth & Runtime Status Semantics
 *
 * Maps raw `auth_status` strings from the backend to human-readable labels
 * and color tones for consistent display across Sidebar, Header, Control Center,
 * and Security settings.
 *
 * | Backend value         | Label              | Tone      | Meaning                          |
 * |-----------------------|--------------------|-----------|----------------------------------|
 * | "ok"                  | Active             | success   | Authenticated, usable right now   |
 * | "configured"          | Ready              | neutral   | Credentials saved, not active    |
 * | "degraded"            | Needs attention    | warning   | Partial auth / limited access    |
 * | "missing"             | Not configured     | danger    | No credentials configured        |
 * | "invalid base_url"    | Setup required     | danger    | Misconfiguration                 |
 * | (anything else)       | Unknown            | neutral   | Unexpected / unhandled state     |
 */

export type Tone = "success" | "warning" | "danger" | "neutral";

export interface AuthSemanticState {
  label: string;
  tone: Tone;
}

/**
 * Get semantic display state from raw auth_status string.
 * Use this instead of direct string comparisons in UI components.
 */
export function getAuthSemanticState(authStatus: string | undefined | null): AuthSemanticState {
  switch (authStatus) {
    case "ok":
      return { label: "Active", tone: "success" };
    case "configured":
      return { label: "Ready", tone: "neutral" };
    case "degraded":
      return { label: "Needs attention", tone: "warning" };
    case "missing":
      return { label: "Not configured", tone: "danger" };
    case "invalid base_url":
      return { label: "Setup required", tone: "danger" };
    default:
      // Covers "missing (run 'oh auth ...')" strings and any other unexpected values
      if (!authStatus || authStatus === "unknown") {
        return { label: "Unknown", tone: "neutral" };
      }
      if (authStatus.startsWith("missing")) {
        return { label: "Not configured", tone: "danger" };
      }
      return { label: "Unknown", tone: "neutral" };
  }
}

/**
 * Resolve CSS class name for status-pill based on tone.
 */
export function statusPillClass(tone: Tone): string {
  switch (tone) {
    case "success":
      return "status-pill status-pill-success";
    case "danger":
      return "status-pill status-pill-danger";
    case "warning":
      return "status-pill status-pill-warning";
    default:
      return "status-pill";
  }
}