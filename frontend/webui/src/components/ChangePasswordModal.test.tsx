import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ChangePasswordModal from "./ChangePasswordModal";

function mockLocalStorage() {
  let store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  });
}

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 204 ? "No Content" : "OK",
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    headers: { get: () => null },
  };
}

function mockChangePassword(success = true) {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    if (url === "/api/auth/change-password" && init?.method === "POST") {
      if (success) {
        return Promise.resolve(jsonResponse({ success: true }, 200));
      }
      return Promise.resolve(jsonResponse({ error: "Current password is incorrect" }, 400));
    }
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
}

describe("ChangePasswordModal", () => {
  beforeEach(() => {
    mockLocalStorage();
  });

  const renderModal = (open = true) => {
    const onClose = vi.fn();
    const onChanged = vi.fn();
    render(
      <BrowserRouter>
        <ChangePasswordModal open={open} onClose={onClose} onChanged={onChanged} />
      </BrowserRouter>,
    );
    return { onClose, onChanged };
  };

  describe("form validation", () => {
    it("disables Save button when form is empty", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /save/i })).toBeTruthy();
      });

      const saveButton = screen.getByRole("button", { name: /save/i }) as HTMLButtonElement;
      expect(saveButton.disabled).toBe(true);
    });

    it("disables Save button when only current password is entered", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });

      const saveButton = screen.getByRole("button", { name: /save/i }) as HTMLButtonElement;
      expect(saveButton.disabled).toBe(true);
    });

    it("disables Save button when new passwords do not match", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });
      // Use exact text for confirm - "Confirm new password" is distinct
      fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "differentpass" } });

      const saveButton = screen.getByRole("button", { name: /save/i }) as HTMLButtonElement;
      expect(saveButton.disabled).toBe(true);
    });

    it("enables Save button when all fields are valid", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });
      // Use exact "New password" label match (not "Confirm new password")
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });
      fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpass123" } });

      const saveButton = screen.getByRole("button", { name: /save/i }) as HTMLButtonElement;
      expect(saveButton.disabled).toBe(false);
    });
  });

  describe("inline validation messages", () => {
    it("shows 'Enter current password' when only new password is filled", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/^New password$/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });

      await waitFor(() => {
        expect(screen.getByText("Enter current password.")).toBeTruthy();
      });
    });

    it("shows 'Enter new password' when only current password is filled", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });

      await waitFor(() => {
        expect(screen.getByText("Enter new password.")).toBeTruthy();
      });
    });

    it("shows 'New passwords do not match' when passwords mismatch", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });
      fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "differentpass" } });

      await waitFor(() => {
        expect(screen.getByText("New passwords do not match.")).toBeTruthy();
      });
    });

    it("does not show validation message when form is empty", async () => {
      mockChangePassword();
      renderModal();

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /save/i })).toBeTruthy();
      });

      expect(screen.queryByText(/enter/i)).toBeNull();
    });
  });

  describe("form submission", () => {
    it("calls API with correct values on submit", async () => {
      const patchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true }));
      vi.stubGlobal("fetch", patchMock);

      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });
      fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpass123" } });

      fireEvent.click(screen.getByRole("button", { name: /save/i }));

      await waitFor(() => {
        expect(patchMock).toHaveBeenCalledWith(
          "/api/auth/change-password",
          expect.objectContaining({
            method: "POST",
            body: JSON.stringify({ old_password: "oldpass", new_password: "newpass123" }),
          }),
        );
      });
    });

    it("shows error message on API failure", async () => {
      vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
        if (url === "/api/auth/change-password" && init?.method === "POST") {
          return Promise.resolve(jsonResponse({ error: "Current password is incorrect" }, 400));
        }
        return Promise.reject(new Error(`unexpected url: ${url}`));
      });

      renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "wrongpass" } });
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });
      fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpass123" } });

      fireEvent.click(screen.getByRole("button", { name: /save/i }));

      await waitFor(() => {
        // Error message contains the JSON response from the API
        expect(screen.getByText(/Current password is incorrect/i)).toBeTruthy();
      });
    });

    it("calls onChanged and closes on success", async () => {
      const patchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true }));
      vi.stubGlobal("fetch", patchMock);

      const { onClose: oc, onChanged: ocb } = renderModal();

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass123" } });
      fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "newpass123" } });

      fireEvent.click(screen.getByRole("button", { name: /save/i }));

      await waitFor(() => {
        expect(ocb).toHaveBeenCalled();
        expect(oc).toHaveBeenCalled();
      });
    });
  });

  describe("reset behavior", () => {
    it("resets form when modal reopens", async () => {
      const { rerender } = render(
        <BrowserRouter>
          <ChangePasswordModal open={true} onClose={vi.fn()} onChanged={vi.fn()} />
        </BrowserRouter>,
      );

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "oldpass" } });
      fireEvent.change(screen.getByLabelText(/^New password$/i), { target: { value: "newpass" } });

      // Re-render with closed state
      rerender(
        <BrowserRouter>
          <ChangePasswordModal open={false} onClose={vi.fn()} onChanged={vi.fn()} />
        </BrowserRouter>,
      );

      // Re-render with open state again
      rerender(
        <BrowserRouter>
          <ChangePasswordModal open={true} onClose={vi.fn()} onChanged={vi.fn()} />
        </BrowserRouter>,
      );

      await waitFor(() => {
        expect(screen.getByLabelText(/current password/i)).toBeTruthy();
      });

      const currentPwdInput = screen.getByLabelText(/current password/i) as HTMLInputElement;
      const newPwdInput = screen.getByLabelText(/^New password$/i) as HTMLInputElement;
      expect(currentPwdInput.value).toBe("");
      expect(newPwdInput.value).toBe("");
    });
  });

  describe("keyboard handling", () => {
    it("closes modal on Escape key", async () => {
      mockChangePassword();
      const { onClose } = renderModal(true);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /save/i })).toBeTruthy();
      });

      fireEvent.keyDown(document, { key: "Escape" });

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  describe("cancel behavior", () => {
    it("closes modal on Cancel button click", async () => {
      mockChangePassword();
      const { onClose } = renderModal();

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /cancel/i })).toBeTruthy();
      });

      fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

      expect(onClose).toHaveBeenCalled();
    });

    it("closes modal on close button click", async () => {
      mockChangePassword();
      const { onClose } = renderModal();

      await waitFor(() => {
        expect(screen.getByRole("dialog", { name: /change password/i })).toBeTruthy();
      });

      fireEvent.click(screen.getByRole("button", { name: /close change password dialog/i }));

      expect(onClose).toHaveBeenCalled();
    });
  });
});