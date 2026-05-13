import { describe, it, expect } from "vitest";
import { getAuthSemanticState, statusPillClass } from "./authStatusSemantics";

describe("authStatusSemantics", () => {
  describe("getAuthSemanticState", () => {
    it('maps "ok" → Active / success', () => {
      const result = getAuthSemanticState("ok");
      expect(result.label).toBe("Active");
      expect(result.tone).toBe("success");
    });

    it('maps "configured" → Ready / neutral', () => {
      const result = getAuthSemanticState("configured");
      expect(result.label).toBe("Ready");
      expect(result.tone).toBe("neutral");
    });

    it('maps "degraded" → Needs attention / warning', () => {
      const result = getAuthSemanticState("degraded");
      expect(result.label).toBe("Needs attention");
      expect(result.tone).toBe("warning");
    });

    it('maps "missing" → Not configured / danger', () => {
      const result = getAuthSemanticState("missing");
      expect(result.label).toBe("Not configured");
      expect(result.tone).toBe("danger");
    });

    it('maps "invalid base_url" → Setup required / danger', () => {
      const result = getAuthSemanticState("invalid base_url");
      expect(result.label).toBe("Setup required");
      expect(result.tone).toBe("danger");
    });

    it('maps "missing (run \'oh auth ...\')" → Not configured / danger', () => {
      const result = getAuthSemanticState("missing (run 'oh auth claude-login')");
      expect(result.label).toBe("Not configured");
      expect(result.tone).toBe("danger");
    });

    it('maps undefined → Unknown / neutral', () => {
      const result = getAuthSemanticState(undefined);
      expect(result.label).toBe("Unknown");
      expect(result.tone).toBe("neutral");
    });

    it('maps null → Unknown / neutral', () => {
      const result = getAuthSemanticState(null);
      expect(result.label).toBe("Unknown");
      expect(result.tone).toBe("neutral");
    });

    it('maps unknown string → Unknown / neutral', () => {
      const result = getAuthSemanticState("some_unexpected_state");
      expect(result.label).toBe("Unknown");
      expect(result.tone).toBe("neutral");
    });
  });

  describe("statusPillClass", () => {
    it("returns success class for success tone", () => {
      expect(statusPillClass("success")).toBe("status-pill status-pill-success");
    });

    it("returns danger class for danger tone", () => {
      expect(statusPillClass("danger")).toBe("status-pill status-pill-danger");
    });

    it("returns warning class for warning tone", () => {
      expect(statusPillClass("warning")).toBe("status-pill status-pill-warning");
    });

    it("returns base class for neutral tone", () => {
      expect(statusPillClass("neutral")).toBe("status-pill");
    });
  });
});