/**
 * Lightweight toast notification system using Zustand.
 * No external libraries required beyond zustand (already in project).
 */
import { create } from "zustand";

export type ToastKind = "success" | "error" | "info" | "warn";

export interface ToastItem {
  id: string;
  kind: ToastKind;
  message: string;
  createdAt: number;
}

interface ToastStore {
  toasts: ToastItem[];
  /** Add a toast; auto-dismisses after 4s */
  addToast: (kind: ToastKind, message: string) => void;
  /** Remove a toast by id */
  removeToast: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],

  addToast: (kind, message) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    set((state) => ({ toasts: [...state.toasts, { id, kind, message, createdAt: Date.now() }] }));
    // Auto-dismiss after 4 seconds
    setTimeout(() => {
      const toast = get().toasts.find((t) => t.id === id);
      if (toast) {
        set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
      }
    }, 4000);
  },

  removeToast: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
}));

/** Convenience helpers — import from this module */
export const toast = {
  success: (message: string) => useToastStore.getState().addToast("success", message),
  error: (message: string) => useToastStore.getState().addToast("error", message),
  info: (message: string) => useToastStore.getState().addToast("info", message),
  warn: (message: string) => useToastStore.getState().addToast("warn", message),
} as const;