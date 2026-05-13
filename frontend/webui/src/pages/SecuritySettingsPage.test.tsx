import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SecuritySettingsPage from "./SecuritySettingsPage";
import { useSession } from "../store/session";

function mockLocalStorage() {
  let store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  });
}

vi.mock("../api/client", () => ({
  api: {
    logout: vi.fn().mockResolvedValue(undefined),
  },
}));

describe("SecuritySettingsPage", () => {
  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({ appState: null });
  });

  it("renders security page heading", () => {
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/security/i)).toBeTruthy();
  });

  it("shows 'Unknown' pill when auth_status is undefined", () => {
    useSession.setState({ appState: {} });
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("Unknown")).toBeTruthy();
  });

  it("shows 'Active' pill with success style for ok status", () => {
    useSession.setState({
      appState: { auth_status: "ok" },
    });
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    const pill = screen.getByText("Active").closest("span");
    expect(pill?.className).toContain("status-pill-success");
  });

  it("shows 'Ready' pill with neutral style for configured status", () => {
    useSession.setState({
      appState: { auth_status: "configured" },
    });
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    const pill = screen.getByText("Ready").closest("span");
    expect(pill?.className).toContain("status-pill");
    expect(pill?.className).not.toContain("status-pill-success");
    expect(pill?.className).not.toContain("status-pill-danger");
    expect(pill?.className).not.toContain("status-pill-warning");
  });

  it("shows 'Needs attention' pill with warning style for degraded status", () => {
    useSession.setState({
      appState: { auth_status: "degraded" },
    });
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    const pill = screen.getByText("Needs attention").closest("span");
    expect(pill?.className).toContain("status-pill-warning");
  });

  it("shows 'Not configured' pill with danger style for missing status", () => {
    useSession.setState({
      appState: { auth_status: "missing" },
    });
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    const pill = screen.getByText("Not configured").closest("span");
    expect(pill?.className).toContain("status-pill-danger");
  });

  it("shows 'Setup required' pill with danger style for invalid base_url", () => {
    useSession.setState({
      appState: { auth_status: "invalid base_url" },
    });
    render(
      <MemoryRouter>
        <SecuritySettingsPage />
      </MemoryRouter>,
    );
    const pill = screen.getByText("Setup required").closest("span");
    expect(pill?.className).toContain("status-pill-danger");
  });
});