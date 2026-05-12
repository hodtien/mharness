import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ChatPage from "./ChatPage";
import { useSession } from "../store/session";

function mockSession(state: Partial<ReturnType<typeof useSession.getState>> = {}) {
  const defaults = {
    connectionStatus: "open" as const,
    transcript: [] as ReturnType<typeof useSession.getState>["transcript"],
    appState: { model: "test-model", cwd: "/test", permission_mode: "default" },
    sessionId: null,
  };
  useSession.setState({ ...defaults, ...state });
}

function renderChatPage(onSend = vi.fn()) {
  return render(
    <BrowserRouter>
      <ChatPage onSend={onSend} />
    </BrowserRouter>,
  );
}

describe("ChatPage", () => {
  it("shows empty state when connected with no user/assistant messages", () => {
    mockSession({ connectionStatus: "open", transcript: [] });
    renderChatPage();

    // Quick actions should appear
    expect(screen.getByText("Resume recent session")).toBeTruthy();
    expect(screen.getByText("Check system status")).toBeTruthy();
    expect(screen.getByText("/help")).toBeTruthy();

    // Status strip should show
    expect(screen.getByText(/\/test/)).toBeTruthy();
    expect(screen.getByText(/test-model/)).toBeTruthy();
  });

  it("shows transcript when there are user/assistant messages", () => {
    mockSession({
      connectionStatus: "open",
      transcript: [
        { id: "1", role: "user", text: "Hello" },
        { id: "2", role: "assistant", text: "Hi there" },
      ],
    });
    renderChatPage();

    // Empty state quick actions should not appear
    expect(screen.queryByText("Resume recent session")).toBeNull();
    expect(screen.queryByText("Check system status")).toBeNull();

    // User message should appear
    expect(screen.getByText("Hello")).toBeTruthy();
  });

  it("hides empty state after user sends first message", () => {
    // Start with connected, empty transcript
    mockSession({ connectionStatus: "open", transcript: [] });
    const { rerender } = renderChatPage();

    // Empty state is shown
    expect(screen.getByText("Resume recent session")).toBeTruthy();

    // Simulate first message being added (by the app via appendUser)
    act(() => {
      mockSession({
        transcript: [{ id: "1", role: "user", text: "My first message" }],
      });
    });
    rerender(
      <BrowserRouter>
        <ChatPage onSend={vi.fn()} />
      </BrowserRouter>,
    );

    // Empty state is gone
    expect(screen.queryByText("Resume recent session")).toBeNull();
    expect(screen.getByText("My first message")).toBeTruthy();
  });

  it("shows disconnected banner when connection is closed", () => {
    mockSession({ connectionStatus: "closed" });
    renderChatPage();

    expect(screen.getByText(/Disconnected/)).toBeTruthy();
  });

  it("renders quick action buttons that trigger onSend", () => {
    const onSend = vi.fn();
    mockSession({ connectionStatus: "open", transcript: [] });
    renderChatPage(onSend);

    const statusBtn = screen.getByText("Check system status");
    statusBtn.click();
    expect(onSend).toHaveBeenCalledWith("/status");
  });
});