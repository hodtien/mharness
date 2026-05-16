import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PathDisplay } from "./PathDisplay";

function mockClipboard() {
  const mock = {
    writeText: vi.fn().mockResolvedValue(undefined),
  };
  vi.stubGlobal("navigator", { clipboard: mock });
  return mock;
}

describe("PathDisplay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("renders the full path when shorter than maxLen", () => {
    mockClipboard();
    render(<PathDisplay path="/short/path" />);
    expect(screen.getByText("/short/path")).toBeTruthy();
    expect(screen.getByRole("button").getAttribute("aria-label")).toBe(
      "Copy path: /short/path",
    );
  });

  it("truncates long paths with ellipsis", () => {
    mockClipboard();
    render(<PathDisplay path="/very/long/path/that/exceeds/forty/characters" maxLen={20} />);
    const code = screen.getByText(/…$/);
    expect(code.textContent?.length).toBeLessThan(
      "/very/long/path/that/exceeds/forty/characters".length,
    );
  });

  it("sets title attribute to full path for tooltip reveal", () => {
    mockClipboard();
    const longPath = "/very/long/path/that/exceeds/forty/characters";
    render(<PathDisplay path={longPath} maxLen={20} />);
    expect(screen.getByTitle(longPath)).toBeTruthy();
  });

  it("copy button has accessible aria-label", () => {
    mockClipboard();
    render(
      <PathDisplay path="/some/path" copyLabel="Copy config directory" />,
    );
    const btn = screen.getByRole("button");
    expect(btn.getAttribute("aria-label")).toBe("Copy config directory");
  });

  it("copy button writes full path to clipboard", async () => {
    mockClipboard();
    render(<PathDisplay path="/full/path/to/copy" />);
    await fireEvent.click(screen.getByRole("button"));
    expect(vi.mocked(navigator.clipboard.writeText)).toHaveBeenCalledWith(
      "/full/path/to/copy",
    );
  });

  it("shows checkmark feedback after copy", async () => {
    mockClipboard();
    render(<PathDisplay path="/any/path" />);
    await fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button").textContent).toBe("✓");
    await vi.advanceTimersByTime(2000);
    expect(screen.getByRole("button").textContent).toBe("⎘");
  });

  it("restores button label after copy timeout", async () => {
    mockClipboard();
    render(<PathDisplay path="/any/path" />);
    const btn = screen.getByRole("button");
    await fireEvent.click(btn);
    expect(btn.textContent).toBe("✓");
    await vi.advanceTimersByTime(2500);
    expect(btn.textContent).toBe("⎘");
  });

  it("shows error toast when clipboard write is rejected", async () => {
    const mock = mockClipboard();
    mock.writeText.mockRejectedValue(new Error("Clipboard unavailable"));
    render(<PathDisplay path="/any/path" />);
    await fireEvent.click(screen.getByRole("button"));
    // No checkmark on failure
    expect(screen.getByRole("button").textContent).toBe("⎘");
  });
});