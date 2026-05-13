import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LoginScreen from "./LoginScreen";

describe("LoginScreen", () => {
  it("shows the default password warning when the backend reports the default password is still active", () => {
    render(<LoginScreen onAuthenticated={vi.fn()} isDefaultPassword />);

    expect(screen.getByText(/Default password:/i)).toBeTruthy();
    expect(screen.getByText("123456")).toBeTruthy();
  });

  it("hides the warning when the password has been customized", () => {
    render(<LoginScreen onAuthenticated={vi.fn()} isDefaultPassword={false} />);

    expect(screen.queryByText(/Default password:/i)).toBeNull();
    expect(screen.getByText(/Sign in to continue\./i)).toBeTruthy();
  });
});
